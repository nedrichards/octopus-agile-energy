import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from time_formatting import (
    format_time_from_now,
    format_uk_time,
    format_uk_time_window,
)


class TimeFormattingTests(unittest.TestCase):
    def test_repeated_autumn_times_include_their_uk_timezone(self):
        first_one_am = datetime(2025, 10, 26, 0, 0, tzinfo=timezone.utc)
        second_one_am = datetime(2025, 10, 26, 1, 0, tzinfo=timezone.utc)

        self.assertEqual(format_uk_time(first_one_am), "01:00 BST")
        self.assertEqual(format_uk_time(second_one_am), "01:00 GMT")

    def test_ordinary_uk_time_remains_compact(self):
        value = datetime(2025, 10, 26, 2, 0, tzinfo=timezone.utc)

        self.assertEqual(format_uk_time(value), "02:00")

    def test_autumn_window_disambiguates_both_ends(self):
        start = datetime(2025, 10, 26, 0, 30, tzinfo=timezone.utc)
        end = datetime(2025, 10, 26, 1, 0, tzinfo=timezone.utc)

        self.assertEqual(
            format_uk_time_window(start, end),
            "01:30 BST-01:00 GMT",
        )

    def test_spring_window_makes_the_clock_jump_explicit(self):
        start = datetime(2025, 3, 30, 0, 30, tzinfo=timezone.utc)
        end = datetime(2025, 3, 30, 1, 0, tzinfo=timezone.utc)

        self.assertEqual(
            format_uk_time_window(start, end),
            "00:30 GMT-02:00 BST",
        )

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

    def test_format_time_from_now_compares_mixed_timezones_in_utc(self):
        now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
        target = datetime(2026, 6, 29, 14, 30, tzinfo=timezone(timedelta(hours=1)))

        self.assertEqual(format_time_from_now(target, now), "1h 30m")

    def test_format_time_from_now_handles_repeated_local_hour_on_clock_change(self):
        london = ZoneInfo("Europe/London")
        now = datetime(2025, 10, 26, 0, 30, tzinfo=timezone.utc).astimezone(london)
        target = datetime(2025, 10, 26, 1, 30, tzinfo=timezone.utc).astimezone(london)

        self.assertEqual(format_time_from_now(target, now), "1h")

    def test_format_time_from_now_rounds_partial_minutes_up(self):
        now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(
            format_time_from_now(now + timedelta(minutes=1, seconds=1), now),
            "2m",
        )
