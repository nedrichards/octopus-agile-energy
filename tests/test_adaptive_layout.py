import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.adaptive_layout import (  # noqa: E402
    get_chart_content_width,
    get_chart_height,
    get_chart_scroll_value,
    get_chart_slot_count,
    get_content_margin,
    get_price_summary_mode,
    get_time_label_interval,
    is_compact_width,
)


class AdaptiveLayoutTests(unittest.TestCase):
    def test_compact_width_threshold(self):
        self.assertTrue(is_compact_width(420))
        self.assertFalse(is_compact_width(560))

    def test_content_margin_shrinks_on_compact_widths(self):
        self.assertEqual(get_content_margin(420), 12)
        self.assertEqual(get_content_margin(800), 20)
        self.assertEqual(get_content_margin(960), 24)
        self.assertEqual(get_content_margin(1280), 32)

    def test_chart_height_scales_with_window_width(self):
        self.assertEqual(get_chart_height(420), 160)
        self.assertEqual(get_chart_height(800), 220)
        self.assertEqual(get_chart_height(1280), 260)

    def test_chart_slot_count_scales_with_window_width(self):
        self.assertEqual(get_chart_slot_count(0), 48)
        self.assertEqual(get_chart_slot_count(360), 24)
        self.assertEqual(get_chart_slot_count(700), 40)
        self.assertEqual(get_chart_slot_count(1280), 84)

    def test_chart_content_width_preserves_legible_bar_width(self):
        self.assertEqual(get_chart_content_width(360, 24), 496)
        self.assertEqual(get_chart_content_width(700, 40), 684)
        self.assertEqual(get_chart_content_width(1280, 84), 1408)

    def test_time_label_interval_varies_by_density(self):
        self.assertEqual(get_time_label_interval(420, 24), 6)
        self.assertEqual(get_time_label_interval(800, 40), 8)
        self.assertEqual(get_time_label_interval(1280, 84), 12)

    def test_chart_scroll_value_keeps_target_visible(self):
        self.assertEqual(get_chart_scroll_value(0, 300, 280, 100), 0)
        self.assertEqual(get_chart_scroll_value(0, 300, 900, 120), 0)
        self.assertEqual(get_chart_scroll_value(0, 300, 900, 360), 336)
        self.assertEqual(get_chart_scroll_value(250, 300, 900, 420), 250)

    def test_price_summary_mode_changes_with_screen_constraints(self):
        self.assertEqual(get_price_summary_mode(420, 900), "compact")
        self.assertEqual(get_price_summary_mode(560, 520), "compact")
        self.assertEqual(get_price_summary_mode(700, 900), "regular")
        self.assertEqual(get_price_summary_mode(700, 520), "regular")


if __name__ == '__main__':
    unittest.main()
