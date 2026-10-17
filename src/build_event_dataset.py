"""Construct aligned market events without stale closes or cross-contract returns."""
import numpy as np
import pandas as pd

from .session_alignment import TZ
from .trading_calendar import next_spot_day, gap_flags
from .data_validation import inspect_bars
from .close_policy import choose_close, BOUNDARY
from .expiry_calendar import expiry_contract_for_day, calendar_confidence
from .returns import compute


def build(bars, spot, cfg, return_diagnostics=False):
    clean, mixed_dates, bad_dates, qa = inspect_bars(bars,cfg['start'],cfg['end'])
    # Group once for multi-year performance; preserve the original provider frames.
    grouped = {(d,s):g for (d,s),g in clean.groupby(['signal_date','session'])}
    qa_grouped = {(d,s):g for (d,s),g in qa.groupby(['signal_trade_date','session'])}
    empty_clean=clean.iloc[:0]
    empty_qa=qa.iloc[:0]
    spot=spot.set_index('date',verify_integrity=True)
    events=[]
    for day in sorted(set(spot.index)|set(clean.signal_date)):
        if not (cfg['start']<=day<=cfg['end']):
            continue
        nxt=next_spot_day(day,spot.index)
        regular=grouped.get((day,'regular'),empty_clean)
        night=grouped.get((day,'afterhours'),empty_clean)
        rq=qa_grouped.get((day,'regular'),empty_qa)
        nq=qa_grouped.get((day,'afterhours'),empty_qa)
        d,df,dwarn,dblock,drule=choose_close(regular,rq,day,'regular',cfg)
        n,nf,nwarn,nblock,nrule=choose_close(night,nq,day,'afterhours',cfg)
        expiry=expiry_contract_for_day(day,cfg)
        row=dict(signal_trade_date=day,next_spot_trade_date=nxt,
                 data_quality_status='EXCLUDED',exclusion_reason='',
                 rollover_flag=False,weekend_flag=False,holiday_gap_flag=False,
                 expiry_day_flag=bool(expiry),expiry_contract_month=expiry,
                 expiry_calendar_confidence=calendar_confidence(day,cfg),
                 day_close_rule=drule,night_close_rule=nrule,
                 boundary_warning_codes='|'.join(sorted(set(dwarn+nwarn))),
                 txf_overnight_return_fixed=np.nan,txf_adaptive_minus_fixed_bp=np.nan)
        reasons=[]
        if day in mixed_dates:
            reasons.append('WITHIN_SESSION_CONTRACT_CHANGE')
        for code in sorted(bad_dates.get(day, [])):
            if (code in BOUNDARY.values() and cfg.get('close_policy','adaptive')=='adaptive'):
                # Individual boundary rows are adjudicated by choose_close.
                continue
            if code not in BOUNDARY.values():
                reasons.append(code)
        reasons.extend(dblock+nblock)
        if day not in spot.index:
            reasons.append('NO_SPOT_SESSION_D')
        if not nxt:
            reasons.append('NO_NEXT_SPOT_SESSION')
        if d is None:
            reasons.append('MISSING_OR_STALE_DAY_CLOSE')
        if n is None:
            reasons.append('MISSING_OR_STALE_NIGHT_CLOSE')
        for label,bar in [('day',d),('night',n)]:
            row[f'txf_{label}_close_timestamp']=bar.timestamp if bar is not None else pd.NaT
            row[f'txf_{label}_contract_month']=bar.contract_month if bar is not None else None
            row[f'txf_{label}_close']=bar.close if bar is not None else np.nan
        if d is not None and expiry and str(d.contract_month)==expiry:
            reasons.append('EXPIRY_CONTRACT_ROLLOVER_EXCLUSION')
        if d is not None and n is not None:
            row['rollover_flag']=str(d.contract_month)!=str(n.contract_month)
            if row['rollover_flag']:
                reasons.append('CONTRACT_MISMATCH')
            if d.timestamp >= n.timestamp:
                reasons.append('CLOSING_CLOCK_ORDER_INVALID')
        if nxt:
            intervening=sorted(set(clean.signal_date[
                (clean.session=='afterhours')&
                (clean.signal_date>day)&(clean.signal_date<nxt)]))
            if intervening:
                reasons.append('INTERVENING_NIGHT_SESSION_BEFORE_NEXT_SPOT')
            row['weekend_flag'],row['holiday_gap_flag']=gap_flags(day,nxt)
            if n is not None and n.timestamp>=pd.Timestamp(f'{nxt} 09:00',tz=TZ):
                reasons.append('SIGNAL_NOT_AVAILABLE_BEFORE_OPEN')
        if day in spot.index and nxt:
            row.update(spot_prev_close=spot.loc[day,'close'],
                       spot_next_open=spot.loc[nxt,'open'],
                       spot_next_close=spot.loc[nxt,'close'],
                       corporate_action_boundary=bool(spot.loc[nxt,'corporate_action_boundary']))
            if not (bool(spot.loc[day,'adjustment_verified']) and
                    bool(spot.loc[nxt,'adjustment_verified'])):
                reasons.append('ADJUSTMENT_UNVERIFIED')
        if not reasons:
            row.update(compute(float(d.close),float(n.close),
                               row['spot_prev_close'],row['spot_next_open'],
                               row['spot_next_close']))
            if df is not None and nf is not None and str(df.contract_month)==str(nf.contract_month):
                fixed=float(nf.close)/float(df.close)-1
                row['txf_overnight_return_fixed']=fixed
                row['txf_adaptive_minus_fixed_bp']=(
                    row['txf_overnight_return']-fixed)*10000
            b=regular[(regular.volume>0)&
                (regular.timestamp==pd.Timestamp(f'{day} 13:30',tz=TZ))]
            b=b.iloc[0] if len(b)==1 else None
            row['txf_1330_to_1345']=(
                float(d.close)/float(b.close)-1
                if b is not None and str(b.contract_month)==str(d.contract_month)
                else np.nan)
            row['txf_1330_to_0500']=(
                float(n.close)/float(b.close)-1
                if b is not None and str(b.contract_month)==str(d.contract_month)
                and str(d.contract_month)==str(n.contract_month) else np.nan)
            nr=grouped.get((nxt,'regular'),empty_clean)
            nr=nr[(nr.volume>0)&
                  (nr.timestamp==pd.Timestamp(f'{nxt} 08:45',tz=TZ))]
            row['txf_0500_to_0845']=(
                float(nr.iloc[0].open)/float(n.close)-1
                if len(nr)==1 and str(nr.iloc[0].contract_month)==str(n.contract_month)
                else np.nan)
            row.update(overnight_negative=row['txf_overnight_return']<0,
                       gap_negative=row['spot_opening_gap']<0,
                       intraday_negative=row['spot_intraday_return']<0,
                       data_quality_status='VALID')
        row['exclusion_reason']='|'.join(sorted(set(reasons)))
        events.append(row)
        if row['data_quality_status']=='VALID' and row['boundary_warning_codes']:
            for session,code in (('regular',drule),('afterhours',nrule)):
                if code=='ADAPTIVE_BOUNDARY':
                    mask=(qa.signal_trade_date==day)&(qa.session==session)&(
                        qa.anomaly_type==BOUNDARY[session])
                    qa.loc[mask,'decision']='INCLUDED_ADAPTIVE_CLOSE'
    result=pd.DataFrame(events)
    return (result,qa) if return_diagnostics else result
