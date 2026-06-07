import os
import json


class Settings:
    """Handles loading and saving of application settings dynamically without hardcoded keys."""

    def __init__(self, filename="settings.json"):
        self.filename = filename
        self.data = {}
        self.load()

    def load(self):
        if not os.path.exists(self.filename):
            return
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.data = loaded
        except Exception as e:
            print(f"Error loading settings: {e}")

    def save(self):
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        # Notice: save() is no longer called here to prevent excessive disk writes.
        # It must be triggered explicitly after a batch of configurations is set.
