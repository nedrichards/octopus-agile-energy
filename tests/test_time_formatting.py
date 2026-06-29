import unittest
from datetime import datetime, timedelta, timezone

from time_formatting import format_time_from_now


class TimeFormattingTests(unittest.TestCase):
    def test_format_time_from_now_formats_whole_hours(self):
        now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(
            format_time_from_now(now + timedelta(hours=3), now),
            "3h",
        )

    def test_format_time_from_now_formats_hours_and_minutes(self):
        now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(
            format_time_from_now(now + timedelta(hours=1, minutes=30), now),
            "1h 30m",
        )

    def test_format_time_from_now_formats_sub_hour_times(self):
        now = datetime(2026, 6, 29, 12, 17, tzinfo=timezone.utc)

        self.assertEqual(
            format_time_from_now(now + timedelta(minutes=43), now),
            "43m",
        )

    def test_format_time_from_now_clamps_past_times_to_now(self):
        now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(
            format_time_from_now(now - timedelta(minutes=1), now),
            "now",
        )
