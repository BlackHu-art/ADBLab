"""
Persistent application settings stored as JSON.

Singleton pattern — load once, access everywhere via AppSettings.instance().
"""

import json
import os
from typing import Any

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             "resources", "app_settings.json")

DEFAULTS = {
    "font_base_size": 12,
    "font_small_size": 12,
    "font_mono_size": 10,
    "font_tab_size": 12,
    "save_directory": "",
    "log_max_lines": 2000,
    "monkey_default_count": "10000",
    "screen_record_duration": 180,
    "confirm_dangerous_ops": True,
    "auto_refresh_on_connect": True,
    "theme": "Light",
    "window_width": 1120,
    "window_height": 640,
}


class AppSettings:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = dict(DEFAULTS)
            cls._instance._load()
        return cls._instance

    @classmethod
    def instance(cls):
        return cls()

    def _load(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    stored = json.load(f)
                for k in DEFAULTS:
                    if k in stored:
                        self._data[k] = stored[k]
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any):
        self._data[key] = value
        self.save()

    def reset(self, key: str = None):
        if key:
            self._data[key] = DEFAULTS.get(key, "")
            self.save()
        else:
            self._data = dict(DEFAULTS)
            self.save()

    @property
    def save_directory(self) -> str:
        d = self.get("save_directory", "")
        if d and os.path.isdir(d):
            return d
        return os.path.join(os.path.expanduser("~"), "ADBLab")

    @property
    def font_base_size(self) -> int:
        return self.get("font_base_size", 12)

    @property
    def font_small_size(self) -> int:
        return self.get("font_small_size", 12)

    @property
    def font_mono_size(self) -> int:
        return self.get("font_mono_size", 10)

    @property
    def font_tab_size(self) -> int:
        return self.get("font_tab_size", 12)
