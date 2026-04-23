from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(IST)


def ist_day_bounds(target: date) -> tuple[datetime, datetime]:
    """
    Returns [start, end) bounds for a date in IST, converted to UTC for DB queries.
    """
    start_ist = datetime.combine(target, time.min, tzinfo=IST)
    end_ist = start_ist + timedelta(days=1)
    return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)


def ist_month_to_date_bounds(reference: datetime | None = None) -> tuple[datetime, datetime]:
    """
    Returns [start_of_month, now) bounds in IST, converted to UTC.
    """
    ref = reference or now_ist()
    start_ist = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start_ist.astimezone(timezone.utc), ref.astimezone(timezone.utc)


def ist_date_range_bounds(from_date: date | None, to_date: date | None) -> tuple[datetime | None, datetime | None]:
    """
    Converts inclusive IST dates into UTC [start, end) datetimes suitable for SQL filtering.
    If a bound is None, returns None for that side.
    """
    start_utc = None
    end_utc = None

    if from_date is not None:
        start_utc, _ = ist_day_bounds(from_date)
    if to_date is not None:
        _, end_utc = ist_day_bounds(to_date)
    return start_utc, end_utc

