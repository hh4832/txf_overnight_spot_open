"""FinLab TX general/afterhours activity calendar: synthetic validation only."""
import json

import numpy as np
import pandas as pd
import pytest

from src.fetch_finlab_calendar import normalize, validate_calendar, partition_activity
from src.synthetic import generate_txf_calendar, generate
from src.config import load


def source(start='2021-01-20',end='2021-03-03',inactive=()):
    dates=pd.bdate_range(start,end)
    closed=set(inactive)
    regular=pd.Series(
        [np.nan if x.strftime('%Y-%m-%d') in closed else 100
         for x in dates],index=dates,dtype=float)
    after=pd.Series(
        [np.nan if x.strftime('%Y-%m-%d') in closed else 30
         for x in dates],index=dates,dtype=float)
    return pd.DataFrame({'TX一般':regular,'TX盤後':after})


def test_2021_holiday_week_no_tx_activity_without_hardcoded_year():
    inactive=pd.date_range('2021-02-08','2021-02-14').strftime('%Y-%m-%d')
    frame=normalize(source(inactive=inactive),'2021-01-25','2021-02-26')
    validate_calendar(frame,'2021-01-25','2021-02-26')
    closed=partition_activity(frame,'2021-02-08','2021-02-14')
    assert closed['has_tx_activity'] is False
    assert closed['tx_regular_dates']==[]
    assert closed['tx_afterhours_dates']==[]
    assert frame.loc[frame.date=='2021-02-08','tx_regular_volume'].isna().all()
    active=partition_activity(frame,'2021-02-15','2021-02-21')
    assert active['has_tx_activity'] is True


def test_any_afterhours_only_activity_protects_partition_from_skip():
    raw=source()
    raw.loc[pd.Timestamp('2021-02-09'),'TX一般']=np.nan
    raw.loc[pd.Timestamp('2021-02-09'),'TX盤後']=80
    frame=normalize(raw,'2021-02-01','2021-02-19')
    result=partition_activity(frame,'2021-02-08','2021-02-14')
    assert '2021-02-09' in result['tx_afterhours_dates']
    assert '2021-02-09' not in result['tx_regular_dates']
    assert result['has_tx_activity']


def test_normalization_and_cached_calendar_detect_bad_input():
    frame=normalize(source(),'2021-02-01','2021-02-19')
    assert len(frame)==19
    assert frame.source_row_present.sum()==15
    assert frame.loc[frame.date=='2021-02-07','has_tx_activity'].iloc[0]==False
    with pytest.raises(ValueError,match='missing TX'):
        normalize(source().drop(columns='TX盤後'),'2021-02-01','2021-02-19')
    bad=source()
    bad.loc[pd.Timestamp('2021-02-09'),'TX一般']=-1
    with pytest.raises(ValueError,match='volume invalid'):
        normalize(bad,'2021-02-01','2021-02-19')
    corrupt=frame.copy()
    corrupt.loc[0,'has_tx_activity']=False
    with pytest.raises(ValueError,match='activity inconsistent'):
        validate_calendar(corrupt,'2021-02-01','2021-02-19')
    with pytest.raises(ValueError,match='cache dates'):
        validate_calendar(frame.iloc[:-1],'2021-02-01','2021-02-19')


def test_stale_history_and_unbracketed_gap_blocked():
    with pytest.raises(ValueError,match='coverage incomplete'):
        normalize(source('2021-01-01','2021-02-03'),
                  '2021-01-01','2021-03-15')
    frame=generate_txf_calendar('2021-02-01','2021-02-14',
        pd.date_range('2021-02-08','2021-02-14').strftime('%Y-%m-%d'))
    with pytest.raises(ValueError,match='unbracketed'):
        partition_activity(frame,'2021-02-08','2021-02-14')


def setup_fake_live(monkeypatch,closed_dates=(),spot_conflict=False,
                    tx_activity_override=()):
    import src.fetch_finlab as finlab
    import src.fetch_finlab_calendar as calendar_source
    import src.fetch_fubon as fubon
    bars,spot=generate()
    excluded=set(closed_dates)
    if not spot_conflict:
        spot=spot.loc[~spot.date.isin(excluded)].copy()
    bars=bars.loc[~bars.timestamp.dt.strftime('%Y-%m-%d').isin(excluded)].copy()
    monkeypatch.setattr(finlab,'fetch',lambda a,b:spot.copy())
    active_extra=set(tx_activity_override)
    def mock_calendar(a,b):
        frame=generate_txf_calendar(a,b,excluded)
        frame.loc[frame.date.isin(active_extra),'tx_afterhours_volume']=10.0
        frame.loc[frame.date.isin(active_extra),'has_tx_activity']=True
        return frame
    monkeypatch.setattr(calendar_source,'fetch',mock_calendar)
    calls=[]
    def mock_fubon(_rest,a,b,_spacing):
        calls.append((a,b))
        # A closed partition must never reach this API.
        if a=='2022-01-10' and b=='2022-01-16':
            raise AssertionError('No-TX-activity partition must not call Fubon')
        dates=bars.timestamp.dt.strftime('%Y-%m-%d')
        return bars.loc[dates.between(a,b)].copy()
    monkeypatch.setattr(fubon,'fetch',mock_fubon)
    cfg={**load(),'mode':'validation','start':'2022-01-03','end':'2022-01-17'}
    return cfg,calls


