import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from usage_insights import build_usage_insight_data


class UsageInsightsTests(unittest.TestCase):
    def test_returns_empty_when_no_samples(self):
        result = build_usage_insight_data([], None)
        self.assertEqual(result["avg_text"], "—")
        self.assertEqual(result["chart_points"], [])

    def test_returns_insights_for_valid_samples(self):
        samples = self._daily_samples(21, lambda day: 10 + day * 0.2)

        result = build_usage_insight_data(samples, "2026-03-22T00:00:00Z")
        self.assertIn("kWh/day", result["avg_text"])
        self.assertIn("%", result["trend_text"])
        self.assertGreater(len(result["chart_points"]), 0)
        self.assertNotIn("Data coverage:", result["summary"])

    def test_includes_low_data_coverage_only_when_history_is_short(self):
        samples = self._daily_samples(10, lambda _day: 10)

        result = build_usage_insight_data(samples, None)

        self.assertIn("Data coverage: low.", result["summary"])

    def test_trend_is_clamped(self):
        samples = self._daily_samples(14, lambda day: 1 if day < 7 else 1000)

        result = build_usage_insight_data(samples, "2026-04-15T00:00:00Z")
        self.assertLessEqual(result["trend_pct"], 100.0)

    def test_trend_excludes_partial_latest_day(self):
        samples = self._daily_samples(14, lambda _day: 10)
        for slot in range(12):
            samples.append({
                "interval_start": f"2026-03-15T{slot // 2:02d}:{'30' if slot % 2 else '00'}:00Z",
                "consumption": 100,
            })

        result = build_usage_insight_data(samples, "2026-03-15T12:00:00Z")

        self.assertEqual(result["trend_text"], "+0.0%")

    def test_trend_needs_fourteen_complete_days(self):
        samples = self._daily_samples(13, lambda _day: 10)

        result = build_usage_insight_data(samples, "2026-03-14T00:00:00Z")

        self.assertEqual(result["trend_text"], "—")
        self.assertIn("14 complete days", result["summary"])

    def _daily_samples(self, day_count, value_for_day):
        samples = []
        for day in range(day_count):
            value = value_for_day(day) / 48
            for slot in range(48):
                samples.append({
                    "interval_start": (
                        f"2026-03-{day+1:02d}T{slot // 2:02d}:"
                        f"{'30' if slot % 2 else '00'}:00Z"
                    ),
                    "consumption": value,
                })
        return samples


if __name__ == "__main__":
    unittest.main()
