import pandas as pd


def session_start(ts, session):
    if ts.tzinfo is None:
        raise ValueError('Timezone required')
    t = ts.tz_convert('Asia/Taipei')
    minute = t.hour*60+t.minute
    if session == 'regular' and 525 <= minute < 825:
        return t.strftime('%Y-%m-%d')
    if session == 'afterhours' and (minute >= 900 or minute < 300):
        return (t-pd.Timedelta(days=1) if minute < 300 else t).strftime('%Y-%m-%d')
    raise ValueError('Bar outside documented session; expiry/irregular session requires exclusion')


def last_bar(frame, day, clock, tolerance):
    end = pd.Timestamp(f'{day} {clock}', tz='Asia/Taipei')
    f = frame[(frame.timestamp < end) & (frame.timestamp+pd.Timedelta(minutes=1) <= end)]
    if f.empty:
        return None
    row = f.sort_values('timestamp').iloc[-1]
    if (end-(row.timestamp+pd.Timedelta(minutes=1))).total_seconds()/60 > tolerance:
        return None
    return row
