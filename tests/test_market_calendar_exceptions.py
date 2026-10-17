"""Reviewed full-closure partitions and ETF-suspension diagnostics.

All OHLCV here are synthetic and are NOT historical exchange observations.
"""
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from src.cache import Cache
from src.config import load
from src.market_calendar_exceptions import (
    reviewed_txf_closed_partition, reviewed_0050_suspension,
)


def test_only_independently_reviewed_txf_windows_are_skipped():
    x=reviewed_txf_closed_partition('2019-02-04','2019-02-10')
    assert x['reason']=='TAIFEX_2019_LUNAR_NEW_YEAR_FULL_CLOSURE'
    assert x['source_url'].startswith('https://www.taifex.com.tw/')
    assert reviewed_txf_closed_partition('2019-02-06','2019-02-10')
    for a,b in [('2019-02-03','2019-02-10'),
                ('2019-02-04','2019-02-11'),
                ('2018-02-04','2018-02-10'),
                ('2020-02-03','2020-02-09')]:
        assert reviewed_txf_closed_partition(a,b) is None
    with pytest.raises(ValueError):
        reviewed_txf_closed_partition('2019-02-10','2019-02-04')


def test_known_0050_split_suspend_dates_only():
    for day in ('2025-06-11','2025-06-12','2025-06-13',
                '2025-06-16','2025-06-17'):
        item=reviewed_0050_suspension(day)
        assert item['reason']=='ETF_0050_VERIFIED_SPLIT_TRADING_SUSPENSION'
        assert 'twse.com.tw' in item['source_url']
    for day in ('2025-06-10','2025-06-18','2024-06-12'):
        assert reviewed_0050_suspension(day) is None


def _bars_for_day(day,price):
    start=pd.Timestamp(day,tz='Asia/Taipei')
    rows=[]
    for session,stamp,close in [
        ('regular',start+pd.Timedelta(hours=8,minutes=45),price),
        ('regular',start+pd.Timedelta(hours=13,minutes=30),price),
        ('regular',start+pd.Timedelta(hours=13,minutes=44),price),
        ('afterhours',start+pd.Timedelta(hours=15),price),
        ('afterhours',start+pd.Timedelta(days=1,hours=4,minutes=59),price+1)]:
        rows.append(dict(timestamp=stamp,session=session,contract_month='201902',
                         open=close,high=close,low=close,close=close,volume=10,
                         source_trade_date=day))
    return rows


def _fake_sources(monkeypatch,include_conflict=False,broken_week=None):
    import src.fetch_finlab as fl
    import src.fetch_fubon as fb

    days=['2019-01-28','2019-02-11','2019-02-18','2019-02-25','2019-03-04']
    spot=pd.DataFrame([
        dict(date=d,open=100+i,close=100+i,adjustment_verified=True,
             corporate_action_boundary=False,fully_missing_0050=False)
        for i,d in enumerate(days)])
    if include_conflict:
        extra=pd.DataFrame([dict(date='2019-02-06',open=90,close=90,
            adjustment_verified=True,corporate_action_boundary=False,
            fully_missing_0050=False)])
        spot=pd.concat([spot,extra],ignore_index=True).sort_values('date')
    monkeypatch.setattr(fl,'fetch',lambda *_:spot.copy())

    raw=pd.DataFrame([entry for i,day in enumerate(days[:-1])
                      for entry in _bars_for_day(day,10000+i)])
    calls=[]
    def fake_fetch(_rest,a,b,_spacing):
        calls.append((a,b))
        if a=='2019-02-04' and b=='2019-02-10':
            raise AssertionError('Known market closure must never query Fubon')
        if broken_week==(a,b):
            return raw.iloc[:0].drop(columns='source_trade_date').copy()
        return raw.loc[raw.source_trade_date.between(a,b)].drop(
            columns='source_trade_date').copy()
    monkeypatch.setattr(fb,'fetch',fake_fetch)
    cfg={**load(),'mode':'validation',
         'start':'2019-01-28','end':'2019-02-11'}
    return cfg,calls


