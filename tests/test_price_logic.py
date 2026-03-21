import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from price_logic import build_region_to_tariffs_map, extract_product_code, find_cheapest_slot


class PriceLogicTests(unittest.TestCase):
    def test_extract_product_code_uses_middle_segments(self):
        self.assertEqual(
            extract_product_code("E-1R-AGILE-24-10-01-A"),
            "AGILE-24-10-01",
        )

    def test_find_cheapest_slot_returns_lowest_cost_window(self):
        now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        prices = []
        values = [0.30, 0.25, 0.05, 0.04, 0.40, 0.50]
        for i, value in enumerate(values):
            start = now + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': value,
            })

        slot = find_cheapest_slot(prices, now, duration_hours=1, start_within_hours=3)

        self.assertIsNotNone(slot)
        self.assertEqual(slot['start'], now + timedelta(hours=1))
        self.assertEqual(slot['end'], now + timedelta(hours=2))
        self.assertAlmostEqual(slot['average_price_gbp'], 0.045)

    def test_find_cheapest_slot_returns_none_when_not_enough_data(self):
        now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        prices = [{
            'valid_from': now,
            'valid_to': now + timedelta(minutes=30),
            'price_gbp': 0.10,
        }]

        self.assertIsNone(find_cheapest_slot(prices, now, duration_hours=1, start_within_hours=1))

    def test_build_region_to_tariffs_map_prefers_direct_debit(self):
        product_data = {
            'full_name': 'Agile Test Tariff',
            'single_register_electricity_tariffs': {
                '_A': {
                    'prepay': {'code': 'PREPAY-A'},
                    'direct_debit_monthly': {'code': 'DDM-A'},
                },
                '_Z': {
                    'direct_debit_monthly': {'code': 'UNKNOWN'},
                },
            },
        }

        result = build_region_to_tariffs_map(product_data, {'_A': 'Eastern England'})

        self.assertEqual(result['_A'][0]['code'], 'DDM-A')
        self.assertEqual(result['_A'][0]['full_name'], 'Agile Test Tariff (Eastern England)')

    def test_build_region_to_tariffs_map_falls_back_to_first_code(self):
        product_data = {
            'single_register_electricity_tariffs': {
                '_A': {
                    'prepay': {'code': 'PREPAY-A'},
                },
            },
        }

        result = build_region_to_tariffs_map(product_data, {'_A': 'Eastern England'})

        self.assertEqual(result['_A'][0]['code'], 'PREPAY-A')


if __name__ == '__main__':
    unittest.main()
