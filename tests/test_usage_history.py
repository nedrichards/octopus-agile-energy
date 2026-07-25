import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.octopus_api import OctopusApiError
from src.price_bands import PRICE_BAND_VERSION
from src.usage_history import (
    fetch_all_tariff_pages,
    fetch_historical_unit_rates,
    fetch_recent_usage_samples,
    get_usage_refresh_start,
    merge_usage_history,
)


class UsageHistoryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

    def test_fetch_historical_unit_rates_expands_dual_register_tariff(self):
        period_start = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
        period_end = datetime(2026, 5, 13, 1, 0, tzinfo=timezone.utc)
        day_rates = [{
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": None,
            "value_inc_vat": 30.0,
        }]
        night_rates = [{
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": None,
            "value_inc_vat": 10.0,
        }]

        with patch("src.usage_history.fetch_historical_tariff_records") as fetch_records:
            fetch_records.side_effect = [
                OctopusApiError("API request failed with status 400. This tariff has day and night rates, not standard."),
                day_rates,
                night_rates,
            ]

            rates = fetch_historical_unit_rates("PRODUCT", "E-2R-PRODUCT-H", period_start, period_end)

        self.assertEqual([rate["value_inc_vat"] for rate in rates], [30.0, 10.0])
        self.assertEqual(fetch_records.call_args_list[1].args[2], "day-unit-rates")
        self.assertEqual(fetch_records.call_args_list[2].args[2], "night-unit-rates")

    def test_fetch_all_tariff_pages_preserves_paginated_api_order(self):
        with patch("src.usage_history.get_json") as get_json:
            get_json.side_effect = [
                {
                    "results": [
                        {"valid_from": "2026-03-20T01:00:00Z", "value_inc_vat": 30.0},
                        {"valid_from": "2026-03-20T00:30:00Z", "value_inc_vat": 20.0},
                    ],
                    "next": "https://example.test/page-2",
                },
                {
                    "results": [
                        {"valid_from": "2026-03-20T00:00:00Z", "value_inc_vat": 10.0},
                    ],
                    "next": None,
                },
            ]

            records = fetch_all_tariff_pages("https://example.test/page-1")

        self.assertEqual(
            [record["valid_from"] for record in records],
            [
                "2026-03-20T01:00:00Z",
                "2026-03-20T00:30:00Z",
                "2026-03-20T00:00:00Z",
            ],
        )
        self.assertEqual(get_json.call_count, 2)
        self.assertEqual(get_json.call_args_list[0].kwargs, {"use_api_key": True, "timeout": 10})

    def test_incremental_refresh_overlaps_latest_cached_sample_by_seven_days(self):
        cached_data = {
            "samples": [{"interval_start": "2026-07-24T10:30:00Z"}],
            "daily_costs": [],
            "price_band_version": PRICE_BAND_VERSION,
        }

        refresh_start = get_usage_refresh_start(cached_data, self.now)

        self.assertEqual(refresh_start, datetime(2026, 7, 17, 0, 0, tzinfo=timezone.utc))

    def test_incompatible_cache_falls_back_to_full_history_window(self):
        cached_data = {
            "samples": [{"interval_start": "2026-07-24T10:30:00Z"}],
            "daily_costs": [],
            "price_band_version": "old",
        }

        refresh_start = get_usage_refresh_start(cached_data, self.now)

        self.assertEqual(refresh_start, self.now - timedelta(days=120))

    def test_merge_replaces_overlap_and_prunes_samples_outside_history_window(self):
        cached_data = {
            "samples": [
                {"interval_start": "2026-03-20T11:30:00Z", "consumption": 0.1},
                {"interval_start": "2026-07-24T10:30:00Z", "consumption": 0.2},
            ],
            "daily_costs": [
                {"date": "2026-03-20", "kwh": 1.0},
                {"date": "2026-07-24", "kwh": 2.0},
            ],
            "price_band_version": PRICE_BAND_VERSION,
        }
        fresh_samples = [
            {"interval_start": "2026-07-24T10:30:00Z", "consumption": 0.3},
            {"interval_start": "2026-07-24T11:00:00Z", "consumption": 0.4},
        ]
        fresh_daily_costs = [{"date": "2026-07-24", "kwh": 3.0}]

        merged = merge_usage_history(cached_data, fresh_samples, fresh_daily_costs, self.now)

        self.assertEqual(
            merged["samples"],
            [
                {"interval_start": "2026-07-24T10:30:00Z", "consumption": 0.3},
                {"interval_start": "2026-07-24T11:00:00Z", "consumption": 0.4},
            ],
        )
        self.assertEqual(merged["daily_costs"], fresh_daily_costs)
        self.assertEqual(merged["price_band_version"], PRICE_BAND_VERSION)

    def test_merge_preserves_cached_costs_when_rate_refresh_fails(self):
        cached_daily_costs = [{"date": "2026-07-24", "kwh": 2.0}]
        cached_data = {
            "samples": [{"interval_start": "2026-07-24T10:30:00Z", "consumption": 0.2}],
            "daily_costs": cached_daily_costs,
            "price_band_version": PRICE_BAND_VERSION,
        }

        merged = merge_usage_history(
            cached_data,
            [{"interval_start": "2026-07-24T11:00:00Z", "consumption": 0.4}],
            None,
            self.now,
        )

        self.assertEqual(merged["daily_costs"], cached_daily_costs)

    def test_fetch_recent_usage_uses_explicit_incremental_start(self):
        account_data = {
            "properties": [{
                "electricity_meter_points": [{
                    "mpan": "test-mpan",
                    "agreements": [{"valid_from": "2025-01-01T00:00:00Z"}],
                    "meters": [{"serial_number": "test-serial"}],
                }],
            }],
        }
        refresh_start = datetime(2026, 7, 17, 10, 30, tzinfo=timezone.utc)

        with patch("src.usage_history.fetch_all_consumption_pages", return_value=[{"consumption": 1.0}]) as fetch:
            samples = fetch_recent_usage_samples(account_data, period_from=refresh_start, now=self.now)

        query = parse_qs(urlparse(fetch.call_args.args[0]).query)
        self.assertEqual(samples, [{"consumption": 1.0}])
        self.assertEqual(query["period_from"], ["2026-07-17T10:30:00Z"])


if __name__ == "__main__":
    unittest.main()
