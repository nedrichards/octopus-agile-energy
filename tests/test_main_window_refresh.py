import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.price_bands import PRICE_BAND_VERSION
from src.ui.main_window import MainWindow
from src.usage_history import USAGE_CACHE_VERSION


class PriceRefreshCoordinationTests(unittest.TestCase):
    def test_duplicate_automatic_refresh_is_ignored(self):
        window = SimpleNamespace(
            price_refresh_in_progress=True,
            _fetch_generation=4,
            _price_refresh_queued=False,
            _queued_price_refresh_force=False,
            _get_price_setup_issue=Mock(return_value=None),
        )

        started = MainWindow.refresh_price(window, force=False)

        self.assertFalse(started)
        self.assertEqual(window._fetch_generation, 4)
        self.assertFalse(window._price_refresh_queued)

    def test_in_flight_refresh_is_invalidated_and_coalesced(self):
        window = SimpleNamespace(
            price_refresh_in_progress=True,
            _fetch_generation=4,
            _price_refresh_queued=False,
            _queued_price_refresh_force=False,
            _get_price_setup_issue=Mock(return_value=None),
        )

        started = MainWindow.refresh_price(window, force=True)

        self.assertFalse(started)
        self.assertEqual(window._fetch_generation, 5)
        self.assertTrue(window._price_refresh_queued)
        self.assertTrue(window._queued_price_refresh_force)

    def test_finishing_refresh_starts_single_queued_forced_refresh(self):
        window = SimpleNamespace(
            price_refresh_in_progress=True,
            _price_refresh_queued=True,
            _queued_price_refresh_force=True,
            refresh_price=Mock(),
        )

        keep_source = MainWindow._finish_price_refresh(window, 4)

        self.assertFalse(keep_source)
        self.assertFalse(window.price_refresh_in_progress)
        self.assertFalse(window._price_refresh_queued)
        self.assertFalse(window._queued_price_refresh_force)
        window.refresh_price.assert_called_once_with(force=True)


class PriceProcessingTests(unittest.TestCase):
    def test_invalid_and_non_finite_rates_are_skipped_and_valid_rates_sorted(self):
        raw_rates = [
            {"valid_from": "2026-07-01T00:30:00Z", "valid_to": "2026-07-01T01:00:00Z", "value_inc_vat": 20},
            {"valid_from": "2026-07-01T00:00:00Z", "valid_to": "2026-07-01T00:30:00Z", "value_inc_vat": 10},
            {"valid_from": "2026-07-01T01:00:00Z", "valid_to": "2026-07-01T01:30:00Z", "value_inc_vat": float("nan")},
            {"valid_from": None, "valid_to": "2026-07-01T02:00:00Z", "value_inc_vat": 30},
        ]

        with patch("src.ui.main_window.GLib.idle_add") as idle_add:
            MainWindow._process_and_set_prices(SimpleNamespace(_apply_processed_prices=Mock()), raw_rates, 7)

        processed = idle_add.call_args.args[1]
        self.assertEqual([price["price_gbp"] for price in processed], [0.1, 0.2])
        self.assertEqual(processed[0]["valid_from"], datetime(2026, 7, 1, tzinfo=timezone.utc))

    def test_error_detail_ignores_non_object_json(self):
        response = Mock()
        response.json.return_value = []

        self.assertEqual(MainWindow._get_response_detail(response), "")

    def test_half_hour_filter_ignores_malformed_and_non_half_hour_records(self):
        valid = {"valid_from": "2026-07-01T00:00:00Z", "valid_to": "2026-07-01T00:30:00Z"}
        rates = [
            {"valid_from": "2026-07-01T01:00:00Z", "valid_to": None},
            {"valid_from": "2026-07-01T00:30:00Z", "valid_to": "2026-07-01T01:30:00Z"},
            valid,
        ]

        self.assertEqual(MainWindow._filter_half_hour_rates(rates), [valid])


