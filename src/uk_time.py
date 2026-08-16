from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UK_TIMEZONE = ZoneInfo("Europe/London")


def expected_half_hours_for_local_day(day: date) -> int:
    """Return the number of half-hours in a Great Britain civil day."""
    local_start = datetime.combine(day, time.min, tzinfo=UK_TIMEZONE)
    local_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=UK_TIMEZONE)
    duration = local_end.astimezone(timezone.utc) - local_start.astimezone(timezone.utc)
    return round(duration.total_seconds() / (30 * 60))


def latest_complete_local_day(synced_at: str | datetime | None) -> date | None:
    """Return the latest GB day known to be complete at a synchronization time."""
    if not synced_at:
        return None

    try:
        if isinstance(synced_at, str):
            synced_at = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
        if synced_at.tzinfo is None:
            synced_at = synced_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None

    return synced_at.astimezone(UK_TIMEZONE).date() - timedelta(days=1)


def is_complete_usage_day(day_text: str | None, sample_count: int, synced_at=None) -> bool:
    """Return whether a daily usage record covers a complete GB civil day."""
    try:
        day = date.fromisoformat(day_text or "")
    except (TypeError, ValueError):
        return False

    latest_complete = latest_complete_local_day(synced_at)
    if latest_complete is not None and day > latest_complete:
        return False
    return sample_count >= expected_half_hours_for_local_day(day)
