"""v0.1.3 QA classification: no fabricated market evidence."""
import pandas as pd
import pytest

from src.config import load
from src.synthetic import generate
from src.expiry_calendar import verified_expiry_contract, scheduled_monthly_expiry
from src.build_event_dataset import build
from src.quality_audit import audit_events, write_quality_report
from src.minute_gaps import missing_minute_intervals

def fixture():
    bars,spot=generate()
    first=spot.date.iloc[0]
    cfg={**load(),'mode':'validation','start':first,'end':first}
    return bars,spot,cfg

def add_marker(bars, day, which='day', price=None, volume=0):
    d=bars[(bars.session=='regular')&
           (bars.timestamp==pd.Timestamp(day+' 13:44',tz='Asia/Taipei'))].iloc[0]
    n=bars[(bars.session=='afterhours')&
           (bars.timestamp==pd.Timestamp(day,tz='Asia/Taipei')+
                                   pd.Timedelta(days=1,hours=4,minutes=59))].iloc[0]
    reference=d if which=='day' else n
    marker=reference.copy()
    marker['timestamp']=(pd.Timestamp(day+' 13:45',tz='Asia/Taipei')
                         if which=='day' else n.timestamp+pd.Timedelta(minutes=1))
    for key in ('open','high','low','close'):
        marker[key]=reference.close if price is None else price
    marker['volume']=volume
    return pd.concat([bars,pd.DataFrame([marker])],ignore_index=True)

def test_expiry_dates_verified():
    assert verified_expiry_contract('2026-07-15')=='202607'
    assert verified_expiry_contract('2026-08-19')=='202608'
    assert verified_expiry_contract('2026-09-16')=='202609'
    assert scheduled_monthly_expiry('202607')=='2026-07-15'
    assert verified_expiry_contract('2026-07-16') is None

def test_expiring_contract_1330_then_next_month_night_is_excluded():
    day='2026-07-15'
    ts=lambda suffix:pd.Timestamp(day+' '+suffix,tz='Asia/Taipei')
    bars=pd.DataFrame([
        dict(timestamp=ts('08:45'),session='regular',contract_month='202607',
             open=100,high=100,low=100,close=100,volume=5),
        dict(timestamp=ts('13:29'),session='regular',contract_month='202607',
             open=100,high=100,low=100,close=100,volume=5),
        dict(timestamp=ts('15:00'),session='afterhours',contract_month='202608',
             open=101,high=101,low=101,close=101,volume=5),
        dict(timestamp=ts('15:00')+pd.Timedelta(hours=13,minutes=59),
             session='afterhours',contract_month='202608',
             open=102,high=102,low=102,close=102,volume=5),
    ])
    spot=pd.DataFrame([
        dict(date='2026-07-15',open=100,close=101,adjustment_verified=True,corporate_action_boundary=False),
        dict(date='2026-07-16',open=102,close=103,adjustment_verified=True,corporate_action_boundary=False),
    ])
    cfg={**load(),'mode':'validation','start':day,'end':day}
    events,qa=build(bars,spot,cfg,return_diagnostics=True)
    e=events.iloc[0]
    assert e.txf_day_close_timestamp.strftime('%H:%M')=='13:29'
    assert e.txf_day_contract_month=='202607' and e.txf_night_contract_month=='202608'
    assert e.data_quality_status=='EXCLUDED'
    assert 'EXPIRY_CONTRACT_ROLLOVER_EXCLUSION' in e.exclusion_reason
    assert pd.isna(e.get('txf_overnight_return',float('nan')))
    gaps=missing_minute_intervals(bars,events,cfg)
    day_gaps=gaps[gaps.session=='regular']
    assert set(day_gaps.expected_session_minutes)=={285}
    assert day_gaps.missing_minutes.sum()==283
    _,daily,monthly,_,status=audit_events(bars,spot,events,qa,cfg)
    assert daily.iloc[0].regular_nominal_bars==285
    assert monthly.iloc[0].expiry_day_events==1
    assert status=='REVIEW_REQUIRED'

