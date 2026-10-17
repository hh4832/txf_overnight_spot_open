"""Independent event-level price, clock, and market-data QA.

Validation is observational only. This module must never change research
formulas, provider candles, raw cache, or statistical inference.
"""
from collections import Counter
from pathlib import Path
import json

import numpy as np
import pandas as pd

from .data_validation import inspect_bars
from .session_alignment import last_bar
from .trading_calendar import next_spot_day
from .returns import compute

PRICE_KEYS = ('txf_overnight_return', 'spot_opening_gap',
              'spot_intraday_return', 'spot_total_return')
NOMINAL_REGULAR_MINUTES = 300
NOMINAL_AFTERHOURS_MINUTES = 840


def _same(a, b):
    try:
        return bool(np.isclose(float(a), float(b), rtol=1e-10, atol=1e-12))
    except (ValueError, TypeError):
        return False


def _ts_equal(a, b):
    return pd.notna(a) and pd.notna(b) and pd.Timestamp(a) == pd.Timestamp(b)


def audit_events(raw_bars, spot, events, anomalies, cfg):
    """Rebuild independently from raw records, compare with stored events.

    Return event audit, daily coverage, monthly QA, reason counts, status.
    A detected price/time mismatch is a BLOCKED audit; ordinary excluded
    events remain explicit REVIEW_REQUIRED, not silently counted as passed.
    """
    clean, _, _, _ = inspect_bars(raw_bars, cfg['start'], cfg['end'])
    traded = clean[clean.volume > 0].copy()
    spot_by_date = spot.set_index('date', verify_integrity=True)
    records = []
    for _, ev in events.iterrows():
        day = ev['signal_trade_date']
        nxt = next_spot_day(day, spot_by_date.index)
        regular = traded[(traded.signal_date == day) & (traded.session == 'regular')]
        night = traded[(traded.signal_date == day) & (traded.session == 'afterhours')]
        night_end = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        dbar = last_bar(regular, day, '13:45', cfg['max_close_staleness_minutes'])
        nbar = last_bar(night, night_end, '05:00', cfg['max_close_staleness_minutes'])
        issues = []
        if ev['next_spot_trade_date'] != nxt:
            issues.append('NEXT_SPOT_DATE_MISMATCH')
        valid = ev['data_quality_status'] == 'VALID'
        if valid:
            if dbar is None or nbar is None or not nxt or day not in spot_by_date.index:
                issues.append('SOURCE_CLOSING_BAR_OR_SPOT_MISSING')
            else:
                for label, bar in (('day', dbar), ('night', nbar)):
                    if not _ts_equal(ev.get(f'txf_{label}_close_timestamp'), bar.timestamp):
                        issues.append(f'{label.upper()}_TIMESTAMP_MISMATCH')
                    if str(ev.get(f'txf_{label}_contract_month')) != str(bar.contract_month):
                        issues.append(f'{label.upper()}_CONTRACT_MISMATCH')
                    if not _same(ev.get(f'txf_{label}_close'), bar.close):
                        issues.append(f'{label.upper()}_PRICE_MISMATCH')
                if dbar.contract_month != nbar.contract_month:
                    issues.append('CONTRACT_ROLLOVER_NOT_EXCLUDED')
                if not (pd.Timestamp(f'{day} 08:45', tz='Asia/Taipei') <= dbar.timestamp
                        and dbar.timestamp + pd.Timedelta(minutes=1)
                        <= pd.Timestamp(f'{day} 13:45', tz='Asia/Taipei')):
                    issues.append('DAY_CLOSE_OUTSIDE_SESSION')
                if not (pd.Timestamp(f'{day} 15:00', tz='Asia/Taipei') <= nbar.timestamp
                        and nbar.timestamp + pd.Timedelta(minutes=1)
                        <= pd.Timestamp(f'{night_end} 05:00', tz='Asia/Taipei')):
                    issues.append('NIGHT_CLOSE_OUTSIDE_SESSION')
                if nbar.timestamp + pd.Timedelta(minutes=1) >= pd.Timestamp(
                        f'{nxt} 09:00', tz='Asia/Taipei'):
                    issues.append('PREDICTOR_NOT_AVAILABLE_BEFORE_OPEN')
                prev = spot_by_date.loc[day]
                following = spot_by_date.loc[nxt]
                if not bool(prev['adjustment_verified']) or not bool(following['adjustment_verified']):
                    issues.append('UNVERIFIED_ETF_ADJUSTMENT')
                checks = {'spot_prev_close': prev['close'],
                          'spot_next_open': following['open'],
                          'spot_next_close': following['close']}
                for key, expected in checks.items():
                    if not _same(ev.get(key), expected):
                        issues.append(f'{key.upper()}_MISMATCH')
                expected_returns = compute(dbar.close, nbar.close, prev['close'],
                                           following['open'], following['close'])
                for key in PRICE_KEYS:
                    if not _same(ev.get(key), expected_returns[key]):
                        issues.append(f'{key.upper()}_MISMATCH')
                if not _same(
                        (1 + ev.get('spot_opening_gap', np.nan)) *
                        (1 + ev.get('spot_intraday_return', np.nan)),
                        1 + ev.get('spot_total_return', np.nan)):
                    issues.append('RETURN_MULTIPLICATIVE_IDENTITY_FAILED')
        elif not ev.get('exclusion_reason'):
            issues.append('UNEXPLAINED_EXCLUDED_EVENT')
        status = 'MISMATCH' if issues else ('PASS' if valid else 'EXCLUDED')
        records.append({
            'signal_trade_date': day,
            'next_spot_trade_date': nxt,
            'data_quality_status': ev['data_quality_status'],
            'audit_status': status,
            'audit_issue_codes': '|'.join(sorted(set(issues))),
            'exclusion_reason': ev.get('exclusion_reason', ''),
            'day_bar_timestamp': dbar.timestamp if dbar is not None else pd.NaT,
            'night_bar_timestamp': nbar.timestamp if nbar is not None else pd.NaT,
            'day_contract_month': dbar.contract_month if dbar is not None else None,
            'night_contract_month': nbar.contract_month if nbar is not None else None,
            'day_close_source': dbar.close if dbar is not None else np.nan,
            'night_close_source': nbar.close if nbar is not None else np.nan,
            'spot_prev_close_source': (spot_by_date.loc[day, 'close']
                                       if day in spot_by_date.index else np.nan),
            'spot_next_open_source': (spot_by_date.loc[nxt, 'open']
                                      if nxt in spot_by_date.index else np.nan),
            'spot_next_close_source': (spot_by_date.loc[nxt, 'close']
                                       if nxt in spot_by_date.index else np.nan),
        })
    details = pd.DataFrame.from_records(records)
    if details.empty:
        details = pd.DataFrame(columns=[
            'signal_trade_date', 'next_spot_trade_date', 'data_quality_status',
            'audit_status', 'audit_issue_codes', 'exclusion_reason',
            'day_bar_timestamp', 'night_bar_timestamp',
            'day_contract_month', 'night_contract_month',
            'day_close_source', 'night_close_source',
            'spot_prev_close_source', 'spot_next_open_source',
            'spot_next_close_source'])

    # Nominal 300/840 bar counts are descriptive, not blanket exclusion rules:
    # expiry days, exchange interruptions, and vendor omissions need inspection.
    counts = clean.groupby(['signal_date', 'session']).size()
    zero = clean[clean.volume == 0].groupby(['signal_date', 'session']).size()
    in_scope = anomalies[anomalies.affects_research_event]
    anomaly_counts = in_scope.groupby('signal_trade_date').size()
    coverage = []
    for _, ev in events.iterrows():
        day = ev['signal_trade_date']
        r = int(counts.get((day, 'regular'), 0))
        n = int(counts.get((day, 'afterhours'), 0))
        coverage.append({
            'signal_trade_date': day,
            'regular_observed_bars': r,
            'regular_nominal_bars': NOMINAL_REGULAR_MINUTES,
            'regular_nominal_coverage': r / NOMINAL_REGULAR_MINUTES,
            'afterhours_observed_bars': n,
            'afterhours_nominal_bars': NOMINAL_AFTERHOURS_MINUTES,
            'afterhours_nominal_coverage': n / NOMINAL_AFTERHOURS_MINUTES,
            'regular_zero_volume': int(zero.get((day, 'regular'), 0)),
            'afterhours_zero_volume': int(zero.get((day, 'afterhours'), 0)),
            'raw_anomalies_in_scope': int(anomaly_counts.get(day, 0)),
            'data_quality_status': ev['data_quality_status'],
            'exclusion_reason': ev.get('exclusion_reason', ''),
            'weekend_flag': bool(ev['weekend_flag']),
            'holiday_gap_flag': bool(ev['holiday_gap_flag']),
            'rollover_flag': bool(ev['rollover_flag']),
        })
    daily = pd.DataFrame(coverage, columns=[
        'signal_trade_date', 'regular_observed_bars', 'regular_nominal_bars',
        'regular_nominal_coverage', 'afterhours_observed_bars',
        'afterhours_nominal_bars', 'afterhours_nominal_coverage',
        'regular_zero_volume', 'afterhours_zero_volume', 'raw_anomalies_in_scope',
        'data_quality_status', 'exclusion_reason', 'weekend_flag',
        'holiday_gap_flag', 'rollover_flag'])
    monthly_rows = []
    if not daily.empty:
        for month, f in daily.groupby(daily.signal_trade_date.str.slice(0, 7)):
            audit_subset = details[details.signal_trade_date.str.startswith(month)]
            monthly_rows.append({
                'month': month,
                'candidate_events': len(f),
                'valid_events': int((f.data_quality_status == 'VALID').sum()),
                'excluded_events': int((f.data_quality_status != 'VALID').sum()),
                'audit_mismatches': int((audit_subset.audit_status == 'MISMATCH').sum()),
                'raw_anomalies_in_scope': int(f.raw_anomalies_in_scope.sum()),
                'contract_rollover_events': int(f.rollover_flag.sum()),
                'weekend_flags': int(f.weekend_flag.sum()),
                'holiday_gap_flags': int(f.holiday_gap_flag.sum()),
                'mean_regular_nominal_coverage': f.regular_nominal_coverage.mean(),
                'mean_afterhours_nominal_coverage': f.afterhours_nominal_coverage.mean(),
            })
    monthly = pd.DataFrame(monthly_rows, columns=[
        'month', 'candidate_events', 'valid_events', 'excluded_events',
        'audit_mismatches', 'raw_anomalies_in_scope', 'contract_rollover_events',
        'weekend_flags', 'holiday_gap_flags', 'mean_regular_nominal_coverage',
        'mean_afterhours_nominal_coverage'])
    reasons = Counter()
    for val in events.get('exclusion_reason', pd.Series(dtype=str)).fillna(''):
        for code in filter(None, val.split('|')):
            reasons[code] += 1
    reason_table = pd.DataFrame(
        [{'reason': k, 'affected_events': v} for k, v in sorted(reasons.items())],
        columns=['reason', 'affected_events'])

    mismatches = int((details.audit_status == 'MISMATCH').sum())
    exclusions = int((details.audit_status == 'EXCLUDED').sum())
    in_scope_anomalies = len(in_scope)
    if mismatches:
        state = 'BLOCKED'
    elif details.empty or exclusions or in_scope_anomalies:
        state = 'REVIEW_REQUIRED'
    else:
        state = 'PASS'
    return details, daily, monthly, reason_table, state


