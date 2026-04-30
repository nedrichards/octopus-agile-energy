import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from usage_insights import build_usage_insight_data


class UsageInsightsTests(unittest.TestCase):
    def test_returns_empty_when_no_samples(self):
        result = build_usage_insight_data([], None)
        self.assertEqual(result["avg_text"], "—")
        self.assertEqual(result["trend_strength"], 0.0)

    def test_returns_insights_for_valid_samples(self):
        samples = []
        for day in range(21):
            samples.append({
                "interval_start": f"2026-03-{day+1:02d}T00:00:00Z",
                "consumption": 10 + day * 0.2,
            })

        result = build_usage_insight_data(samples, "2026-03-21T12:00:00Z")
        self.assertIn("kWh/day", result["avg_text"])
        self.assertIn("%", result["trend_text"])
        self.assertGreater(len(result["chart_points"]), 0)
        self.assertIn("Confidence:", result["summary"])

    def test_trend_is_clamped(self):
        samples = []
        for day in range(14):
            value = 1 if day < 7 else 1000
            samples.append({
                "interval_start": f"2026-04-{day+1:02d}T00:00:00Z",
                "consumption": value,
            })

        result = build_usage_insight_data(samples, None)
        self.assertLessEqual(result["trend_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
