import math
from datetime import timezone

try:
    from .uk_time import UK_TIMEZONE
except ImportError:
    from uk_time import UK_TIMEZONE


def is_ambiguous_uk_time(value):
    """Return whether an instant falls in a repeated UK wall-clock hour."""
    local_value = value.astimezone(UK_TIMEZONE)
    return (
        local_value.replace(fold=0).utcoffset()
        != local_value.replace(fold=1).utcoffset()
    )


def format_uk_time(value, force_timezone=False):
    """Format a UK time, identifying repeated autumn clock times."""
    local_value = value.astimezone(UK_TIMEZONE)
    pattern = "%H:%M %Z" if force_timezone or is_ambiguous_uk_time(value) else "%H:%M"
    return local_value.strftime(pattern)


def format_uk_time_window(start_time, end_time, separator="-"):
    """Format a UK time range without making a clock-change range ambiguous."""
    local_start = start_time.astimezone(UK_TIMEZONE)
    local_end = end_time.astimezone(UK_TIMEZONE)
    include_timezone = (
        local_start.utcoffset() != local_end.utcoffset()
        or is_ambiguous_uk_time(start_time)
        or is_ambiguous_uk_time(end_time)
    )
    start_text = format_uk_time(start_time, force_timezone=include_timezone)
    end_text = format_uk_time(end_time, force_timezone=include_timezone)
    return f"{start_text}{separator}{end_text}"


def format_time_from_now(target_time, now):
    seconds_from_now = (
        target_time.astimezone(timezone.utc) - now.astimezone(timezone.utc)
    ).total_seconds()
    minutes_from_now = max(0, math.ceil(seconds_from_now / 60))

    if minutes_from_now == 0:
        return "now"

    hours, minutes = divmod(minutes_from_now, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")

    return ' '.join(parts)