def test_live_pipeline_skips_only_full_week_without_tx(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    inactive=pd.date_range('2022-01-10','2022-01-16').strftime('%Y-%m-%d')
    cfg,calls=setup_fake_live(monkeypatch,inactive)
    run_dir=pipeline.run(cfg,tmp_path,rest=object())
    info=json.loads((run_dir/'run_info.json').read_text())
    assert info['status']!='FAILED'
    assert ('2022-01-10','2022-01-16') not in calls
    assert ('2022-01-03','2022-01-09') in calls
    assert ('2022-01-17','2022-01-23') in calls
    assert info['fubon_finlab_no_activity_partition_count']==1
    skipped=pd.read_csv(run_dir/'diagnostics/fubon_calendar_alignment.csv')
    row=skipped.loc[skipped.start=='2022-01-10'].iloc[0]
    assert row.decision=='SKIP_FINLAB_NO_RECORDED_TX_ACTIVITY'
    manifest=json.loads((run_dir/'raw_manifest/manifest.json').read_text())
    assert any(x['provider']=='finlab_txf_calendar' and x['sha256'] for x in manifest)
    assert any(x.get('status')=='SKIPPED_FINLAB_NO_TX_ACTIVITY' for x in manifest)
    cache_parquet=list((tmp_path/'cache/fubon_txf').glob('*.parquet'))
    assert len(cache_parquet)==4
    # Repeat must reuse the exact immutable bytes of previous downloads.
    before={p.name:p.read_bytes() for p in cache_parquet}
    import src.fetch_finlab_calendar as cal
    import src.fetch_finlab as fl
    import src.fetch_fubon as fubon
    monkeypatch.setattr(cal,'fetch',lambda *args:pytest.fail('calendar re-fetched'))
    monkeypatch.setattr(fl,'fetch',lambda *args:pytest.fail('spot re-fetched'))
    monkeypatch.setattr(fubon,'fetch',lambda *args:pytest.fail('TXF re-fetched'))
    again=pipeline.run(cfg,tmp_path,rest=object())
    assert {p.name:p.read_bytes() for p in cache_parquet}==before
    again_manifest=json.loads((again/'raw_manifest/manifest.json').read_text())
    assert all(x['cache_hit'] for x in again_manifest
               if x.get('sha256') is not None)


def test_normal_spot_session_conflict_stops_even_with_tx_zero(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    inactive=pd.date_range('2022-01-10','2022-01-16').strftime('%Y-%m-%d')
    cfg,_=setup_fake_live(monkeypatch,inactive,spot_conflict=True)
    with pytest.raises(RuntimeError,match='sanitized diagnostics'):
        pipeline.run(cfg,tmp_path,rest=object())
    out=next((tmp_path/'runs').iterdir())
    info=json.loads((out/'run_info.json').read_text())
    assert info['status']=='FAILED'
    assert info['error_stage']=='FUBON_FETCH'
    row=pd.read_csv(out/'diagnostics/fubon_calendar_alignment.csv')
    assert row.loc[row.start=='2022-01-10','decision'].iloc[0]=='BLOCKED_SOURCE_CONFLICT'


def test_futures_activity_full_week_always_requests_api(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    import src.fetch_fubon as fubon
    inactive=pd.date_range('2022-01-10','2022-01-16').strftime('%Y-%m-%d')
    cfg,_=setup_fake_live(monkeypatch,inactive,tx_activity_override=['2022-01-11'])
    def fail_week(*args):
        if args[1]=='2022-01-10':
            raise RuntimeError('synthetic vendor outage')
        return generate()[0].iloc[:4].copy()
    monkeypatch.setattr(fubon,'fetch',fail_week)
    with pytest.raises(RuntimeError,match='sanitized diagnostics'):
        pipeline.run(cfg,tmp_path,rest=object())
    out=next((tmp_path/'runs').iterdir())
    info=json.loads((out/'run_info.json').read_text())
    assert info['error_stage']=='FUBON_FETCH'
    alignment=pd.read_csv(out/'diagnostics/fubon_calendar_alignment.csv')
    assert alignment.loc[alignment.start=='2022-01-10','decision'].iloc[0]=='REQUEST_FUBON_ACTIVE_WEEK'


def test_fail_closed_if_calendar_provider_rejects(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    import src.fetch_finlab_calendar as cal
    cfg,_=setup_fake_live(monkeypatch)
    monkeypatch.setattr(cal,'fetch',
        lambda *args:(_ for _ in ()).throw(RuntimeError('API_UNAVAILABLE')))
    with pytest.raises(RuntimeError,match='sanitized diagnostics'):
        pipeline.run(cfg,tmp_path,rest=object())
    info=json.loads(next((tmp_path/'runs').iterdir()).joinpath('run_info.json').read_text())
    assert info['error_stage']=='FINLAB_TX_CALENDAR_FETCH'
    assert info['status']=='FAILED'
