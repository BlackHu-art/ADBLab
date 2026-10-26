"""提供 ADBController 的模型装配、结果分派和任务生命周期基础能力。"""

import os
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from controllers.model_dependencies import ControllerModelFactory
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
from models.device_store import DeviceStore
from services.apps.apk_selection import ApkFilePicker
from services.apps.install_batch import InstallBatchUseCase
from services.devices.device_batch import DeviceBatchUseCase
from services.devices.device_connection_lifecycle import DeviceConnectionLifecycle
from services.monkey_batch import MonkeyBatchCoordinator
from services.screen_record import ScreenRecordUseCase
from services.tasks.action_results import (
    ActionEnvelope,
    ActionResults,
    report_action_message,
)
from services.tasks.envelope import OperationMetadata, split_operation_metadata
from services.tasks.operations import OperationManager, OperationState


class _ADBControllerBase:
    """封装 ADBController 共用的模型、信号和处理器分派基础设施。"""

    def __init__(
        self, log_service: LogService, *, apk_picker: ApkFilePicker,
        device_lifecycle: DeviceConnectionLifecycle,
        model_factory: ControllerModelFactory,
        load_device_history: bool = True,
    ) -> None:
        """装配控制器；仅已完成历史加载的 GUI 组合根可显式跳过同步读取。"""
        self.apk_picker = apk_picker
        self.device_lifecycle = device_lifecycle
        self.signals = ADBControllerSignals()
        self.log_service = log_service
        self.action_results = ActionResults(self.signals.action_result_changed.emit)
        self._settings = AppSettings.instance()
        models = model_factory()
        self.device_model = models.device_model
        self.app_model = models.app_model
        self.testing_model = models.testing_model
        self.advanced_model = models.advanced_model
        self._pending_lock = threading.Lock()
        self._device_topology_lock = threading.Lock()
        self._device_topology_generation = 0
        self._device_topology: tuple[str, ...] = ()
        self._discovery_generation = 0
        self._discovery_refresh_pending = 0
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
        self.monkey_batches = MonkeyBatchCoordinator()
        self._monkey_lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._shutting_down = False
        self._build_handler_map()

        if load_device_history:
            try:
                DeviceStore.load()
            except Exception as e:
                # 加载失败保留已有快照，不输出可能携带用户路径的异常正文。
                self.log_service.log("ERROR", f"Failed to load DeviceStore: {type(e).__name__}")

    def _connect_model_signals(self):
        # command_finished 由各 model 在工作线程发出；此处不指定连接类型，
        # Qt 的 AutoConnection 会把 _handle_async_response 调度回 GUI 线程执行。
        self.device_model.command_finished.connect(self._handle_async_response)
        self.app_model.command_finished.connect(self._handle_async_response)
        self.testing_model.command_finished.connect(self._handle_async_response)
        self.advanced_model.command_finished.connect(self._handle_async_response)
        for model in (self.device_model, self.app_model, self.testing_model, self.advanced_model):
            model.action_progress.connect(self.action_results.progress)

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

    def _emit_operation(
        self, operation: str, success: bool, message: str, *, record_action: bool = True,
    ):
        """发布兼容反馈；批次摘要可只发信号与日志，避免归入最后一台设备的结果。"""
        if getattr(self, "_shutting_down", False):
            return
        level = "INFO" if success else "ERROR"
        if not message.strip():
            return
        has_result = record_action and report_action_message(success, message)
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
                ) if not has_result else None,
            ),
        )

    @staticmethod
    def _attempt_actions_preserving_first(
        *actions: tuple[str, Callable[[], object]],
    ) -> None:
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

    def _accepts_apk_selection(self) -> bool:
        """同步选框可能运行嵌套事件循环；返回后重检关闭许可再提交模型或批次。"""
        return not self._shutting_down and not self.action_results.closed

    def _require_devices(self, devices: list, op_name: str) -> bool:
        """校验设备列表；为空时发出失败结果并返回 False。"""
        if not devices:
            self._emit_operation(op_name, False, "⚠️ No devices selected")
            return False
        return True

    def device_discovery_token(self) -> tuple[int, int]:
        """为扫描捕获线程安全的代次；手动刷新在途时不接纳连续扫描结果。"""
        with self._device_topology_lock:
            return (
                getattr(self, "_discovery_generation", 0),
                getattr(self, "_discovery_refresh_pending", 0),
            )

    def _finish_device_discovery(self, request: int | None = None) -> bool:
        """按请求身份关闭一次准入区间，仅最新请求可以发布；无身份载荷保留旧调用兼容。"""
        with self._device_topology_lock:
            requests = getattr(self, "_discovery_requests", set())
            if request is not None and request not in requests:
                return False
            if request is None and requests:
                request = max(requests)
            if request is not None:
                requests.discard(request)
            self._discovery_generation = getattr(self, "_discovery_generation", 0) + 1
            self._discovery_refresh_pending = max(
                0, getattr(self, "_discovery_refresh_pending", 0) - 1,
            )
            return request is None or request == getattr(self, "_latest_discovery_request", None)


    def _complete_action_envelope(
        self, job, result: ActionEnvelope, method_name: str,
    ) -> None:
        """完成单个 ActionEnvelope；异常由调用方保证至少交付失败终态。"""
        payload, _metadata = split_operation_metadata(result.payload)
        payload, _perf = split_perf(payload)
        with self.action_results.scope(job.request_id, job):
            terminal = self._handle_async_response(method_name, result.payload)
        if isinstance(terminal, dict):
            if terminal.get("stale"):
                payload = terminal
        elif _metadata is not None:
            snapshot = getattr(terminal, "snapshot", terminal)
            if snapshot is None:
                snapshot = self.operation_manager.get(
                    _metadata.operation_id, expected_generation=_metadata.generation_token,
                )
            if snapshot is None:
                # 取消会先移除活动操作；晚到结果仍要按取消前的终态收口，
                # 不能把成功返回的单元误报成身份校验失败。
                snapshot = self.operation_manager.terminal(
                    _metadata.operation_id,
                    expected_generation=_metadata.generation_token,
                )
            unit = next((
                item for item in (snapshot.unit_results if snapshot is not None else ())
                if item.unit_id == _metadata.unit_id
            ), None)
            payload = dict(payload) if isinstance(payload, dict) else {}
            terminal_cancelled = (
                snapshot is not None and snapshot.state is OperationState.CANCELLED
            )
            payload.update(
                _validated_unit=True,
                success=unit is not None and unit.state is OperationState.SUCCEEDED,
                cancelled=(unit is not None and unit.state is OperationState.CANCELLED)
                or terminal_cancelled
                or bool(payload.get("cancelled")),
            )
            if not payload["success"]:
                if unit is not None:
                    payload["error"] = unit.message
                elif terminal_cancelled and snapshot is not None:
                    payload["error"] = snapshot.message or "操作已取消"
                else:
                    payload["error"] = "操作结果未通过身份校验或任务已结束"
        self.action_results.complete(job, payload)

    def _handle_async_response(self, method_name: str, result):
        """分派 model 线程经 Qt 队列回到 GUI 线程的 command_finished 结果。

        ActionEnvelope 先按请求身份拒收旧任务，带 OperationMetadata 的载荷再按 operation
        与 generation 校验；过期设备列表只按取消收尾，不发布拓扑。
        """
        if getattr(self, "_shutting_down", False):
            return
        if isinstance(result, ActionEnvelope):
            job = result.job
            if not self.action_results.accepts(job):
                return
            try:
                self._complete_action_envelope(job, result, method_name)
            except Exception as exc:
                # 分派/释放/所有权异常不能把请求留在 running；否则同 spec 的
                # 后续操作会被永久拒绝，且 running 请求不参与淘汰。
                self.log_service.log(
                    "ERROR",
                    f"[action-result] envelope dispatch failed: {type(exc).__name__}",
                )
                try:
                    self.action_results.complete(
                        job, {"success": False, "error": "操作结果分派失败"},
                    )
                except Exception as complete_error:
                    self.log_service.log(
                        "ERROR",
                        "[action-result] terminal fallback failed: "
                        f"{type(complete_error).__name__}",
                    )
            return
        result, operation_metadata = split_operation_metadata(result)
        result, perf = split_perf(result)
        op_type = method_name.replace("_async", "")
        ui_started_at = perf_counter()

        try:
            if operation_metadata is not None:
                return self._route_operation_response(op_type, result, operation_metadata)

            if op_type == "get_connected_devices":
                request = result.get("_discovery_request") if isinstance(result, dict) else None
                if not self._finish_device_discovery(request):
                    if isinstance(result, dict):
                        result.update(success=False, cancelled=True, stale=True)
                    return result
                if isinstance(result, dict) and result.get("stale"):
                    # 过期刷新在结果库按取消收尾，不能撤销更新列表建立的发现状态。
                    self.signals.device_refresh_superseded.emit()
                    return
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
        """应用关闭时统一收口资源；阻塞到 executor 与各 model 命令排空并核验进程归属。

        必须在关闭阶段的后台任务线程执行，不能从 GUI 线程调用。单个模型的清理失败不会
        跳过其他模型，最后统一抛出；返回不代表所有外部资源已确认退出。
        """
        self._shutting_down = True
        actions: list[tuple[str, Callable[[], object]]] = [
            ("action results close", self.action_results.close),
        ]
        for model in (
            self.device_model,
            self.app_model,
            self.testing_model,
            self.advanced_model,
        ):
            begin_shutdown = getattr(model, "begin_shutdown", None)
            if callable(begin_shutdown):
                actions.append((f"{type(model).__name__} begin_shutdown", begin_shutdown))
        for model in (self.testing_model, self.advanced_model):
            shutdown = getattr(model, "shutdown", None)
            if callable(shutdown):
                actions.append((f"{type(model).__name__} shutdown", shutdown))
        actions.append(("process runner stop", ProcessRunner.stop_all_tracked))
        actions.append((
            "controller executor shutdown",
            lambda: self.executor.shutdown(wait=True, cancel_futures=True),
        ))
        for model in (
            self.device_model, self.app_model, self.testing_model, self.advanced_model,
        ):
            wait = getattr(model, "wait_for_commands", None)
            if callable(wait):
                actions.append((f"{type(model).__name__} wait_for_commands", wait))
        # 等所有模型排空后再核验进程归属，失败不能跳过其它模型的等待与清理。
        for model in (self.device_model, self.testing_model):
            assert_cleanup_complete = getattr(model, "assert_cleanup_complete", None)
            if callable(assert_cleanup_complete):
                actions.append(("model cleanup verification", assert_cleanup_complete))
        self.log_service.log("DEBUG", "controller shutdown started")
        # 单一模型的关闭或等待失败不能中断后续进程与模型收口，最后统一抛出首个异常。
        self._attempt_actions_preserving_first(*actions)
        self.log_service.log("DEBUG", "controller shutdown completed")
