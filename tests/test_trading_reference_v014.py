"""v0.1.4 trading-reference and adaptive-close regression tests.

Synthetic fixtures test code invariants only, not market predictive performance.
"""
import numpy as np
import pandas as pd
import pytest
from src.synthetic import generate
from src.config import load
from src.build_event_dataset import build
from src.quality_audit import audit_events
from src.close_policy import choose_close
from src.expiry_calendar import expiry_contract_for_day,calendar_confidence
from src.trading_reference import trading_reference,LABELS


def prepare():
    bars,spot=generate()
    day=spot.date.iloc[0]
    return bars,spot,{**load(),'start':day,'end':day}


def boundary(bars,day,session='regular',volume=1,delta=10,contract=None):
    key=(bars.session==session)
    tm=(pd.Timestamp(day+' 13:44',tz='Asia/Taipei') if session=='regular'
        else pd.Timestamp(day+' 04:59',tz='Asia/Taipei')+pd.Timedelta(days=1))
    src=bars.loc[key & (bars.timestamp==tm)].iloc[0].copy()
    src['timestamp']=src['timestamp']+pd.Timedelta(minutes=1)
    src['close']=src['open']=src['high']=src['low']=float(src.close)+delta
    src['volume']=volume
    if contract: src['contract_month']=contract
    return pd.concat([bars,pd.DataFrame([src])],ignore_index=True)


def test_adaptive_day_prefers_1345_and_fixed_comparator():
    bars,spot,cfg=prepare(); day=cfg['start']
    base=build(bars,spot,cfg).iloc[0]
    altered=boundary(bars,day)
    events,qa=build(altered,spot,cfg,return_diagnostics=True)
    ev=events.iloc[0]
    assert ev.data_quality_status=='VALID'
    assert ev.day_close_rule=='ADAPTIVE_BOUNDARY'
    assert ev.txf_day_close_timestamp.strftime('%H:%M')=='13:45'
    assert ev.txf_overnight_return!=base.txf_overnight_return
    assert ev.txf_overnight_return_fixed==pytest.approx(base.txf_overnight_return)
    assert ev.txf_adaptive_minus_fixed_bp==pytest.approx(
        (ev.txf_overnight_return-base.txf_overnight_return)*10000)
    assert 'INCLUDED_ADAPTIVE_CLOSE' in qa.decision.tolist()
    detail,*_,state=audit_events(altered,spot,events,qa,cfg)
    assert state=='PASS'
    assert detail.iloc[0].audit_status=='PASS'


def test_adaptive_night_prefers_0500():
    bars,spot,cfg=prepare(); day=cfg['start']
    altered=boundary(bars,day,session='afterhours',delta=-8)
    e,qa=build(altered,spot,cfg,return_diagnostics=True)
    assert e.iloc[0].data_quality_status=='VALID'
    assert e.iloc[0].night_close_rule=='ADAPTIVE_BOUNDARY'
    assert e.iloc[0].txf_night_close_timestamp.strftime('%H:%M')=='05:00'
    assert e.iloc[0].txf_adaptive_minus_fixed_bp!=0


def test_strict_mode_preserves_old_quarantine():
    bars,spot,cfg=prepare(); day=cfg['start']
    data=boundary(bars,day)
    e,_=build(data,spot,{**cfg,'close_policy':'strict'},return_diagnostics=True)
    assert e.iloc[0].data_quality_status=='EXCLUDED'
    assert 'UNVERIFIED_REGULAR_1345_BOUNDARY' in e.iloc[0].exclusion_reason


def test_no_stale_close_fallback():
    bars,spot,cfg=prepare()
    day=cfg['start']
    bars=bars[bars.timestamp!=pd.Timestamp(day+' 13:44',tz='Asia/Taipei')]
    e=build(bars,spot,cfg).iloc[0]
    assert e.data_quality_status=='EXCLUDED'
    assert 'MISSING_EXACT_CLOSING_BAR' in e.exclusion_reason
    assert 'MISSING_OR_STALE_DAY_CLOSE' in e.exclusion_reason


