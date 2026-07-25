"""通过 JSON 文件持久化应用设置。

使用 AppSettings.instance() 访问单例，并通过原子写入降低配置损坏风险。
"""

import json
import os
import tempfile
import threading
from typing import Any

from core.log_service import LogService
from utils.resource_path import resource_path
from utils.user_data import user_config_path

# 模块级路径常量 — 与 SETTINGS_FILE 同目录
SETTINGS_FILE = user_config_path("app_settings.json")
LEGACY_SETTINGS_FILE = resource_path("resources/app_settings.json")

DEFAULTS = {
    "font_family": "Segoe UI",
    "ui_font_size": 12,
    "log_font_size": 9,
    "save_directory": "",
    "log_max_lines": 2000,
    "confirm_dangerous_ops": True,
    "continuous_device_scan": True,
    "device_scan_interval_ms": 15000,
    "always_on_top": False,
    "performance_log_threshold_ms": 300,
    "monkey_params": {
        "events": 10000,
        "throttle": 300,
        "touch": 30, "motion": 15, "trackball": 0, "nav": 20,
        "majornav": 10, "syskeys": 5, "appswitch": 8, "anyevent": 10, "pinch": 2,
        # 事件比例必须合计为 100%，开始 Monkey 前会统一校验。
        "ignore_crashes": True, "ignore_timeouts": True, "ignore_security": True,
    },
    "theme": "Light",
    "window_width": 1120,
    "window_height": 640,
    "left_panel_width": 400,
    "right_panel_width": 600,
}


class AppSettings:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = dict(DEFAULTS)
            cls._instance._save_timer = None
            cls._instance._load()
        return cls._instance

    @classmethod
    def instance(cls):
        return cls()

    def _load(self):
        """从 JSON 文件加载设置，失败时保留默认值并记录错误。"""
        paths = [SETTINGS_FILE]
        if os.path.normcase(os.path.abspath(LEGACY_SETTINGS_FILE)) != os.path.normcase(os.path.abspath(SETTINGS_FILE)):
            paths.append(LEGACY_SETTINGS_FILE)
        settings_path = next((path for path in paths if os.path.exists(path)), "")
        if not settings_path:
            return
        loaded_from = ""
        try:
            with open(settings_path, encoding="utf-8") as f:
                stored = json.load(f)
            if not isinstance(stored, dict):
                raise ValueError("settings file is not a JSON object")
            for k in DEFAULTS:
                if k in stored:
                    self._data[k] = stored[k]
            loaded_from = settings_path
        except (json.JSONDecodeError, ValueError, OSError) as e:
            try:
                LogService().log("WARNING", f"Failed to load settings ({e}), using defaults")
            except Exception:
                pass
        if loaded_from and loaded_from != SETTINGS_FILE and not os.path.exists(SETTINGS_FILE):
            self._save_atomic()

    def _save_atomic(self):
        """原子写入：先写临时文件，再原子替换，避免写入中途崩溃损坏文件。"""
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                suffix=".json", prefix="adblab_settings_", dir=os.path.dirname(SETTINGS_FILE)
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, SETTINGS_FILE)  # 原子替换（同文件系统）
            except Exception:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
        except Exception as e:
            try:
                LogService().log("ERROR", f"Failed to save settings: {e}")
            except Exception:
                pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any):
        """更新内存设置，并在 500 毫秒防抖后持久化。"""
        self._data[key] = value
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(0.5, self._save_atomic)
        self._save_timer.daemon = True
        self._save_timer.start()

    def reset(self, key: str = None):
        """将指定设置或全部设置恢复为默认值。"""
        if key:
            self._data[key] = DEFAULTS.get(key, "")
        else:
            self._data = dict(DEFAULTS)
        self._save_atomic()

    @property
    def save_directory(self) -> str:
        d = self.get("save_directory", "")
        if d and os.path.isdir(d):
            return d
        return os.path.join(os.path.expanduser("~"), "ADBLab")

    @property
    def ui_font_size(self) -> int:
        return self.get("ui_font_size", 12)

    @property
    def log_font_size(self) -> int:
        return self.get("log_font_size", 9)
