import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.price_bands import (
    HIGH_PRICE_THRESHOLD_GBP,
    LOW_PRICE_THRESHOLD_GBP,
    PRICE_BAND_HIGH,
    PRICE_BAND_LOW,
    PRICE_BAND_MEDIUM,
    PRICE_BAND_NEGATIVE,
    PRICE_BAND_VERSION,
    format_price_threshold,
    get_price_band,
)


class PriceBandTests(unittest.TestCase):
    def test_band_version_is_explicit_for_cached_usage_classification(self):
        self.assertEqual(PRICE_BAND_VERSION, 2)

    def test_negative_band_stops_at_zero(self):
        self.assertEqual(get_price_band(-0.0001), PRICE_BAND_NEGATIVE)
        self.assertEqual(get_price_band(0.0), PRICE_BAND_LOW)

    def test_low_band_excludes_twenty_pence_boundary(self):
        self.assertEqual(get_price_band(LOW_PRICE_THRESHOLD_GBP - 0.0001), PRICE_BAND_LOW)
        self.assertEqual(get_price_band(LOW_PRICE_THRESHOLD_GBP), PRICE_BAND_MEDIUM)

    def test_high_band_starts_at_twenty_six_point_five_pence(self):
        self.assertEqual(get_price_band(HIGH_PRICE_THRESHOLD_GBP - 0.0001), PRICE_BAND_MEDIUM)
        self.assertEqual(get_price_band(HIGH_PRICE_THRESHOLD_GBP), PRICE_BAND_HIGH)

    def test_threshold_formatting_preserves_half_pence(self):
        self.assertEqual(format_price_threshold(LOW_PRICE_THRESHOLD_GBP), "20p/kWh")
        self.assertEqual(format_price_threshold(HIGH_PRICE_THRESHOLD_GBP), "26.5p/kWh")


if __name__ == '__main__':
    unittest.main()
