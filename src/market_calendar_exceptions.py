"""Reviewed exchange exceptions; never infer closures from an empty API response.

Only exact, independently corroborated market closures are listed here.
Unlisted periods remain fail-closed, including whole-week provider outages.
Add further years only after checking official exchange announcements.
"""
from datetime import date

TAIFEX_2019_CNY = (
    "https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/"
    "%E5%85%AC%E5%91%8A%E6%9C%AC%E5%85%AC%E5%8F%B8%E6%9C%9F%E8%B2%A8"
    "%E9%9B%86%E4%B8%AD%E4%BA%A4%E6%98%93%E5%B8%82%E5%A0%B4108%E5%B9%B4"
    "%E8%BE%B2%E6%9B%86%E6%98%A5%E7%AF%80%E4%BC%91%E5%B8%82%E6%9A%A8"
    "%E7%9B%B8%E9%97%9C%E4%BA%8B%E5%AE%9C.pdf"
)
TWSE_0050_SPLIT = (
    "https://www.twse.com.tw/zh/ETFortune/announcement?"
    "company=A00005&date=20250617&fund=0050&seq=1&type=other"
)

# TAIFEX letter dated 2019-01-02: no trading during 2019-02-04..08,
# plus ordinary weekend 2019-02-09..10.
REVIEWED_TXF_CLOSED_WINDOWS = (
    dict(start="2019-02-04", end="2019-02-10",
         reason="TAIFEX_2019_LUNAR_NEW_YEAR_FULL_CLOSURE",
         source_url=TAIFEX_2019_CNY),
)

# TWSE official ETF announcement: 0050 had no trading 2025-06-11..17
# while conducting a 4-for-1 split; reopened 2025-06-18.
REVIEWED_0050_SUSPENSIONS = (
    dict(start="2025-06-11", end="2025-06-17",
         reason="ETF_0050_VERIFIED_SPLIT_TRADING_SUSPENSION",
         source_url=TWSE_0050_SPLIT),
)


def _iso(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Expected ISO-8601 YYYY-MM-DD exchange date")
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("Invalid exchange date") from None
    if parsed.isoformat() != value:
        raise ValueError("Non-canonical exchange date")
    return parsed


def reviewed_txf_closed_partition(start, end):
    """Verified only when every requested date is within one known closure."""
    a, b = _iso(start), _iso(end)
    if a > b:
        raise ValueError("Partition start is after end")
    for entry in REVIEWED_TXF_CLOSED_WINDOWS:
        if _iso(entry["start"]) <= a and b <= _iso(entry["end"]):
            return entry.copy()
    return None


def reviewed_0050_suspension(day):
    """Return reviewed suspension reason/evidence, or None for unknown gaps."""
    current = _iso(day)
    for entry in REVIEWED_0050_SUSPENSIONS:
        if _iso(entry["start"]) <= current <= _iso(entry["end"]):
            return entry.copy()
    return None
