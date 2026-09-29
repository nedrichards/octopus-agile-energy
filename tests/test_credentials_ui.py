import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.ui.preferences_window import PreferencesDialog
from src.ui.setup_window import SetupWindow


class PreferencesCredentialTests(unittest.TestCase):
    def window(self):
        window = SimpleNamespace(
            _api_key_dirty=False, _credential_revision=0, _closed=False,
            _credential_save_pending=False, _credential_save_callbacks=[],
            _set_auto_detect_status=Mock(), api_key_entry=Mock(),
        )
        window._save_api_key_entry = lambda callback: PreferencesDialog._save_api_key_entry(window, callback)
        window._finish_credential_save = lambda saved: PreferencesDialog._finish_credential_save(window, saved)
        return window

    @patch("src.ui.preferences_window.save_api_key_async")
    def test_keyring_write_is_deferred_and_account_action_waits_for_completion(self, save):
        window = self.window()
        PreferencesDialog.on_api_key_changed(window, Mock())
        save.assert_not_called()
        self.assertTrue(window._api_key_dirty)
        window.api_key_entry.get_text.return_value = " secret-key "
        callback = Mock()
        window._save_api_key_entry(callback)
        self.assertTrue(window._credential_save_pending)
        self.assertTrue(window._api_key_dirty)
        callback.assert_not_called()
        self.assertEqual(save.call_args.args[0], "secret-key")
        save.call_args.args[1](True)
        self.assertFalse(window._api_key_dirty)
        callback.assert_called_once_with(True)
        window._save_api_key_entry(callback)
        save.assert_called_once()

    @patch("src.ui.preferences_window.save_api_key_async")
    def test_edited_key_is_saved_again_before_releasing_waiting_actions(self, save):
        window = self.window()
        window._api_key_dirty = True
        window.api_key_entry.get_text.return_value = "first"
        callback = Mock()
        window._save_api_key_entry(callback)
        window.api_key_entry.get_text.return_value = "second"
        save.call_args.args[1](True)
        callback.assert_not_called()
        self.assertEqual(save.call_args.args[0], "second")
        save.call_args.args[1](True)
        callback.assert_called_once_with(True)

    def test_late_lookup_does_not_replace_user_edits_or_a_saved_key(self):
        for dirty, revision in ((True, 0), (False, 1)):
            window = self.window()
            window._api_key_dirty, window._credential_revision = dirty, revision
            PreferencesDialog._apply_existing_api_key(window, "old")
            window.api_key_entry.set_text.assert_not_called()

    def test_close_cancels_location_and_saves_credentials_asynchronously(self):
        location_portal = Mock()
        window = SimpleNamespace(location_portal=location_portal, _save_api_key_entry=Mock())
        PreferencesDialog.on_closed(window, None)
        location_portal.cancel.assert_called_once_with()
        self.assertIsNone(window.location_portal)
        window._save_api_key_entry.assert_called_once()
        self.assertTrue(window._closed)


class SetupCredentialTests(unittest.TestCase):
    @patch("src.ui.setup_window.save_api_key_async")
    def test_failed_keyring_write_remains_dirty(self, save):
        window = SimpleNamespace(
            _manual_api_key_dirty=True, _credential_save_pending=False,
            _credential_save_callbacks=[], _credential_revision=0,
            manual_api_key_entry=Mock(), _update_manual_api_section=Mock(),
        )
        window._finish_manual_credential_save = lambda saved: SetupWindow._finish_manual_credential_save(window, saved)
        window.manual_api_key_entry.get_text.return_value = "secret-key"
        callback = Mock()
        SetupWindow._save_manual_api_key_entry(window, callback)
        callback.assert_not_called()
        save.call_args.args[1](False)
        callback.assert_called_once_with(False)
        self.assertTrue(window._manual_api_key_dirty)
        self.assertFalse(window._credential_save_pending)

    def test_close_waits_for_save_then_retries_close(self):
        window = SimpleNamespace(location_portal=None, _manual_api_key_dirty=True,
                                 _credential_save_pending=False, _save_manual_api_key_entry=Mock(),
                                 _close_after_credential_save=Mock())
        self.assertTrue(SetupWindow.on_close_request(window, None))
        window._save_manual_api_key_entry.assert_called_once_with(window._close_after_credential_save)


if __name__ == "__main__":
    unittest.main()
