import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from historical_costs import build_daily_costs, build_tariff_periods, get_usage_period


class HistoricalCostsTests(unittest.TestCase):
    def test_get_usage_period_uses_interval_end_when_available(self):
        samples = [
            {
                "interval_start": "2026-03-20T00:00:00Z",
                "interval_end": "2026-03-20T00:30:00Z",
                "consumption": 1.0,
            },
            {
                "interval_start": "2026-03-21T23:30:00Z",
                "interval_end": "2026-03-22T00:00:00Z",
                "consumption": 1.0,
            },
        ]

        start, end = get_usage_period(samples)

        self.assertEqual(start, datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc))

    def test_build_tariff_periods_clips_agreements_to_requested_range(self):
        account_data = {
            "properties": [
                {
                    "electricity_meter_points": [
                        {
                            "agreements": [
                                {
                                    "tariff_code": "E-1R-AGILE-FLEX-22-11-25-C",
                                    "valid_from": "2026-01-01T00:00:00Z",
                                    "valid_to": None,
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        periods = build_tariff_periods(
            account_data,
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["valid_from"], datetime(2026, 3, 1, tzinfo=timezone.utc))
        self.assertEqual(periods[0]["valid_to"], datetime(2026, 3, 2, tzinfo=timezone.utc))

    def test_build_daily_costs_matches_usage_to_rates_and_standing_charge(self):
        tariff_code = "E-1R-AGILE-FLEX-22-11-25-C"
        samples = [
            {"interval_start": "2026-03-20T00:00:00Z", "consumption": 1.5},
            {"interval_start": "2026-03-20T00:30:00Z", "consumption": 0.5},
        ]
        tariff_periods = [
            {
                "tariff_code": tariff_code,
                "valid_from": datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc),
                "valid_to": datetime(2026, 3, 21, 0, 0, tzinfo=timezone.utc),
            }
        ]
        rates = {
            tariff_code: [
                {
                    "valid_from": "2026-03-20T00:00:00Z",
                    "valid_to": "2026-03-20T00:30:00Z",
                    "value_inc_vat": 10.0,
                },
                {
                    "valid_from": "2026-03-20T00:30:00Z",
                    "valid_to": "2026-03-20T01:00:00Z",
                    "value_inc_vat": 20.0,
                },
            ]
        }
        standing = {
            tariff_code: [
                {
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": None,
                    "value_inc_vat": 50.0,
                }
            ]
        }

        daily = build_daily_costs(samples, tariff_periods, rates, standing)

        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["kwh"], 2.0)
        self.assertAlmostEqual(daily[0]["energy_cost_gbp"], 0.25)
        self.assertAlmostEqual(daily[0]["standing_charge_gbp"], 0.5)
        self.assertAlmostEqual(daily[0]["total_cost_gbp"], 0.75)
        self.assertEqual(daily[0]["missing_rate_count"], 0)


if __name__ == "__main__":
    unittest.main()
