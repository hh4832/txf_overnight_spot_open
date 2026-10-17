"""Exact-only Fubon duplicate candle regressions and cache provenance.

All OHLCV in these tests is fabricated. No real market performance is inferred.
"""
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from src.cache import Cache
from src.config import load
from src.fetch_fubon import fetch, normalize
from src.fubon_candle_dedup import reconcile_identical_candles
from src.synthetic import generate


def candle(ts='2019-09-27T15:00:00+08:00',month='201910',price=10835,volume=503):
    return dict(date=ts,contractMonth=month,open=price,high=price,
                low=price,close=price,volume=volume)


def test_provider_identical_night_duplicates_removed_without_repricing():
    base=candle()
    later=candle(ts='2019-09-27T15:01:00+08:00',price=10836)
    original=[base,dict(base),later,dict(later)]
    f=normalize({'data':original},'afterhours')
    assert len(f)==2
    assert f['close'].tolist()==[10835,10836]
    assert f['volume'].sum()==1006
    assert f.timestamp.dt.tz is not None
    assert f.attrs['fubon_duplicate_audit']=={
        'rows_before':4,'rows_after':2,'exact_duplicates_removed':2,
        'duplicated_timestamp_groups':2,'conflicting_timestamp_groups':0,
        'status':'EXACT_ONLY_VERIFIED'}


@pytest.mark.parametrize('field,new_value',[
    ('close',10834),('volume',504),('contractMonth','201911'),
    ('open',10834),('high',10836),('low',10834),
])
def test_provider_conflicting_same_timestamp_fails(field,new_value):
    base=candle()
    bad={**base,field:new_value}
    if field=='close':
        bad['low']=10834
    if field=='open':
        bad['low']=10834
    f=pd.DataFrame([base,bad])
    with pytest.raises(ValueError,match='Conflicting duplicate TXF timestamp'):
        normalize({'data':f.to_dict('records')},'afterhours')


def test_different_timestamp_same_price_not_deleted():
    frame=normalize({'data':[candle(),candle('2019-09-27T15:01:00+08:00')]},
                    'afterhours')
    assert len(frame)==2


def test_fetch_session_audit_tracks_provider_raw_rows():
    regular=candle('2019-10-01T13:44:00+08:00')
    night=candle()
    resp={'regular':[regular], 'afterhours':[night,dict(night),dict(night)]}
    def candles(**kw):
        return {'data':resp[kw['session']]}
    rest=SimpleNamespace(historical=SimpleNamespace(candles=candles))
    f=fetch(rest,'2019-09-30','2019-10-06',spacing=0)
    assert len(f)==2
    audit=f.attrs['fubon_duplicate_audit']
    assert audit['raw_rows']==4
    assert audit['stored_rows']==2
    assert audit['within_fetch_duplicates_removed']==2
    assert audit['status']=='PROVIDER_RESPONSE_AUDITED'


def test_cross_week_identical_overlap_preserves_prices_and_blocks_conflicts():
    f=normalize({'data':[candle(),candle('2019-09-27T15:01:00+08:00',price=10836)]},
                'afterhours')
    combined=pd.concat([f,f.iloc[:1].copy()],ignore_index=True)
    result,stats=reconcile_identical_candles(combined)
    pd.testing.assert_frame_equal(result,f)
    assert stats['exact_duplicates_removed']==1
    assert stats['duplicated_timestamp_groups']==1
    for field,value in [('volume',999),('contract_month','201911'),('session','regular')]:
        bad=f.iloc[:1].copy()
        bad.loc[bad.index[0],field]=value
        with pytest.raises(ValueError,match='Conflicting duplicate'):
            reconcile_identical_candles(pd.concat([f,bad],ignore_index=True))


