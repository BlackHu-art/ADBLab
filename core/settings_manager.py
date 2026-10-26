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
import time
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from core.settings import migrations as _migrations
from core.settings import schema as _schema
from utils.resource_path import resource_path
from utils.user_data import user_config_path

# 旧模块继续暴露同一规则对象，避免消费者持有相互漂移的默认值或迁移表。
DEFAULTS = _schema.DEFAULTS
SCRCPY_SETTING_DEFAULTS = _schema.SCRCPY_SETTING_DEFAULTS
UI_SCALE_OPTIONS = _schema.UI_SCALE_OPTIONS
LANGUAGE_OPTIONS = _schema.LANGUAGE_OPTIONS
normalise_language = _schema.normalise_language
normalise_ui_scale = _schema.normalise_ui_scale
_FONT_SIZE_RULES = _schema._FONT_SIZE_RULES
_normalise_integer = _schema._normalise_integer
_normalise_adb_client = _schema._normalise_adb_client
_legacy_panel_ratio = _migrations.legacy_panel_ratio
_stored_schema_version = _migrations.stored_schema_version
_MIGRATIONS = _migrations._MIGRATIONS
CURRENT_SCHEMA_VERSION = _migrations.CURRENT_SCHEMA_VERSION

SETTINGS_FILE = user_config_path("app_settings.json")
LEGACY_SETTINGS_FILE = resource_path("resources/app_settings.json")

# 设置文件只允许有界读取，避免损坏/恶意文件在启动阶段拖垮进程。
MAX_SETTINGS_BYTES = 4 * 1024 * 1024

# 设置层错误日志的注入点：组合根先注入启动缓冲，再在 LogService 创建后注入正式实现，
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


def _normalise_setting(key: str, value: Any) -> Any:
    """兼容旧入口，统一委托纯字段规则。"""

    return _schema.normalise_setting(key, value)


def _migrate_1_to_2(stored: dict) -> None:
    """兼容旧迁移入口，调用时传递当前管理器诊断接收器。"""

    _migrations.migrate_1_to_2(stored, _log_error)


def _migrate_2_to_3(stored: dict) -> None:
    """兼容旧清理步骤，诊断替换在每次调用时生效。"""

    _migrations.migrate_2_to_3(stored, _log_error)


def _run_migrations(stored: dict, from_version: int) -> None:
    """兼容旧迁移调度，保持版本顺序与调用时诊断注入。"""

    _migrations.run_migrations(stored, from_version, _log_error)


