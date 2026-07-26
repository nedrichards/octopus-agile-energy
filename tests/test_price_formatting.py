import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from price_formatting import format_gbp, format_unit_price_gbp


class PriceFormattingTests(unittest.TestCase):
    def test_format_gbp_places_minus_before_currency_symbol(self):
        self.assertEqual(format_gbp(-0.06), "-£0.06")

    def test_format_gbp_does_not_show_negative_zero_after_rounding(self):
        self.assertEqual(format_gbp(-0.004), "£0.00")

    def test_format_gbp_supports_whole_pound_amounts(self):
        self.assertEqual(format_gbp(-12.4, decimals=0), "-£12")

    def test_format_unit_price_gbp_adds_kwh_suffix(self):
        self.assertEqual(format_unit_price_gbp(-0.061), "-£0.06/kWh")


if __name__ == "__main__":
    unittest.main()
