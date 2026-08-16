import math

COMPACT_WIDTH_THRESHOLD = 560
COMPACT_PRICE_WIDTH_THRESHOLD = 480
COMPACT_PRICE_HEIGHT_THRESHOLD = 560
REGULAR_PRICE_WIDTH_THRESHOLD = 640
PLAN_WIDE_WIDTH_THRESHOLD = 1000
PLAN_PANE_WIDTH = 320
PLAN_COLUMN_SPACING = 20
USAGE_WIDE_WIDTH_THRESHOLD = 920
USAGE_PANE_WIDTH = 330
USAGE_COLUMN_SPACING = 20
USAGE_DETAILS_WIDE_WIDTH_THRESHOLD = 1000
USAGE_DETAILS_NARROW_MAX_WIDTH = 600
USAGE_DETAILS_MAX_WIDTH = 920
USAGE_DETAILS_COLUMN_SPACING = 20
DEFAULT_CHART_SLOTS = 48
MAX_CHART_SLOTS = 96
COMPACT_CHART_SLOT_WIDTH = 18
REGULAR_CHART_SLOT_WIDTH = 14
WIDE_CHART_SLOT_WIDTH = 16
USAGE_MIN_SLOT_WIDTH = 8


def is_compact_width(width):
    return width > 0 and width < COMPACT_WIDTH_THRESHOLD


def is_plan_wide_layout(width):
    return width >= PLAN_WIDE_WIDTH_THRESHOLD


def get_plan_chart_width(width, content_margin):
    available_width = max(240, width - (2 * content_margin))
    if not is_plan_wide_layout(width):
        return available_width

    return max(320, available_width - PLAN_PANE_WIDTH - PLAN_COLUMN_SPACING)


def is_usage_wide_layout(width):
    return width >= USAGE_WIDE_WIDTH_THRESHOLD


def is_usage_details_wide_layout(width):
    return width >= USAGE_DETAILS_WIDE_WIDTH_THRESHOLD


def get_usage_details_max_width(width):
    if is_usage_details_wide_layout(width):
        return USAGE_DETAILS_MAX_WIDTH
    return USAGE_DETAILS_NARROW_MAX_WIDTH


def get_usage_chart_width(width, content_margin):
    available_width = max(240, width - (2 * content_margin))
    if not is_usage_wide_layout(width):
        return available_width
    return max(360, available_width - USAGE_PANE_WIDTH - USAGE_COLUMN_SPACING)


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

    return MAX_CHART_SLOTS


def get_chart_content_width(width, slot_count):
    if slot_count <= 0:
        slot_count = DEFAULT_CHART_SLOTS

    if width >= 1100:
        slot_width = WIDE_CHART_SLOT_WIDTH
    elif is_compact_width(width):
        slot_width = COMPACT_CHART_SLOT_WIDTH
    else:
        slot_width = REGULAR_CHART_SLOT_WIDTH

    viewport_width = max(width - 16, 240) if width > 0 else 240
    content_width = slot_count * slot_width + 64
    return max(viewport_width, content_width)


def get_usage_chart_content_width(width, slot_count):
    """Fit normal Usage ranges while retaining scrolling at extreme widths."""
    if slot_count <= 0:
        slot_count = DEFAULT_CHART_SLOTS

    viewport_width = max(width - 16, 240) if width > 0 else 240
    content_width = slot_count * USAGE_MIN_SLOT_WIDTH + 64
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
