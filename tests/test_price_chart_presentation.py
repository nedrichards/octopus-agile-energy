import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from price_chart_presentation import (
    find_price_index_by_start,
    get_animation_factors,
    get_composited_overlay_alpha,
    get_day_transition_markers,
    get_flyout_horizontal_position,
    get_price_axis_bounds,
)


class PriceChartPresentationTests(unittest.TestCase):
    def test_animation_factors_preserve_motion_speed_across_refresh_rates(self):
        two_frame_rise, two_frame_decay = get_animation_factors(2.0)

        self.assertAlmostEqual(two_frame_rise, 1 - ((1 - 0.28) ** 2))
        self.assertAlmostEqual(two_frame_decay, 0.82 ** 2)

    def test_overlay_alpha_recreates_the_original_combined_fill(self):
        base_alpha = 0.035
        target_alpha = 0.215
        overlay_alpha = get_composited_overlay_alpha(base_alpha, target_alpha)
        composited_alpha = 1 - ((1 - base_alpha) * (1 - overlay_alpha))

        self.assertAlmostEqual(composited_alpha, target_alpha)

    def test_overlay_alpha_never_reduces_the_static_fill(self):
        self.assertEqual(get_composited_overlay_alpha(0.075, 0.035), 0.0)

    def test_flyout_uses_space_to_the_right_inside_scrolled_viewport(self):
        self.assertEqual(
            get_flyout_horizontal_position(360, 150, 300, 700),
            374,
        )

    def test_flyout_flips_left_at_scrolled_viewport_edge(self):
        self.assertEqual(
            get_flyout_horizontal_position(650, 150, 300, 700),
            486,
        )

    def test_flyout_clamps_to_scrolled_viewport_when_neither_side_fits(self):
        self.assertEqual(
            get_flyout_horizontal_position(505, 180, 500, 700),
            508,
        )

    def test_axis_includes_zero_for_positive_prices(self):
        self.assertEqual(get_price_axis_bounds([0.12, 0.24]), (0.0, 0.24))

    def test_axis_includes_zero_for_negative_prices(self):
        self.assertEqual(get_price_axis_bounds([-0.08, -0.02]), (-0.08, 0.0))

    def test_axis_spans_mixed_prices(self):
        self.assertEqual(get_price_axis_bounds([-0.05, 0.21]), (-0.05, 0.21))

    def test_zero_only_axis_still_has_a_drawable_range(self):
        self.assertEqual(get_price_axis_bounds([0.0, 0.0]), (0.0, 0.01))

    def test_axis_rejects_empty_prices(self):
        with self.assertRaises(ValueError):
            get_price_axis_bounds([])

    def test_price_index_follows_a_slot_when_the_window_moves(self):
        first = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
        selected = datetime(2026, 7, 25, 10, 30, tzinfo=timezone.utc)
        prices = [
            {'valid_from': first},
            {'valid_from': selected},
        ]

        self.assertEqual(find_price_index_by_start(prices, selected), 1)

    def test_price_index_clears_a_slot_that_left_the_window(self):
        selected = datetime(2026, 7, 25, 10, 30, tzinfo=timezone.utc)

        self.assertEqual(find_price_index_by_start([], selected), -1)

    def test_day_markers_include_every_visible_midnight(self):
        london = ZoneInfo("Europe/London")
        values = [
            datetime(2026, 7, 25, 23, 30, tzinfo=london),
            datetime(2026, 7, 26, 0, 0, tzinfo=london),
            datetime(2026, 7, 26, 23, 30, tzinfo=london),
            datetime(2026, 7, 27, 0, 0, tzinfo=london),
        ]

        self.assertEqual(
            get_day_transition_markers(values, london),
            [(1, "Tomorrow"), (3, "Monday")],
        )

    def test_day_markers_use_local_dates(self):
        values = [
            datetime(2026, 7, 25, 22, 30, tzinfo=timezone.utc),
            datetime(2026, 7, 25, 23, 0, tzinfo=timezone.utc),
        ]

        london = ZoneInfo("Europe/London")
        self.assertEqual(
            get_day_transition_markers(values, london),
            [(1, "Tomorrow")],
        )


if __name__ == '__main__':
    unittest.main()
