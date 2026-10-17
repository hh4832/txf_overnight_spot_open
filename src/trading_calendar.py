import pandas as pd


def next_spot_day(date, dates):
    """Actual validated 0050 sessions, not a weekday calendar or missing-price dropna."""
    later = sorted(d for d in dates if d > date)
    return later[0] if later else None


def gap_flags(day, nxt):
    days = pd.date_range(pd.Timestamp(day)+pd.Timedelta(days=1), pd.Timestamp(nxt)-pd.Timedelta(days=1))
    return any(d.dayofweek >= 5 for d in days), any(d.dayofweek < 5 for d in days)
