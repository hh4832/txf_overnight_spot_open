import contextlib
import io
import numpy as np
import pandas as pd
from .credentials import secret


def normalize(open_, close_, raw_open=None, raw_close=None):
    if not isinstance(open_.index, pd.DatetimeIndex) or not open_.index.equals(close_.index):
        raise ValueError('FinLab date index mismatch')
    if open_.index.has_duplicates or not open_.index.is_monotonic_increasing:
        raise ValueError('FinLab calendar invalid')
    df = pd.DataFrame({'date': open_.index.strftime('%Y-%m-%d'),
                       'open': open_.to_numpy(), 'close': close_.to_numpy()})
    if df.empty or not np.isfinite(df[['open','close']]).all().all() or (df[['open','close']] <= 0).any().any():
        raise ValueError('Missing/nonpositive adjusted prices; calendar cannot be inferred')
    df['adjustment_verified'] = False
    df['corporate_action_boundary'] = False
    if raw_open is not None and raw_close is not None:
        ro, rc = raw_open.reindex(open_.index), raw_close.reindex(close_.index)
        ao, ac = open_/ro, close_/rc
        if not np.isfinite(ao).all() or not np.isfinite(ac).all() or not np.allclose(ao, ac, rtol=1e-5):
            raise ValueError('Open/close corporate action adjustment inconsistent')
        df['adjustment_verified'] = True
        df['corporate_action_boundary'] = ~np.isclose(ac/ac.shift(1), 1, rtol=1e-5)
        df.loc[0, 'corporate_action_boundary'] = False
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
