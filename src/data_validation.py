"""Strict per-event validation; retain out-of-range anomalies as QA evidence."""
import pandas as pd
from .session_alignment import classify_session


REQUIRED = {'timestamp', 'session', 'contract_month', 'open', 'high',
            'low', 'close', 'volume'}


def inspect_bars(bars, start, end):
    """Return (usable bars, within-session mixed dates, bad-date codes, QA frame).

    Out-of-range records are classified and retained in QA, not incorporated
    into signal events. In-range ambiguity excludes the entire candidate event.
    Never fix, shift or silently reassign a boundary candle.
    """
    if bars.empty or not REQUIRED.issubset(bars.columns):
        raise ValueError('Empty/missing futures columns')
    if bars.timestamp.isna().any():
        raise ValueError('Missing timestamps')
    working = bars.copy()
    dates, codes = [], []
    for ts, session in zip(working.timestamp, working.session):
        day, code = classify_session(ts, session)
        dates.append(day)
        codes.append(code)
    working['signal_date'] = dates
    working['anomaly_code'] = codes

    # Structural errors are quarantined per associated trading date.
    invalid_month = ~working.contract_month.astype(str).str.fullmatch(r'\d{6}')
    prices = working[['open', 'high', 'low', 'close', 'volume']]
    numeric = prices.apply(pd.to_numeric, errors='coerce')
    invalid_ohlcv = (numeric.isna().any(axis=1) |
                     (numeric[['open', 'high', 'low', 'close']] <= 0).any(axis=1) |
                     (numeric.volume < 0) |
                     (numeric.low > numeric[['open', 'close']].min(axis=1)) |
                     (numeric.high < numeric[['open', 'close']].max(axis=1)))
    duplicate = working.duplicated(['session', 'timestamp'], keep=False)
    working.loc[invalid_month, 'anomaly_code'] = working.loc[
        invalid_month, 'anomaly_code'].fillna('INVALID_CONTRACT_MONTH')
    working.loc[invalid_ohlcv, 'anomaly_code'] = working.loc[
        invalid_ohlcv, 'anomaly_code'].fillna('INVALID_OHLCV')
    working.loc[duplicate, 'anomaly_code'] = working.loc[
        duplicate, 'anomaly_code'].fillna('DUPLICATE_TIMESTAMP')

    anomaly = working[working.anomaly_code.notna()].copy()
    if not anomaly.empty:
        anomaly['affects_research_event'] = anomaly.signal_date.between(start, end)
        anomaly['decision'] = anomaly.affects_research_event.map(
            {True: 'EXCLUDE_EVENT', False: 'QUARANTINE_OUTSIDE_RANGE'})
    else:
        anomaly['affects_research_event'] = pd.Series(dtype=bool)
        anomaly['decision'] = pd.Series(dtype=str)
    qa_cols = ['timestamp', 'session', 'contract_month', 'open', 'high',
               'low', 'close', 'volume', 'anomaly_code',
               'signal_date', 'affects_research_event', 'decision']
    qa = anomaly[qa_cols].rename(columns={'anomaly_code': 'anomaly_type',
                                          'signal_date': 'signal_trade_date'})
    bad_dates = {}
    for row in anomaly.itertuples():
        if start <= row.signal_date <= end:
            bad_dates.setdefault(row.signal_date, set()).add(row.anomaly_code)

    clean = working[working.anomaly_code.isna()].copy()
    clean[['open', 'high', 'low', 'close', 'volume']] = numeric.loc[
        clean.index, ['open', 'high', 'low', 'close', 'volume']]
    groups = clean.groupby(['signal_date', 'session']).contract_month.nunique()
    mixed = set(groups[groups > 1].index.get_level_values('signal_date'))
    clean.drop(columns='anomaly_code', inplace=True)
    return clean, mixed, bad_dates, qa


def validate_bars(bars):
    """Legacy strict validation helper, retained for callers needing fatal QA."""
    clean, mixed, bad, _ = inspect_bars(bars, '0000-01-01', '9999-12-31')
    if bad:
        raise ValueError('Futures bars require event-level quarantine')
    return mixed
