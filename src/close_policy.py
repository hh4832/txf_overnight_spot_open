"""Observable close-price convention for TXF minute bars.

Adaptive convention (not vendor-confirmed): choose valid 13:45 / next-day
05:00 when present, otherwise exact 13:44 / 04:59. No stale fallback.
Boundary rows remain unchanged and auditable; invalid/duplicate records do
not become research observations. Fixed prices are descriptive comparators.
"""
import pandas as pd

from .session_alignment import TZ
from .expiry_calendar import expiry_contract_for_day

BOUNDARY = {'regular':'UNVERIFIED_REGULAR_1345_BOUNDARY',
            'afterhours':'UNVERIFIED_AFTERHOURS_0500_BOUNDARY'}
BASE_CLOCK = {'regular':'13:44','afterhours':'04:59'}
ADAPTIVE_CLOCK = {'regular':'13:45','afterhours':'05:00'}


def _one(frame, stamp):
    found=frame[frame.timestamp==stamp]
    return found.iloc[0] if len(found)==1 else None


def _valid_boundary(row):
    if row is None:
        return False
    try:
        o,h,l,c,v=(float(row[k]) for k in ('open','high','low','close','volume'))
        return (o>0 and c>0 and l>0 and h>0 and v>0 and
                l<=min(o,c)<=max(o,c)<=h and
                str(row.contract_month).isdigit() and len(str(row.contract_month))==6)
    except (TypeError,ValueError,AttributeError):
        return False


def choose_close(clean, qa, day, session, cfg):
    """Return (selected bar, fixed bar, warning codes, blocking codes, rule).

    Select only exact close labels; never reuse a prior completed minute.
    The raw source 13:45/05:00 anomaly is examined separately from valid
    regular-session candles, and only a single valid positive-volume
    record may become the preferred adaptive close.
    """
    if session not in BOUNDARY:
        raise ValueError('Unsupported session')
    end_day=(pd.Timestamp(day)+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    clock_day=day if session=='regular' else end_day
    fixed_time=pd.Timestamp(f'{clock_day} {BASE_CLOCK[session]}',tz=TZ)
    extra_time=pd.Timestamp(f'{clock_day} {ADAPTIVE_CLOCK[session]}',tz=TZ)
    f=clean[(clean.signal_date==day)&(clean.session==session)]
    base=_one(f[f.volume>0],fixed_time)
    q=qa[(qa.signal_trade_date==day)&(qa.session==session)&
         (qa.timestamp==extra_time)]
    warnings=[]; blocks=[]
    policy=cfg.get('close_policy','adaptive')
    if policy not in ('adaptive','strict'):
        raise ValueError('Invalid close policy')
    if len(q)>1:
        blocks.append('DUPLICATE_BOUNDARY_TIMESTAMP')
    elif len(q)==1:
        row=q.iloc[0]
        if policy=='strict':
            blocks.append(row.anomaly_type)
        elif _valid_boundary(row):
            if base is not None and str(base.contract_month)!=str(row.contract_month):
                blocks.append('BOUNDARY_CONTRACT_MISMATCH')
            else:
                warnings.append('ADAPTIVE_BOUNDARY_INCLUDED')
                return row, base, warnings, blocks, 'ADAPTIVE_BOUNDARY'
        elif float(row.volume)==0 and _flat_valid_zero(row):
            warnings.append('ZERO_VOLUME_BOUNDARY_IGNORED')
        else:
            blocks.append('INVALID_BOUNDARY_RECORD')
    if base is not None:
        return base, base, warnings, blocks, 'FIXED_LAST_MINUTE'
    if session=='regular':
        expiry=expiry_contract_for_day(day,cfg)
        if expiry is not None:
            at=pd.Timestamp(f'{day} 13:29',tz=TZ)
            candidate=_one(f[f.volume>0],at)
            if candidate is not None and str(candidate.contract_month)==expiry:
                return candidate, None, warnings, blocks,'EXPIRING_MONTH_1329'
    blocks.append('MISSING_EXACT_CLOSING_BAR')
    return None,base,warnings,blocks,'MISSING'


def _flat_valid_zero(row):
    try:
        vals=[float(row[k]) for k in ('open','high','low','close')]
        return float(row.volume)==0 and vals[0]>0 and len(set(vals))==1
    except (TypeError, ValueError):
        return False
