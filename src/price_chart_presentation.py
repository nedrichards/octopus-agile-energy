def get_price_axis_bounds(prices):
    """Return axis bounds that always include the zero-price baseline."""
    if not prices:
        raise ValueError("prices must not be empty")

    lower_bound = min(0.0, min(prices))
    upper_bound = max(0.0, max(prices))
    if upper_bound == lower_bound:
        upper_bound = lower_bound + 0.01

    return lower_bound, upper_bound


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


def get_day_transition_markers(valid_from_values, local_timezone=None):
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
