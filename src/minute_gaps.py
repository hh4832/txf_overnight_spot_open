"""Minute-level *unobserved timestamp* diagnostics (not proof of data loss).

Never synthesize/fill candles or alter research signals. Use verified monthly
expiry contract rule only when the regular series actually contains that
expiring month's contract; other months retain the normal 300-minute clock.
"""
import pandas as pd

from .data_validation import inspect_bars
from .expiry_calendar import expiry_contract_for_day

COLUMNS = [
    'signal_trade_date','session','expected_contract_context',
    'expected_session_minutes','observed_session_minutes',
    'missing_start','missing_end','missing_minutes',
    'minutes_before_session_close','within_last_15_minutes',
    'interpretation'
]


def _minutes(day, session, total):
    if session == 'regular':
        start = pd.Timestamp(day+' 08:45', tz='Asia/Taipei')
    else:
        start = pd.Timestamp(day+' 15:00', tz='Asia/Taipei')
    return pd.date_range(start, periods=total, freq='min')


def missing_minute_intervals(raw_bars, events, cfg):
    """Report consecutive missing minute labels, with no imputation."""
    clean,_,_,_ = inspect_bars(raw_bars, cfg['start'], cfg['end'])
    records=[]
    for _, event in events.iterrows():
        day=event['signal_trade_date']
        for session in ('regular','afterhours'):
            frame=clean[(clean.signal_date==day)&(clean.session==session)]
            months=sorted(set(frame.contract_month.astype(str)))
            expiry=expiry_contract_for_day(day,cfg)
            expiring_only=(session=='regular' and expiry and months==[expiry])
            expected=285 if expiring_only else (300 if session=='regular' else 840)
            context=('EXPIRING_CONTRACT_1330' if expiring_only
                     else ('MIXED_CONTRACTS' if len(months)>1
                           else ('|'.join(months) if months else 'NO_OBSERVED_BARS')))
            timeline=_minutes(day,session,expected)
            observed=set(pd.to_datetime(frame.timestamp))
            missing=[stamp for stamp in timeline if stamp not in observed]
            if not missing:
                continue
            groups=[]
            segment=[missing[0]]
            for ts in missing[1:]:
                if ts-segment[-1] == pd.Timedelta(minutes=1):
                    segment.append(ts)
                else:
                    groups.append(segment)
                    segment=[ts]
            groups.append(segment)
            close=timeline[-1]+pd.Timedelta(minutes=1)
            for group in groups:
                dist=int((close-(group[-1]+pd.Timedelta(minutes=1))).total_seconds()/60)
                records.append({
                    'signal_trade_date':day, 'session':session,
                    'expected_contract_context':context,
                    'expected_session_minutes':expected,
                    'observed_session_minutes':len(observed.intersection(set(timeline))),
                    'missing_start':group[0],
                    'missing_end':group[-1],
                    'missing_minutes':len(group),
                    'minutes_before_session_close':dist,
                    'within_last_15_minutes':dist<15,
                    'interpretation':'UNOBSERVED_MINUTE_NOT_PROVEN_VENDOR_LOSS',
                })
    return pd.DataFrame(records,columns=COLUMNS)