class PlanWorkspaceTests(unittest.TestCase):
    def test_ctrl_f_action_opens_plan_workspace(self):
        window = SimpleNamespace(
            main_view_stack=Mock(),
            duration_spin_button=Mock(),
        )

        MainWindow.on_find_cheapest_action(window, None, None)

        window.main_view_stack.set_visible_child_name.assert_called_once_with("plan")

    def test_input_change_only_recalculates_while_plan_is_visible(self):
        window = SimpleNamespace(
            main_view_stack=Mock(),
            duration_spin_button=Mock(),
            start_within_spin_button=Mock(),
            _update_find_cheapest_settings=Mock(),
            find_cheapest_slot=Mock(),
        )
        window.main_view_stack.get_visible_child_name.return_value = "prices"

        MainWindow.on_find_cheapest_slot_triggered(window, None)

        window._update_find_cheapest_settings.assert_called_once_with()
        window.find_cheapest_slot.assert_not_called()

        window.main_view_stack.get_visible_child_name.return_value = "plan"
        window.duration_spin_button.get_value.return_value = 1.5
        window.start_within_spin_button.get_value_as_int.return_value = 8

        MainWindow.on_find_cheapest_slot_triggered(window, None)

        window.find_cheapest_slot.assert_called_once_with(1.5, 8)

    @patch("src.ui.main_window.GLib.idle_add")
    def test_switching_workspace_remeasures_the_adaptive_layout(self, idle_add):
        stack = Mock()
        stack.get_visible_child_name.return_value = "prices"
        window = SimpleNamespace(
            _refresh_adaptive_layout=Mock(return_value=False),
            best_slot_start_time=None,
            settings=Mock(),
        )

        MainWindow.on_visible_tab_changed(window, stack, None)

        idle_add.assert_called_once_with(window._refresh_adaptive_layout)
        window.settings.set_string.assert_called_once_with("selected-main-view", "prices")

    def test_saved_workspace_is_restored_when_valid(self):
        settings = Mock()
        settings.get_string.return_value = "plan"
        window = SimpleNamespace(settings=settings)

        self.assertEqual(MainWindow._get_saved_main_view_name(window), "plan")

    def test_unknown_saved_workspace_falls_back_to_prices(self):
        settings = Mock()
        settings.get_string.return_value = "retired-experiment"
        window = SimpleNamespace(settings=settings)

        self.assertEqual(MainWindow._get_saved_main_view_name(window), "prices")

    def test_price_chart_selection_does_not_change_plan_comparison(self):
        price_chart = Mock()
        plan_chart = Mock()
        window = SimpleNamespace(
            plan_price_chart=plan_chart,
            plan_comparison_start_time=None,
            _update_plan_comparison=Mock(),
        )

        MainWindow.on_chart_click(window, price_chart, 0)

        self.assertIsNone(window.plan_comparison_start_time)
        window._update_plan_comparison.assert_not_called()

    def test_plan_chart_selection_uses_selected_half_hour(self):
        selected_time = object()
        plan_chart = Mock()
        plan_chart.prices = [{"valid_from": selected_time}]
        window = SimpleNamespace(
            plan_price_chart=plan_chart,
            plan_comparison_start_time=None,
            _update_plan_comparison=Mock(),
        )

        MainWindow.on_chart_click(window, plan_chart, 0)

        self.assertIs(window.plan_comparison_start_time, selected_time)
        window._update_plan_comparison.assert_called_once_with()

    def test_window_size_notification_remeasures_the_adaptive_layout(self):
        window = SimpleNamespace(_refresh_adaptive_layout=Mock())

        MainWindow.on_window_width_changed(window, None, None)

        window._refresh_adaptive_layout.assert_called_once_with()


class UsageRefreshTests(unittest.TestCase):
    def test_long_usage_ranges_select_the_requested_number_of_months(self):
        months = [
            {
                "month_start": f"{2020 + index // 12:04d}-{index % 12 + 1:02d}-01",
                "average_kwh": float(index + 1),
                "day_count": 28,
                "expected_days": 28,
            }
            for index in range(72)
        ]
        insight = {"seasonal": {"chart_months": months}}

        for mode, expected_months in (
            ("12-months", 12),
            ("24-months", 24),
            ("5-years", 60),
        ):
            window = SimpleNamespace(usage_period_mode=mode)
            points, dates, unit, daily_data, rolling = MainWindow._get_usage_chart_series(
                window,
                insight,
                [],
            )
            self.assertEqual(len(points), expected_months)
            self.assertEqual(len(dates), expected_months)
            self.assertEqual(len(daily_data), expected_months)
            self.assertEqual(len(rolling), expected_months)
            self.assertEqual(unit, "kWh")

    def test_old_usage_cache_is_not_fresh_without_seasonal_archive(self):
        window = SimpleNamespace(
            _get_usage_cache=Mock(
                return_value=(
                    {
                        "cache_version": USAGE_CACHE_VERSION - 1,
                        "price_band_version": PRICE_BAND_VERSION,
                        "samples": [],
                        "daily_costs": [],
                    },
                    100.0,
                )
            )
        )

        with patch("src.ui.main_window.time.time", return_value=101.0):
            self.assertFalse(MainWindow._usage_cache_is_fresh(window, "A-TEST"))

    def test_current_usage_cache_with_archive_can_be_fresh(self):
        window = SimpleNamespace(
            _get_usage_cache=Mock(
                return_value=(
                    {
                        "cache_version": USAGE_CACHE_VERSION,
                        "price_band_version": PRICE_BAND_VERSION,
                        "samples": [],
                        "daily_costs": [],
                        "daily_usage_archive": [],
                    },
                    100.0,
                )
            )
        )

        with patch("src.ui.main_window.time.time", return_value=101.0):
            self.assertTrue(MainWindow._usage_cache_is_fresh(window, "A-TEST"))

    def test_seasonal_view_keeps_cost_modes_disabled(self):
        window = SimpleNamespace(
            usage_period_mode="12-months",
            usage_graph_mode="kwh",
            usage_energy_cost_button=Mock(),
            usage_total_cost_button=Mock(),
            usage_kwh_button=Mock(),
        )

        MainWindow._set_usage_cost_graph_controls_enabled(window, True)

        window.usage_energy_cost_button.set_sensitive.assert_called_once_with(False)
        window.usage_total_cost_button.set_sensitive.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
