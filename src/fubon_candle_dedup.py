"""Exact-only duplicate TXF minute candle reconciliation.

A duplicate is defined by the same normalized Asia/Taipei timestamp with
identical session, ACTUAL contract month and numeric OHLCV. Never pick a
preferred conflicting observation. No interpolation, price modification or
contract rollover is performed here.
"""
import pandas as pd

CANDLE_IDENTITY = ['session', 'contract_month', 'open', 'high', 'low', 'close', 'volume']
REQUIRED = ['timestamp', *CANDLE_IDENTITY]


def reconcile_identical_candles(frame):
    """Return (deduplicated copy, statistics) or raise on any timestamp conflict.

    Stable order is preserved. Raw vendor date strings may format equivalent
    instants differently; the time identity is the normalized timestamp.
    """
    if not isinstance(frame, pd.DataFrame) or not set(REQUIRED).issubset(frame.columns):
        raise ValueError('Duplicate audit requires timestamp/session/contract/OHLCV')
    if frame.timestamp.isna().any():
        raise ValueError('Duplicate audit timestamp missing')
    original = len(frame)
    repeated = frame.timestamp.duplicated(keep=False)
    n_timestamps = 0
    if repeated.any():
        repetitions = frame.loc[repeated, REQUIRED]
        differences = repetitions.groupby('timestamp', sort=False)[CANDLE_IDENTITY].nunique(dropna=False)
        if differences.gt(1).any(axis=1).any():
            raise ValueError('Conflicting duplicate TXF timestamp (session/contract/OHLCV)')
        n_timestamps = len(differences)
        cleaned = frame.loc[~frame.timestamp.duplicated(keep='first')].copy()
    else:
        cleaned = frame.copy()
    stats = {
        'rows_before': int(original),
        'rows_after': int(len(cleaned)),
        'exact_duplicates_removed': int(original-len(cleaned)),
        'duplicated_timestamp_groups': int(n_timestamps),
        'conflicting_timestamp_groups': 0,
        'status': 'EXACT_ONLY_VERIFIED',
    }
    return cleaned.reset_index(drop=True), stats
