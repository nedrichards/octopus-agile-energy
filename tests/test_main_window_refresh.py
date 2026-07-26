import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ui.main_window import MainWindow


class PriceRefreshCoordinationTests(unittest.TestCase):
    def test_duplicate_automatic_refresh_is_ignored(self):
        window = SimpleNamespace(
            price_refresh_in_progress=True,
            _fetch_generation=4,
            _price_refresh_queued=False,
            _queued_price_refresh_force=False,
            _get_price_setup_issue=Mock(return_value=None),
        )

        started = MainWindow.refresh_price(window, force=False)

        self.assertFalse(started)
        self.assertEqual(window._fetch_generation, 4)
        self.assertFalse(window._price_refresh_queued)

    def test_in_flight_refresh_is_invalidated_and_coalesced(self):
        window = SimpleNamespace(
            price_refresh_in_progress=True,
            _fetch_generation=4,
            _price_refresh_queued=False,
            _queued_price_refresh_force=False,
            _get_price_setup_issue=Mock(return_value=None),
        )

        started = MainWindow.refresh_price(window, force=True)

        self.assertFalse(started)
        self.assertEqual(window._fetch_generation, 5)
        self.assertTrue(window._price_refresh_queued)
        self.assertTrue(window._queued_price_refresh_force)

    def test_finishing_refresh_starts_single_queued_forced_refresh(self):
        window = SimpleNamespace(
            price_refresh_in_progress=True,
            _price_refresh_queued=True,
            _queued_price_refresh_force=True,
            refresh_price=Mock(),
        )

        keep_source = MainWindow._finish_price_refresh(window, 4)

        self.assertFalse(keep_source)
        self.assertFalse(window.price_refresh_in_progress)
        self.assertFalse(window._price_refresh_queued)
        self.assertFalse(window._queued_price_refresh_force)
        window.refresh_price.assert_called_once_with(force=True)


if __name__ == "__main__":
    unittest.main()
