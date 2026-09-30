import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.ui.main_window import MainWindow
from src.ui.paid_rate_chart import PaidRateChart
from src.ui.preferences_window import PreferencesDialog


class UsageRefreshRecoveryTests(unittest.TestCase):
    def window(self):
        window = SimpleNamespace(
            _closed=False, usage_refresh_in_progress=False, usage_refresh_attempted=True,
            _usage_refresh_retry_after=100, settings=Mock(), _set_usage_refreshing_label=Mock(),
            _refresh_usage_history_background=Mock(),
        )
        window.settings.get_string.return_value = "A-EXAMPLE"
        return window

    def test_retry_is_throttled_but_not_blocked_for_the_session(self):
        window = self.window()
        with patch("src.ui.main_window.time.monotonic", return_value=99), \
                patch("src.ui.main_window.threading.Thread") as worker:
            self.assertFalse(MainWindow.refresh_usage_history_background(window))
            worker.assert_not_called()
        with patch("src.ui.main_window.time.monotonic", return_value=101), \
                patch("src.ui.main_window.threading.Thread") as worker:
            self.assertTrue(MainWindow.refresh_usage_history_background(window))
            worker.return_value.start.assert_called_once()
        self.assertEqual(window._usage_refresh_retry_after, 401)

    def test_manual_refresh_bypasses_retry_delay_but_not_an_active_worker(self):
        window = self.window()
        with patch("src.ui.main_window.time.monotonic", return_value=99), \
                patch("src.ui.main_window.threading.Thread") as worker:
            self.assertTrue(MainWindow.refresh_usage_history_background(window, force=True))
            self.assertFalse(MainWindow.refresh_usage_history_background(window, force=True))
            worker.return_value.start.assert_called_once()
        window._set_usage_refreshing_label.assert_called_once()

    def test_fresh_cache_avoids_network_even_on_a_later_automatic_check(self):
        window = SimpleNamespace(_usage_cache_is_fresh=Mock(return_value=True),
                                 _finish_usage_history_background_refresh=Mock())
        with patch("src.ui.main_window.get_api_key", return_value="example"), \
                patch("src.ui.main_window.get_account_data") as account, \
                patch("src.ui.main_window.GLib.idle_add") as idle:
            MainWindow._refresh_usage_history_background(window, "A-EXAMPLE")
        account.assert_not_called()
        idle.assert_called_once_with(window._finish_usage_history_background_refresh, False)

    def test_failed_manual_refresh_restores_timestamp_and_reports_failure(self):
        for failed in (False, True):
            window = SimpleNamespace(
                _closed=False, usage_refresh_in_progress=True, _usage_synced_at="2026-09-30T08:00:00Z",
                _usage_dashboard_insight={"cached": True}, _refresh_button_waiting_for_usage=True,
                _set_usage_updated_label=Mock(), toast_overlay=Mock(), main_view_stack=Mock(),
                _update_usage_insights=Mock(), header_refresh_button=Mock(),
            )
            window.main_view_stack.get_visible_child_name.return_value = "usage"
            with patch("src.ui.main_window.Adw.Toast.new"):
                MainWindow._finish_usage_history_background_refresh(window, False, failed)
            window._set_usage_updated_label.assert_called_once_with("2026-09-30T08:00:00Z")
            window.header_refresh_button.set_sensitive.assert_called_once_with(True)
            self.assertEqual(window.toast_overlay.add_toast.call_count, int(failed))
            self.assertFalse(window.usage_refresh_in_progress)
            self.assertFalse(window._refresh_button_waiting_for_usage)
            self.assertEqual(window._usage_dashboard_insight, {"cached": True})

    def test_visible_usage_checks_again_on_the_half_hour(self):
        window = SimpleNamespace(_closed=False, update_current_price=Mock(), main_view_stack=Mock(),
                                 refresh_usage_history_background=Mock(), schedule_next_ui_update=Mock())
        window.main_view_stack.get_visible_child_name.return_value = "usage"
        MainWindow._on_ui_update_timer(window)
        window.refresh_usage_history_background.assert_called_once_with()

    def test_network_recovery_resets_retry_delay_and_checks_visible_usage(self):
        window = SimpleNamespace(_usage_refresh_retry_after=999, _on_data_fetch_timer=Mock(),
                                 main_view_stack=Mock(), refresh_usage_history_background=Mock())
        window.main_view_stack.get_visible_child_name.return_value = "usage"
        MainWindow._on_network_changed(window, None, True)
        self.assertEqual(window._usage_refresh_retry_after, 0)
        window.refresh_usage_history_background.assert_called_once_with()


class PaidRateSelectionRetentionTests(unittest.TestCase):
    def test_refresh_preserves_date_when_new_points_are_added_or_removed(self):
        for points, expected in (([("a", 1), ("b", 2), ("c", 3), ("d", 4)], 1),
                                 ([("b", 2), ("c", 3)], 0), ([("c", 3)], 0), ([], 0)):
            chart = SimpleNamespace(
                _changing_periods=False, period=Mock(), period_options=[(None, "All")],
                points=[("a", 1), ("b", 2), ("c", 3)], selected=1,
                _presentation={"periods": {None: {"points": points, "coverage": ""}}},
                coverage=Mock(), coverage_box=Mock(), area=Mock(),
                _invalidate_static=Mock(), _describe=Mock(),
            )
            chart.period.get_selected.return_value = 0
            PaidRateChart._update(chart)
            self.assertEqual(chart.selected, expected)


class AutoDetectResultTests(unittest.TestCase):
    def window(self):
        return SimpleNamespace(
            _closed=False, _auto_detect_generation=2, _auto_detect_context=Mock(return_value=("current",)),
            _set_auto_detect_status=Mock(), _set_auto_detect_button_state=Mock(),
            _apply_auto_detected_tariff=Mock(return_value=False),
        )

    def test_closed_or_superseded_requests_do_not_change_choices_or_feedback(self):
        for closed, request in ((True, 2), (False, 1)):
            window = self.window()
            window._closed = closed
            PreferencesDialog._finish_auto_detect(window, request, ("current",), ("tariff", "_A", "AGILE"), None)
            window._apply_auto_detected_tariff.assert_not_called()
            window._set_auto_detect_status.assert_not_called()
            window._set_auto_detect_button_state.assert_not_called()

    def test_changed_account_or_manual_choices_discard_success_and_error_results(self):
        for result, error in ((("tariff", "_A", "AGILE"), None), (None, "Network error")):
            window = self.window()
            PreferencesDialog._finish_auto_detect(window, 2, ("old choices",), result, error)
            window._apply_auto_detected_tariff.assert_not_called()
            self.assertIn("Settings changed", window._set_auto_detect_status.call_args.args[0])
            window._set_auto_detect_button_state.assert_called_once_with(True)

    def test_current_result_applies_detected_choices(self):
        window = self.window()
        PreferencesDialog._finish_auto_detect(window, 2, ("current",), ("tariff", "_A", "AGILE"), None)
        window._apply_auto_detected_tariff.assert_called_once_with("tariff", "_A", "AGILE")

    def test_reopening_preferences_restores_auto_detect_after_cancelled_request(self):
        preferences = Mock()
        preferences._closed = True
        window = SimpleNamespace(preferences_window=preferences)
        MainWindow.on_preferences_action(window, None, None)
        preferences._set_auto_detect_button_state.assert_called_once_with(True)
        preferences._set_auto_detect_status.assert_called_once_with("")
        self.assertFalse(preferences._closed)


if __name__ == "__main__":
    unittest.main()
