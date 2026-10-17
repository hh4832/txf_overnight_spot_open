"""TXF monthly expiry calendar for event QA, not a price-series rollover.

Exchange specification: expiring month's contract ends regular trading at
13:30 (last start-labelled minute 13:29) and has no afterhours session.
Normal contracts can still trade until 13:45 on the same calendar day.
Third Wednesday is the *scheduled* TXF monthly expiry; any exchange
rescheduling must be entered as explicit reviewed exceptions.
https://www.taifex.com.tw/cht/2/tX?menuid1=12
"""
from datetime import date, timedelta
import pandas as pd

# Independently confirmed monthly settlement dates for the evaluated period.
VERIFIED_2026 = {
    '202607': '2026-07-15',
    '202608': '2026-08-19',
    '202609': '2026-09-16',
}


def scheduled_monthly_expiry(month):
    """Scheduled third Wednesday (informational outside verified range)."""
    year, mon = int(month[:4]), int(month[4:6])
    first = date(year, mon, 1)
    return (first + timedelta(days=(2 - first.weekday()) % 7 + 14)).isoformat()


def verified_expiry_contract(day):
    """Return expiring contract only for explicitly verified exchange dates."""
    for month, expiry in VERIFIED_2026.items():
        if str(day) == expiry:
            return month
    return None


def expected_regular_bars(day, contract_month):
    """Normal 300; 285 only if the specific *expiring* contract trades."""
    return (285 if verified_expiry_contract(day) == str(contract_month)
            else 300)


def is_verified_expiring_contract(day, contract_month):
    return verified_expiry_contract(day) == str(contract_month)


def select_verified_day_close(regular, day, tolerance):
    """Prefer normal 13:44; use 13:29 only for verified expiring contract."""
    from .session_alignment import last_bar
    bar = last_bar(regular, day, '13:45', tolerance)
    if bar is not None:
        return bar
    if verified_expiry_contract(day):
        candidate = last_bar(regular, day, '13:30', 0)
        if candidate is not None and is_verified_expiring_contract(
                day, candidate.contract_month):
            return candidate
    return None
