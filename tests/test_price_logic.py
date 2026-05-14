import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from price_logic import (
    build_dual_register_price_windows,
    build_region_to_tariffs_map,
    extract_product_code,
    find_cheapest_slot,
)


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

    def test_find_cheapest_slot_can_restrict_to_whole_hour_starts(self):
        now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        prices = []
        values = [0.30, 0.01, 0.01, 0.20, 0.05, 0.05]
        for i, value in enumerate(values):
            start = now + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': value,
            })

        exact_slot = find_cheapest_slot(prices, now, duration_hours=1, start_within_hours=3)
        whole_hour_slot = find_cheapest_slot(
            prices,
            now,
            duration_hours=1,
            start_within_hours=3,
            whole_hour_starts_only=True,
        )

        self.assertEqual(exact_slot['start'], now + timedelta(minutes=30))
        self.assertEqual(whole_hour_slot['start'], now + timedelta(hours=2))
        self.assertAlmostEqual(whole_hour_slot['average_price_gbp'], 0.05)

    def test_find_cheapest_slot_can_use_exact_current_time(self):
        slot_start = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 21, 12, 17, tzinfo=timezone.utc)
        prices = []
        for i in range(4):
            start = slot_start + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': 0.10,
            })

        slot = find_cheapest_slot(
            prices,
            now,
            duration_hours=1,
            start_within_hours=1,
            continuous_starts=True,
        )

        self.assertIsNotNone(slot)
        self.assertEqual(slot['start'], now)
        self.assertEqual(slot['end'], now + timedelta(hours=1))

    def test_find_cheapest_slot_continuous_uses_system_clock_minute_cadence(self):
        slot_start = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 21, 12, 17, tzinfo=timezone.utc)
        prices = []
        values = [1.00, 1.00, 0.01, 0.01, 1.00]
        for i, value in enumerate(values):
            start = slot_start + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': value,
            })

        slot = find_cheapest_slot(
            prices,
            now,
            duration_hours=1,
            start_within_hours=2,
            continuous_starts=True,
        )

        self.assertIsNotNone(slot)
        self.assertEqual(slot['start'], datetime(2026, 3, 21, 12, 47, tzinfo=timezone.utc))
        self.assertEqual(slot['end'], datetime(2026, 3, 21, 13, 47, tzinfo=timezone.utc))

    def test_find_cheapest_slot_returns_exact_window_when_duration_fills_search_window(self):
        now = datetime(2026, 3, 21, 12, 30, tzinfo=timezone.utc)
        prices = []
        for i in range(16):
            start = now + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': 0.10,
            })

        exact_slot = find_cheapest_slot(prices, now, duration_hours=8, start_within_hours=8)
        whole_hour_slot = find_cheapest_slot(
            prices,
            now,
            duration_hours=8,
            start_within_hours=8,
            whole_hour_starts_only=True,
        )

        self.assertIsNotNone(exact_slot)
        self.assertEqual(exact_slot['start'], now)
        self.assertEqual(exact_slot['end'], now + timedelta(hours=8))
        self.assertIsNone(whole_hour_slot)

    def test_find_cheapest_slot_continuous_returns_exact_window_when_duration_fills_search_window(self):
        slot_start = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 21, 12, 17, tzinfo=timezone.utc)
        prices = []
        for i in range(17):
            start = slot_start + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': 0.10,
            })

        slot = find_cheapest_slot(
            prices,
            now,
            duration_hours=8,
            start_within_hours=8,
            continuous_starts=True,
        )

        self.assertIsNotNone(slot)
        self.assertEqual(slot['start'], now)
        self.assertEqual(slot['end'], now + timedelta(hours=8))

    def test_find_cheapest_slot_returns_none_when_not_enough_data(self):
        now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        prices = [{
            'valid_from': now,
            'valid_to': now + timedelta(minutes=30),
            'price_gbp': 0.10,
        }]

        self.assertIsNone(find_cheapest_slot(prices, now, duration_hours=1, start_within_hours=1))

    def test_build_dual_register_price_windows_uses_night_rate_inside_window(self):
        period_start = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
        period_end = datetime(2026, 5, 13, 8, 0, tzinfo=timezone.utc)
        day_rates = [{
            'valid_from': '2026-01-01T00:00:00Z',
            'valid_to': None,
            'value_inc_vat': 30.0,
        }]
        night_rates = [{
            'valid_from': '2026-01-01T00:00:00Z',
            'valid_to': None,
            'value_inc_vat': 10.0,
        }]

        prices = build_dual_register_price_windows(day_rates, night_rates, period_start, period_end)

        self.assertEqual(len(prices), 16)
        self.assertEqual(prices[0]['value_inc_vat'], 30.0)
        self.assertEqual(prices[1]['valid_from'], '2026-05-13T00:30:00Z')
        self.assertEqual(prices[1]['value_inc_vat'], 10.0)
        self.assertEqual(prices[14]['valid_from'], '2026-05-13T07:00:00Z')
        self.assertEqual(prices[14]['value_inc_vat'], 10.0)
        self.assertEqual(prices[15]['valid_from'], '2026-05-13T07:30:00Z')
        self.assertEqual(prices[15]['value_inc_vat'], 30.0)

    def test_build_dual_register_price_windows_uses_rate_valid_at_slot(self):
        period_start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        period_end = datetime(2026, 4, 1, 1, 0, tzinfo=timezone.utc)
        day_rates = [{
            'valid_from': '2026-01-01T00:00:00Z',
            'valid_to': None,
            'value_inc_vat': 30.0,
        }]
        night_rates = [
            {
                'valid_from': '2026-01-01T00:00:00Z',
                'valid_to': '2026-04-01T00:30:00Z',
                'value_inc_vat': 12.0,
            },
            {
                'valid_from': '2026-04-01T00:30:00Z',
                'valid_to': None,
                'value_inc_vat': 9.0,
            },
        ]

        prices = build_dual_register_price_windows(day_rates, night_rates, period_start, period_end)

        self.assertEqual([price['value_inc_vat'] for price in prices], [30.0, 9.0])

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
