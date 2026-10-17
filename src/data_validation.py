"""Checks on combined partitions, including contract changes inside a session."""
import pandas as pd
from .session_alignment import session_start


def validate_bars(bars):
    required={'timestamp','session','contract_month','open','high','low','close','volume'}
    if bars.empty or not required.issubset(bars):
        raise ValueError('Empty/missing futures columns')
    if bars.duplicated(['session','timestamp']).any():
        raise ValueError('Duplicate bars across partitions')
    if bars.timestamp.isna().any():
        raise ValueError('Missing timestamps')
    if not bars.contract_month.astype(str).str.fullmatch(r'\d{6}').all():
        raise ValueError('Actual contract months required')
    for c in ['open','high','low','close','volume']:
        if bars[c].isna().any(): raise ValueError('Missing OHLCV')
    if (bars[['open','high','low','close']]<=0).any().any() or (bars.volume<0).any():
        raise ValueError('Invalid OHLCV')
    starts=[session_start(t,s) for t,s in zip(bars.timestamp,bars.session)]
    f=bars.assign(start=starts)
    # Event builder records session-level inconsistency as an explicit exclusion.
    bad=f.groupby(['start','session']).contract_month.nunique()
    return set(bad[bad>1].index.get_level_values(0))