def _prune_unknown_keys(stored: dict) -> None:
    """兼容旧清理入口，由管理器保留错误接收器所有权。"""

    _migrations.prune_unknown_keys(stored, _log_error)


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
    _deferred_save_pending: bool
    _save_timers: set[threading.Timer]
    _active_saves: int
    _save_condition: threading.Condition
    _close_lock: threading.Lock
    _closed: bool
    _close_snapshot: dict | None
    _close_snapshot_error: str
    _close_saved: bool
    _unreadable_settings: bool
    _unreadable_path: str
    _unreadable_is_parse: bool

    def __new__(cls, *, defer_migration_save: bool = False):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._lock = threading.RLock()
                    instance._write_lock = threading.Lock()
                    instance._data = deepcopy(DEFAULTS)
                    instance._save_timer = None
                    instance._save_timers = set()
                    instance._active_saves = 0
                    instance._save_condition = threading.Condition(instance._lock)
                    instance._close_lock = threading.Lock()
                    instance._closed = False
                    instance._close_snapshot = None
                    instance._close_snapshot_error = ""
                    instance._close_saved = False
                    instance._unreadable_settings = False
                    instance._unreadable_path = ""
                    instance._unreadable_is_parse = False
                    instance._seen_version = CURRENT_SCHEMA_VERSION
                    instance._future_extra = {}
                    instance._deferred_save_pending = False
                    # 先完成磁盘加载再发布单例；否则并发首次调用可能读到默认值，
                    # 或先把 update() 写入内存又被随后的 _load() 覆盖。
                    instance._load(defer_migration_save=defer_migration_save)
                    cls._instance = instance
        return cls._instance

    def __init__(self, *, defer_migration_save: bool = False) -> None:
        """仅首次构造时使用迁移回写选项；已有单例不会重新加载。"""

    @classmethod
    def instance(cls, *, defer_migration_save: bool = False):
        """返回单例；首次创建可延后迁移回写，供启动后台阶段显式完成。"""

        return cls(defer_migration_save=defer_migration_save)

    def _load(self, *, defer_migration_save: bool = False) -> None:
        """加载用户设置；不存在时尝试迁移旧安装目录中的设置。

        按 ADR-0006 的迁移链补齐结构：无 ``schema_version`` 的文件视为 v1，
        逐版本迁移到 ``CURRENT_SCHEMA_VERSION`` 后剔除未知键；来自旧版本文件的
        迁移结果默认立即落盘；启动阶段可仅延后回写，读取及内存规范化保持同步。
        版本高于当前支持范围的文件只读已知键、不清理不迁移。
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
            if os.path.getsize(settings_path) > MAX_SETTINGS_BYTES:
                raise ValueError("settings file is too large")
            with open(settings_path, encoding="utf-8") as file:
                stored = json.loads(file.read(MAX_SETTINGS_BYTES + 1))
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
        except (json.JSONDecodeError, ValueError, RecursionError) as error:
            backup = self._backup_corrupt_settings(settings_path)
            self._unreadable_settings = not backup
            self._unreadable_path = settings_path if not backup else ""
            self._unreadable_is_parse = not backup
            suffix = "; original preserved" if backup else ""
            _log_error(
                "WARNING",
                f"Failed to load settings ({type(error).__name__}), using defaults{suffix}",
            )
        except OSError as error:
            # 读取权限/占用属于 I/O 失败，不能把合法文件改名为损坏备份。
            # legacy 输入不可读不应阻断主设置文件创建；主文件才需要保护。
            is_main_file = os.path.normcase(settings_path) == os.path.normcase(
                SETTINGS_FILE
            )
            self._unreadable_settings = is_main_file
            self._unreadable_path = settings_path if is_main_file else ""
            self._unreadable_is_parse = False
            _log_error(
                "WARNING",
                f"Failed to read settings ({type(error).__name__}), using defaults",
            )

        if loaded_from and (
            needs_immediate_save
            or (loaded_from != SETTINGS_FILE and not os.path.exists(SETTINGS_FILE))
        ):
            if defer_migration_save:
                with self._lock:
                    self._deferred_save_pending = True
            else:
                self._save_atomic()

    @staticmethod
    def _backup_corrupt_settings(settings_path: str) -> str:
        """保留无法解析的设置原文；备份失败时调用方必须禁止覆盖。"""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        candidate = f"{settings_path}.corrupt-{stamp}"
        index = 1
        while os.path.exists(candidate):
            candidate = f"{settings_path}.corrupt-{stamp}-{index}"
            index += 1
        try:
            # 同目录原子改名即可完整保留原文，不复制任意大小文件。
            os.replace(settings_path, candidate)
        except OSError as error:
            _log_error(
                "ERROR",
                f"Failed to preserve corrupt settings: {type(error).__name__}",
            )
            return ""
        return candidate

    def flush_deferred_save(self) -> bool:
        """由启动后台任务回写待迁移设置；失败保留待写状态供后续重试。"""

        return self._save_atomic(deferred_only=True)

    def _save_atomic(self, *, deferred_only: bool = False) -> bool:
        """原子保存并返回成功状态；失败保留原文件和内存值，供下次更新或关闭重试。"""

        with self._lock:
            if self._closed:
                return False
            self._active_saves += 1
        return self._run_admitted_save(deferred_only=deferred_only)

    def _run_admitted_save(self, *, deferred_only: bool = False) -> bool:
        """完成已准入保存；包括等写锁的阶段都属于 owner 的排空义务。"""

        try:
            return self._write_snapshot(deferred_only=deferred_only)
        finally:
            with self._save_condition:
                self._active_saves -= 1
                self._save_condition.notify_all()

    def _snapshot_locked(self) -> dict:
        """在状态锁内完整冻结数据、版本和未来字段，避免重试读取外部可变对象。"""

        return deepcopy({
            **self._data,
            "schema_version": self._seen_version,
            **self._future_extra,
        })

    def _write_snapshot(
        self, snapshot: dict | None = None, *, deferred_only: bool = False,
    ) -> bool:
        """串行原子落盘；普通保存锁后取快照，关闭保存使用首次冻结内容。"""

        temporary_path = ""
        try:
            # Timer、重置和关闭收尾可能同时触发保存；串行化整个写入过程，
            # 并在取得写锁后再生成快照，避免旧快照最后覆盖新设置。
            with self._write_lock:
                with self._lock:
                    if self._unreadable_settings:
                        if not self._unreadable_is_parse:
                            _log_error(
                                "ERROR",
                                "Settings file could not be read; preserving it and "
                                "refusing to overwrite with defaults",
                            )
                            return False
                        if os.path.normcase(self._unreadable_path) != os.path.normcase(
                            SETTINGS_FILE
                        ):
                            # 损坏的是 legacy 输入；主设置文件仍可正常写入。
                            self._unreadable_settings = False
                            self._unreadable_is_parse = False
                        else:
                            backup = self._backup_corrupt_settings(
                                self._unreadable_path,
                            )
                            if backup:
                                self._unreadable_settings = False
                                self._unreadable_path = ""
                                self._unreadable_is_parse = False
                            else:
                                _log_error(
                                    "ERROR",
                                    "Settings are unreadable and no backup was created; "
                                    "refusing to overwrite the original file",
                                )
                                return False
                    if deferred_only and not self._deferred_save_pending:
                        return True
                    if snapshot is None:
                        snapshot = self._snapshot_locked()
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
                with self._lock:
                    self._deferred_save_pending = False
            return True
        except Exception as error:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
            _log_error("ERROR", f"Failed to save settings: {type(error).__name__}")
            return False

    def _schedule_save(self) -> None:
        """锁内登记并启动防抖线程；被替换线程直到真正退出仍由本实例持有。"""

        with self._lock:
            if self._closed:
                return
            self._save_timers = {timer for timer in self._save_timers if timer.is_alive()}
            previous_timer = self._save_timer
            if previous_timer is not None:
                previous_timer.cancel()
            timer = threading.Timer(0.5, self._save_atomic)
            timer.daemon = True
            self._save_timer = timer
            self._save_timers.add(timer)
            try:
                timer.start()
            except Exception:
                # start 可能在线程已经启动后才抛错；只撤销确实不可 join 的对象。
                if timer.ident is None:
                    self._save_timers.discard(timer)
                    self._save_timer = previous_timer
                raise

    def close(self) -> bool:
        """封闭修改与保存准入，等待全部工作退出，再保存首次冻结快照。

        仅供后台收尾和非 GUI 清理调用；无内部超时。False 表示排空后的冻结或
        落盘失败；有快照时后续 close 仅重试该快照，成功后幂等且不再执行 I/O。
        冻结失败时保持终止且不再读取可变数据，后续 close 仍返回 False。
        不支持从本实例的 Timer、保存函数或错误回调重入。
        """

        with self._close_lock:
            with self._lock:
                if self._close_saved:
                    return True
                if not self._closed:
                    self._closed = True
                    try:
                        self._close_snapshot = self._snapshot_locked()
                    except Exception as error:
                        # 任意运行时值可能拒绝复制；冻结失败也不能跳过资源排空，
                        # 且重试不得改用已封闭后的可变数据冒充首次快照。
                        self._close_snapshot_error = type(error).__name__
                timers = tuple(self._save_timers)
                for timer in timers:
                    timer.cancel()
            # 不持状态锁等线程或写锁，否则回调无法完成保存与活动计数归还。
            for timer in timers:
                timer.join()
            with self._save_condition:
                self._save_timers.difference_update(timers)
                self._save_condition.wait_for(lambda: self._active_saves == 0)
            if self._close_snapshot is None:
                _log_error(
                    "ERROR", f"Failed to freeze settings: {self._close_snapshot_error}",
                )
                return False
            self._close_saved = self._write_snapshot(self._close_snapshot)
            return self._close_saved

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

        with self._lock:
            if self._closed:
                raise RuntimeError("AppSettings is closed")
            if not isinstance(values, Mapping):
                raise TypeError("values must be a mapping")
            normalised = {
                str(key): _normalise_setting(str(key), value)
                for key, value in values.items()
                if str(key) != "schema_version"
            }
            ignored_version = any(str(key) == "schema_version" for key in values)
            if normalised:
                self._data.update(normalised)
                self._schedule_save()
        if ignored_version:
            _log_error("WARNING", "schema_version is loader-managed; update() ignored it")

    def set_many(self, values: Mapping[str, Any]) -> None:
        """兼容性批量设置别名。"""

        self.update(values)

    def reset(self, key: str | None = None) -> None:
        """将指定设置或全部设置恢复为默认值，并立即持久化。"""

        with self._lock:
            if self._closed:
                raise RuntimeError("AppSettings is closed")
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
            self._active_saves += 1
        self._run_admitted_save()

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
