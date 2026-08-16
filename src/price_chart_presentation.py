try:
    from .uk_time import UK_TIMEZONE
except ImportError:
    from uk_time import UK_TIMEZONE


def get_price_axis_bounds(prices):
    """Return axis bounds that always include the zero-price baseline."""
    if not prices:
        raise ValueError("prices must not be empty")

    lower_bound = min(0.0, min(prices))
    upper_bound = max(0.0, max(prices))
    if upper_bound == lower_bound:
        upper_bound = lower_bound + 0.01

    return lower_bound, upper_bound


def get_animation_factors(elapsed_frames, rise_per_frame=0.28, decay_per_frame=0.82):
    """Return refresh-rate-independent rise and decay factors."""
    elapsed_frames = max(0.0, elapsed_frames)
    return (
        1 - ((1 - rise_per_frame) ** elapsed_frames),
        decay_per_frame ** elapsed_frames,
    )


def get_composited_overlay_alpha(base_alpha, target_alpha):
    """Return the overlay alpha needed to preserve a target visual opacity."""
    if not 0.0 <= base_alpha < 1.0:
        raise ValueError("base_alpha must be between zero and one")
    target_alpha = max(base_alpha, min(1.0, target_alpha))
    return (target_alpha - base_alpha) / (1 - base_alpha)


def find_price_index_by_start(prices, target_time):
    """Find a visible slot by its stable start time, or return -1."""
    if target_time is None:
        return -1

    return next(
        (
            index
            for index, price in enumerate(prices)
            if price['valid_from'] == target_time
        ),
        -1,
    )


def get_flyout_horizontal_position(
    point_x,
    flyout_width,
    viewport_left,
    viewport_right,
    gap=14,
    padding=8,
):
    """Place a chart flyout beside its point while keeping it in the viewport."""
    minimum_x = viewport_left + padding
    maximum_x = max(minimum_x, viewport_right - padding - flyout_width)

    if point_x + gap + flyout_width <= viewport_right - padding:
        preferred_x = point_x + gap
    elif point_x - gap - flyout_width >= viewport_left + padding:
        preferred_x = point_x - gap - flyout_width
    else:
        preferred_x = point_x - flyout_width / 2

    return max(minimum_x, min(preferred_x, maximum_x))


def get_day_transition_markers(valid_from_values, local_timezone=UK_TIMEZONE):
    """Return each visible day boundary as an index and short chart label."""
    if not valid_from_values:
        return []

    first_date = valid_from_values[0].astimezone(local_timezone).date()
    previous_date = first_date
    markers = []

    for index, valid_from in enumerate(valid_from_values[1:], start=1):
        current_date = valid_from.astimezone(local_timezone).date()
        if current_date != previous_date:
            day_offset = (current_date - first_date).days
            label = "Tomorrow" if day_offset == 1 else current_date.strftime("%A")
            markers.append((index, label))
        previous_date = current_date

    return markers
