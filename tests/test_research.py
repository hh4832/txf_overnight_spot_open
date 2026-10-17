from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from src.config import load
from src.synthetic import generate
from src.returns import compute
from src.session_alignment import session_start,last_bar
from src.trading_calendar import next_spot_day,gap_flags
from src.contract_rollover import consistent
from src.fetch_finlab import normalize as fin_normalize
from src.fetch_fubon import normalize,fetch
from src.conditional_analysis import historical_bins
from src.statistics import oos
from src.build_event_dataset import build
from src.cache import Cache
from src.pipeline import run
from src.drive_io import validate_folder

@pytest.fixture
def cfg(): return load()


def test_returns():
    r=compute(100,98,100,99,101)
    assert r['txf_overnight_return']==pytest.approx(-.02)
    assert 1+r['spot_total_return']==pytest.approx((1+r['spot_opening_gap'])*(1+r['spot_intraday_return']))
    with pytest.raises(ValueError):compute(0,1,1,1,1)

@pytest.mark.parametrize('stamp,expected',[('2026-10-16 15:00','2026-10-16'),('2026-10-17 04:59','2026-10-16')])
def test_cross_midnight(stamp,expected):
    assert session_start(pd.Timestamp(stamp,tz='Asia/Taipei'),'afterhours')==expected


def test_naive():
    with pytest.raises(ValueError): session_start(pd.Timestamp('2026-10-16'),'regular')


def test_calendar():
    assert next_spot_day('2026-10-16',['2026-10-16','2026-10-19'])=='2026-10-19'
    assert gap_flags('2026-10-16','2026-10-19')==(True,False)
    assert next_spot_day('2026-10-08',['2026-10-08','2026-10-12'])=='2026-10-12'
    assert gap_flags('2026-10-08','2026-10-12')==(True,True)


def test_missing_closing_minute():
    f=pd.DataFrame({'timestamp':[pd.Timestamp('2026-10-16 13:43',tz='Asia/Taipei')]})
    assert last_bar(f,'2026-10-16','13:45',1) is not None
    assert last_bar(f,'2026-10-16','13:45',0) is None


def test_rollover(cfg):
    bars,spot=generate();cfg={**cfg,'start':spot.date.iloc[0],'end':spot.date.iloc[0]}
    bars.loc[(bars.timestamp.dt.strftime('%Y-%m-%d')==spot.date.iloc[0])&(bars.session=='regular'),'contract_month']='202211'
    event=build(bars,spot,cfg).iloc[0]
    assert event.rollover_flag and 'CONTRACT_MISMATCH' in event.exclusion_reason
    assert not consistent('1!','1!')


def test_split():
    idx=pd.date_range('2025-06-10',periods=3)
    adj=pd.Series([25.,25.,26.],index=idx);raw=pd.Series([100.,25.,26.],index=idx)
    df=fin_normalize(adj,adj,raw,raw)
    assert df.adjustment_verified.all() and df.corporate_action_boundary.iloc[1]
    with pytest.raises(ValueError):fin_normalize(adj,adj,raw,adj)


def test_future_quantiles():
    x=pd.Series(np.arange(400,dtype=float));a=historical_bins(x,30)
    x.iloc[200:]=1e6;b=historical_bins(x,30)
    pd.testing.assert_series_equal(a.iloc[:200],b.iloc[:200])
    assert a.iloc[:30].isna().all()


def test_chronology(cfg):
    bars,spot=generate();cfg={**cfg,'start':spot.date.min(),'end':spot.date.iloc[-2]}
    events=build(bars,spot,cfg);pred=oos(events[events.data_quality_status=='VALID'],{**cfg,'initial_train':30})
    assert (pred.train_last_date<pred.test_date).all()


def test_api_errors():
    for payload in [{},{'data':[]}]:
        with pytest.raises(ValueError):normalize(payload,'regular')
    def broken(**kw): raise RuntimeError('SECRET_DO_NOT_LEAK')
    rest=SimpleNamespace(historical=SimpleNamespace(candles=broken))
    with pytest.raises(RuntimeError) as e:fetch(rest,'2026-10-01','2026-10-02',0)
    assert 'SECRET' not in str(e.value)