def test_verified_closed_week_skipped_and_audited_in_full_pipeline(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    cfg,calls=_fake_sources(monkeypatch)
    out=pipeline.run(cfg,tmp_path,rest=object())
    info=json.loads((out/'run_info.json').read_text())
    skipped=pd.read_csv(out/'diagnostics/fubon_closed_partitions.csv')
    missing=pd.read_csv(out/'diagnostics/finlab_missing_dates.csv')
    manifest=json.loads((out/'raw_manifest/manifest.json').read_text())
    assert info['status']!='FAILED'
    assert not missing.shape[0]
    assert calls==[
        ('2019-01-28','2019-02-03'),
        ('2019-02-11','2019-02-17'),
        ('2019-02-18','2019-02-24'),
        ('2019-02-25','2019-02-25')]
    assert skipped.shape[0]==1
    assert skipped.iloc[0]['reason']=='TAIFEX_2019_LUNAR_NEW_YEAR_FULL_CLOSURE'
    assert info['fubon_verified_closed_partition_count']==1
    assert info['fubon_verified_closed_partitions'][0]['start']=='2019-02-04'
    holiday=[m for m in manifest if m.get('status')=='SKIPPED_REVIEWED_FULL_CLOSURE']
    assert len(holiday)==1
    assert holiday[0]['rows']==0 and holiday[0]['sha256'] is None
    # No synthetic empty parquet is created for the closed interval.
    assert len(list((tmp_path/'cache/fubon_txf').glob('*.parquet')))==4


def test_reuse_unchanged_cache_and_do_not_requery_holiday(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    import src.fetch_finlab as fl
    import src.fetch_fubon as fb
    cfg,_=_fake_sources(monkeypatch)
    first=pipeline.run(cfg,tmp_path,rest=object())
    before={p.name:p.read_bytes() for p in
            (tmp_path/'cache/fubon_txf').glob('*.parquet')}
    def no_fetch(*_):
        raise AssertionError('Previously completed source cache must be reused')
    monkeypatch.setattr(fl,'fetch',no_fetch)
    monkeypatch.setattr(fb,'fetch',no_fetch)
    second=pipeline.run(cfg,tmp_path,rest=object())
    after={p.name:p.read_bytes() for p in
           (tmp_path/'cache/fubon_txf').glob('*.parquet')}
    assert before==after and second!=first
    manifest=json.loads((second/'raw_manifest/manifest.json').read_text())
    assert sum(x.get('cache_hit') is True for x in manifest)==5
    assert sum(x.get('status')=='SKIPPED_REVIEWED_FULL_CLOSURE'
               for x in manifest)==1


def test_unapproved_empty_fubon_week_still_fails(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    cfg,_=_fake_sources(monkeypatch,broken_week=('2019-02-11','2019-02-17'))
    with pytest.raises(RuntimeError,match='sanitized diagnostics'):
        pipeline.run(cfg,tmp_path,rest=object())
    out=next((tmp_path/'runs').iterdir())
    info=json.loads((out/'run_info.json').read_text())
    assert info['status']=='FAILED'
    assert info['error_stage']=='FUBON_FETCH'
    assert info['current_partition']=='2019-02-11..2019-02-17'
    assert info['fubon_verified_closed_partition_count']==1


def test_conflicting_spot_day_inside_closed_futures_week_fails(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    cfg,_=_fake_sources(monkeypatch,include_conflict=True)
    with pytest.raises(RuntimeError,match='sanitized diagnostics'):
        pipeline.run(cfg,tmp_path,rest=object())
    out=next((tmp_path/'runs').iterdir())
    info=json.loads((out/'run_info.json').read_text())
    assert info['status']=='FAILED'
    assert info['current_partition']=='2019-02-04..2019-02-10'


def test_split_missing_dates_documented_without_imputation(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    import src.fetch_finlab as fl
    cfg,calls=_fake_sources(monkeypatch)
    original=fl.fetch
    def provider(*args):
        spot=original(*args)
        return pd.concat([spot,pd.DataFrame([
            dict(date=d,open=float('nan'),close=float('nan'),
                 adjustment_verified=False,corporate_action_boundary=False,
                 fully_missing_0050=True)
            for d in ('2025-06-11','2025-06-12','2025-06-13',
                      '2025-06-16','2025-06-17')])],ignore_index=True)
    monkeypatch.setattr(fl,'fetch',provider)
    out=pipeline.run(cfg,tmp_path,rest=object())
    missing=pd.read_csv(out/'diagnostics/finlab_missing_dates.csv')
    info=json.loads((out/'run_info.json').read_text())
    assert info['finlab_0050_fully_missing_count']==5
    assert len(info['finlab_0050_verified_suspension_dates'])==5
    assert (missing.calendar_interpretation ==
            'ETF_0050_VERIFIED_SPLIT_TRADING_SUSPENSION').all()
    assert missing.evidence_url.str.contains('twse.com.tw').all()
