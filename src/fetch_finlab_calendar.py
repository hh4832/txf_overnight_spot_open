"""Historical TX session-volume calendar for Fubon request scheduling only.

Daily activity from futures_price:成交量 TX一般 and TX盤後. Empty dates
are NOT proof of official exchange holidays. No forward fill, inference
signals, candle edits or date-shifting. Complete-week skips require nearby
activity anchors and independent 0050-session cross-check in pipeline.
"""
import contextlib
import io
import numpy as np
import pandas as pd
from .credentials import secret

SOURCE = 'futures_price:成交量'
SOURCE_URL = 'https://finlab.finance/data/tw-futures-daily'
SCHEMA = 'TX_GENERAL_AND_AFTERHOURS_VOLUME_V1'
COLUMNS = {'TX一般': 'tx_regular_volume', 'TX盤後': 'tx_afterhours_volume'}


def normalize(volume, start, end):
    """Return one row for every calendar date; keep unknown volumes as NaN."""
    if not isinstance(volume, pd.DataFrame) or not set(COLUMNS).issubset(volume.columns):
        raise ValueError('FinLab TX calendar missing TX一般 or TX盤後 columns')
    if (not isinstance(volume.index, pd.DatetimeIndex) or
            volume.index.tz is not None or volume.index.has_duplicates or
            not volume.index.is_monotonic_increasing or
            not volume.index.equals(volume.index.normalize())):
        raise ValueError('FinLab TX calendar dates invalid')
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    if first > last:
        raise ValueError('FinLab TX calendar bounds invalid')
    tx = volume[list(COLUMNS)].apply(pd.to_numeric, errors='raise')
    numeric = tx.to_numpy(dtype=float)
    if np.isinf(numeric).any() or (numeric[np.isfinite(numeric)] < 0).any():
        raise ValueError('FinLab TX calendar volume invalid')
    positive = tx.gt(0).any(axis=1)
    if not positive.any():
        raise ValueError('FinLab TX calendar has no positive observations')
    observed_dates = tx.index[positive]
    # Do not accept a partially downloaded historical feed as a holiday list.
    if (observed_dates.min() > first + pd.Timedelta(days=14) or
            observed_dates.max() < last - pd.Timedelta(days=14)):
        raise ValueError('FinLab TX calendar historical coverage incomplete')
    days = pd.date_range(first, last, freq='D')
    values = tx.reindex(days).rename(columns=COLUMNS)
    regular = values['tx_regular_volume']
    after = values['tx_afterhours_volume']
    return pd.DataFrame({
        'date': days.strftime('%Y-%m-%d'),
        'tx_regular_volume': regular.to_numpy(),
        'tx_afterhours_volume': after.to_numpy(),
        'source_row_present': days.isin(tx.index),
        'has_tx_activity': (regular.gt(0) | after.gt(0)).to_numpy(),
    })


def validate_calendar(frame, start, end):
    """Recheck schema and continuity on both new and SHA-verified cached frames."""
    expected = pd.date_range(start, end, freq='D').strftime('%Y-%m-%d').tolist()
    if (not isinstance(frame, pd.DataFrame) or
            not {'date','tx_regular_volume','tx_afterhours_volume',
                 'source_row_present','has_tx_activity'}.issubset(frame.columns) or
            frame['date'].tolist() != expected):
        raise ValueError('FinLab TX calendar cache dates/schema incomplete')
    regular = pd.to_numeric(frame.tx_regular_volume, errors='raise')
    after = pd.to_numeric(frame.tx_afterhours_volume, errors='raise')
    numbers = frame[['tx_regular_volume','tx_afterhours_volume']].to_numpy(dtype=float)
    if np.isinf(numbers).any() or (numbers[np.isfinite(numbers)] < 0).any():
        raise ValueError('FinLab TX calendar cached volume invalid')
    if (not frame.has_tx_activity.isin([True,False]).all() or
            not frame.source_row_present.isin([True,False]).all() or
            not (frame.has_tx_activity.to_numpy() ==
                 (regular.gt(0) | after.gt(0)).to_numpy()).all()):
        raise ValueError('FinLab TX calendar activity inconsistent')
    if not frame.has_tx_activity.any():
        raise ValueError('FinLab TX calendar has no active dates')
    return frame


def partition_activity(frame, start, end, anchor_days=14):
    """Describe a 7-day Fubon provider-date window without adjusting candles."""
    a, b = pd.Timestamp(start), pd.Timestamp(end)
    dates = pd.to_datetime(frame.date)
    if a > b or a < dates.min() or b > dates.max():
        raise ValueError('FinLab TX calendar partition outside coverage')
    in_window = dates.between(a,b)
    part = frame.loc[in_window]
    if len(part) != (b-a).days+1:
        raise ValueError('FinLab TX calendar partition not continuous')
    regular_dates = part.loc[part.tx_regular_volume.gt(0),'date'].tolist()
    afterhours_dates = part.loc[part.tx_afterhours_volume.gt(0),'date'].tolist()
    tx_dates = part.loc[part.has_tx_activity,'date'].tolist()
    if not tx_dates:
        active = dates[frame.has_tx_activity]
        before = active[active < a]
        after = active[active > b]
        if (before.empty or after.empty or
                (a-before.max()).days > anchor_days or
                (after.min()-b).days > anchor_days):
            raise ValueError('FinLab TX calendar unbracketed no-activity interval')
    return {
        'tx_trading_dates': tx_dates,
        'tx_regular_dates': regular_dates,
        'tx_afterhours_dates': afterhours_dates,
        'has_tx_activity': bool(tx_dates),
    }


def fetch(start, end):
    try:
        import finlab
        from finlab import data
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            finlab.login(secret('FINLAB_API_TOKEN'))
            volume = data.get(SOURCE)
        return normalize(volume,start,end)
    except Exception:
        raise RuntimeError('FinLab TX calendar access/schema/coverage failed; details suppressed') from None
