"""FinLab 0050 adjusted daily open/close, with explicit missing-date QA.

Only dates missing all four source fields may remain as flagged placeholders.
Incomplete/invalid observed dates and adjustment-factor disagreement are fatal.
The caller must exclude placeholders from the usable trading calendar, record
the omitted dates, and never silently treat them as verified holidays.
"""
import contextlib
import io
import numpy as np
import pandas as pd
from .credentials import secret


def normalize(open_, close_, raw_open=None, raw_close=None):
    if (raw_open is None) != (raw_close is None):
        raise ValueError('FinLab raw open/close must be supplied together')
    inputs = {'adj_open': open_, 'adj_close': close_}
    if raw_open is not None:
        inputs.update(raw_open=raw_open, raw_close=raw_close)
    if not isinstance(open_, pd.Series) or not isinstance(open_.index, pd.DatetimeIndex):
        raise ValueError('FinLab date index invalid')
    if open_.index.has_duplicates or not open_.index.is_monotonic_increasing:
        raise ValueError('FinLab calendar invalid')
    for item in inputs.values():
        if not isinstance(item, pd.Series) or not open_.index.equals(item.index):
            raise ValueError('FinLab date index mismatch')
    values = pd.DataFrame({
        name: pd.to_numeric(item, errors='raise').to_numpy()
        for name, item in inputs.items()
    })
    if values.empty:
        raise ValueError('FinLab empty price series')

    missing_any = values.isna().any(axis=1)
    missing_all = values.isna().all(axis=1)
    if (missing_any & ~missing_all).any():
        raise ValueError('Partial 0050 price fields missing on a date')
    observed = values.loc[~missing_all]
    if observed.empty or not np.isfinite(observed.to_numpy(dtype=float)).all():
        raise ValueError('No valid or nonfinite observed 0050 prices')
    if (observed <= 0).any().any():
        raise ValueError('Nonpositive observed 0050 price')

    df = pd.DataFrame({
        'date': open_.index.strftime('%Y-%m-%d'),
        'open': values['adj_open'].to_numpy(),
        'close': values['adj_close'].to_numpy(),
        'fully_missing_0050': missing_all.to_numpy(),
        'adjustment_verified': False,
        'corporate_action_boundary': False,
    })
    if raw_open is not None:
        open_factor = observed['adj_open'] / observed['raw_open']
        close_factor = observed['adj_close'] / observed['raw_close']
        if not np.isfinite(open_factor).all() or not np.isfinite(close_factor).all():
            raise ValueError('Nonfinite corporate action adjustment')
        if not np.allclose(open_factor, close_factor, rtol=1e-5):
            raise ValueError('Open/close corporate action adjustment inconsistent')
        idx = observed.index
        df.loc[idx, 'adjustment_verified'] = True
        ratio = close_factor / close_factor.shift(1)
        boundary = ~np.isclose(ratio, 1, rtol=1e-5)
        if len(boundary):
            boundary[0] = False
        df.loc[idx, 'corporate_action_boundary'] = boundary

    return df


def fetch(start, end):
    try:
        import finlab
        from finlab import data
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            finlab.login(secret('FINLAB_API_TOKEN'))
            frames = [data.get(k) for k in ('etl:adj_open','etl:adj_close','price:開盤價','price:收盤價')]
        series = [x['0050'].loc[start:end] for x in frames]
        return normalize(*series)
    except Exception:
        raise RuntimeError('FinLab access/schema/adjustment validation failed; details suppressed') from None
