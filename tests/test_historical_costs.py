import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.historical_costs import build_daily_costs, build_tariff_periods, get_usage_period
from src.price_bands import PRICE_BAND_VERSION

from price_fixtures import (  # noqa: E402
    AGILE_REGION_A_2025_04_07_PENCE,
    AGILE_REGION_A_2025_05_25_PENCE,
    historical_agile_rate_records,
)


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
        self.assertAlmostEqual(daily[0]["matched_kwh"], 2.0)
        self.assertAlmostEqual(daily[0]["cheap_kwh"], 1.5)
        self.assertAlmostEqual(daily[0]["negative_kwh"], 0.0)
        self.assertAlmostEqual(daily[0]["high_kwh"], 0.0)
        self.assertEqual(daily[0]["price_band_version"], PRICE_BAND_VERSION)

    def test_build_daily_costs_matches_unsorted_rate_records(self):
        tariff_code = "E-1R-AGILE-FLEX-22-11-25-C"
        samples = [
            {"interval_start": "2026-03-20T00:00:00Z", "consumption": 1.0},
            {"interval_start": "2026-03-20T00:30:00Z", "consumption": 1.0},
        ]
        tariff_periods = [{
            "tariff_code": tariff_code,
            "valid_from": datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc),
            "valid_to": datetime(2026, 3, 21, 0, 0, tzinfo=timezone.utc),
        }]
        rates = {
            tariff_code: [
                {
                    "valid_from": "2026-03-20T00:30:00Z",
                    "valid_to": "2026-03-20T01:00:00Z",
                    "value_inc_vat": 20.0,
                },
                {
                    "valid_from": "2026-03-20T00:00:00Z",
                    "valid_to": "2026-03-20T00:30:00Z",
                    "value_inc_vat": 10.0,
                },
            ]
        }
        standing = {
            tariff_code: [{
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": None,
                "value_inc_vat": 50.0,
            }]
        }

        daily = build_daily_costs(samples, tariff_periods, rates, standing)

        self.assertEqual(daily[0]["missing_rate_count"], 0)
        self.assertAlmostEqual(daily[0]["energy_cost_gbp"], 0.3)
        self.assertAlmostEqual(daily[0]["total_cost_gbp"], 0.8)

    def test_build_daily_costs_tracks_price_band_usage(self):
        tariff_code = "E-1R-AGILE-FLEX-22-11-25-C"
        samples = [
            {"interval_start": "2026-03-20T00:00:00Z", "consumption": 1.0},
            {"interval_start": "2026-03-20T00:30:00Z", "consumption": 2.0},
            {"interval_start": "2026-03-20T01:00:00Z", "consumption": 3.0},
        ]
        tariff_periods = [{
            "tariff_code": tariff_code,
            "valid_from": datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc),
            "valid_to": datetime(2026, 3, 21, 0, 0, tzinfo=timezone.utc),
        }]
        rates = {
            tariff_code: [
                {
                    "valid_from": "2026-03-20T00:00:00Z",
                    "valid_to": "2026-03-20T00:30:00Z",
                    "value_inc_vat": -5.0,
                },
                {
                    "valid_from": "2026-03-20T00:30:00Z",
                    "valid_to": "2026-03-20T01:00:00Z",
                    "value_inc_vat": 12.0,
                },
                {
                    "valid_from": "2026-03-20T01:00:00Z",
                    "valid_to": "2026-03-20T01:30:00Z",
                    "value_inc_vat": 31.0,
                },
            ]
        }

        daily = build_daily_costs(samples, tariff_periods, rates, {})

        self.assertAlmostEqual(daily[0]["matched_kwh"], 6.0)
        self.assertAlmostEqual(daily[0]["negative_kwh"], 1.0)
        self.assertAlmostEqual(daily[0]["cheap_kwh"], 3.0)
        self.assertAlmostEqual(daily[0]["high_kwh"], 3.0)

    def test_build_daily_costs_uses_exact_price_band_boundaries(self):
        tariff_code = "E-1R-AGILE-24-10-01-C"
        samples = [
            {
                "interval_start": f"2026-07-25T{slot // 2:02d}:{'30' if slot % 2 else '00'}:00Z",
                "consumption": 1.0,
            }
            for slot in range(4)
        ]
        tariff_periods = [{
            "tariff_code": tariff_code,
            "valid_from": datetime(2026, 7, 25, tzinfo=timezone.utc),
            "valid_to": datetime(2026, 7, 26, tzinfo=timezone.utc),
        }]
        rates = {
            tariff_code: [
                {
                    "valid_from": sample["interval_start"],
                    "valid_to": None,
                    "value_inc_vat": price_pence,
                }
                for sample, price_pence in zip(samples, (19.99, 20.0, 26.49, 26.5))
            ]
        }

        daily = build_daily_costs(samples, tariff_periods, rates, {})

        self.assertAlmostEqual(daily[0]["cheap_kwh"], 1.0)
        self.assertAlmostEqual(daily[0]["high_kwh"], 1.0)

    def test_build_daily_costs_allows_negative_energy_costs_to_offset_standing_charge(self):
        tariff_code = "E-1R-AGILE-24-10-01-A"
        day_start = datetime(2025, 5, 25, 0, 0, tzinfo=timezone.utc)
        samples = [
            {"interval_start": f"2025-05-25T{hour:02d}:{minute:02d}:00Z", "consumption": 1.0}
            for hour, minute in [(12, 0), (12, 30), (13, 0), (13, 30), (14, 0), (14, 30)]
        ]
        tariff_periods = [{
            "tariff_code": tariff_code,
            "valid_from": day_start,
            "valid_to": datetime(2025, 5, 26, 0, 0, tzinfo=timezone.utc),
        }]
        rates = {tariff_code: historical_agile_rate_records(day_start, AGILE_REGION_A_2025_05_25_PENCE)}
        standing = {
            tariff_code: [{
                "valid_from": "2025-01-01T00:00:00Z",
                "valid_to": None,
                "value_inc_vat": 50.0,
            }]
        }

        daily = build_daily_costs(samples, tariff_periods, rates, standing)

        expected_energy_cost = sum(AGILE_REGION_A_2025_05_25_PENCE[24:30]) / 100
        self.assertEqual(daily[0]["kwh"], 6.0)
        self.assertAlmostEqual(daily[0]["energy_cost_gbp"], expected_energy_cost)
        self.assertLess(daily[0]["energy_cost_gbp"], 0)
        self.assertAlmostEqual(daily[0]["standing_charge_gbp"], 0.5)
        self.assertAlmostEqual(daily[0]["total_cost_gbp"], 0.5 + expected_energy_cost)

    def test_build_daily_costs_counts_missing_rates_without_dropping_high_peak_usage(self):
        tariff_code = "E-1R-AGILE-24-10-01-A"
        day_start = datetime(2025, 4, 7, 0, 0, tzinfo=timezone.utc)
        samples = [
            {"interval_start": "2025-04-07T17:00:00Z", "consumption": 1.0},
            {"interval_start": "2025-04-07T17:30:00Z", "consumption": 1.0},
            {"interval_start": "2025-04-07T18:00:00Z", "consumption": 1.0},
        ]
        tariff_periods = [{
            "tariff_code": tariff_code,
            "valid_from": day_start,
            "valid_to": datetime(2025, 4, 8, 0, 0, tzinfo=timezone.utc),
        }]
        rates = {
            tariff_code: [
                record for record in historical_agile_rate_records(day_start, AGILE_REGION_A_2025_04_07_PENCE)
                if record["valid_from"] != "2025-04-07T18:00:00Z"
            ]
        }
        standing = {
            tariff_code: [{
                "valid_from": "2025-01-01T00:00:00Z",
                "valid_to": None,
                "value_inc_vat": 50.0,
            }]
        }

        daily = build_daily_costs(samples, tariff_periods, rates, standing)

        self.assertEqual(daily[0]["sample_count"], 3)
        self.assertEqual(daily[0]["missing_rate_count"], 1)
        self.assertAlmostEqual(
            daily[0]["energy_cost_gbp"],
            (39.9105 + 42.0945) / 100,
        )
        self.assertAlmostEqual(daily[0]["total_cost_gbp"], 1.32005)

    def test_build_daily_costs_matches_rates_across_tariff_period_boundary(self):
        old_tariff = "E-1R-AGILE-OLD-A"
        new_tariff = "E-1R-AGILE-NEW-A"
        samples = [
            {"interval_start": "2026-03-20T11:30:00Z", "consumption": 1.0},
            {"interval_start": "2026-03-20T12:00:00Z", "consumption": 1.0},
        ]
        tariff_periods = [
            {
                "tariff_code": old_tariff,
                "valid_from": datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc),
                "valid_to": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
            },
            {
                "tariff_code": new_tariff,
                "valid_from": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                "valid_to": datetime(2026, 3, 21, 0, 0, tzinfo=timezone.utc),
            },
        ]
        rates = {
            old_tariff: [{
                "valid_from": "2026-03-20T00:00:00Z",
                "valid_to": "2026-03-20T12:00:00Z",
                "value_inc_vat": 10.0,
            }],
            new_tariff: [{
                "valid_from": "2026-03-20T12:00:00Z",
                "valid_to": None,
                "value_inc_vat": 40.0,
            }],
        }
        standing = {
            old_tariff: [{
                "valid_from": "2026-03-20T00:00:00Z",
                "valid_to": "2026-03-20T12:00:00Z",
                "value_inc_vat": 20.0,
            }],
            new_tariff: [{
                "valid_from": "2026-03-20T12:00:00Z",
                "valid_to": None,
                "value_inc_vat": 50.0,
            }],
        }

        daily = build_daily_costs(samples, tariff_periods, rates, standing)

        self.assertAlmostEqual(daily[0]["energy_cost_gbp"], 0.5)
        self.assertAlmostEqual(daily[0]["standing_charge_gbp"], 0.5)
        self.assertAlmostEqual(daily[0]["total_cost_gbp"], 1.0)


if __name__ == "__main__":
    unittest.main()
