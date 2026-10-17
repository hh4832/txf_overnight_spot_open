import numpy as np
import pandas as pd
from .session_alignment import session_start, last_bar
from .trading_calendar import next_spot_day, gap_flags
from .contract_rollover import consistent
from .returns import compute


def build(bars, spot, cfg):
    from .data_validation import validate_bars
    mixed_dates = validate_bars(bars)
    bars = bars[bars.volume > 0].copy()
    bars['signal_date'] = [session_start(t,s) for t,s in zip(bars.timestamp,bars.session)]
    spot = spot.set_index('date', verify_integrity=True)
    events = []
    for day in sorted(set(spot.index) | set(bars.signal_date)):
        if day < cfg['start'] or day > cfg['end']:
            continue
        row = dict(signal_trade_date=day, next_spot_trade_date=next_spot_day(day,spot.index),
                   data_quality_status='EXCLUDED', exclusion_reason='', rollover_flag=False,
                   weekend_flag=False, holiday_gap_flag=False)
        nxt = row['next_spot_trade_date']
        regular = bars[(bars.signal_date==day)&(bars.session=='regular')]
        night = bars[(bars.signal_date==day)&(bars.session=='afterhours')]
        d = last_bar(regular,day,'13:45',cfg['max_close_staleness_minutes'])
        endday = (pd.Timestamp(day)+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        n = last_bar(night,endday,'05:00',cfg['max_close_staleness_minutes'])
        reasons = []
        if day in mixed_dates: reasons.append('WITHIN_SESSION_CONTRACT_CHANGE')
        if day not in spot.index: reasons.append('NO_SPOT_SESSION_D')
        if not nxt: reasons.append('NO_NEXT_SPOT_SESSION')
        if d is None: reasons.append('MISSING_OR_STALE_DAY_CLOSE')
        if n is None: reasons.append('MISSING_OR_STALE_NIGHT_CLOSE')
        for label,bar in [('day',d),('night',n)]:
            row[f'txf_{label}_close_timestamp'] = bar.timestamp if bar is not None else pd.NaT
            row[f'txf_{label}_contract_month'] = bar.contract_month if bar is not None else None
            row[f'txf_{label}_close'] = bar.close if bar is not None else np.nan
        if d is not None and n is not None:
            row['rollover_flag'] = not consistent(d.contract_month,n.contract_month)
            if row['rollover_flag']: reasons.append('CONTRACT_MISMATCH')
        if nxt:
            intervening = sorted(set(bars.signal_date[(bars.session=='afterhours') & (bars.signal_date>day) & (bars.signal_date<nxt)]))
            if intervening: reasons.append('INTERVENING_NIGHT_SESSION_BEFORE_NEXT_SPOT')
            row['weekend_flag'],row['holiday_gap_flag'] = gap_flags(day,nxt)
            if n is not None and n.timestamp+pd.Timedelta(minutes=1) >= pd.Timestamp(f'{nxt} 09:00',tz='Asia/Taipei'):
                reasons.append('SIGNAL_NOT_AVAILABLE_BEFORE_OPEN')
        if day in spot.index and nxt:
            row.update(spot_prev_close=spot.loc[day,'close'],spot_next_open=spot.loc[nxt,'open'],
                       spot_next_close=spot.loc[nxt,'close'],
                       corporate_action_boundary=bool(spot.loc[nxt,'corporate_action_boundary']))
            if not bool(spot.loc[day,'adjustment_verified']) or not bool(spot.loc[nxt,'adjustment_verified']):
                reasons.append('ADJUSTMENT_UNVERIFIED')
        if not reasons:
            row.update(compute(d.close,n.close,row['spot_prev_close'],row['spot_next_open'],row['spot_next_close']))
            b = last_bar(regular,day,'13:30',0)
            row['txf_1330_to_1345'] = d.close/b.close-1 if b is not None and b.contract_month==d.contract_month else np.nan
            row['txf_1330_to_0500'] = n.close/b.close-1 if b is not None and b.contract_month==d.contract_month else np.nan
            nr = bars[(bars.signal_date==nxt)&(bars.session=='regular')]
            nr = nr[nr.timestamp == pd.Timestamp(f'{nxt} 08:45',tz='Asia/Taipei')]
            row['txf_0500_to_0845'] = nr.iloc[0].open/n.close-1 if len(nr)==1 and nr.iloc[0].contract_month==n.contract_month else np.nan
            row.update(overnight_negative=row['txf_overnight_return']<0,
                       gap_negative=row['spot_opening_gap']<0,intraday_negative=row['spot_intraday_return']<0,
                       data_quality_status='VALID')
        row['exclusion_reason'] = '|'.join(reasons)
        events.append(row)
    return pd.DataFrame(events)
