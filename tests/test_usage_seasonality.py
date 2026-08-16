import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.uk_time import expected_half_hours_for_local_day, latest_complete_local_day
from src.usage_seasonality import (
    build_daily_usage_archive,
    build_seasonal_usage_insight,
    merge_daily_usage_archive,
)


class UsageSeasonalityTests(unittest.TestCase):
    def test_expected_half_hours_follow_clock_changes(self):
        self.assertEqual(expected_half_hours_for_local_day(date(2026, 3, 29)), 46)
        self.assertEqual(expected_half_hours_for_local_day(date(2026, 10, 25)), 50)

    def test_latest_complete_day_uses_great_britain_time(self):
        self.assertEqual(
            latest_complete_local_day("2026-07-01T23:30:00Z"),
            date(2026, 7, 1),
        )

    def test_daily_archive_groups_samples_by_local_day(self):
        archive = build_daily_usage_archive([
            {"interval_start": "2026-07-01T23:00:00Z", "consumption": 1.0},
            {"interval_start": "2026-07-02T00:00:00Z", "consumption": 2.0},
        ])

        self.assertEqual(archive, [{"date": "2026-07-02", "kwh": 3.0}])

    def test_archive_merge_replaces_overlap_and_prunes_old_days(self):
        now = datetime(2026, 8, 16, tzinfo=timezone.utc)
        merged = merge_daily_usage_archive(
            [
                {"date": "2020-07-01", "kwh": 9.0},
                {"date": "2026-08-01", "kwh": 8.0},
            ],
            [
                {"date": "2026-08-01", "kwh": 7.0},
                {"date": "2026-08-02", "kwh": 6.0},
            ],
            now,
        )

        self.assertEqual(merged, [
            {"date": "2026-08-01", "kwh": 7.0},
            {"date": "2026-08-02", "kwh": 6.0},
        ])

    def test_seasonal_comparison_uses_same_period_last_year(self):
        latest = date(2026, 8, 15)
        archive = []
        for offset in range(28):
            day = latest - timedelta(days=offset)
            archive.append({"date": day.isoformat(), "kwh": 8.0})
            previous = day.replace(year=day.year - 1)
            archive.append({"date": previous.isoformat(), "kwh": 10.0})

        result = build_seasonal_usage_insight(archive, "2026-08-16T12:00:00Z")

        self.assertEqual(result["recent_average_text"], "8.00 kWh/day")
        self.assertEqual(result["year_comparison_text"], "-20.0%")
        self.assertEqual(result["annual_average"], 8.0)
        self.assertIn("20% lower", result["summary"])

    def test_seasonal_comparison_waits_for_sufficient_prior_coverage(self):
        archive = [
            {"date": f"2026-08-{day:02d}", "kwh": 8.0}
            for day in range(1, 16)
        ]

        result = build_seasonal_usage_insight(archive, "2026-08-16T12:00:00Z")

        self.assertEqual(result["year_comparison_text"], "—")
        self.assertIn("matching period", result["summary"])


if __name__ == "__main__":
    unittest.main()
