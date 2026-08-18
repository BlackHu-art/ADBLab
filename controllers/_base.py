"""提供 ADBController 的模型装配、结果分派和任务生命周期基础能力。"""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QThreadPool, Slot

from adblab.application.envelope import OperationMetadata, split_operation_metadata
from adblab.application.operations import OperationManager, OperationState
from core.log_service import LogService
from core.perf_trace import (
    DEFAULT_SLOW_THRESHOLD_MS,
    format_perf,
    perf_counter,
    should_log_perf,
    split_perf,
    summarize_perf,
)
from core.settings_manager import AppSettings
from gui.panels.adb_control_signals import ADBControllerSignals
from models.adb_advanced import ADBAdvanced
from models.adb_app import ADBApp
from models.adb_device import ADBDevice
from models.adb_testing import ADBTesting
from models.base.process_runner import ProcessRunner
from models.device_store import DeviceStore
from utils.resource_path import resource_path


class _ADBControllerBase:
    """封装 ADBController 共用的模型、信号和处理器分派基础设施。"""

    def __init__(self, log_service: LogService):
        self.signals = ADBControllerSignals()
        self.log_service = log_service
        self._settings = AppSettings.instance()
        self.device_model = ADBDevice()
        self.app_model = ADBApp()
        self.testing_model = ADBTesting()
        self.advanced_model = ADBAdvanced()
        self.connected_devices_file = resource_path("resources/connected_devices.yaml")
        self.package_info = resource_path("resources/package_info.yaml")
        self.thread_pool = QThreadPool.globalInstance()
        self._pending_ops = {}
        self._pending_lock = threading.Lock()
        self.operation_manager = OperationManager()
        self._operation_handler_map = {}
        self._connect_model_signals()
        # 由界面组装根注入，只负责生命周期托管，不建立 Qt 原生父子关系。
        self.window_owner = None
        self.last_save_dir = None
        self._active_viewers = []
        self._monkey_running = set()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._batch_trackers = {}
        self._build_handler_map()

        try:
            DeviceStore.load()
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to load DeviceStore: {str(e)}")
            DeviceStore.initialize_empty()

    def _connect_model_signals(self):
        self.device_model.command_finished.connect(self._handle_async_response)
        self.app_model.command_finished.connect(self._handle_async_response)
        self.testing_model.command_finished.connect(self._handle_async_response)
        self.advanced_model.command_finished.connect(self._handle_async_response)

    def _build_handler_map(self):
        self._handler_map = {}
        self._operation_handler_map = {}
        _handler_names: dict[str, str] = {}
        _operation_handler_names: dict[str, str] = {}
        for klass in reversed(type(self).__mro__):
            registered = klass.__dict__.get("_handlers", {})
            for op_key, handler_name in registered.items():
                if op_key in _handler_names:
                    prev_name = _handler_names[op_key]
                    self.log_service.log(
                        "WARNING",
                        f"Handler collision: '{op_key}' — {klass.__name__}.{handler_name} "
                        f"overrides {prev_name}",
                    )
                _handler_names[op_key] = handler_name
                self._handler_map[op_key] = getattr(self, handler_name)
            operation_handlers = klass.__dict__.get("_operation_handlers", {})
            for op_key, handler_name in operation_handlers.items():
                if op_key in _operation_handler_names:
                    previous = _operation_handler_names[op_key]
                    self.log_service.log(
                        "WARNING",
                        f"Operation handler collision: '{op_key}' — "
                        f"{klass.__name__}.{handler_name} overrides {previous}",
                    )
                _operation_handler_names[op_key] = handler_name
                self._operation_handler_map[op_key] = getattr(self, handler_name)

    def _generate_operation_id(self) -> str:
        return str(uuid.uuid4())

    def _register_operation_handler(self, op_type: str, handler):
        """注册 vNext 处理器，同时保持旧处理器签名不变。"""
        if not isinstance(op_type, str) or not op_type.strip():
            raise ValueError("op_type must be a non-empty string")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._operation_handler_map[op_type.strip()] = handler

    @Slot(str, bool, str)
    def _emit_operation(self, operation: str, success: bool, message: str):
        level = "INFO" if success else "ERROR"
        if not message.strip():
            return
        # 用户点击后的完成态日志要立即进入界面，避免再叠加 200ms 批量刷新延迟。
        self.log_service.log(level, f"{message}", flush_immediately=True)
        self.signals.operation_completed.emit(operation, success, message)

    def _require_devices(self, devices: list, op_name: str) -> bool:
        """校验设备列表；为空时发出失败结果并返回 False。"""
        if not devices:
            self._emit_operation(op_name, False, "⚠️ No devices selected")
            return False
        return True

    def _handle_async_response(self, method_name: str, result):
        result, operation_metadata = split_operation_metadata(result)
        result, perf = split_perf(result)
        op_type = method_name.replace("_async", "")
        ui_started_at = perf_counter()

        try:
            if operation_metadata is not None:
                self._route_operation_response(op_type, result, operation_metadata)
                return

            if op_type == "get_connected_devices":
                if isinstance(result, list):
                    self._process_device_list(result)
                else:
                    self._emit_operation(op_type, False, "Invalid device list format")
                return

            handler = self._handler_map.get(op_type)
            if handler:
                try:
                    handler(result)
                except Exception as e:
                    self.log_service.log("ERROR", f"[{op_type}] Handler error: {str(e)}")
                    self._emit_operation(op_type, False, f"Handler error: {str(e)}")
            else:
                self._default_async_handler(op_type, result)
        finally:
            self._log_perf_if_slow(op_type, perf, ui_started_at, perf_counter())

    def _route_operation_response(
        self,
        op_type: str,
        result,
        metadata: OperationMetadata,
    ):
        snapshot = self.operation_manager.get(metadata.operation_id)
        if snapshot is None:
            self.log_service.log(
                "DEBUG",
                f"[{op_type}] Ignored stale operation result",
            )
            return
        if metadata.method_name != op_type or metadata.operation_kind != snapshot.kind:
            self.log_service.log(
                "ERROR",
                f"[{op_type}] Operation metadata mismatch",
            )
            self._fail_operation_protocol(
                snapshot,
                "Operation metadata mismatch",
            )
            return
        operation_handler = self._operation_handler_map.get(op_type)
        if operation_handler is None:
            self.log_service.log(
                "ERROR",
                f"[{op_type}] No vNext operation handler registered",
            )
            self._fail_operation_protocol(
                snapshot,
                "Operation handler missing",
            )
            return
        self._dispatch_operation_handler(
            operation_handler,
            op_type,
            result,
            metadata,
        )

    def _dispatch_operation_handler(
        self,
        handler,
        op_type: str,
        result,
        metadata: OperationMetadata,
    ):
        try:
            handler(result, metadata)
        except Exception as exc:
            self.log_service.log(
                "ERROR",
                f"[{op_type}] Operation handler error: {type(exc).__name__}",
            )
            snapshot = self.operation_manager.get(metadata.operation_id)
            terminal = (
                self._fail_operation_protocol(
                    snapshot,
                    "Operation handler failed",
                )
                if snapshot is not None
                else None
            )
            if terminal is None:
                self.log_service.log(
                    "DEBUG",
                    f"[{op_type}] Operation already terminal after handler error",
                )

    def _fail_operation_protocol(self, snapshot, message: str):
        return self.operation_manager.finish(
            snapshot.operation_id,
            OperationState.FAILED,
            message=message,
        )

    def _log_perf_if_slow(self, op_type: str, perf, ui_started_at: float, ui_finished_at: float):
        summary = summarize_perf(perf, ui_started_at, ui_finished_at)
        threshold_ms = self._performance_log_threshold_ms()
        if should_log_perf(summary, threshold_ms):
            self.log_service.log("DEBUG", format_perf(op_type, summary))

    def _performance_log_threshold_ms(self) -> float:
        try:
            return float(
                self._settings.get(
                    "performance_log_threshold_ms",
                    DEFAULT_SLOW_THRESHOLD_MS,
                )
            )
        except (AttributeError, TypeError, ValueError):
            return DEFAULT_SLOW_THRESHOLD_MS

    def _default_async_handler(self, op_type: str, result):
        if isinstance(result, dict):
            # device_info_updated 仅对包含设备属性（Model/Brand等）的结果触发
            # 避免每次 adb 操作都触发设备列表刷新
            if "Model" in result or "ip" in result:
                device = result.get("device_ip") or result.get("ip", "")
                if device:
                    self.signals.device_info_updated.emit(device, result)
            if result.get("success", False):
                self._emit_operation(op_type, True, f"{op_type} completed")
            else:
                error_msg = result.get("error", "Unknown error")
                self._emit_operation(op_type, False, error_msg)
        else:
            self._emit_operation(op_type, True, f"{op_type} completed")

    def _indent_output(self, text: str, prefix: str = "     ") -> str:
        return "\n".join(f"{prefix}{line}" for line in text.splitlines() if line.strip())

    def _get_screenshot_dir(self) -> str:
        if self.last_save_dir and os.path.exists(self.last_save_dir):
            return self.last_save_dir
        settings = AppSettings.instance()
        default_dir = settings.save_directory
        os.makedirs(default_dir, exist_ok=True)
        self.last_save_dir = default_dir
        return default_dir

    def shutdown(self):
        """应用退出时统一收口后台资源，避免 adb/logcat/scrcpy 等子进程残留。"""
        self.log_service.log("DEBUG", "controller shutdown started")
        for model in (self.testing_model, self.advanced_model):
            shutdown = getattr(model, "shutdown", None)
            if callable(shutdown):
                shutdown()
        ProcessRunner.stop_all_tracked()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.log_service.log("DEBUG", "controller shutdown completed")
