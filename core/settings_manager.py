"""通过 JSON 文件持久化应用设置。

使用 :meth:`AppSettings.instance` 访问单例，并通过原子写入和批量更新降低配置
损坏及高频重复写入的风险。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from core.log_service import LogService
from utils.resource_path import resource_path
from utils.user_data import user_config_path

SETTINGS_FILE = user_config_path("app_settings.json")
LEGACY_SETTINGS_FILE = resource_path("resources/app_settings.json")

DEFAULTS = {
    # 空字符串表示跟随 Qt 提供的系统默认界面字体。
    "font_family": "",
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
        "touch": 30,
        "motion": 15,
        "trackball": 0,
        "nav": 20,
        "majornav": 10,
        "syskeys": 5,
        "appswitch": 8,
        "anyevent": 10,
        "pinch": 2,
        # 各事件比例须合计为 100%，启动 Monkey 前会再次统一校验。
        "ignore_crashes": True,
        "ignore_timeouts": True,
        "ignore_security": True,
    },
    "theme": "Light",
    "window_width": 1120,
    "window_height": 640,
    "left_panel_width": 400,
    "right_panel_width": 600,
    "panel_split_ratio": 0.4,
}

_FONT_SIZE_RULES = {
    "ui_font_size": (8, 22, 12),
    "log_font_size": (7, 16, 9),
}


def _normalise_setting(key: str, value: Any) -> Any:
    """校验需要稳定边界的设置，其他设置保持原有类型与行为。"""

    if key == "font_family":
        if not isinstance(value, str):
            return DEFAULTS[key]
        family = value.strip()
        if family.casefold() == "system default":
            return ""
        return family[:128]

    if key in _FONT_SIZE_RULES:
        minimum, maximum, default = _FONT_SIZE_RULES[key]
        if isinstance(value, bool):
            return default
        try:
            size = int(value)
        except (TypeError, ValueError, OverflowError):
            return default
        return max(minimum, min(maximum, size))

    if key == "panel_split_ratio":
        if isinstance(value, bool):
            return DEFAULTS[key]
        try:
            ratio = float(value)
        except (TypeError, ValueError, OverflowError):
            return DEFAULTS[key]
        return max(0.2, min(0.7, ratio))

    return value


def _legacy_panel_ratio(left_width: Any, right_width: Any) -> float:
    """把旧版左右像素宽度迁移为受限的左栏比例。"""

    try:
        left = max(0.0, float(left_width))
        right = max(0.0, float(right_width))
    except (TypeError, ValueError, OverflowError):
        return DEFAULTS["panel_split_ratio"]
    total = left + right
    if total <= 0:
        return DEFAULTS["panel_split_ratio"]
    return max(0.2, min(0.7, left / total))


class AppSettings:
    """线程安全的应用设置单例。"""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._lock = threading.RLock()
                    instance._write_lock = threading.Lock()
                    instance._data = deepcopy(DEFAULTS)
                    instance._save_timer = None
                    cls._instance = instance
                    instance._load()
        return cls._instance

    @classmethod
    def instance(cls):
        """返回应用设置单例。"""

        return cls()

    def _load(self) -> None:
        """加载用户设置；不存在时尝试迁移旧安装目录中的设置。"""

        paths = [SETTINGS_FILE]
        if os.path.normcase(os.path.abspath(LEGACY_SETTINGS_FILE)) != os.path.normcase(
            os.path.abspath(SETTINGS_FILE)
        ):
            paths.append(LEGACY_SETTINGS_FILE)
        settings_path = next((path for path in paths if os.path.exists(path)), "")
        if not settings_path:
            return

        loaded_from = ""
        migrated_panel_ratio = False
        try:
            with open(settings_path, encoding="utf-8") as file:
                stored = json.load(file)
            if not isinstance(stored, dict):
                raise ValueError("settings file is not a JSON object")
            with self._lock:
                for key in DEFAULTS:
                    if key in stored:
                        self._data[key] = _normalise_setting(key, stored[key])
                if "panel_split_ratio" not in stored:
                    self._data["panel_split_ratio"] = _legacy_panel_ratio(
                        self._data["left_panel_width"],
                        self._data["right_panel_width"],
                    )
                    migrated_panel_ratio = True
            loaded_from = settings_path
        except (json.JSONDecodeError, ValueError, OSError) as error:
            try:
                LogService().log(
                    "WARNING",
                    f"Failed to load settings ({error}), using defaults",
                )
            except Exception:
                pass

        if loaded_from and (
            migrated_panel_ratio
            or (loaded_from != SETTINGS_FILE and not os.path.exists(SETTINGS_FILE))
        ):
            self._save_atomic()

    def _save_atomic(self) -> None:
        """先写临时文件再原子替换，避免中途退出导致配置文件损坏。"""

        temporary_path = ""
        try:
            # Timer、重置和关闭收尾可能同时触发保存；串行化整个写入过程，
            # 并在取得写锁后再生成快照，避免旧快照最后覆盖新设置。
            with self._write_lock:
                with self._lock:
                    snapshot = deepcopy(self._data)
                target = os.fspath(SETTINGS_FILE)
                target_directory = os.path.dirname(target) or os.curdir
                os.makedirs(target_directory, exist_ok=True)
                temporary_fd, temporary_path = tempfile.mkstemp(
                    suffix=".json",
                    prefix="adblab_settings_",
                    dir=target_directory,
                )
                with os.fdopen(temporary_fd, "w", encoding="utf-8") as file:
                    json.dump(snapshot, file, indent=2, ensure_ascii=False)
                os.replace(temporary_path, target)
                temporary_path = ""
        except Exception as error:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
            try:
                LogService().log("ERROR", f"Failed to save settings: {error}")
            except Exception:
                pass

    def _schedule_save(self) -> None:
        """重新启动单个防抖计时器。"""

        with self._lock:
            previous_timer = self._save_timer
            timer = threading.Timer(0.5, self._save_atomic)
            timer.daemon = True
            self._save_timer = timer
        if previous_timer is not None:
            previous_timer.cancel()
        timer.start()

    def get(self, key: str, default: Any = None) -> Any:
        """读取设置，不存在时按默认设置和调用方默认值依次回退。"""

        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        """更新单项设置，并在 500 毫秒防抖后持久化。"""

        self.update({key: value})

    def update(self, values: Mapping[str, Any]) -> None:
        """批量更新多项设置，并仅安排一次防抖持久化。"""

        if not isinstance(values, Mapping):
            raise TypeError("values must be a mapping")
        normalised = {
            str(key): _normalise_setting(str(key), value) for key, value in values.items()
        }
        if not normalised:
            return
        with self._lock:
            self._data.update(normalised)
        self._schedule_save()

    def set_many(self, values: Mapping[str, Any]) -> None:
        """兼容性批量设置别名。"""

        self.update(values)

    def reset(self, key: str | None = None) -> None:
        """将指定设置或全部设置恢复为默认值，并立即持久化。"""

        with self._lock:
            pending_timer = self._save_timer
            self._save_timer = None
            if key:
                self._data[key] = deepcopy(DEFAULTS.get(key, ""))
            else:
                self._data = deepcopy(DEFAULTS)
        if pending_timer is not None:
            pending_timer.cancel()
        self._save_atomic()

    @property
    def save_directory(self) -> str:
        """返回已配置且有效的保存目录，否则使用用户主目录下的 ADBLab。"""

        directory = self.get("save_directory", "")
        if directory and os.path.isdir(directory):
            return directory
        return os.path.join(os.path.expanduser("~"), "ADBLab")

    @property
    def ui_font_size(self) -> int:
        """返回已校验的界面字号。"""

        return self.get("ui_font_size", 12)

    @property
    def log_font_size(self) -> int:
        """返回已校验的日志字号。"""

        return self.get("log_font_size", 9)


__all__ = ["AppSettings", "DEFAULTS", "LEGACY_SETTINGS_FILE", "SETTINGS_FILE"]
