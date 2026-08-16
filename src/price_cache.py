from datetime import datetime

from .uk_time import UK_TIMEZONE

PRICE_RELEASE_HOUR = 16


def build_rates_cache_key(tariff_code: str, now: datetime) -> str:
    local_date = now.astimezone(UK_TIMEZONE).date().isoformat()
    return f"octopus_rates_{tariff_code}_{local_date}"


def is_rates_cache_stale(cache_mtime: datetime, now: datetime) -> bool:
    local_now = now.astimezone(UK_TIMEZONE)
    release_time = local_now.replace(hour=PRICE_RELEASE_HOUR, minute=0, second=0, microsecond=0)
    return local_now >= release_time and cache_mtime.astimezone(UK_TIMEZONE) < release_time
