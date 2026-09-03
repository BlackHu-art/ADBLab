"""提供 ADBController 的模型装配、结果分派和任务生命周期基础能力。"""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from adblab.application.device_batch import DeviceBatchUseCase
from adblab.application.envelope import OperationMetadata, split_operation_metadata
from adblab.application.install_batch import InstallBatchUseCase
from adblab.application.operations import OperationManager, OperationState
from adblab.application.screen_record import ScreenRecordUseCase
from controllers.signals import ADBControllerSignals
from core.exec import ProcessRunner
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
from models.adb_advanced import ADBAdvanced
from models.adb_app import ADBApp
from models.adb_device import ADBDevice
from models.adb_testing import ADBTesting
from models.device_store import DeviceStore


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
        self._pending_lock = threading.Lock()
        self._device_topology_lock = threading.Lock()
        self._device_topology_generation = 0
        self._device_topology: tuple[str, ...] = ()
        self.operation_manager = OperationManager()
        self.install_batch_use_case = InstallBatchUseCase(
            self.operation_manager,
            id_factory=self._generate_operation_id,
        )
        self.device_batches = DeviceBatchUseCase(
            self.operation_manager,
            id_factory=self._generate_operation_id,
        )
        self.screen_records = ScreenRecordUseCase()
        self._batch_starts = {}
        self._install_terminal_lock = threading.RLock()
        self._install_owned_operations = {}
        self._install_starting_operations = set()
        self._install_result_callbacks = {}
        self._install_deferred_terminals = {}
        self._install_orphaned_operations = {}
        self._connect_model_signals()
        # 由界面组装根注入，只负责生命周期托管，不建立 Qt 原生父子关系。
        self.window_owner = None
        self.last_save_dir = None
        self._active_viewers = []
        self._monkey_running = set()
        self._monkey_lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._shutting_down = False
        self._build_handler_map()

        try:
            DeviceStore.load()
        except Exception as e:
            # load 失败时 DeviceStore 内部已保留内存快照并记录原因，
            # 这里只补一条控制器可见日志，不再清空设备列表。
            self.log_service.log("ERROR", f"Failed to load DeviceStore: {str(e)}")

    def _connect_model_signals(self):
        # command_finished 由各 model 在工作线程发出；此处不指定连接类型，
        # Qt 的 AutoConnection 会把 _handle_async_response 调度回 GUI 线程执行。
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

    def _emit_operation(self, operation: str, success: bool, message: str):
        if getattr(self, "_shutting_down", False):
            return
        level = "INFO" if success else "ERROR"
        if not message.strip():
            return
        self._attempt_actions_preserving_first(
            (
                "operation completion signal",
                lambda: self.signals.operation_completed.emit(operation, success, message),
            ),
            (
                "operation completion log",
                # 用户点击后的完成态日志要立即进入界面，避免再叠加 200ms 批量刷新延迟。
                lambda: self.log_service.log(
                    level,
                    f"{message}",
                    flush_immediately=True,
                ),
            ),
        )

    @staticmethod
    def _attempt_actions_preserving_first(*actions) -> None:
        """依次尝试所有动作，并在最后传播第一个异常。"""

        first_error = None
        for label, action in actions:
            try:
                action()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                else:
                    first_error.add_note(f"{label} also failed: {type(exc).__name__}: {exc}")
        if first_error is not None:
            raise first_error

    def _require_devices(self, devices: list, op_name: str) -> bool:
        """校验设备列表；为空时发出失败结果并返回 False。"""
        if not devices:
            self._emit_operation(op_name, False, "⚠️ No devices selected")
            return False
        return True

    def _handle_async_response(self, method_name: str, result):
        if getattr(self, "_shutting_down", False):
            return
        result, operation_metadata = split_operation_metadata(result)
        result, perf = split_perf(result)
        op_type = method_name.replace("_async", "")
        ui_started_at = perf_counter()

        try:
            if operation_metadata is not None:
                self._route_operation_response(op_type, result, operation_metadata)
                return

            if op_type == "get_connected_devices":
                if isinstance(result, dict) and "devices" in result:
                    if result.get("success", False):
                        getattr(self, "_process_device_list")(result["devices"])
                    else:
                        self._emit_operation(
                            "refresh",
                            False,
                            result.get("error", "Failed to list devices"),
                        )
                else:
                    self._emit_operation("refresh", False, "Invalid device list format")
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
        except Exception as e:
            self.log_service.log("ERROR", f"[{op_type}] Response routing error: {str(e)}")
            self._emit_operation(op_type, False, f"Response routing error: {str(e)}")
        finally:
            self._log_perf_if_slow(op_type, perf, ui_started_at, perf_counter())

    def _route_operation_response(
        self,
        op_type: str,
        result,
        metadata: OperationMetadata,
    ):
        accepted, response_claim = self._claim_operation_response(op_type, metadata)
        if not accepted:
            return None
        terminal = None
        route_error = None
        try:
            snapshot = self.operation_manager.get(
                metadata.operation_id,
                expected_generation=metadata.generation_token,
            )
            if snapshot is None:
                self.log_service.log(
                    "DEBUG",
                    f"[{op_type}] Ignored stale operation result",
                )
                return None
            if not self._operation_metadata_matches(
                op_type,
                metadata,
                snapshot,
                response_claim,
            ):

                def fail_metadata_mismatch():
                    nonlocal terminal
                    terminal = self._fail_claimed_operation_protocol(
                        snapshot,
                        "Operation metadata mismatch",
                        op_type,
                        metadata,
                        response_claim,
                    )

                self._attempt_actions_preserving_first(
                    ("operation protocol failure", fail_metadata_mismatch),
                    (
                        "operation metadata mismatch log",
                        lambda: self.log_service.log(
                            "ERROR",
                            f"[{op_type}] Operation metadata mismatch",
                        ),
                    ),
                )
                return terminal
            operation_handler = self._operation_handler_map.get(op_type)
            if operation_handler is None:

                def fail_missing_handler():
                    nonlocal terminal
                    terminal = self._fail_claimed_operation_protocol(
                        snapshot,
                        "Operation handler missing",
                        op_type,
                        metadata,
                        response_claim,
                    )

                self._attempt_actions_preserving_first(
                    ("operation protocol failure", fail_missing_handler),
                    (
                        "missing operation handler log",
                        lambda: self.log_service.log(
                            "ERROR",
                            f"[{op_type}] No vNext operation handler registered",
                        ),
                    ),
                )
                return terminal
            try:
                terminal = self._invoke_operation_handler(
                    operation_handler,
                    op_type,
                    result,
                    metadata,
                    response_claim,
                )
            except Exception as handler_error:
                handler_error_name = type(handler_error).__name__

                def fail_handler_error():
                    nonlocal terminal
                    current = self.operation_manager.get(
                        metadata.operation_id,
                        expected_generation=metadata.generation_token,
                    )
                    terminal = (
                        self._fail_claimed_operation_protocol(
                            current,
                            "Operation handler failed",
                            op_type,
                            metadata,
                            response_claim,
                        )
                        if current is not None
                        else None
                    )

                self._attempt_actions_preserving_first(
                    ("operation handler protocol failure", fail_handler_error),
                    (
                        "operation handler error log",
                        lambda: self.log_service.log(
                            "ERROR",
                            f"[{op_type}] Operation handler error: {handler_error_name}",
                        ),
                    ),
                )
                if terminal is None:
                    self.log_service.log(
                        "DEBUG",
                        f"[{op_type}] Operation already terminal after handler error",
                    )
            return terminal
        except Exception as exc:
            route_error = exc
            raise
        finally:
            try:
                self._release_operation_response(
                    op_type,
                    metadata,
                    response_claim,
                    terminal,
                )
            except Exception as release_error:
                if route_error is None:
                    raise
                route_error.add_note(
                    "operation response release also failed: "
                    f"{type(release_error).__name__}: {release_error}"
                )

    def _claim_operation_response(
        self,
        op_type: str,
        metadata: OperationMetadata,
    ) -> tuple[bool, object | None]:
        return True, None

    def _release_operation_response(
        self,
        op_type: str,
        metadata: OperationMetadata,
        response_claim: object | None,
        terminal,
    ) -> None:
        return None

    def _operation_metadata_matches(
        self,
        op_type: str,
        metadata: OperationMetadata,
        snapshot,
        response_claim: object | None,
    ) -> bool:
        return (
            metadata.method_name == op_type
            and metadata.operation_kind == snapshot.kind
            and (
                metadata.generation_token is None
                or metadata.generation_token is snapshot.generation_token
            )
        )

    def _fail_claimed_operation_protocol(
        self,
        snapshot,
        message: str,
        op_type: str,
        metadata: OperationMetadata,
        response_claim: object | None,
    ):
        return self._fail_operation_protocol(snapshot, message)

    def _invoke_operation_handler(
        self,
        handler,
        op_type: str,
        result,
        metadata: OperationMetadata,
        response_claim: object | None,
    ):
        return handler(result, metadata)

    def _fail_operation_protocol(self, snapshot, message: str):
        return self.operation_manager.finish(
            snapshot.operation_id,
            OperationState.FAILED,
            message=message,
            expected_kind=snapshot.kind,
            expected_generation=snapshot.generation_token,
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
        self._shutting_down = True
        for model in (
            self.device_model,
            self.app_model,
            self.testing_model,
            self.advanced_model,
        ):
            begin_shutdown = getattr(model, "begin_shutdown", None)
            if callable(begin_shutdown):
                begin_shutdown()
        self.log_service.log("DEBUG", "controller shutdown started")
        for model in (self.testing_model, self.advanced_model):
            shutdown = getattr(model, "shutdown", None)
            if callable(shutdown):
                shutdown()
        ProcessRunner.stop_all_tracked()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.log_service.log("DEBUG", "controller shutdown completed")
