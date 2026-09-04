from datetime import datetime, time, timedelta, timezone

from .uk_time import UK_TIMEZONE

PRICE_RELEASE_HOUR = 16
PRICE_RELEASE_MINUTE = 1
PRICE_RETRY_DELAYS_SECONDS = (2 * 60, 5 * 60, 10 * 60, 20 * 60, 30 * 60, 60 * 60)


def build_rates_cache_key(tariff_code: str, now: datetime) -> str:
    local_date = now.astimezone(UK_TIMEZONE).date().isoformat()
    return f"octopus_rates_{tariff_code}_{local_date}"


def expected_rates_horizon(now: datetime) -> datetime:
    """Return the end of the GB day prices should cover at this point."""
    local_now = now.astimezone(UK_TIMEZONE)
    published_today = local_now.time() >= time(PRICE_RELEASE_HOUR)
    days_ahead = 2 if published_today else 1
    local_horizon = datetime.combine(
        local_now.date() + timedelta(days=days_ahead),
        time.min,
        tzinfo=UK_TIMEZONE,
    )
    return local_horizon.astimezone(timezone.utc)


def rates_cover_expected_horizon(rates, now: datetime) -> bool:
    """Return whether rates continuously cover now through the expected horizon."""
    now_utc = now.astimezone(timezone.utc)
    minute = 0 if now_utc.minute < 30 else 30
    cursor = now_utc.replace(minute=minute, second=0, microsecond=0)
    horizon = expected_rates_horizon(now)
    intervals = []
    for rate in rates or ():
        try:
            valid_from = rate["valid_from"]
            valid_to = rate["valid_to"]
            if isinstance(valid_from, str):
                valid_from = datetime.fromisoformat(valid_from.replace("Z", "+00:00"))
            if isinstance(valid_to, str):
                valid_to = datetime.fromisoformat(valid_to.replace("Z", "+00:00"))
            if valid_from.tzinfo is None:
                valid_from = valid_from.replace(tzinfo=timezone.utc)
            if valid_to.tzinfo is None:
                valid_to = valid_to.replace(tzinfo=timezone.utc)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if valid_to > valid_from:
            intervals.append((valid_from, valid_to))

    for valid_from, valid_to in sorted(intervals):
        if valid_to <= cursor:
            continue
        if valid_from > cursor:
            return False
        cursor = max(cursor, valid_to)
        if cursor >= horizon:
            return True
    return False


def next_price_release_check(now: datetime) -> datetime:
    """Return the next 16:01 GB wall-clock release check."""
    local_now = now.astimezone(UK_TIMEZONE)
    next_check = local_now.replace(
        hour=PRICE_RELEASE_HOUR,
        minute=PRICE_RELEASE_MINUTE,
        second=0,
        microsecond=0,
    )
    if local_now >= next_check:
        next_check += timedelta(days=1)
    return next_check


def get_price_request_period(now: datetime) -> tuple[datetime, datetime]:
    """Return the smallest useful current-and-forecast API period."""
    now_utc = now.astimezone(timezone.utc)
    minute = 0 if now_utc.minute < 30 else 30
    period_from = now_utc.replace(minute=minute, second=0, microsecond=0)
    return period_from, expected_rates_horizon(now)


def is_rates_cache_stale(cache_mtime: datetime, now: datetime, rates=None) -> bool:
    local_now = now.astimezone(UK_TIMEZONE)
    release_time = local_now.replace(hour=PRICE_RELEASE_HOUR, minute=0, second=0, microsecond=0)
    written_before_release = (
        local_now >= release_time
        and cache_mtime.astimezone(UK_TIMEZONE) < release_time
    )
    return written_before_release or (
        rates is not None and not rates_cover_expected_horizon(rates, now)
    )