def test_unverified_flat_boundary_stays_excluded():
    bars,spot,cfg=fixture()
    bars=add_marker(bars,cfg['start'])
    cfg={**cfg,'close_policy':'strict'}
    events,qa=build(bars,spot,cfg,return_diagnostics=True)
    assert 'UNVERIFIED_REGULAR_1345_BOUNDARY' in events.iloc[0].exclusion_reason
    assert events.iloc[0].data_quality_status=='EXCLUDED'
    assert len(qa)==1 and qa.iloc[0].volume==0

def test_approved_flat_boundary_can_be_retained_with_warning():
    bars,spot,cfg=fixture()
    bars=add_marker(bars,cfg['start'])
    cfg={**cfg,'boundary_semantics_verified':True,
         'boundary_evidence_reference':'https://example.com/reviewed-provider-document'}
    events,qa=build(bars,spot,cfg,return_diagnostics=True)
    e=events.iloc[0]
    assert e.data_quality_status=='VALID'
    assert e.exclusion_reason==''
    assert 'ZERO_VOLUME_BOUNDARY_IGNORED' in e.boundary_warning_codes
    details,daily,monthly,reason,status=audit_events(bars,spot,events,qa,cfg)
    assert status=='REVIEW_REQUIRED'  # Zero-volume boundary remains a QA anomaly
    assert details.iloc[0].audit_status=='PASS'
    assert monthly.iloc[0].boundary_warning_events==1

def test_verified_evidence_cannot_override_trade_or_price_conflict():
    bars,spot,cfg=fixture()
    cfg={**cfg,'close_policy':'strict','boundary_semantics_verified':True,
         'boundary_evidence_reference':'https://example.com/reviewed-provider-document'}
    for volume,price in [(1,None),(0,999)]:
        data=add_marker(bars,cfg['start'],volume=volume,price=price)
        ev,_=build(data,spot,cfg,return_diagnostics=True)
        assert ev.iloc[0].data_quality_status=='EXCLUDED'

def test_night_0500_unverified_and_verified():
    bars,spot,cfg=fixture()
    data=add_marker(bars,cfg['start'],which='night')
    ev,_=build(data,spot,{**cfg,'close_policy':'strict'},return_diagnostics=True)
    assert 'UNVERIFIED_AFTERHOURS_0500_BOUNDARY' in ev.iloc[0].exclusion_reason
    cfg={**cfg,'boundary_semantics_verified':True,
         'boundary_evidence_reference':'https://example.com/reviewed-provider-document'}
    ev,_=build(data,spot,cfg,return_diagnostics=True)
    assert ev.iloc[0].data_quality_status=='VALID'

def test_minute_gaps_not_imputed():
    bars,spot,cfg=fixture()
    ev,_=build(bars,spot,cfg,return_diagnostics=True)
    gaps=missing_minute_intervals(bars,ev,cfg)
    assert not gaps.empty
    assert {'missing_start','missing_end','missing_minutes',
            'minutes_before_session_close','within_last_15_minutes'}.issubset(gaps)
    assert gaps[gaps.session=='regular'].missing_minutes.sum()==297
    assert gaps[gaps.session=='afterhours'].missing_minutes.sum()==838
    assert gaps.missing_minutes.min()>0

def test_missing_evidence_rejected():
    with pytest.raises(ValueError,match='reviewed HTTPS'):
        load(boundary_semantics_verified=True,boundary_evidence_reference='')

def test_audit_writes_new_outputs(tmp_path):
    bars,spot,cfg=fixture()
    ev,qa=build(bars,spot,cfg,return_diagnostics=True)
    for folder in ('tables','reports'):
        (tmp_path/folder).mkdir()
    status,tables=write_quality_report(tmp_path,ev,qa,bars,spot,cfg,
                     {'data_label':'SYNTHETIC_SMOKE_ONLY','git_sha':'FIXTURE'})
    assert status=='PASS'
    for name in ('boundary_audit','missing_minute_intervals','classification_comparison'):
        assert (tmp_path/'tables'/f'{name}.csv').exists()
    assert 'missing_minute_intervals' in tables
    assert (tables['classification_comparison']['basis']
            =='INFERRED_FROM_V013_RULES_NOT_ARCHIVED_RUN').all()
