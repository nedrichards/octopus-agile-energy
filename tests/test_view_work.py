"""Regression checks for blocking work, stale results, and retained redraws."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gi.repository import GLib
from src.ui.main_window import MainWindow
from src.ui.paid_rate_chart import PaidRateChart
from src.ui.price_chart import PriceChartWidget
from src.usage_insights import build_paid_rate_presentation, select_paid_rate_period
from src.usage_presentation import add_usage_cost_insights, get_usage_chart_series


class ViewWorkTests(unittest.TestCase):
    def test_usage_loading_waits_for_startup_delay(self):
        window = SimpleNamespace(_usage_loading_delay_id=42, usage_loading_spinner=Mock(),
                                 usage_state_stack=Mock())
        MainWindow._set_usage_loading_state(window)
        window.usage_loading_spinner.start.assert_not_called()
        window.usage_state_stack.set_visible_child_name.assert_not_called()

    def test_usage_delay_only_shows_loading_when_still_pending_and_open(self):
        for closed, state in ((False, "pending"), (False, "content"), (True, "pending")):
            window = SimpleNamespace(_closed=closed, _usage_loading_delay_id=42,
                                     usage_state_stack=Mock(), _set_usage_loading_state=Mock())
            window.usage_state_stack.get_visible_child_name.return_value = state
            self.assertFalse(MainWindow._show_delayed_usage_loading(window))
            self.assertIsNone(window._usage_loading_delay_id)
            self.assertEqual(window._set_usage_loading_state.call_count,
                             int(not closed and state == "pending"))

    def test_fast_usage_result_cancels_loading_before_showing_content_or_setup(self):
        for state in ("content", "empty"):
            window = SimpleNamespace(_usage_loading_delay_id=42, usage_loading_spinner=Mock(),
                                     usage_state_stack=Mock(), usage_empty_title=Mock(),
                                     usage_empty_description=Mock())
            window._cancel_usage_loading_delay = lambda: MainWindow._cancel_usage_loading_delay(window)
            with patch("src.ui.main_window.GLib.source_remove") as remove:
                if state == "content":
                    MainWindow._set_usage_content_state(window)
                else:
                    MainWindow._set_usage_empty_state(window, "Missing key", "Add a key")
            remove.assert_called_once_with(42)
            self.assertIsNone(window._usage_loading_delay_id)
            window.usage_state_stack.set_visible_child_name.assert_called_once_with(state)

    def test_usage_worker_distinguishes_missing_key_from_keyring_failure(self):
        for key, error, state in ((None, None, "key-required"),
                                  (None, GLib.Error("Unavailable"), "keyring-error")):
            window = SimpleNamespace(_apply_usage_dashboard_result=Mock())
            with patch("src.ui.main_window.get_api_key", return_value=key, side_effect=error) as lookup, \
                    patch("src.ui.main_window.GLib.idle_add") as idle:
                MainWindow._load_usage_dashboard_background(window, 1, "", "", (), None)
            lookup.assert_called_once_with(raise_on_error=True)
            self.assertEqual(idle.call_args.args[3]["state"], state)

    def test_usage_transition_only_starts_worker_and_never_reads_keyring_or_cache(self):
        window = SimpleNamespace(
            _closed=False, _usage_analysis_generation=0, _usage_analysis_in_progress=False,
            _usage_analysis_queued=False, settings=Mock(), all_prices=[],
            _usage_insights_input_signature=None, _load_usage_dashboard_background=Mock(),
        )
        with patch("src.ui.main_window.get_api_key", side_effect=AssertionError("UI keyring I/O")), \
                patch("src.ui.main_window.threading.Thread") as thread:
            MainWindow._update_usage_insights(window)
        thread.return_value.start.assert_called_once()
        self.assertTrue(window._usage_analysis_in_progress)

    def test_usage_requests_are_coalesced_and_outdated_results_do_not_touch_widgets(self):
        window = SimpleNamespace(
            _closed=False, _usage_analysis_generation=1, _usage_analysis_in_progress=True,
            _usage_analysis_queued=False, _update_usage_insights=Mock(),
            _set_usage_empty_state=Mock(),
        )
        with patch("src.ui.main_window.threading.Thread") as thread:
            MainWindow._update_usage_insights(window)
            MainWindow._update_usage_insights(window)
            thread.assert_not_called()
        MainWindow._apply_usage_dashboard_result(window, 1, "", {"state": "key-required"})
        window._set_usage_empty_state.assert_not_called()
        window._update_usage_insights.assert_called_once()
        self.assertFalse(window._usage_analysis_in_progress)

    def test_plan_keeps_latest_pending_request_without_applying_old_results(self):
        old, latest = object(), object()
        window = SimpleNamespace(
            _closed=False, _plan_generation=3, _plan_in_progress=True, _plan_queued=latest,
            _apply_plan_presentation=Mock(), _start_plan_calculation=Mock(),
        )
        MainWindow._finish_plan_calculation(window, 2, old, None, None)
        window._apply_plan_presentation.assert_not_called()
        window._start_plan_calculation.assert_called_once_with(latest)
        self.assertIsNone(window._plan_queued)

    def test_closed_views_discard_results_and_do_not_restart_workers(self):
        window = SimpleNamespace(
            _closed=True, _plan_in_progress=True, _plan_queued=object(),
            _apply_plan_presentation=Mock(), _start_plan_calculation=Mock(),
        )
        MainWindow._finish_plan_calculation(window, 1, {}, None, None)
        window._apply_plan_presentation.assert_not_called()
        window._start_plan_calculation.assert_not_called()

    def test_repeated_layout_requests_schedule_one_idle_callback(self):
        window = SimpleNamespace(_closed=False, _layout_refresh_id=None, _refresh_adaptive_layout=Mock())
        with patch("src.ui.main_window.GLib.idle_add", return_value=10) as idle:
            for _ in range(10):
                MainWindow._queue_adaptive_layout(window)
        idle.assert_called_once_with(window._refresh_adaptive_layout)

    def test_reduced_motion_and_unmapped_fades_do_not_schedule_frames(self):
        for mapped, animations in ((True, False), (False, True)):
            widget = Mock()
            widget.get_mapped.return_value = mapped
            window = SimpleNamespace(_closed=False, _fade_animation_sources={},
                                     _animations_enabled=Mock(return_value=animations))
            MainWindow._fade_widget_in(window, widget)
            widget.add_tick_callback.assert_not_called()
            widget.set_opacity.assert_called_once_with(1.0)

    def test_destroy_removes_timers_and_frame_callbacks(self):
        widget, monitor, style = Mock(), Mock(), Mock()
        window = SimpleNamespace(
            _closed=False, _fetch_generation=1, _usage_analysis_generation=2, _plan_generation=3,
            _signal_handlers=[], _draw_areas=[], _owned_actions=[],
            _ui_update_timer_id=4, _price_refresh_watchdog_id=5, _layout_refresh_id=6,
            _usage_loading_delay_id=10,
            _fade_animation_sources={1: (widget, 7)}, network_monitor=monitor,
            _network_handler_id=8, _style_handlers=[(style, 9)],
        )
        with patch("src.ui.main_window.GLib.source_remove") as remove:
            MainWindow._on_destroy(window)
        self.assertEqual([call.args[0] for call in remove.call_args_list], [4, 5, 6, 10])
        widget.remove_tick_callback.assert_called_once_with(7)
        monitor.disconnect.assert_called_once_with(8)
        style.disconnect.assert_called_once_with(9)
        self.assertTrue(window._closed)

    def test_unchanged_prices_do_not_invalidate_geometry(self):
        prices = [{"valid_from": "same", "price_gbp": 0.2}]
        window = SimpleNamespace(prices=prices, current_price_index=0, _queue_static_draw=Mock())
        PriceChartWidget.set_prices(window, list(prices), 0)
        window._queue_static_draw.assert_not_called()

    def test_paid_rate_selection_only_redraws_interaction_layer(self):
        chart = SimpleNamespace(
            points=[("2026-09-01", 10.0)], selected=0,
            _period_data={"descriptions": [("10.0p/kWh", "30 days to 01 Sep 2026")]},
            value=Mock(), detail=Mock(), area=Mock(), _base_area=Mock(),
        )
        PaidRateChart._describe(chart)
        chart.area.queue_draw.assert_called_once()
        chart._base_area.queue_draw.assert_not_called()

    def test_paid_rate_worker_geometry_preserves_gaps_and_periods(self):
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        history = [((start + timedelta(days=i)).date().isoformat(), None if i == 365 else 10.0)
                   for i in range(600)]
        result = build_paid_rate_presentation(history)
        available, _ = select_paid_rate_period(history, None)
        for months, _label in result["options"]:
            points, coverage = select_paid_rate_period(available, months)
            prepared = result["periods"][months]
            self.assertEqual(prepared["points"], points)
            self.assertEqual(prepared["coverage"], coverage)
            self.assertEqual(len(prepared["descriptions"]), len(points))
        self.assertEqual(len(result["periods"][None]["segments"]), 2)

    def test_off_thread_cost_presentation_preserves_negative_rates(self):
        insight = {"avg_text": "8 kWh", "monthly_text": "240 kWh"}
        result = add_usage_cost_insights(insight, None, [], -0.1, 0.5)
        self.assertEqual(result["daily_cost_text"], "-£0.80/day")
        self.assertEqual(result["daily_total_cost_text"], "-£0.30/day")

    def test_prepared_series_retains_uk_dst_completeness(self):
        insight = {"chart_dates": ["2026-03-29", "2026-10-25"], "chart_points": [1, 2]}
        days = [{"date": "2026-03-29", "sample_count": 46, "energy_cost_gbp": -0.5},
                {"date": "2026-10-25", "sample_count": 48, "energy_cost_gbp": 1.0}]
        points, dates, _unit, _days, _rolling = get_usage_chart_series(
            insight, days, graph_mode="energy_cost_gbp",
        )
        self.assertEqual(dates, ["2026-03-29"])
        self.assertEqual(points, [-0.5])


if __name__ == "__main__":
    unittest.main()
