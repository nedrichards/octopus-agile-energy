import math
from datetime import timezone


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
