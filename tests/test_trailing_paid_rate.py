import unittest
from datetime import date, timedelta

from src.uk_time import expected_half_hours_for_local_day
from src.usage_insights import (
    build_paid_rate_history,
    build_trailing_paid_rate,
    build_usage_dashboard_data,
    paid_rate_period_options,
    select_paid_rate_period,
)
from src.usage_seasonality import merge_daily_usage_archive


class TrailingPaidRateTests(unittest.TestCase):
    def test_period_options_follow_available_history(self):
        start = date(2026, 1, 1)
        for length, expected in ((45, [None]), (181, [None]), (212, [6, None]),
                                 (400, [6, 12, None]), (800, [6, 12, 24, None])):
            with self.subTest(length=length):
                history = [((start + timedelta(days=i)).isoformat(), 20) for i in range(length)]
                options, label = paid_rate_period_options(history)
                self.assertEqual([months for months, _ in options], expected)
                self.assertTrue(label.startswith("Available history"))

    def test_unavailable_edges_do_not_unlock_longer_periods(self):
        start = date(2025, 1, 1)
        history = [((start + timedelta(days=i)).isoformat(), 20 if 300 <= i < 345 else None)
                   for i in range(400)]
        options, label = paid_rate_period_options(history)
        self.assertEqual(options, [(None, "All available · 45 days")])
        self.assertEqual(label, "Available history · 45 days")
        points, message = select_paid_rate_period(history, None)
        self.assertEqual(len(points), 45)
        self.assertEqual(message, "")

    def test_all_available_preserves_gaps_without_shortfall_warning(self):
        points, message = select_paid_rate_period([("2026-01-01", 20), ("2026-01-02", None),
                                                  ("2026-01-03", 21)], None)
        self.assertEqual(len(points), 3)
        self.assertEqual(message, "Gaps mark missing usage or prices.")

    def test_chart_trims_empty_edges_but_keeps_internal_gaps(self):
        start = date(2026, 3, 1)
        history = [((start + timedelta(days=i)).isoformat(),
                    20 if i in (20, 21, 23) else None) for i in range(90)]
        points, message = select_paid_rate_period(history, 6)
        self.assertEqual(len(points), 4)
        self.assertIsNone(points[2][1])
        self.assertIn("full selected period", message)
        self.assertIn("Gaps", message)

    def test_chart_empty_period_and_single_point(self):
        self.assertEqual(select_paid_rate_period([("2026-09-07", None)], 6)[0], [])
        self.assertEqual(select_paid_rate_period([("2026-09-07", 20)], 6)[0], [("2026-09-07", 20)])

    def test_complete_chart_period_has_no_shortfall_notice(self):
        start = date(2026, 3, 8)
        history = [((start + timedelta(days=i)).isoformat(), 20) for i in range(184)]
        points, message = select_paid_rate_period(history, 6)
        self.assertEqual(len(points), 184)
        self.assertEqual(message, "")

    def test_rolling_history_requires_every_calendar_day_and_recovers(self):
        start = date(2026, 3, 1)
        days = [self.day(start + timedelta(days=i), kwh=10 if i else 100, cost=2 if i else -5)
                for i in range(61)]
        result = dict(build_paid_rate_history(days, "2026-05-01T23:00:00Z"))
        self.assertAlmostEqual(result["2026-03-30"], 100 * 53 / 390)
        self.assertIsNone(result["2026-03-29"])
        days[30]["missing_rate_count"] = 1
        result = dict(build_paid_rate_history(days, "2026-05-01T23:00:00Z"))
        self.assertIsNone(result["2026-04-29"])
        self.assertEqual(result["2026-04-30"], 20)

    def test_daily_archive_retains_costs_beyond_recent_samples(self):
        from datetime import datetime, timezone

        day = dict(self.day(date(2025, 1, 1)), kwh=10)
        archive = merge_daily_usage_archive([day], [], datetime(2026, 9, 7, tzinfo=timezone.utc))
        self.assertEqual(archive[0]["energy_cost_gbp"], 2)
        self.assertEqual(archive[0]["matched_kwh"], 10)

    @staticmethod
    def day(day, kwh=10, cost=2):
        return {"date": day.isoformat(), "sample_count": expected_half_hours_for_local_day(day),
                "missing_rate_count": 0, "matched_kwh": kwh, "energy_cost_gbp": cost,
                "total_cost_gbp": cost + 1}

    def test_calendar_window_weighting_and_standing_charge_exclusion(self):
        start = date(2026, 8, 8)
        days = [self.day(start + timedelta(days=i)) for i in range(30)]
        days[0] = self.day(start, kwh=100, cost=5)
        days += [self.day(start - timedelta(days=1), cost=999),
                 self.day(date(2026, 9, 7), cost=999)]
        result = build_usage_dashboard_data([], "2026-09-07T10:00:00Z", days)
        self.assertEqual(result["average_unit_text"], "16.2p/kWh")
        self.assertIn("30/30", result["average_unit_detail"])
        self.assertIn("08 Aug 2026–06 Sep 2026", result["average_unit_detail"])

    def test_missing_days_are_not_replaced_by_older_days(self):
        days = [self.day(date(2026, 9, 6)), self.day(date(2026, 9, 5)),
                self.day(date(2026, 9, 4)), self.day(date(2026, 8, 7), cost=999)]
        days[1]["sample_count"] = 47
        days[2]["missing_rate_count"] = 1
        result = build_trailing_paid_rate(days, "2026-09-07T10:00:00Z")
        self.assertEqual(result["text"], "20.0p/kWh")
        self.assertIn("1/30", result["detail"])

    def test_clock_changes_and_uk_midnight(self):
        for day, sync in ((date(2026, 3, 29), "2026-03-29T23:00:00Z"),
                          (date(2026, 10, 25), "2026-10-26T00:00:00Z")):
            with self.subTest(day=day):
                result = build_trailing_paid_rate([self.day(day, cost=-1)], sync)
                self.assertEqual(result["text"], "-10.0p/kWh")
                self.assertIn("1/30", result["detail"])

    def test_empty_and_zero_usage(self):
        self.assertEqual(build_trailing_paid_rate([], None)["text"], "—")
        self.assertEqual(build_trailing_paid_rate(
            [self.day(date(2026, 9, 6), kwh=0, cost=0)], "2026-09-07T00:00:00Z"
        )["text"], "—")