def test_cache(tmp_path):
    cache=Cache(tmp_path);calls=[]
    def provider(): calls.append(1);return pd.DataFrame({'x':[1]})
    cache.get('p',{'d':1},provider);cache.get('p',{'d':1},provider)
    assert len(calls)==1
    next(tmp_path.rglob('*.parquet')).write_bytes(b'bad')
    with pytest.raises(ValueError):cache.get('p',{'d':1},provider)


def test_drive_reject():
    with pytest.raises(ValueError):validate_folder(None,'wrong')


def test_deterministic():
    a,b=generate();c,d=generate();pd.testing.assert_frame_equal(a,c);pd.testing.assert_frame_equal(b,d)


def test_full_requires_confirmation():
    with pytest.raises(ValueError):load(mode='full')


def test_smoke(tmp_path,cfg):
    out=run(cfg,tmp_path)
    import json
    info=json.loads((out/'run_info.json').read_text())
    assert info['status']=='SMOKE_COMPLETE'
    assert info['research_decision']=='DATA_INSUFFICIENT'
    assert (out/'reports/summary.xlsx').exists()
    assert len(list((out/'figures').glob('*.png')))==5


def test_contract_change_inside_session(cfg):
    bars,spot=generate();day=spot.date.iloc[0]
    bars.loc[0,'contract_month']='202211'
    events=build(bars,spot,{**cfg,'start':day,'end':day})
    assert 'WITHIN_SESSION_CONTRACT_CHANGE' in events.iloc[0].exclusion_reason


def test_zero_volume_close_not_valid(cfg):
    bars,spot=generate();day=spot.date.iloc[0]
    mask=(bars.timestamp==pd.Timestamp(day+' 13:44',tz='Asia/Taipei'))
    bars.loc[mask,'volume']=0
    events=build(bars,spot,{**cfg,'start':day,'end':day})
    assert 'MISSING_OR_STALE_DAY_CLOSE' in events.iloc[0].exclusion_reason


def test_duplicate_partition_rejected(cfg):
    bars,spot=generate()
    day=spot.date.iloc[0]
    events,qa=build(pd.concat([bars,bars.iloc[:1]]),spot,
                    {**cfg,'start':day,'end':day},return_diagnostics=True)
    assert 'DUPLICATE_TIMESTAMP' in events.iloc[0].exclusion_reason
    assert len(qa)==2


def test_adjustment_missing_excluded(cfg):
    bars,spot=generate();spot['adjustment_verified']=False
    day=spot.date.iloc[0]
    events=build(bars,spot,{**cfg,'start':day,'end':day})
    assert events.iloc[0].exclusion_reason=='ADJUSTMENT_UNVERIFIED'


def test_schema_accepts_only_real_month():
    record={'date':'2026-10-16T13:44:00+08:00','contractMonth':'202610',
            'open':100,'high':100,'low':100,'close':100,'volume':1}
    f=normalize({'data':[record]},'regular')
    assert str(f.timestamp.dt.tz)=='Asia/Taipei'
    for field,value in [('contractMonth','1!'),('date','2026-10-16T13:44:00')]:
        with pytest.raises(ValueError):normalize({'data':[{**record,field:value}]},'regular')


def test_live_failure_no_synthetic_fallback(tmp_path,cfg,monkeypatch):
    import src.fetch_finlab
    def fail(*args):raise RuntimeError('SECRET_HIDDEN')
    monkeypatch.setattr(src.fetch_finlab,'fetch',fail)
    with pytest.raises(RuntimeError) as error:run({**cfg,'mode':'pilot'},tmp_path)
    assert 'SECRET_HIDDEN' not in str(error.value)
    import json
    info=json.loads(next(tmp_path.rglob('run_info.json')).read_text())
    assert info['status']=='FAILED' and info['data_label']=='LIVE_DATA'
    assert not list(tmp_path.rglob('summary.md'))


def test_notebook_python_compiles():
    import json
    from pathlib import Path
    notebook=json.loads(Path('notebooks/run_txf_overnight_spot_open.ipynb').read_text())
    for cell in notebook['cells']:
        if cell['cell_type']=='code':compile(''.join(cell['source']),'<notebook>','exec')
