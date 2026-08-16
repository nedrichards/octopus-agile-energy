import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils import CacheManager


class CacheManagerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
