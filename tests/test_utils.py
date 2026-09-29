import os
import stat
import tempfile
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch

from src.utils import CacheManager, weak_callback


class CacheManagerTests(unittest.TestCase):
    def test_deferred_cache_construction_does_not_touch_disk(self):
        with patch("src.utils.os.makedirs", side_effect=AssertionError("UI disk I/O")), \
                patch("src.utils.os.listdir", side_effect=AssertionError("UI expiry scan")):
            cache = CacheManager(initialize=False)
        self.assertFalse(cache._initialized)

    def test_deleted_file_releases_its_in_memory_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch("src.utils.GLib.get_user_cache_dir", return_value=temp_dir):
            cache = CacheManager()
            cache.set("usage", {"samples": [1]})
            Path(cache._get_cache_filepath("usage")).unlink()
            self.assertEqual(cache.get("usage"), (None, None))
            self.assertFalse(cache._memory_cache)

    def test_cache_directory_and_files_are_private(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.utils.GLib.get_user_cache_dir", return_value=temp_dir):
                cache = CacheManager()
                cache.set("octopus_usage_A-SECRET", {"samples": [1]})

            cache_path = Path(cache._get_cache_filepath("octopus_usage_A-SECRET"))
            directory_mode = stat.S_IMODE(os.stat(cache.cache_dir).st_mode)
            file_mode = stat.S_IMODE(cache_path.stat().st_mode)

            self.assertEqual(directory_mode, 0o700)
            self.assertEqual(file_mode, 0o600)
            self.assertEqual(cache.get("octopus_usage_A-SECRET")[0], {"samples": [1]})

    def test_invalid_scalar_cache_payload_is_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.utils.GLib.get_user_cache_dir", return_value=temp_dir):
                cache = CacheManager()

            cache_path = Path(cache._get_cache_filepath("bad"))
            cache_path.write_text("42", encoding="utf-8")

            self.assertEqual(cache.get("bad"), (None, None))
            self.assertFalse(cache_path.exists())

    def test_unchanged_cache_is_decoded_only_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.utils.GLib.get_user_cache_dir", return_value=temp_dir):
                cache = CacheManager()
                cache.set("rates", {"results": [1]})
                cache._memory_cache.clear()

                with patch("src.utils.json.load", wraps=__import__("json").load) as json_load:
                    self.assertEqual(cache.get("rates")[0], {"results": [1]})
                    self.assertEqual(cache.get("rates")[0], {"results": [1]})

            self.assertEqual(json_load.call_count, 1)


class WeakCallbackTests(unittest.TestCase):
    def test_native_callback_does_not_keep_its_owner_alive(self):
        class Owner:
            def callback(self, value):
                return value

        owner = Owner()
        reference = weakref.ref(owner)
        callback = weak_callback(owner.callback)
        self.assertEqual(callback(7), 7)
        del owner
        self.assertIsNone(reference())
        self.assertIsNone(callback(7))


if __name__ == "__main__":
    unittest.main()
