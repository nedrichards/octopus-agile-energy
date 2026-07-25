import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.main import OctopusAgileApp  # noqa: E402


class ApplicationActivationTests(unittest.TestCase):
    def test_reuses_active_window(self):
        window = Mock()
        app = Mock()
        app.get_active_window.return_value = window
        application = SimpleNamespace(window=None)

        OctopusAgileApp.on_activate(application, app)

        self.assertIs(application.window, window)
        window.present.assert_called_once_with()

    def test_creates_window_when_none_is_active(self):
        app = Mock()
        app.get_active_window.return_value = None
        application = SimpleNamespace(window=None)
        window = Mock()

        with patch("src.main.MainWindow", return_value=window) as main_window:
            OctopusAgileApp.on_activate(application, app)

        main_window.assert_called_once_with(application=app)
        window.present.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