def write_quality_report(run, events, anomalies, raw_bars, spot, cfg, info):
    """Persist reports even on QA mismatch; only pipeline sets final status."""
    run = Path(run)
    details, daily, monthly, reasons, audit_status = audit_events(
        raw_bars, spot, events, anomalies, cfg)
    tables = {'event_price_audit': details, 'daily_coverage': daily,
              'monthly_qa': monthly, 'exclusion_reasons': reasons}
    for name, frame in tables.items():
        frame.to_csv(run / 'tables' / f'{name}.csv', index=False)
    with pd.ExcelWriter(run / 'reports' / 'summary.xlsx') as writer:
        for name, frame in tables.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
    valid = int((events.data_quality_status == 'VALID').sum()) if len(events) else 0
    failures = int((details.audit_status == 'MISMATCH').sum())
    report = (
        '# TXF Overnight → 0050 Data Quality Audit v0.1.2\n\n'
        f"Data label: {info['data_label']}\n\n"
        f"Mode: {cfg['mode']}\n\n"
        f"Configured window: {cfg['start']} to {cfg['end']}\n\n"
        f"Git SHA: {info['git_sha']}\n\n"
        f"QA status: {audit_status}\n\n"
        f"Candidates: {len(events)}; valid: {valid}; excluded: {len(events)-valid}; "
        f"audit mismatches: {failures}.\n\n"
        f"In-range anomalous raw bars: {int(anomalies.affects_research_event.sum()) if len(anomalies) else 0}; "
        f"overfetch anomalous raw bars: {int((~anomalies.affects_research_event).sum()) if len(anomalies) else 0}.\n\n"
        'All valid events are independently recomputed from preserved provider '
        'records and adjusted ETF observations, with strict clock and contract checks.\n\n'
        'Nominal daily minute counts (300 regular, 840 afterhours) are '
        'informational, not proof of exchange outages or invalidity. '
        'Boundary bar labeling remains a provider-semantic assumption pending external verification.\n\n'
        '**No H1/H2/H3 inference, HAC, FDR, OOS, p-values or trading conclusions '
        'are produced in validation mode.**\n\n'
        'Detailed rows: tables/event_price_audit.csv, daily_coverage.csv, '
        'monthly_qa.csv, exclusion_reasons.csv; '
        'diagnostics/session_anomalies.csv; raw_manifest/manifest.json.\n'
    )
    (run / 'reports' / 'data_quality_audit.md').write_text(report, encoding='utf-8')
    (run / 'reports' / 'summary.md').write_text(report, encoding='utf-8')
    return audit_status, tables
