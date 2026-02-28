import os
import json
import hashlib
import time
import logging
from gi.repository import GLib

logger = logging.getLogger(__name__)

class CacheManager:
    """
    Manages simple file-based caching for network requests.
    """
    def __init__(self, cache_dir_name="octopus-agile-app", cache_expiry_days=7):
        self.cache_dir = os.path.join(GLib.get_user_cache_dir(), cache_dir_name)
        self.cache_expiry_days = cache_expiry_days
        self._ensure_cache_dir()
        self.cleanup()

    def _ensure_cache_dir(self):
        """Ensures the cache directory exists."""
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_filepath(self, key):
        """Generates a unique file path for a given cache key."""
        # Use MD5 hash of the key for the filename
        hashed_key = hashlib.md5(key.encode('utf-8')).hexdigest()
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
            file_mtime = os.path.getmtime(filepath)
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data, file_mtime
        except (IOError, json.JSONDecodeError, OSError) as e:
            logger.error("Cache read error for key '%s': %s", key, e)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError as rm_e:
                    logger.error("Failed to remove corrupted cache file '%s': %s", filepath, rm_e)
            return None, None

    def set(self, key: str, data: dict | list) -> None:
        """Stores data in the cache atomically, but only if it's not empty."""
        if not data:
            logger.warning("Cache warning: Refusing to cache empty data for key '%s'.", key)
            return

        filepath = self._get_cache_filepath(key)
        # Create a temporary file in the same directory
        temp_filepath = filepath + ".tmp"
        
        try:
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is flushed to disk
                
            # Atomically replace the old file with the new one
            os.replace(temp_filepath, filepath)
            logger.debug("Successfully updated cache for key: %s", key)
        except (IOError, OSError) as e:
            logger.error("Cache write error for key '%s': %s", key, e)
            # Cleanup temp file if it exists
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except OSError:
                    pass

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
                    print(f"Removed expired cache file: {filename}")
            except OSError as e:
                print(f"Error removing cache file {filepath}: {e}")