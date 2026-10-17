"""Bounded Hong Kong securities sessions; never reuse mainland holidays.

2026 holidays: https://www.gov.hk/en/about/abouthk/holiday/2026.htm
HKEX securities holiday circular and trading-hours references are retained in
docs/en/operations/hk-daily-prices.md. Unknown years require an audited calendar
update; an observed vendor bar cannot turn an unknown weekday into a session.
"""

from datetime import date, datetime, time, timedelta, timezone

HK_TZ = timezone(timedelta(hours=8), name="Asia/Hong_Kong")
HOLIDAYS = {
    2026: frozenset(
        date.fromisoformat(day)
        for day in (
            "2026-01-01",
            "2026-02-17",
            "2026-02-18",
            "2026-02-19",
            "2026-04-03",
            "2026-04-04",
            "2026-04-06",
            "2026-04-07",
            "2026-05-01",
            "2026-05-25",
            "2026-06-19",
            "2026-07-01",
            "2026-09-26",
            "2026-10-01",
            "2026-10-19",
            "2026-12-25",
            "2026-12-26",
        )
    ),
}
HALF_DAYS = frozenset(
    date.fromisoformat(day)
    for day in (
        "2026-02-16",
        "2026-12-24",
        "2026-12-31",
    )
)
# Five minutes after the latest possible closing-auction end, including half days.
FINAL_AT = time(16, 15)
HALF_DAY_FINAL_AT = time(12, 15)


def is_hk_session(day: date) -> bool:
    if day.year not in HOLIDAYS:
        raise ValueError(f"HK calendar does not cover {day.year}; verified coverage: 2026")
    return day.weekday() < 5 and day not in HOLIDAYS[day.year]


def hk_sessions(start: date, end: date) -> list[date]:
    if start > end:
        raise ValueError("HK calendar start must not exceed end")
    return [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if is_hk_session(start + timedelta(days=i))
    ]


def is_hk_session_final(day: date, now: datetime | None = None) -> bool:
    if not is_hk_session(day):
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("HK session clock must be timezone-aware")
    current = current.astimezone(HK_TZ)
    final_at = HALF_DAY_FINAL_AT if day in HALF_DAYS else FINAL_AT
    return day < current.date() or (day == current.date() and current.time() >= final_at)
