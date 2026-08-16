try:
    from .price_formatting import format_unit_price_gbp
    from .time_formatting import format_time_from_now
except ImportError:
    from price_formatting import format_unit_price_gbp
    from time_formatting import format_time_from_now

MISSING_TIMER_DETAIL = "Not enough price data"
MISSING_TIMER_TEXT = "—"


def build_find_cheapest_presentation(
    cheapest_slot,
    start_timer_slot,
    finish_timer_slot,
    duration_hours,
    now,
):
    if not cheapest_slot:
        return None

    best_start = cheapest_slot['start']
    best_end = cheapest_slot['end']
    best_average_price = cheapest_slot['average_price_gbp']

    return {
        "highlight_start": best_start,
        "highlight_end": best_end,
        "highlight_label": f"Best {format_duration(duration_hours)}",
        "best_window_text": format_time_window(best_start, best_end),
        "average_price_text": format_unit_price_gbp(best_average_price),
        "start_timer_text": _format_timer_relative_start(start_timer_slot, now),
        "finish_timer_text": _format_timer_relative_finish(finish_timer_slot, now),
        "start_timer_detail": format_timer_slot_detail(start_timer_slot, best_average_price),
        "finish_timer_detail": format_timer_slot_detail(finish_timer_slot, best_average_price),
    }


def build_fixed_start_presentation(slot, best_average_price):
    if not slot:
        return None

    return {
        "highlight_start": slot['start'],
        "highlight_end": slot['end'],
        "window_text": format_time_window(slot['start'], slot['end']),
        "average_price_text": format_unit_price_gbp(slot['average_price_gbp']),
        "comparison_text": format_price_comparison(
            slot['average_price_gbp'],
            best_average_price,
        ),
    }


def format_time_window(start_time, end_time):
    start_text = start_time.astimezone().strftime('%H:%M')
    end_text = end_time.astimezone().strftime('%H:%M')
    return f"{start_text}-{end_text}"


def format_duration(duration_hours):
    hours = int(duration_hours)
    minutes = round((duration_hours - hours) * 60)
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h {minutes}m"


def format_timer_slot_detail(slot, best_average_price):
    if not slot:
        return MISSING_TIMER_DETAIL

    detail = f"{format_time_window(slot['start'], slot['end'])} · {format_unit_price_gbp(slot['average_price_gbp'])}"
    price_delta = format_price_delta(slot['average_price_gbp'], best_average_price)
    if price_delta:
        detail = f"{detail} · {price_delta}"
    return detail


def format_price_delta(average_price, best_average_price):
    delta_pence = max(0, (average_price - best_average_price) * 100)
    if delta_pence < 0.05:
        return None

    delta_text = f"{delta_pence:.1f}".rstrip('0').rstrip('.')
    return f"+{delta_text}p/kWh"


def format_price_comparison(average_price, best_average_price):
    delta_pence = (average_price - best_average_price) * 100
    if abs(delta_pence) < 0.05:
        return "Same as cheapest"

    delta_text = f"{abs(delta_pence):.1f}".rstrip('0').rstrip('.')
    comparison = "more" if delta_pence > 0 else "less"
    return f"{delta_text}p/kWh {comparison}"


def _format_timer_relative_start(slot, now):
    if not slot:
        return MISSING_TIMER_TEXT
    return format_time_from_now(slot['start'], now)


def _format_timer_relative_finish(slot, now):
    if not slot:
        return MISSING_TIMER_TEXT
    return format_time_from_now(slot['end'], now)
