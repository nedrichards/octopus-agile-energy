import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.adaptive_layout import (
    get_chart_content_width,
    get_chart_height,
    get_chart_scroll_value,
    get_chart_slot_count,
    get_content_margin,
    get_plan_chart_width,
    get_price_summary_mode,
    get_time_label_interval,
    get_usage_chart_content_width,
    get_usage_chart_width,
    get_usage_details_max_width,
    get_usage_top_row_height,
    is_compact_width,
    is_plan_wide_layout,
    is_usage_details_wide_layout,
    is_usage_wide_layout,
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

    def test_chart_slot_count_keeps_forecast_horizon_across_widths(self):
        self.assertEqual(get_chart_slot_count(0), 48)
        self.assertEqual(get_chart_slot_count(360), 96)
        self.assertEqual(get_chart_slot_count(700), 96)
        self.assertEqual(get_chart_slot_count(1280), 96)

    def test_chart_content_width_preserves_legible_slot_width(self):
        self.assertEqual(get_chart_content_width(360, 96), 1792)
        self.assertEqual(get_chart_content_width(700, 96), 1408)
        self.assertEqual(get_chart_content_width(1280, 96), 1600)

    def test_time_label_interval_varies_by_density(self):
        self.assertEqual(get_time_label_interval(420, 96), 24)
        self.assertEqual(get_time_label_interval(800, 96), 16)
        self.assertEqual(get_time_label_interval(1280, 96), 12)

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

    def test_plan_workspace_stacks_until_a_wide_window_is_available(self):
        self.assertFalse(is_plan_wide_layout(700))
        self.assertFalse(is_plan_wide_layout(999))
        self.assertTrue(is_plan_wide_layout(1000))

    def test_plan_chart_width_reserves_a_wide_planner_pane(self):
        self.assertEqual(get_plan_chart_width(700, 20), 660)
        self.assertEqual(get_plan_chart_width(1000, 24), 612)
        self.assertEqual(get_plan_chart_width(1280, 32), 876)

    def test_usage_layout_uses_equal_tracks_for_the_wide_workspace(self):
        self.assertFalse(is_usage_wide_layout(999))
        self.assertTrue(is_usage_wide_layout(1000))
        self.assertEqual(get_usage_chart_width(999, 24), 951)
        self.assertEqual(get_usage_chart_width(1000, 24), 466)

    def test_usage_details_align_with_the_wide_workspace(self):
        self.assertFalse(is_usage_details_wide_layout(999))
        self.assertTrue(is_usage_details_wide_layout(1000))
        self.assertEqual(get_usage_details_max_width(999), 600)
        self.assertEqual(get_usage_details_max_width(1000), 952)

    def test_usage_chart_keeps_normal_ranges_at_a_stable_viewport_width(self):
        self.assertEqual(get_usage_chart_content_width(396, 30), 380)
        self.assertEqual(get_usage_chart_content_width(396, 12), 380)
        self.assertEqual(get_usage_chart_content_width(522, 30), 506)
        self.assertEqual(get_usage_chart_content_width(522, 12), 506)

    def test_usage_wide_top_row_reserves_chart_controls_and_detail(self):
        self.assertEqual(get_usage_top_row_height(705), 366)
        self.assertEqual(get_usage_top_row_height(1100), 406)

    def test_usage_chart_only_scrolls_at_extreme_widths(self):
        self.assertEqual(get_usage_chart_content_width(240, 30), 304)


if __name__ == '__main__':
    unittest.main()
