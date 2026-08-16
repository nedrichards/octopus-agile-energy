import os
import sys
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from find_cheapest_presentation import (
    build_find_cheapest_presentation,
    build_fixed_start_presentation,
)
from price_fixtures import AGILE_REGION_A_2025_05_25_PENCE, historical_agile_prices
from price_logic import find_cheapest_slot, find_cheapest_timer_slot


@contextmanager
def utc_process_timezone():
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        yield
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


class FindCheapestPresentationTests(unittest.TestCase):
    def test_builds_fixed_start_comparison_for_more_expensive_window(self):
        slot = {
            "start": datetime(2025, 5, 25, 15, 0, tzinfo=timezone.utc),
            "end": datetime(2025, 5, 25, 16, 30, tzinfo=timezone.utc),
            "average_price_gbp": 0.173,
        }

        with utc_process_timezone():
            presentation = build_fixed_start_presentation(slot, 0.142)

        self.assertEqual(presentation["window_text"], "15:00-16:30")
        self.assertEqual(presentation["average_price_text"], "£0.17/kWh")
        self.assertEqual(presentation["comparison_text"], "3.1p/kWh more")

    def test_fixed_start_comparison_can_be_cheaper_outside_search_window(self):
        slot = {
            "start": datetime(2025, 5, 25, 23, 0, tzinfo=timezone.utc),
            "end": datetime(2025, 5, 26, 0, 0, tzinfo=timezone.utc),
            "average_price_gbp": 0.10,
        }

        presentation = build_fixed_start_presentation(slot, 0.142)

        self.assertEqual(presentation["comparison_text"], "4.2p/kWh less")

    def test_builds_user_visible_rows_for_negative_price_appliance_window(self):
        day_start = datetime(2025, 5, 25, 0, 0, tzinfo=timezone.utc)
        now = datetime(2025, 5, 25, 10, 17, tzinfo=timezone.utc)
        prices = historical_agile_prices(day_start, AGILE_REGION_A_2025_05_25_PENCE)
        cheapest_slot = find_cheapest_slot(
            prices,
            now,
            duration_hours=3.5,
            start_within_hours=12,
        )
        start_timer_slot = find_cheapest_timer_slot(prices, now, 3.5, 12, "start")
        finish_timer_slot = find_cheapest_timer_slot(prices, now, 3.5, 12, "finish")

        with utc_process_timezone():
            presentation = build_find_cheapest_presentation(
                cheapest_slot,
                start_timer_slot,
                finish_timer_slot,
                duration_hours=3.5,
                now=now,
            )

        self.assertEqual(presentation["highlight_label"], "Best 3h 30m")
        self.assertEqual(presentation["best_window_text"], "11:00-14:30")
        self.assertEqual(presentation["average_price_text"], "-£0.06/kWh")
        self.assertEqual(presentation["start_timer_text"], "1h")
        self.assertEqual(
            presentation["start_timer_detail"],
            "11:17-14:47 · -£0.06/kWh",
        )
        self.assertEqual(presentation["finish_timer_text"], "4h")
        self.assertEqual(
            presentation["finish_timer_detail"],
            "10:47-14:17 · -£0.06/kWh · +0.2p/kWh",
        )

    def test_returns_none_without_a_cheapest_slot(self):
        now = datetime(2025, 5, 25, 10, 17, tzinfo=timezone.utc)

        self.assertIsNone(
            build_find_cheapest_presentation(
                cheapest_slot=None,
                start_timer_slot=None,
                finish_timer_slot=None,
                duration_hours=1,
                now=now,
            )
        )

    def test_uses_missing_timer_copy_when_cheapest_slot_exists_without_timer_data(self):
        now = datetime(2025, 5, 25, 10, 17, tzinfo=timezone.utc)
        cheapest_slot = {
            "start": datetime(2025, 5, 25, 11, 0, tzinfo=timezone.utc),
            "end": datetime(2025, 5, 25, 12, 0, tzinfo=timezone.utc),
            "average_price_gbp": -0.05,
        }

        with utc_process_timezone():
            presentation = build_find_cheapest_presentation(
                cheapest_slot,
                start_timer_slot=None,
                finish_timer_slot=None,
                duration_hours=1,
                now=now,
            )

        self.assertEqual(presentation["start_timer_text"], "—")
        self.assertEqual(presentation["finish_timer_text"], "—")
        self.assertEqual(presentation["start_timer_detail"], "Not enough price data")
        self.assertEqual(presentation["finish_timer_detail"], "Not enough price data")


if __name__ == "__main__":
    unittest.main()
