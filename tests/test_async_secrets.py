import unittest
from unittest.mock import Mock, patch

from src import secrets_manager


class AsyncSecretTests(unittest.TestCase):
    def test_lookup_can_distinguish_keyring_failure_from_a_missing_key(self):
        error = secrets_manager.GLib.Error("Unavailable")
        with patch.object(secrets_manager.Secret, "password_lookup_sync", side_effect=error):
            self.assertIsNone(secrets_manager.get_api_key())
            with self.assertRaises(secrets_manager.GLib.Error):
                secrets_manager.get_api_key(raise_on_error=True)
        with patch.object(secrets_manager.Secret, "password_lookup_sync", return_value=None):
            self.assertIsNone(secrets_manager.get_api_key(raise_on_error=True))

    def test_lookup_uses_native_async_call_and_only_finishes_in_callback(self):
        ready = Mock()
        with patch.object(secrets_manager.Secret, "password_lookup") as lookup, \
                patch.object(secrets_manager.Secret, "password_lookup_finish", return_value="example") as finish, \
                patch.object(secrets_manager.Secret, "password_lookup_sync", side_effect=AssertionError("UI lookup")):
            secrets_manager.get_api_key_async(ready)
            ready.assert_not_called()
            finish.assert_not_called()
            result = object()
            lookup.call_args.args[3](None, result, None)
            finish.assert_called_once_with(result)
            ready.assert_called_once_with("example")

    def test_store_waits_for_native_completion(self):
        saved = Mock()
        with patch.object(secrets_manager.Secret, "password_store") as store, \
                patch.object(secrets_manager.Secret, "password_store_finish", return_value=True):
            secrets_manager.save_api_key_async("example", saved)
            saved.assert_not_called()
            store.call_args.args[6](None, object(), None)
            saved.assert_called_once_with(True)

    def test_clearing_an_already_empty_store_is_successful(self):
        saved = Mock()
        with patch.object(secrets_manager.Secret, "password_clear") as clear, \
                patch.object(secrets_manager.Secret, "password_clear_finish", return_value=False):
            secrets_manager.save_api_key_async("", saved)
            saved.assert_not_called()
            clear.call_args.args[3](None, object(), None)
            saved.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
