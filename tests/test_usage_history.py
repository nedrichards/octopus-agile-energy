import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.octopus_api import OctopusApiError
from src.usage_history import fetch_historical_unit_rates


class UsageHistoryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
