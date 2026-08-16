import logging
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.main import OctopusAgileApp, configure_logging


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


class LoggingTests(unittest.TestCase):
    @patch("src.main.is_development_build", return_value=True)
    @patch("src.main.logging.getLogger")
    @patch("src.main.logging.basicConfig")
    def test_development_logging_does_not_enable_dependency_debug_logs(
        self,
        basic_config,
        get_logger,
        _is_development_build,
    ):
        application_logger = Mock()
        get_logger.return_value = application_logger

        configure_logging()

        self.assertEqual(basic_config.call_args.kwargs["level"], logging.INFO)
        get_logger.assert_called_once_with("src")
        application_logger.setLevel.assert_called_once_with(logging.DEBUG)


if __name__ == "__main__":
    unittest.main()
