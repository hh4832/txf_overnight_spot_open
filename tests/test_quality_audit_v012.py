"""Independent event price/clock audit regression tests (SYNTHETIC_SMOKE_ONLY)."""
import pandas as pd

from src.build_event_dataset import build
from src.config import load
from src.quality_audit import audit_events, write_quality_report
from src.synthetic import generate


def sample():
    bars, spot = generate()
    first, last = spot.date.iloc[0], spot.date.iloc[4]
    cfg = {**load(), 'mode': 'validation', 'start': first, 'end': last}
    events, qa = build(bars, spot, cfg, return_diagnostics=True)
    return bars, spot, cfg, events, qa


def test_recomputes_all_prices_and_clocks():
    bars, spot, cfg, events, qa = sample()
    details, daily, monthly, reasons, state = audit_events(bars, spot, events, qa, cfg)
    assert state == 'PASS'
    assert (details.audit_status == 'PASS').all()
    assert details.day_bar_timestamp.dt.strftime('%H:%M').eq('13:44').all()
    assert details.night_bar_timestamp.dt.strftime('%H:%M').eq('04:59').all()
    assert len(daily) == 5 and len(monthly) == 1 and reasons.empty
    assert monthly.iloc[0].valid_events == 5


def test_price_mismatch_fails_independent_audit():
    bars, spot, cfg, events, qa = sample()
    events.loc[0, 'txf_overnight_return'] += .005
    details, _, _, _, status = audit_events(bars, spot, events, qa, cfg)
    assert status == 'BLOCKED'
    assert details.iloc[0].audit_status == 'MISMATCH'
    assert 'TXF_OVERNIGHT_RETURN_MISMATCH' in details.iloc[0].audit_issue_codes


def test_contract_mismatch_fails_independent_audit():
    bars, spot, cfg, events, qa = sample()
    events.loc[0, 'txf_night_contract_month'] = '209912'
    details, _, _, _, status = audit_events(bars, spot, events, qa, cfg)
    assert status == 'BLOCKED'
    assert 'NIGHT_CONTRACT_MISMATCH' in details.iloc[0].audit_issue_codes


def test_clock_mismatch_fails_independent_audit():
    bars, spot, cfg, events, qa = sample()
    events.loc[0, 'txf_night_close_timestamp'] = pd.Timestamp(
        '2022-01-05 04:59', tz='Asia/Taipei')
    details, _, _, _, status = audit_events(bars, spot, events, qa, cfg)
    assert status == 'BLOCKED'
    assert 'NIGHT_TIMESTAMP_MISMATCH' in details.iloc[0].audit_issue_codes


def test_excluded_event_not_passed_as_clean():
    bars, spot, cfg, events, qa = sample()
    idx = bars.index[bars.timestamp == pd.Timestamp(
        cfg['start']+' 13:44', tz='Asia/Taipei')][0]
    bars.loc[idx, 'volume'] = 0
    events, qa = build(bars, spot, cfg, return_diagnostics=True)
    details, daily, monthly, reasons, status = audit_events(bars, spot, events, qa, cfg)
    assert status == 'REVIEW_REQUIRED'
    assert details.iloc[0].audit_status == 'EXCLUDED'
    assert 'MISSING_OR_STALE_DAY_CLOSE' in reasons.reason.tolist()
    assert monthly.iloc[0].excluded_events >= 1


def test_boundary_in_scope_requires_review():
    bars, spot, cfg, _, _ = sample()
    b = bars.iloc[0].copy()
    b['timestamp'] = pd.Timestamp(cfg['start']+' 13:45', tz='Asia/Taipei')
    bars = pd.concat([bars, pd.DataFrame([b])], ignore_index=True)
    events, qa = build(bars, spot, cfg, return_diagnostics=True)
    _, daily, _, _, status = audit_events(bars, spot, events, qa, cfg)
    assert status == 'REVIEW_REQUIRED'
    assert daily.iloc[0].raw_anomalies_in_scope == 1


def test_report_has_no_statistical_claims(tmp_path):
    bars, spot, cfg, events, qa = sample()
    for folder in ('tables','reports'):
        (tmp_path/folder).mkdir()
    info = {'data_label':'SYNTHETIC_SMOKE_ONLY','git_sha':'TEST_ONLY'}
    status, tables = write_quality_report(tmp_path, events, qa, bars, spot, cfg, info)
    report = (tmp_path/'reports/data_quality_audit.md').read_text()
    assert status == 'PASS'
    assert 'No H1/H2/H3 inference' in report
    assert 'SYNTHETIC_SMOKE_ONLY' in report
    assert (tmp_path/'reports/summary.xlsx').exists()
    display = pd.read_excel(tmp_path/'reports/summary.xlsx',sheet_name='event_price_audit')
    assert '+08:00' in display.loc[0,'day_bar_timestamp']
    assert len(tables) == 7


def test_empty_sample_requests_review():
    bars, spot, cfg, events, qa = sample()
    empty = events.iloc[:0].copy()
    details, _, _, _, status = audit_events(bars, spot, empty, qa, cfg)
    assert details.empty
    assert status == 'REVIEW_REQUIRED'
