import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.ui.preferences_window import PreferencesWindow
from src.ui.setup_window import SetupWindow


class PreferencesCredentialTests(unittest.TestCase):
    @patch("src.ui.preferences_window.store_api_key")
    def test_keyring_write_is_deferred_until_an_account_action(self, store_api_key):
        window = SimpleNamespace(
            _api_key_dirty=False,
            _set_auto_detect_status=Mock(),
            api_key_entry=Mock(),
        )

        PreferencesWindow.on_api_key_changed(window, Mock())

        self.assertTrue(window._api_key_dirty)
        store_api_key.assert_not_called()

        window.api_key_entry.get_text.return_value = " secret-key "
        store_api_key.return_value = True
        self.assertTrue(PreferencesWindow._save_api_key_entry(window))
        self.assertFalse(window._api_key_dirty)
        store_api_key.assert_called_once_with("secret-key")

        self.assertTrue(PreferencesWindow._save_api_key_entry(window))
        store_api_key.assert_called_once_with("secret-key")


class SetupCredentialTests(unittest.TestCase):
    @patch("src.ui.setup_window.store_api_key", return_value=False)
    def test_failed_keyring_write_remains_dirty(self, store_api_key):
        window = SimpleNamespace(
            _manual_api_key_dirty=True,
            manual_api_key_entry=Mock(),
            _update_manual_api_section=Mock(),
        )
        window.manual_api_key_entry.get_text.return_value = "secret-key"

        self.assertFalse(SetupWindow._save_manual_api_key_entry(window))

        self.assertTrue(window._manual_api_key_dirty)
        store_api_key.assert_called_once_with("secret-key")


if __name__ == "__main__":
    unittest.main()
