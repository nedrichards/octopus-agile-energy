import unittest
from datetime import datetime, timedelta, timezone

from src.price_cache import (
    PRICE_RETRY_DELAYS_SECONDS,
    build_rates_cache_key,
    expected_rates_horizon,
    get_price_request_period,
    is_rates_cache_stale,
    next_price_release_check,
    rates_cover_expected_horizon,
)


class PriceCacheTests(unittest.TestCase):
    @staticmethod
    def build_half_hour_rates(start, end):
        rates = []
        cursor = start
        while cursor < end:
            rates.append({"valid_from": cursor, "valid_to": cursor + timedelta(minutes=30)})
            cursor += timedelta(minutes=30)
        return rates

    def test_cache_key_uses_the_great_britain_date(self):
        now = datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc)

        self.assertEqual(build_rates_cache_key("TARIFF", now), "octopus_rates_TARIFF_2026-07-02")

    def test_summer_cache_becomes_stale_at_four_pm_british_time(self):
        cache_mtime = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

        self.assertFalse(is_rates_cache_stale(cache_mtime, datetime(2026, 7, 25, 14, 59, tzinfo=timezone.utc)))
        self.assertTrue(is_rates_cache_stale(cache_mtime, datetime(2026, 7, 25, 15, 1, tzinfo=timezone.utc)))

    def test_cache_written_after_release_is_not_stale(self):
        cache_mtime = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
        now = datetime(2026, 7, 25, 15, 1, tzinfo=timezone.utc)

        self.assertFalse(is_rates_cache_stale(cache_mtime, now))

    def test_post_release_cache_is_stale_when_tomorrow_is_missing(self):
        now = datetime(2026, 7, 25, 15, 30, tzinfo=timezone.utc)
        cache_mtime = datetime(2026, 7, 25, 15, 5, tzinfo=timezone.utc)
        rates = [{"valid_from": "2026-07-25T15:00:00Z", "valid_to": "2026-07-25T23:00:00Z"}]

        self.assertTrue(is_rates_cache_stale(cache_mtime, now, rates))

    def test_post_release_rates_cover_tomorrow_through_gb_midnight(self):
        now = datetime(2026, 7, 25, 15, 30, tzinfo=timezone.utc)
        rates = [{"valid_from": "2026-07-25T15:00:00Z", "valid_to": "2026-07-26T23:00:00Z"}]

        self.assertEqual(expected_rates_horizon(now), datetime(2026, 7, 26, 23, tzinfo=timezone.utc))
        self.assertTrue(rates_cover_expected_horizon(rates, now))

    def test_horizon_is_incomplete_when_current_half_hour_is_missing(self):
        now = datetime(2026, 7, 25, 15, 30, tzinfo=timezone.utc)
        rates = [{"valid_from": "2026-07-25T16:00:00Z", "valid_to": "2026-07-26T23:00:00Z"}]

        self.assertFalse(rates_cover_expected_horizon(rates, now))

    def test_agile_publication_boundary_and_missing_slots(self):
        for now in (
            datetime(2026, 9, 7, 10, tzinfo=timezone.utc),
            datetime(2026, 9, 7, 16, tzinfo=timezone.utc),
            datetime(2026, 1, 7, 17, tzinfo=timezone.utc),
            datetime(2026, 3, 28, 17, tzinfo=timezone.utc),
            datetime(2026, 10, 24, 17, tzinfo=timezone.utc),
        ):
            with self.subTest(now=now):
                end = expected_rates_horizon(now) - timedelta(hours=1)
                rates = self.build_half_hour_rates(now, end)
                self.assertTrue(rates_cover_expected_horizon(rates, now, "AGILE"))
                self.assertFalse(is_rates_cache_stale(now, now, rates, "AGILE"))
                self.assertFalse(rates_cover_expected_horizon(rates, now, "GO"))
                for missing in (0, len(rates) // 2, len(rates) - 1):
                    with self.subTest(missing=missing):
                        partial = rates[:missing] + rates[missing + 1:]
                        self.assertFalse(rates_cover_expected_horizon(partial, now, "AGILE"))
                        self.assertTrue(is_rates_cache_stale(now, now, partial, "AGILE"))

    def test_horizon_is_incomplete_when_internal_half_hour_is_missing(self):
        now = datetime(2026, 7, 25, 15, 30, tzinfo=timezone.utc)
        rates = [
            {"valid_from": "2026-07-25T15:00:00Z", "valid_to": "2026-07-25T16:00:00Z"},
            {"valid_from": "2026-07-25T16:30:00Z", "valid_to": "2026-07-26T23:00:00Z"},
        ]

        self.assertFalse(rates_cover_expected_horizon(rates, now))

    def test_expected_horizon_observes_autumn_clock_change(self):
        now = datetime(2026, 10, 24, 15, 30, tzinfo=timezone.utc)

        self.assertEqual(expected_rates_horizon(now), datetime(2026, 10, 26, tzinfo=timezone.utc))

    def test_complete_spring_clock_change_forecast_is_accepted(self):
        now = datetime(2026, 3, 28, 16, 30, tzinfo=timezone.utc)
        horizon = expected_rates_horizon(now)
        rates = self.build_half_hour_rates(now, horizon)

        self.assertEqual(horizon, datetime(2026, 3, 29, 23, tzinfo=timezone.utc))
        self.assertEqual(len(rates), 61)
        self.assertTrue(rates_cover_expected_horizon(rates, now))

    def test_complete_autumn_clock_change_forecast_is_accepted(self):
        now = datetime(2026, 10, 24, 15, 30, tzinfo=timezone.utc)
        horizon = expected_rates_horizon(now)
        rates = self.build_half_hour_rates(now, horizon)

        self.assertEqual(len(rates), 65)
        self.assertTrue(rates_cover_expected_horizon(rates, now))

    def test_missing_spring_transition_slot_is_incomplete(self):
        now = datetime(2026, 3, 28, 16, 30, tzinfo=timezone.utc)
        rates = self.build_half_hour_rates(now, expected_rates_horizon(now))
        rates = [
            rate
            for rate in rates
            if rate["valid_from"] != datetime(2026, 3, 29, 1, tzinfo=timezone.utc)
        ]

        self.assertFalse(rates_cover_expected_horizon(rates, now))

    def test_missing_repeated_autumn_slot_is_incomplete(self):
        now = datetime(2026, 10, 24, 15, 30, tzinfo=timezone.utc)
        rates = self.build_half_hour_rates(now, expected_rates_horizon(now))
        rates = [
            rate
            for rate in rates
            if rate["valid_from"] != datetime(2026, 10, 25, 1, tzinfo=timezone.utc)
        ]

        self.assertFalse(rates_cover_expected_horizon(rates, now))

    def test_next_release_check_uses_gb_wall_clock(self):
        before = datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc)
        after = datetime(2026, 7, 25, 16, 0, tzinfo=timezone.utc)

        self.assertEqual(next_price_release_check(before).isoformat(), "2026-07-25T16:01:00+01:00")
        self.assertEqual(next_price_release_check(after).isoformat(), "2026-07-26T16:01:00+01:00")

    def test_next_release_check_stays_at_four_pm_across_spring_clock_change(self):
        now = datetime(2026, 3, 28, 17, 0, tzinfo=timezone.utc)

        self.assertEqual(next_price_release_check(now).isoformat(), "2026-03-29T16:01:00+01:00")

    def test_next_release_check_stays_at_four_pm_across_autumn_clock_change(self):
        now = datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)

        self.assertEqual(next_price_release_check(now).isoformat(), "2026-10-25T16:01:00+00:00")

    def test_request_period_is_bounded_to_current_forecast(self):
        now = datetime(2026, 7, 25, 15, 17, tzinfo=timezone.utc)

        period_from, period_to = get_price_request_period(now)

        self.assertEqual(period_from, datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(period_to, datetime(2026, 7, 26, 23, 0, tzinfo=timezone.utc))
        self.assertEqual(PRICE_RETRY_DELAYS_SECONDS, (120, 300, 600, 1200, 1800, 3600))


if __name__ == "__main__":
    unittest.main()
