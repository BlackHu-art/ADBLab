"""通过 JSON 文件持久化应用设置。

使用 :meth:`AppSettings.instance` 访问单例，并通过原子写入和批量更新降低配置
损坏及高频重复写入的风险。设置文件顶层携带 ``schema_version``，加载时按迁移链
补齐结构（ADR-0006），未知键显式剔除并记录警告。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from utils.resource_path import resource_path
from utils.user_data import user_config_path

SETTINGS_FILE = user_config_path("app_settings.json")
LEGACY_SETTINGS_FILE = resource_path("resources/app_settings.json")

# 设置层错误日志的注入点：组合根在创建 LogService 后调用 set_error_sink 注入实现，
# 使 core 不依赖 Qt/LogService 即可单测；未注入时错误静默丢弃（ADR-0003 Phase 3）。
_error_sink = None
_error_sink_lock = threading.Lock()


def set_error_sink(sink) -> None:
    """注入 ``(level: str, message: str) -> None`` 形式的错误日志接收器。"""

    global _error_sink
    with _error_sink_lock:
        _error_sink = sink


def _log_error(level: str, message: str) -> None:
    """向注入的错误日志接收器转发消息；无接收器或接收器异常时静默。"""

    with _error_sink_lock:
        sink = _error_sink
    if sink is None:
        return
    try:
        sink(level, message)
    except Exception:
        pass

# RemotePanel 只允许通过这组正式键跨会话保存 scrcpy 表单值。该映射同时作为
# AppSettings 加载白名单的一部分，使旧版本已经写入 JSON 的同名键无需迁移即可恢复。
SCRCPY_SETTING_DEFAULTS = {
    "scrcpy_preset": "Smooth",
    "scrcpy_maxsize": "1024",
    "scrcpy_fps": "30",
    "scrcpy_codec": "h264",
    "scrcpy_buffer": "50",
    "scrcpy_bitrate": "4",
    "scrcpy_orientation": "0",
}


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
    "window_width": 1250,
    "window_height": 700,
    "left_panel_width": 400,
    "right_panel_width": 600,
    "panel_split_ratio": 0.4,
    "device_log_split_ratio": 0.6,
    **SCRCPY_SETTING_DEFAULTS,
}

_FONT_SIZE_RULES = {
    "ui_font_size": (8, 22, 12),
    "log_font_size": (7, 16, 9),
}


def _normalise_setting(key: str, value: Any) -> Any:
    """校验需要稳定边界的设置，其他设置保持原有类型与行为。"""

    if key in SCRCPY_SETTING_DEFAULTS:
        if value is None or isinstance(value, (bool, dict, list, tuple, set)):
            return SCRCPY_SETTING_DEFAULTS[key]
        text = str(value).strip()
        return text[:128] if text else SCRCPY_SETTING_DEFAULTS[key]

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

    if key in {"panel_split_ratio", "device_log_split_ratio"}:
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


def _stored_schema_version(stored: dict) -> int:
    """读取存储字典的 schema 版本；缺失或非正整数一律视为 v1（种子时代）。"""

    version = stored.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        return 1
    return max(1, version)


def _migrate_1_to_2(stored: dict) -> None:
    """v1 → v2：折算面板比例并补齐缺失键，用户已设值一律不动（ADR-0006）。"""

    if "panel_split_ratio" not in stored:
        stored["panel_split_ratio"] = _legacy_panel_ratio(
            stored.get("left_panel_width"),
            stored.get("right_panel_width"),
        )
    for key, default in DEFAULTS.items():
        if key not in stored:
            stored[key] = deepcopy(default)
    monkey = stored.get("monkey_params")
    if isinstance(monkey, dict):
        merged = deepcopy(DEFAULTS["monkey_params"])
        merged.update(monkey)
        stored["monkey_params"] = merged
    else:
        stored["monkey_params"] = deepcopy(DEFAULTS["monkey_params"])


def _migrate_2_to_3(stored: dict) -> None:
    """v2 → v3：剔除未知键（含 monkey_params 内的死键）并记录警告（ADR-0006）。"""

    _prune_unknown_keys(stored)


def _run_migrations(stored: dict, from_version: int) -> None:
    """按版本升序对存储字典做原地结构迁移。"""

    for version in range(from_version, CURRENT_SCHEMA_VERSION):
        migration = _MIGRATIONS.get(version)
        if migration is not None:
            migration(stored)


def _prune_unknown_keys(stored: dict) -> None:
    """剔除未知顶层键与未知 monkey_params 键，每类一次性记录警告。"""

    unknown = sorted(
        str(key) for key in stored if key not in DEFAULTS and key != "schema_version"
    )
    for key in unknown:
        stored.pop(key, None)
    if unknown:
        _log_error(
            "WARNING",
            f"Ignored {len(unknown)} unknown settings key(s): {', '.join(unknown)}",
        )
    monkey = stored.get("monkey_params")
    if not isinstance(monkey, dict):
        return
    monkey_defaults = DEFAULTS["monkey_params"]
    monkey_unknown = sorted(str(key) for key in monkey if key not in monkey_defaults)
    for key in monkey_unknown:
        monkey.pop(key, None)
    if monkey_unknown:
        _log_error(
            "WARNING",
            f"Ignored {len(monkey_unknown)} unknown monkey_params key(s): "
            f"{', '.join(monkey_unknown)}",
        )


_MIGRATIONS: dict[int, Callable[[dict], None]] = {
    1: _migrate_1_to_2,
    2: _migrate_2_to_3,
}
CURRENT_SCHEMA_VERSION = max(_MIGRATIONS) + 1


class AppSettings:
    """线程安全的应用设置单例。"""

    _instance = None
    _instance_lock = threading.Lock()

    # 实例状态在 __new__ 中初始化；此处仅声明类型供静态检查。
    _lock: threading.RLock
    _write_lock: threading.Lock
    _data: dict
    _save_timer: threading.Timer | None
    _seen_version: int

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._lock = threading.RLock()
                    instance._write_lock = threading.Lock()
                    instance._data = deepcopy(DEFAULTS)
                    instance._save_timer = None
                    instance._seen_version = CURRENT_SCHEMA_VERSION
                    instance._future_extra = {}
                    cls._instance = instance
                    instance._load()
        return cls._instance

    @classmethod
    def instance(cls):
        """返回应用设置单例。"""

        return cls()

    def _load(self) -> None:
        """加载用户设置；不存在时尝试迁移旧安装目录中的设置。

        按 ADR-0006 的迁移链补齐结构：无 ``schema_version`` 的文件视为 v1，
        逐版本迁移到 ``CURRENT_SCHEMA_VERSION`` 后剔除未知键；来自旧版本文件的
        迁移结果立即落盘。版本高于当前支持范围的文件只读已知键、不清理不迁移。
        """

        paths = [SETTINGS_FILE]
        if os.path.normcase(os.path.abspath(LEGACY_SETTINGS_FILE)) != os.path.normcase(
            os.path.abspath(SETTINGS_FILE)
        ):
            paths.append(LEGACY_SETTINGS_FILE)
        settings_path = next((path for path in paths if os.path.exists(path)), "")
        if not settings_path:
            return

        loaded_from = ""
        needs_immediate_save = False
        try:
            with open(settings_path, encoding="utf-8") as file:
                stored = json.load(file)
            if not isinstance(stored, dict):
                raise ValueError("settings file is not a JSON object")
            stored_version = _stored_schema_version(stored)
            with self._lock:
                if stored_version > CURRENT_SCHEMA_VERSION:
                    self._seen_version = stored_version
                    _log_error(
                        "WARNING",
                        f"Settings schema v{stored_version} is newer than supported "
                        f"v{CURRENT_SCHEMA_VERSION}; known keys loaded, file left untouched",
                    )
                    self._future_extra = {
                        k: v for k, v in stored.items()
                        if k not in DEFAULTS and k != "schema_version"
                    }
                else:
                    _run_migrations(stored, stored_version)
                    _prune_unknown_keys(stored)
                    needs_immediate_save = stored_version < CURRENT_SCHEMA_VERSION
                for key in DEFAULTS:
                    if key in stored:
                        self._data[key] = _normalise_setting(key, stored[key])
            loaded_from = settings_path
        except (json.JSONDecodeError, ValueError, OSError) as error:
            _log_error("WARNING", f"Failed to load settings ({error}), using defaults")

        if loaded_from and (
            needs_immediate_save
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
                    # 版本号由加载/保存流程托管：来自更高版本的只读文件保留其
                    # 版本号，避免降级安装把新文件改写回旧版本。
                    snapshot["schema_version"] = self._seen_version
                    # 保留更高版本文件的未知字段，避免降级安装一次保存就破坏新版本数据。
                    snapshot.update(self._future_extra)
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
            _log_error("ERROR", f"Failed to save settings: {error}")

    def _schedule_save(self) -> None:
        """重新启动单个防抖计时器。

        旧计时器的取消在锁内完成，避免并发 update/reset 取消已被替换的
        Timer 之后仍然启动新 Timer 的窗口（审计 T-5）。
        """

        with self._lock:
            previous_timer = self._save_timer
            if previous_timer is not None:
                previous_timer.cancel()
            timer = threading.Timer(0.5, self._save_atomic)
            timer.daemon = True
            self._save_timer = timer
        timer.start()

    def get(self, key: str, default: Any = None) -> Any:
        """读取设置，不存在时按默认设置和调用方默认值依次回退。"""

        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        """更新单项设置，并在 500 毫秒防抖后持久化。"""

        self.update({key: value})

    def update(self, values: Mapping[str, Any]) -> None:
        """批量更新多项设置，并仅安排一次防抖持久化。

        ``schema_version`` 由加载/保存流程托管，调用方写入会被忽略并记录警告。
        """

        if not isinstance(values, Mapping):
            raise TypeError("values must be a mapping")
        normalised = {
            str(key): _normalise_setting(str(key), value)
            for key, value in values.items()
            if str(key) != "schema_version"
        }
        if any(str(key) == "schema_version" for key in values):
            _log_error("WARNING", "schema_version is loader-managed; update() ignored it")
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
                if key in DEFAULTS:
                    self._data[key] = deepcopy(DEFAULTS[key])
                else:
                    self._data.pop(key, None)
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


__all__ = [
    "AppSettings",
    "CURRENT_SCHEMA_VERSION",
    "DEFAULTS",
    "LEGACY_SETTINGS_FILE",
    "SCRCPY_SETTING_DEFAULTS",
    "SETTINGS_FILE",
    "set_error_sink",
]