def test_cache_preserves_duplicate_counts_and_marks_legacy_unknown(tmp_path):
    row=normalize({'data':[candle()]},'afterhours')
    row.attrs['fubon_duplicate_audit']={
        'raw_rows':2,'stored_rows':1,
        'within_fetch_duplicates_removed':1,
        'duplicated_timestamp_groups':1,'status':'PROVIDER_RESPONSE_AUDITED'}
    cache=Cache(tmp_path)
    p={'start':'2019-09-30','end':'2019-10-06'}
    cache.get('fubon_txf',p,lambda:row)
    cache.get('fubon_txf',p,lambda:pytest.fail('No refetch allowed'))
    assert cache.manifest[0]['fubon_duplicate_audit']==cache.manifest[1]['fubon_duplicate_audit']
    assert cache.manifest[1]['cache_hit']
    old=Cache(tmp_path)
    old.get('fubon_txf',{'legacy':True},lambda:pd.DataFrame({'x':[1]}))
    old.get('fubon_txf',{'legacy':True},lambda:pytest.fail('No refetch allowed'))
    assert old.manifest[1]['fubon_duplicate_audit']['status']=='NOT_RECORDED_LEGACY_CACHE'
    assert old.manifest[1]['fubon_duplicate_audit']['raw_rows'] is None


def _integration_sources(monkeypatch,conflicting=False):
    import src.fetch_finlab as fl
    import src.fetch_fubon as fb
    bars,spot=generate()
    monkeypatch.setattr(fl,'fetch',lambda a,b:spot.copy())
    raw=bars.iloc[:150].copy()
    raw['source_date']=[d for d in spot.date.iloc[:30] for _ in range(5)]
    previous=raw[(raw.source_date=='2022-01-07') & (raw.session=='afterhours')].copy()
    calls=[]
    def provider(_rest,a,b,spacing):
        calls.append((a,b))
        part=raw.loc[raw.source_date.between(a,b)].copy()
        if a=='2022-01-10':
            appendix=previous.copy()
            if conflicting:
                appendix.iloc[0,appendix.columns.get_loc('volume')]+=1
            part=pd.concat([appendix,part],ignore_index=True)
        part=part.drop(columns='source_date').reset_index(drop=True)
        part.attrs['fubon_duplicate_audit']={
            'raw_rows':len(part),'stored_rows':len(part),
            'within_fetch_duplicates_removed':0,
            'duplicated_timestamp_groups':0,'status':'PROVIDER_RESPONSE_AUDITED'}
        return part
    monkeypatch.setattr(fb,'fetch',provider)
    cfg={**load(), 'mode':'validation','start':'2022-01-03','end':'2022-01-14'}
    return cfg,calls


def test_pipeline_cross_week_overlap_reported_and_cache_reused(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    import src.fetch_finlab as fl
    import src.fetch_fubon as fb
    cfg,calls=_integration_sources(monkeypatch)
    a=pipeline.run(cfg,tmp_path,rest=object())
    info=json.loads((a/'run_info.json').read_text())
    summary=pd.read_csv(a/'diagnostics/fubon_cross_partition_duplicate_audit.csv')
    parts=pd.read_csv(a/'diagnostics/fubon_partition_duplicate_audit.csv')
    assert info['status']!='FAILED'
    assert info['fubon_cross_partition_duplicates_removed']==2
    assert summary.iloc[0].exact_duplicates_removed==2
    assert len(parts)>=2 and parts.audit_status.eq('PROVIDER_RESPONSE_AUDITED').all()
    before={p.name:p.read_bytes() for p in (tmp_path/'cache/fubon_txf').glob('*.parquet')}
    monkeypatch.setattr(fl,'fetch',lambda *args:pytest.fail('Refetched FinLab cache'))
    monkeypatch.setattr(fb,'fetch',lambda *args:pytest.fail('Refetched Fubon cache'))
    b=pipeline.run(cfg,tmp_path,rest=object())
    after={p.name:p.read_bytes() for p in (tmp_path/'cache/fubon_txf').glob('*.parquet')}
    assert before==after and a!=b
    again=json.loads((b/'run_info.json').read_text())
    assert again['fubon_cross_partition_duplicates_removed']==2


def test_pipeline_cross_week_conflict_remains_fatal(tmp_path,monkeypatch):
    import src.pipeline as pipeline
    cfg,_=_integration_sources(monkeypatch,conflicting=True)
    with pytest.raises(RuntimeError,match='sanitized diagnostics'):
        pipeline.run(cfg,tmp_path,rest=object())
    out=next((tmp_path/'runs').iterdir())
    info=json.loads((out/'run_info.json').read_text())
    assert info['error_stage']=='FUBON_CROSS_PARTITION_DEDUP'
    assert info['status']=='FAILED'
    assert not (out/'processed/event_dataset.parquet').exists()
