"""Strict opt-in for independently verified non-price boundary markers.

Do not infer vendor timestamp semantics merely from matching prices. To
classify a boundary row as non-price marker, require reviewed documentary
evidence *and* a flat zero-volume marker matching the verified closing bar
of the SAME contract. A price conflict or positive volume remains blocking.
No raw candle is ever deleted or normalized by this classification.
"""
import pandas as pd

BOUNDARY_CODES = {
    'UNVERIFIED_REGULAR_1345_BOUNDARY',
    'UNVERIFIED_AFTERHOURS_0500_BOUNDARY',
}


def can_ignore_boundary(marker, close_bar, cfg):
    if not cfg.get('boundary_semantics_verified', False):
        return False
    if not str(cfg.get('boundary_evidence_reference', '')).strip():
        return False
    if close_bar is None:
        return False
    if str(marker.contract_month) != str(close_bar.contract_month):
        return False
    fields = ('open', 'high', 'low', 'close')
    try:
        same = all(float(getattr(marker, k)) == float(close_bar.close) for k in fields)
        return same and float(marker.volume) == 0
    except (TypeError, ValueError):
        return False


def decide_boundaries(anomalies, day, dbar, nbar, cfg):
    """Return (exclusion codes, warnings, boundary audit rows)."""
    excluded, warnings, rows = [], [], []
    matched = anomalies[anomalies.signal_trade_date == day]
    for entry in matched.itertuples(index=False):
        code = entry.anomaly_type
        if code not in BOUNDARY_CODES:
            continue
        bar = dbar if entry.session == 'regular' else nbar
        verified = can_ignore_boundary(entry, bar, cfg)
        close = float(bar.close) if bar is not None else None
        selected = pd.Timestamp(bar.timestamp) if bar is not None else pd.NaT
        decision = 'VERIFIED_NONPRICE_MARKER' if verified else 'EXCLUDE_UNVERIFIED'
        if verified:
            warnings.append(code)
        else:
            excluded.append(code)
        rows.append({
            'signal_trade_date': day, 'marker_timestamp': entry.timestamp,
            'session': entry.session, 'contract_month': entry.contract_month,
            'anomaly_code': code, 'marker_open': entry.open,
            'marker_high': entry.high, 'marker_low': entry.low,
            'marker_close': entry.close, 'marker_volume': entry.volume,
            'selected_close_timestamp': selected, 'selected_close': close,
            'price_difference': (float(entry.close) - close
                                 if close is not None else float('nan')),
            'documentary_evidence': str(cfg.get('boundary_evidence_reference', '')) if verified else '',
            'decision': decision,
        })
    return excluded, warnings, rows
