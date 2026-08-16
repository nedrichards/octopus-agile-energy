import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.price_bands import PRICE_BAND_VERSION
from src.usage_insights import build_rolling_average, build_usage_insight_data, build_usage_pattern_insights


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
        self.assertEqual(len(result["chart_rolling_average"]), len(result["chart_points"]))
        self.assertNotIn("Data coverage:", result["summary"])

    def test_builds_trailing_rolling_average(self):
        result = build_rolling_average([1, 2, 3, 4], window_size=3)

        self.assertEqual(result, [1, 1.5, 2, 3])

    def test_rolling_average_rejects_invalid_window_size(self):
        with self.assertRaises(ValueError):
            build_rolling_average([1, 2, 3], window_size=0)

    def test_builds_usage_pattern_insights(self):
        samples = self._daily_samples(7, lambda _day: 4.8)
        daily_costs = [{
            "date": f"2026-03-{day+1:02d}",
            "sample_count": 48,
            "missing_rate_count": 0,
            "matched_kwh": 10.0,
            "cheap_kwh": 4.0,
            "negative_kwh": 1.0,
            "high_kwh": 2.0,
            "price_band_version": PRICE_BAND_VERSION,
            "energy_cost_gbp": 1.25,
        } for day in range(7)]

        result = build_usage_pattern_insights(samples, daily_costs)

        self.assertEqual(result["baseline_text"], "~200 W")
        self.assertEqual(result["cheap_rate_text"], "40%")
        self.assertEqual(result["average_unit_text"], "12.5p/kWh")
        self.assertIn("negative prices", result["cheap_rate_detail"])
        self.assertIn("below 20p/kWh", result["cheap_rate_detail"])
        self.assertIn("at 26.5p/kWh or above", result["average_unit_detail"])

    def test_rate_capture_handles_old_cached_daily_costs_without_price_bands(self):
        result = build_usage_pattern_insights([], [{
            "date": "2026-03-01",
            "sample_count": 48,
            "missing_rate_count": 0,
            "kwh": 10.0,
            "energy_cost_gbp": 1.25,
        }])

        self.assertEqual(result["cheap_rate_text"], "—")
        self.assertEqual(result["average_unit_text"], "12.5p/kWh")
        self.assertIn("Refresh usage history", result["cheap_rate_detail"])

    def test_rate_capture_accepts_a_complete_spring_clock_change_day(self):
        result = build_usage_pattern_insights([], [{
            "date": "2026-03-29",
            "sample_count": 46,
            "missing_rate_count": 0,
            "matched_kwh": 10.0,
            "cheap_kwh": 4.0,
            "negative_kwh": 0.0,
            "high_kwh": 2.0,
            "price_band_version": PRICE_BAND_VERSION,
            "energy_cost_gbp": 1.25,
        }])

        self.assertEqual(result["cheap_rate_text"], "40%")
        self.assertEqual(result["average_unit_text"], "12.5p/kWh")

    def test_rate_capture_rejects_an_older_price_band_version(self):
        result = build_usage_pattern_insights([], [{
            "date": "2026-03-01",
            "sample_count": 48,
            "missing_rate_count": 0,
            "matched_kwh": 10.0,
            "cheap_kwh": 4.0,
            "negative_kwh": 1.0,
            "high_kwh": 2.0,
            "price_band_version": PRICE_BAND_VERSION - 1,
            "energy_cost_gbp": 1.25,
        }])

        self.assertEqual(result["cheap_rate_text"], "—")
        self.assertIn("Refresh usage history", result["cheap_rate_detail"])

    def test_peak_pattern_identifies_largest_usage_band(self):
        samples = []
        for slot in range(48):
            hour = slot // 2
            minute = "30" if slot % 2 else "00"
            consumption = 2.0 if hour == 18 else 0.1
            samples.append({
                "interval_start": f"2026-03-01T{hour:02d}:{minute}:00Z",
                "consumption": consumption,
            })

        result = build_usage_pattern_insights(samples, [])

        self.assertIn("Evening", result["peak_text"])
        self.assertIn("18:00-18:30", result["peak_detail"])

    def test_peak_pattern_formats_half_hour_across_midnight(self):
        result = build_usage_pattern_insights([{
            "interval_start": "2026-03-01T23:30:00Z",
            "consumption": 1.0,
        }], [])

        self.assertIn("23:30-00:00", result["peak_detail"])

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
