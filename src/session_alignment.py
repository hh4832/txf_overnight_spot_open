"""Session timestamps: primary candles are START-labelled until proven otherwise."""
import pandas as pd

TZ = 'Asia/Taipei'


def classify_session(ts, session):
    """Return (session trade date, anomaly code or None).

    Exact 13:45 and 05:00 timestamps are quarantined: the official source has
    not established whether these are end-labelled close records. They must
    never silently replace the 13:44/04:59 starting-bar close.
    """
    if pd.isna(ts) or getattr(ts, 'tzinfo', None) is None:
        raise ValueError('Timezone-aware timestamp required')
    t = ts.tz_convert(TZ)
    minute = t.hour * 60 + t.minute
    if session == 'regular':
        day = t.strftime('%Y-%m-%d')
        if 525 <= minute < 825:
            return day, None
        if minute == 825:
            return day, 'UNVERIFIED_REGULAR_1345_BOUNDARY'
        return day, 'OUT_OF_REGULAR_SESSION'
    if session == 'afterhours':
        day = (t - pd.Timedelta(days=1) if minute <= 300 else t).strftime('%Y-%m-%d')
        if minute >= 900 or minute < 300:
            return day, None
        if minute == 300:
            return day, 'UNVERIFIED_AFTERHOURS_0500_BOUNDARY'
        return day, 'OUT_OF_AFTERHOURS_SESSION'
    return t.strftime('%Y-%m-%d'), 'UNKNOWN_SESSION'


def session_start(ts, session):
    day, anomaly = classify_session(ts, session)
    if anomaly:
        raise ValueError('Bar outside documented start-labelled session')
    return day


def last_bar(frame, day, clock, tolerance):
    """Use the final completed 1-minute START-labelled bar, never an end marker."""
    end = pd.Timestamp(f'{day} {clock}', tz=TZ)
    f = frame[(frame.timestamp < end) &
              (frame.timestamp + pd.Timedelta(minutes=1) <= end)]
    if f.empty:
        return None
    row = f.sort_values('timestamp').iloc[-1]
    if (end - (row.timestamp + pd.Timedelta(minutes=1))).total_seconds() / 60 > tolerance:
        return None
    return row
