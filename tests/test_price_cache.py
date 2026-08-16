import unittest
from datetime import datetime, timezone

from src.price_cache import build_rates_cache_key, is_rates_cache_stale


class PriceCacheTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
