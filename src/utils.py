import hashlib
import json
import logging
import os
import tempfile
import time
from contextlib import suppress

from gi.repository import GLib

logger = logging.getLogger(__name__)

class CacheManager:
    """
    Manages simple file-based caching for network requests.
    """
    def __init__(self, cache_dir_name="octopus-agile-app", cache_expiry_days=7):
        self.cache_dir = os.path.join(GLib.get_user_cache_dir(), cache_dir_name)
        self.cache_expiry_days = cache_expiry_days
        self._memory_cache = {}
        self._ensure_cache_dir()
        self.cleanup()

    def _ensure_cache_dir(self):
        """Ensures the cache directory exists."""
        os.makedirs(self.cache_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(self.cache_dir, 0o700)
        except OSError as exc:
            logger.warning("Could not enforce private cache-directory permissions: %s", type(exc).__name__)

    def _get_cache_filepath(self, key):
        """Generates a unique file path for a given cache key."""
        # Use a stable hash to make the key safe for use as a filename.
        hashed_key = hashlib.sha256(key.encode('utf-8')).hexdigest()
        return os.path.join(self.cache_dir, hashed_key + ".json")

    def get(self, key: str) -> tuple[dict | None, float | None]:
        """
        Retrieves data from cache if available.
        Returns a tuple: (data, modification_time_as_timestamp).
        Returns (None, None) if not found or on error.
        """
        filepath = self._get_cache_filepath(key)
        if not os.path.exists(filepath):
            return None, None

        try:
            file_stat = os.stat(filepath)
            signature = (file_stat.st_mtime_ns, file_stat.st_size)
            memory_entry = self._memory_cache.get(filepath)
            if memory_entry and memory_entry[0] == signature:
                return memory_entry[1], file_stat.st_mtime

            with open(filepath, encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, (dict, list)):
                raise TypeError("Unexpected cache payload type")
            self._memory_cache[filepath] = (signature, data)
            return data, file_stat.st_mtime
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            self._memory_cache.pop(filepath, None)
            logger.error("Cache read failed: %s", type(exc).__name__)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError as rm_e:
                    logger.error("Failed to remove a corrupted cache file: %s", type(rm_e).__name__)
            return None, None

    def set(self, key: str, data: dict | list) -> None:
        """Stores data in the cache atomically, but only if it's not empty."""
        if not data:
            logger.warning("Refusing to cache an empty response")
            return

        filepath = self._get_cache_filepath(key)
        file_descriptor = None
        temp_filepath = None

        try:
            file_descriptor, temp_filepath = tempfile.mkstemp(
                prefix=".cache-",
                suffix=".tmp",
                dir=self.cache_dir,
                text=True,
            )
            with os.fdopen(file_descriptor, 'w', encoding='utf-8') as f:
                file_descriptor = None
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is flushed to disk

            # Atomically replace the old file with the new one
            os.replace(temp_filepath, filepath)
            temp_filepath = None
            file_stat = os.stat(filepath)
            self._memory_cache[filepath] = ((file_stat.st_mtime_ns, file_stat.st_size), data)
            logger.debug("Cache updated")
        except (OSError, TypeError, ValueError) as exc:
            logger.error("Cache write failed: %s", type(exc).__name__)
            if file_descriptor is not None:
                with suppress(OSError):
                    os.close(file_descriptor)
            if temp_filepath and os.path.exists(temp_filepath):
                with suppress(OSError):
                    os.remove(temp_filepath)

    def cleanup(self) -> None:
        """Removes cache files older than the specified expiry days."""
        if not os.path.exists(self.cache_dir):
            return

        cutoff = time.time() - (self.cache_expiry_days * 86400)
        for filename in os.listdir(self.cache_dir):
            filepath = os.path.join(self.cache_dir, filename)
            try:
                if os.path.isfile(filepath) and os.path.getmtime(filepath) < cutoff:
                    os.remove(filepath)
                    self._memory_cache.pop(filepath, None)
                    logger.debug("Removed expired cache file: %s", filename)
            except OSError as e:
                logger.warning("Error removing an expired cache file: %s", type(e).__name__)