def test_invalid_adaptive_bar_blocks_instead_of_falling_back():
    bars,spot,cfg=prepare()
    data=boundary(bars,cfg['start'],contract='209912')
    e=build(data,spot,cfg).iloc[0]
    assert e.data_quality_status=='EXCLUDED'
    assert 'BOUNDARY_CONTRACT_MISMATCH' in e.exclusion_reason
    data=boundary(bars,cfg['start'],volume=0)
    e=build(data,spot,cfg).iloc[0]
    assert e.data_quality_status=='VALID'
    assert e.day_close_rule=='FIXED_LAST_MINUTE'


def test_missing_fixed_comparator_is_reported_not_filled():
    bars,spot,cfg=prepare(); day=cfg['start']
    data=boundary(bars,day)
    data=data[data.timestamp!=pd.Timestamp(day+' 13:44',tz='Asia/Taipei')]
    e=build(data,spot,cfg).iloc[0]
    assert e.data_quality_status=='VALID'
    assert pd.isna(e.txf_overnight_return_fixed)
    assert e.day_close_rule=='ADAPTIVE_BOUNDARY'


def test_dynamic_calendar_has_explicit_confidence():
    assert expiry_contract_for_day('2023-03-15',{})=='202303'
    assert calendar_confidence('2023-03-15',{})=='SCHEDULED_THIRD_WEDNESDAY_UNVERIFIED'
    cfg={'expiry_date_overrides':{'202303':'2023-03-14'}}
    assert expiry_contract_for_day('2023-03-14',cfg)=='202303'
    assert expiry_contract_for_day('2023-03-15',cfg) is None
    assert calendar_confidence('2023-03-14',cfg)=='EXCHANGE_REVIEWED_OVERRIDE'


def test_trading_reference_predeclared_bins_and_no_oos_shortcut():
    f=pd.DataFrame(dict(signal_trade_date=pd.bdate_range('2020-01-01',periods=6).strftime('%Y-%m-%d'),
        txf_overnight_return=[-.011,-.007,-.001,.001,.006,.011],
        txf_overnight_return_fixed=[-.01,-.005,0,.001,.006,.012],
        txf_adaptive_minus_fixed_bp=[-10,-20,-10,0,0,-10],
        day_close_rule=['FIXED_LAST_MINUTE']*6,
        night_close_rule=['FIXED_LAST_MINUTE']*6,
        spot_opening_gap=[-.01,-.005,-.001,.001,.005,.01],
        spot_intraday_return=[.002,.003,.004,-.001,-.002,-.003]))
    t=trading_reference(f,{'initial_train':252})
    assert t['trading_reference'].scenario.tolist()==LABELS
    assert t['trading_reference'].n.tolist()==[1]*6
    assert (t['trading_reference_holdout'].status=='NOT_EVALUATED_INSUFFICIENT_HISTORY').all()
    assert t['close_policy_comparison'].iloc[0].paired_fixed_comparator==6


def test_trading_reference_future_outcomes_do_not_rewrite_past_data():
    rng=np.random.default_rng(20261017)
    f=pd.DataFrame(dict(
        signal_trade_date=pd.bdate_range('2020-01-01',periods=265).strftime('%Y-%m-%d'),
        txf_overnight_return=rng.normal(0,.01,265),
        txf_overnight_return_fixed=rng.normal(0,.01,265),
        txf_adaptive_minus_fixed_bp=rng.normal(0,1,265),
        day_close_rule=['FIXED_LAST_MINUTE']*265,
        night_close_rule=['FIXED_LAST_MINUTE']*265,
        spot_opening_gap=rng.normal(0,.01,265),
        spot_intraday_return=rng.normal(0,.01,265)))
    before=trading_reference(f,{'initial_train':252})
    mutated=f.copy()
    mutated.loc[252:,'spot_opening_gap']=100
    after=trading_reference(mutated,{'initial_train':252})
    assert before['trading_reference_holdout'].holdout_from.iloc[0]==f.signal_trade_date.iloc[252]
    assert before['trading_reference_holdout'].train_last_date.iloc[0]==f.signal_trade_date.iloc[251]
    # Chronology of the holdout is unchanged by a future value revision.
    assert after['trading_reference_holdout'].train_last_date.iloc[0]==f.signal_trade_date.iloc[251]
