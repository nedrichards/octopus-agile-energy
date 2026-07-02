import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from price_fixtures import (  # noqa: E402
    AGILE_REGION_A_2025_04_07_PENCE,
    AGILE_REGION_A_2025_05_25_PENCE,
    AGILE_REGION_A_2025_10_26_PENCE,
    historical_agile_prices,
)
from price_logic import (  # noqa: E402
    build_dual_register_price_windows,
    build_region_to_tariffs_map,
    extract_product_code,
    find_cheapest_slot,
    find_cheapest_timer_slot,
)


class PriceLogicTests(unittest.TestCase):
    def assertSlot(self, slot, start, end, average_price_gbp):
        self.assertIsNotNone(slot)
        self.assertEqual(slot['start'], start)
        self.assertEqual(slot['end'], end)
        self.assertAlmostEqual(slot['average_price_gbp'], average_price_gbp)

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

    def test_find_cheapest_slot_supports_half_hour_durations(self):
        now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        prices = []
        values = [0.40, 0.30, 0.20, 0.04, 0.03, 0.02, 0.50, 0.60]
        for i, value in enumerate(values):
            start = now + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': value,
            })

        slot = find_cheapest_slot(prices, now, duration_hours=1.5, start_within_hours=4)

        self.assertIsNotNone(slot)
        self.assertEqual(slot['start'], now + timedelta(hours=1, minutes=30))
        self.assertEqual(slot['end'], now + timedelta(hours=3))
        self.assertAlmostEqual(slot['average_price_gbp'], 0.03)

    def test_find_cheapest_slot_uses_current_active_half_hour_slot_boundary(self):
        slot_start = datetime(2026, 3, 21, 2, 30, tzinfo=timezone.utc)
        now = datetime(2026, 3, 21, 2, 32, tzinfo=timezone.utc)
        prices = []
        values = [0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.50, 0.50]
        for i, value in enumerate(values):
            start = slot_start + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': value,
            })

        slot = find_cheapest_slot(prices, now, duration_hours=3.5, start_within_hours=8)

        self.assertSlot(
            slot,
            datetime(2026, 3, 21, 2, 30, tzinfo=timezone.utc),
            datetime(2026, 3, 21, 6, 0, tzinfo=timezone.utc),
            0.01,
        )

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

    def test_find_cheapest_slot_returns_none_when_not_enough_data(self):
        now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        prices = [{
            'valid_from': now,
            'valid_to': now + timedelta(minutes=30),
            'price_gbp': 0.10,
        }]

        self.assertIsNone(find_cheapest_slot(prices, now, duration_hours=1, start_within_hours=1))

    def test_find_cheapest_slot_uses_historical_negative_prices_for_long_appliance_run(self):
        day_start = datetime(2025, 5, 25, 0, 0, tzinfo=timezone.utc)
        prices = historical_agile_prices(day_start, AGILE_REGION_A_2025_05_25_PENCE)

        slot = find_cheapest_slot(
            prices,
            day_start,
            duration_hours=3.5,
            start_within_hours=24,
        )

        self.assertSlot(
            slot,
            datetime(2025, 5, 25, 11, 0, tzinfo=timezone.utc),
            datetime(2025, 5, 25, 14, 30, tzinfo=timezone.utc),
            -0.061425,
        )

    def test_find_cheapest_slot_avoids_historical_evening_price_spike(self):
        day_start = datetime(2025, 4, 7, 0, 0, tzinfo=timezone.utc)
        now = datetime(2025, 4, 7, 15, 0, tzinfo=timezone.utc)
        prices = historical_agile_prices(day_start, AGILE_REGION_A_2025_04_07_PENCE)

        slot = find_cheapest_slot(
            prices,
            now,
            duration_hours=3.5,
            start_within_hours=9,
        )

        self.assertSlot(
            slot,
            datetime(2025, 4, 7, 20, 30, tzinfo=timezone.utc),
            datetime(2025, 4, 8, 0, 0, tzinfo=timezone.utc),
            0.18342,
        )

    def test_find_cheapest_slot_half_hour_windows_require_full_run_inside_search_window(self):
        day_start = datetime(2025, 5, 25, 0, 0, tzinfo=timezone.utc)
        now = datetime(2025, 5, 25, 13, 47, tzinfo=timezone.utc)
        prices = historical_agile_prices(day_start, AGILE_REGION_A_2025_05_25_PENCE)

        slot = find_cheapest_slot(prices, now, duration_hours=1, start_within_hours=1)

        self.assertSlot(
            slot,
            datetime(2025, 5, 25, 13, 30, tzinfo=timezone.utc),
            datetime(2025, 5, 25, 14, 30, tzinfo=timezone.utc),
            -0.0691425,
        )

    def test_find_cheapest_slot_skips_missing_half_hour_api_gap(self):
        day_start = datetime(2025, 5, 25, 0, 0, tzinfo=timezone.utc)
        prices = [
            price for price in historical_agile_prices(day_start, AGILE_REGION_A_2025_05_25_PENCE)
            if price['valid_from'] != datetime(2025, 5, 25, 14, 0, tzinfo=timezone.utc)
        ]

        slot = find_cheapest_slot(
            prices,
            datetime(2025, 5, 25, 13, 0, tzinfo=timezone.utc),
            duration_hours=1,
            start_within_hours=3,
        )

        self.assertSlot(
            slot,
            datetime(2025, 5, 25, 13, 0, tzinfo=timezone.utc),
            datetime(2025, 5, 25, 14, 0, tzinfo=timezone.utc),
            -0.05922,
        )

    def test_find_cheapest_slot_handles_octopus_newest_first_price_ordering(self):
        day_start = datetime(2025, 5, 25, 0, 0, tzinfo=timezone.utc)
        prices = list(reversed(historical_agile_prices(day_start, AGILE_REGION_A_2025_05_25_PENCE)))

        slot = find_cheapest_slot(
            prices,
            day_start,
            duration_hours=2,
            start_within_hours=24,
        )

        self.assertSlot(
            slot,
            datetime(2025, 5, 25, 12, 30, tzinfo=timezone.utc),
            datetime(2025, 5, 25, 14, 30, tzinfo=timezone.utc),
            -0.0704025,
        )

    def test_find_cheapest_timer_slot_uses_whole_hour_start_delays_from_now(self):
        period_start = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 21, 12, 17, tzinfo=timezone.utc)
        prices = []
        values = [1.00, 1.00, 0.80, 0.80, 0.10, 0.10, 0.50, 0.50, 1.00]
        for i, value in enumerate(values):
            start = period_start + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': value,
            })

        slot = find_cheapest_timer_slot(
            prices,
            now,
            duration_hours=1,
            start_within_hours=4,
            timer_mode="start",
        )

        self.assertIsNotNone(slot)
        self.assertEqual(slot['start'], now + timedelta(hours=2))
        self.assertEqual(slot['end'], now + timedelta(hours=3))

    def test_find_cheapest_timer_slot_uses_whole_hour_finish_delays_from_now(self):
        period_start = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 21, 12, 17, tzinfo=timezone.utc)
        prices = []
        values = [1.00, 1.00, 0.80, 0.80, 0.10, 0.10, 0.50, 0.05, 0.05]
        for i, value in enumerate(values):
            start = period_start + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': value,
            })

        slot = find_cheapest_timer_slot(
            prices,
            now,
            duration_hours=1,
            start_within_hours=4,
            timer_mode="finish",
        )

        self.assertIsNotNone(slot)
        self.assertEqual(slot['start'], now + timedelta(hours=3))
        self.assertEqual(slot['end'], now + timedelta(hours=4))

    def test_find_cheapest_timer_slots_can_describe_different_start_times(self):
        period_start = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 21, 12, 17, tzinfo=timezone.utc)
        prices = []
        values = [1.00, 1.00, 1.00, 1.00, 0.01, 0.50, 0.50, 0.01, 0.01]
        for i, value in enumerate(values):
            start = period_start + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': value,
            })

        start_timer_slot = find_cheapest_timer_slot(
            prices,
            now,
            duration_hours=1.5,
            start_within_hours=4,
            timer_mode="start",
        )
        finish_timer_slot = find_cheapest_timer_slot(
            prices,
            now,
            duration_hours=1.5,
            start_within_hours=4,
            timer_mode="finish",
        )

        self.assertIsNotNone(start_timer_slot)
        self.assertIsNotNone(finish_timer_slot)
        self.assertEqual(start_timer_slot['start'], now + timedelta(hours=2))
        self.assertEqual(finish_timer_slot['start'], now + timedelta(hours=2, minutes=30))
        self.assertEqual(finish_timer_slot['end'], now + timedelta(hours=4))

    def test_find_cheapest_timer_slot_rejects_windows_past_the_search_cutoff(self):
        now = datetime(2026, 3, 21, 12, 17, tzinfo=timezone.utc)
        prices = []
        values = [0.50, 0.50, 0.50, 0.50, 0.01, 0.01]
        for i, value in enumerate(values):
            start = now + timedelta(minutes=30 * i)
            prices.append({
                'valid_from': start,
                'valid_to': start + timedelta(minutes=30),
                'price_gbp': value,
            })

        slot = find_cheapest_timer_slot(
            prices,
            now,
            duration_hours=1,
            start_within_hours=1,
            timer_mode="start",
        )

        self.assertIsNotNone(slot)
        self.assertEqual(slot['start'], now)
        self.assertEqual(slot['end'], now + timedelta(hours=1))

    def test_find_cheapest_timer_slot_uses_historical_negative_prices(self):
        day_start = datetime(2025, 5, 25, 0, 0, tzinfo=timezone.utc)
        now = datetime(2025, 5, 25, 10, 17, tzinfo=timezone.utc)
        prices = historical_agile_prices(day_start, AGILE_REGION_A_2025_05_25_PENCE)

        start_timer_slot = find_cheapest_timer_slot(
            prices,
            now,
            duration_hours=3.5,
            start_within_hours=12,
            timer_mode="start",
        )
        finish_timer_slot = find_cheapest_timer_slot(
            prices,
            now,
            duration_hours=3.5,
            start_within_hours=12,
            timer_mode="finish",
        )

        self.assertSlot(
            start_timer_slot,
            datetime(2025, 5, 25, 11, 17, tzinfo=timezone.utc),
            datetime(2025, 5, 25, 14, 47, tzinfo=timezone.utc),
            -0.0613655,
        )
        self.assertSlot(
            finish_timer_slot,
            datetime(2025, 5, 25, 10, 47, tzinfo=timezone.utc),
            datetime(2025, 5, 25, 14, 17, tzinfo=timezone.utc),
            -0.0596505,
        )

    def test_find_cheapest_timer_slot_avoids_historical_evening_price_spike(self):
        day_start = datetime(2025, 4, 7, 0, 0, tzinfo=timezone.utc)
        now = datetime(2025, 4, 7, 15, 0, tzinfo=timezone.utc)
        prices = historical_agile_prices(day_start, AGILE_REGION_A_2025_04_07_PENCE)

        start_timer_slot = find_cheapest_timer_slot(
            prices,
            now,
            duration_hours=3.5,
            start_within_hours=9,
            timer_mode="start",
        )
        finish_timer_slot = find_cheapest_timer_slot(
            prices,
            now,
            duration_hours=3.5,
            start_within_hours=9,
            timer_mode="finish",
        )

        self.assertSlot(
            start_timer_slot,
            datetime(2025, 4, 7, 20, 0, tzinfo=timezone.utc),
            datetime(2025, 4, 7, 23, 30, tzinfo=timezone.utc),
            0.19197,
        )
        self.assertSlot(
            finish_timer_slot,
            datetime(2025, 4, 7, 20, 30, tzinfo=timezone.utc),
            datetime(2025, 4, 8, 0, 0, tzinfo=timezone.utc),
            0.18342,
        )

    def test_find_cheapest_timer_slot_handles_historical_clock_change_day(self):
        day_start = datetime(2025, 10, 26, 0, 0, tzinfo=timezone.utc)
        now = datetime(2025, 10, 26, 0, 17, tzinfo=timezone.utc)
        prices = historical_agile_prices(day_start, AGILE_REGION_A_2025_10_26_PENCE)

        slot = find_cheapest_timer_slot(
            prices,
            now,
            duration_hours=2,
            start_within_hours=8,
            timer_mode="start",
        )

        self.assertSlot(
            slot,
            datetime(2025, 10, 26, 2, 17, tzinfo=timezone.utc),
            datetime(2025, 10, 26, 4, 17, tzinfo=timezone.utc),
            -0.013888,
        )

    def test_find_cheapest_timer_slot_rejects_unknown_timer_mode(self):
        now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
        prices = [{
            'valid_from': now,
            'valid_to': now + timedelta(hours=1),
            'price_gbp': 0.10,
        }]

        with self.assertRaises(ValueError):
            find_cheapest_timer_slot(
                prices,
                now,
                duration_hours=1,
                start_within_hours=1,
                timer_mode="delay",
            )

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

    def test_build_dual_register_price_windows_uses_one_price_per_register(self):
        period_start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        period_end = datetime(2026, 4, 1, 2, 0, tzinfo=timezone.utc)
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

        self.assertEqual([price['value_inc_vat'] for price in prices], [30.0, 12.0, 12.0, 12.0])
        self.assertEqual(sorted({price['value_inc_vat'] for price in prices}), [12.0, 30.0])

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
