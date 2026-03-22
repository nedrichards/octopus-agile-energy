import math


COMPACT_WIDTH_THRESHOLD = 560
COMPACT_PRICE_WIDTH_THRESHOLD = 480
COMPACT_PRICE_HEIGHT_THRESHOLD = 560
REGULAR_PRICE_WIDTH_THRESHOLD = 640
DEFAULT_CHART_SLOTS = 48
MIN_CHART_SLOTS = 24
MAX_CHART_SLOTS = 96
COMPACT_CHART_BAR_WIDTH = 18
REGULAR_CHART_BAR_WIDTH = 14
WIDE_CHART_BAR_WIDTH = 16


def is_compact_width(width):
    return width > 0 and width < COMPACT_WIDTH_THRESHOLD


def get_content_margin(width):
    if width >= 1200:
        return 32
    if width >= 900:
        return 24
    return 12 if is_compact_width(width) else 20


def get_chart_height(width):
    if width >= 1100:
        return 260
    if is_compact_width(width):
        return 160
    return 220


def get_chart_slot_count(width):
    if width <= 0:
        return DEFAULT_CHART_SLOTS

    usable_width = max(width - 96, 240)
    slot_count = usable_width // 14
    slot_count = max(MIN_CHART_SLOTS, min(MAX_CHART_SLOTS, slot_count))

    remainder = slot_count % 4
    if remainder:
        slot_count -= remainder

    return max(MIN_CHART_SLOTS, slot_count)


def get_chart_content_width(width, slot_count):
    if slot_count <= 0:
        slot_count = DEFAULT_CHART_SLOTS

    if width >= 1100:
        bar_width = WIDE_CHART_BAR_WIDTH
    elif is_compact_width(width):
        bar_width = COMPACT_CHART_BAR_WIDTH
    else:
        bar_width = REGULAR_CHART_BAR_WIDTH

    viewport_width = max(width - 16, 240) if width > 0 else 240
    content_width = slot_count * bar_width + 64
    return max(viewport_width, content_width)


def get_time_label_interval(width, slot_count):
    if slot_count <= 0:
        return 2

    target_labels = 4 if is_compact_width(width) else 6
    if width >= 1100:
        target_labels = 8

    interval = max(2, math.ceil(slot_count / target_labels))
    if interval % 2:
        interval += 1

    return interval


def get_price_summary_mode(width, height):
    if width >= REGULAR_PRICE_WIDTH_THRESHOLD:
        return "regular"

    narrow_width = width > 0 and width < COMPACT_PRICE_WIDTH_THRESHOLD
    short_height = height > 0 and height < COMPACT_PRICE_HEIGHT_THRESHOLD
    return "compact" if narrow_width or short_height else "regular"


def get_chart_scroll_value(current_value, page_size, content_width, target_x, padding=24):
    if page_size <= 0 or content_width <= page_size:
        return 0

    visible_start = current_value
    visible_end = current_value + page_size
    desired_start = max(0, target_x - padding)

    if visible_start <= target_x <= visible_end - padding:
        return current_value

    max_scroll = max(0, content_width - page_size)
    return min(max_scroll, max(0, desired_start))
