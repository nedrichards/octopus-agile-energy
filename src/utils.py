import os
import json
import hashlib
import time
from gi.repository import GLib

class CacheManager:
    """
    Manages simple file-based caching for network requests.
    """
    def __init__(self, cache_dir_name="octopus-agile-app", default_ttl_seconds=300): # Default TTL 5 minutes
        self.cache_dir = os.path.join(GLib.get_user_cache_dir(), cache_dir_name)
        self.default_ttl = default_ttl_seconds
        self._ensure_cache_dir()

    def _ensure_cache_dir(self):
        """Ensures the cache directory exists."""
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_filepath(self, key):
        """Generates a unique file path for a given cache key."""
        # Use MD5 hash of the key for the filename
        hashed_key = hashlib.md5(key.encode('utf-8')).hexdigest()
        return os.path.join(self.cache_dir, hashed_key + ".json")

    def get(self, key):
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
            print(f"Cache read error for key '{key}': {e}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return None, None

    def set(self, key, data):
        """Stores data in the cache, but only if it's not empty."""
        if not data:
            print(f"Cache warning: Refusing to cache empty data for key '{key}'.")
            return

        filepath = self._get_cache_filepath(key)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (IOError, OSError) as e:
            print(f"Cache write error for key '{key}': {e}")
