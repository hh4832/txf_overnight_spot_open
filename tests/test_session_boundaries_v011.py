"""Regression tests for strict quarantine of provider boundary records."""
import pandas as pd
import pytest
from src.config import load
from src.synthetic import generate
from src.session_alignment import classify_session, session_start
from src.build_event_dataset import build


def bar(ts, session='regular'):
    return dict(timestamp=pd.Timestamp(ts,tz='Asia/Taipei'),session=session,
                contract_month='202609',open=100,high=100,low=100,close=100,volume=1)


def test_boundary_records_not_silent_fills():
    assert classify_session(bar('2026-09-15 13:44')['timestamp'],'regular') == ('2026-09-15',None)
    assert classify_session(bar('2026-09-15 13:45')['timestamp'],'regular') == (
        '2026-09-15','UNVERIFIED_REGULAR_1345_BOUNDARY')
    assert classify_session(bar('2026-09-16 04:59')['timestamp'],'afterhours') == ('2026-09-15',None)
    assert classify_session(bar('2026-09-16 05:00')['timestamp'],'afterhours') == (
        '2026-09-15','UNVERIFIED_AFTERHOURS_0500_BOUNDARY')
    with pytest.raises(ValueError):
        session_start(bar('2026-09-15 13:45')['timestamp'],'regular')


def test_outside_range_anomaly_does_not_block_pilot():
    bars,spot=generate()
    bars=pd.concat([bars,pd.DataFrame([bar('2026-09-15 13:45')])],ignore_index=True)
    first=spot.date.iloc[0]
    ev,qa=build(bars,spot,{**load(),'start':first,'end':first},return_diagnostics=True)
    assert ev.iloc[0].data_quality_status=='VALID'
    assert len(qa)==1
    assert qa.iloc[0].decision=='QUARANTINE_OUTSIDE_RANGE'


def test_inside_range_anomaly_excludes_event():
    bars,spot=generate();first=spot.date.iloc[0]
    bars=pd.concat([bars,pd.DataFrame([bar(first+' 13:45')])],ignore_index=True)
    ev,qa=build(bars,spot,{**load(close_policy='strict'),'start':first,'end':first},return_diagnostics=True)
    assert ev.iloc[0].data_quality_status=='EXCLUDED'
    assert 'UNVERIFIED_REGULAR_1345_BOUNDARY' in ev.iloc[0].exclusion_reason
    assert qa.iloc[0].affects_research_event


def test_friday_night_session_date():
    day,code=classify_session(pd.Timestamp('2026-10-17 04:59',tz='Asia/Taipei'),'afterhours')
    assert (day,code)==('2026-10-16',None)
