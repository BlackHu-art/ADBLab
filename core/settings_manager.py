"""持久化应用设置（JSON 存储）。

单例模式 — 全局通过 AppSettings.instance() 访问。
采用原子写入 + 静默回退策略，避免高频写入导致文件损坏。
"""

import json
import os
import tempfile
from typing import Any

from core.log_service import LogService

# 模块级路径常量 — 与 SETTINGS_FILE 同目录
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(_BASE_DIR, "resources", "app_settings.json")

DEFAULTS = {
    "font_family": "Segoe UI",
    "ui_font_size": 12,
    "log_font_size": 9,
    "save_directory": "",
    "log_max_lines": 2000,
    "monkey_default_count": "10000",
    "screen_record_duration": 180,
    "confirm_dangerous_ops": True,
    "auto_refresh_on_connect": True,
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
            cls._instance._dirty = False
            cls._instance._load()
        return cls._instance

    @classmethod
    def instance(cls):
        return cls()

    # ── File I/O ──

    def _load(self):
        """从 JSON 文件加载设置，失败时保留默认值并记录错误。"""
        if not os.path.exists(SETTINGS_FILE):
            return
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                stored = json.load(f)
            if not isinstance(stored, dict):
                raise ValueError("settings file is not a JSON object")
            for k in DEFAULTS:
                if k in stored:
                    self._data[k] = stored[k]
        except (json.JSONDecodeError, ValueError, OSError) as e:
            try:
                LogService().log("WARNING", f"Failed to load settings ({e}), using defaults")
            except Exception:
                pass

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

    # ── 公共 API ──────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any):
        """更新内存中的设置值并自动持久化。"""
        self._data[key] = value
        self._save_atomic()

    def reset(self, key: str = None):
        """重置指定 key 或全部设置到默认值。"""
        if key:
            self._data[key] = DEFAULTS.get(key, "")
        else:
            self._data = dict(DEFAULTS)
        self._save_atomic()

    # ── 便捷属性 ───────────────────────────────────────────────────────

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
