"""提供应用安装、卸载、清数据、重启与当前 Activity 查询的控制能力。"""

from __future__ import annotations

import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, cast

from PySide6.QtWidgets import QFileDialog

from adblab.application.device_batch import DeviceBatchStart, DeviceBatchUseCase
from adblab.application.envelope import OperationMetadata
from adblab.application.install_batch import (
    InstallBatchOutcome,
    InstallBatchStart,
    InstallBatchUseCase,
    InstallRequest,
    InstallUnit,
)
from adblab.application.operations import OperationState, OperationTransitionError
from controllers._base import _ADBControllerBase
from controllers.signals import ADBControllerSignals
from core.log_service import LogService
from models.adb_app import ADBApp


class _InstallOperationOwner:
    """标识只属于 Controller 安装 generation 的不透明所有权。"""

    __slots__ = ()


def _unit_for_device(start: DeviceBatchStart, device_ip: str):
    """返回批次中指定设备的执行单元；设备不在批次中时返回 None。"""
    for unit in start.units:
        if unit.device == device_ip:
            return unit
    return None


def _record_device_batch_result(controller, operation: str, device_ip: str, success: bool) -> str:
    """把无 envelope 的遗留批次结果记入 DeviceBatchUseCase，返回进度字符串。

    兼容 Gate C 之前的批次安装路径：结果不携带 operation 信封时，按批次标识在
    ``_batch_starts`` 中查找已登记的批次；全部单元收口后发射与旧 BatchOperationTracker
    相同的汇总信号。未登记批次时返回空进度。以模块级函数实现，兼容测试里的
    unbound 调用与 Mock 控制器。
    """
    with controller._pending_lock:
        start = controller._batch_starts.get(operation)
    if start is None:
        return ""
    unit = _unit_for_device(start, device_ip)
    if unit is not None:
        outcome = controller.device_batches.record_unit_result(unit.unit_id, device_ip, success)
        if outcome is not None:
            with controller._pending_lock:
                controller._batch_starts.pop(operation, None)
            controller._emit_operation(operation, outcome.success, outcome.message)
    return controller.device_batches.progress(start.operation_id)


class ADBAppInstallMixin(_ADBControllerBase):
    """协调应用安装、卸载、清数据、重启和当前 Activity 查询。"""

    # 以下属性由 _ADBControllerBase 提供。
    app_model: ADBApp
    signals: ADBControllerSignals
    log_service: LogService
    executor: ThreadPoolExecutor
    _batch_starts: dict
    device_batches: DeviceBatchUseCase
    install_batch_use_case: InstallBatchUseCase

    _handlers = {
        "uninstall_app": "_process_uninstall_apk_result",
        "clear_app_data": "_process_clear_app_data_result",
        "restart_app": "_process_restart_app_result",
        "get_current_activity": "_process_get_current_activity_result",
    }
    _operation_handlers = {
        "install_apk": "_process_install_operation_result",
    }

    # 应用安装与卸载

    def install_apk(self, devices: list) -> str | None:
        if not self._require_devices(devices, "install"):
            return None
        apk_path, _ = QFileDialog.getOpenFileName(
            getattr(self, "window_owner", None),
            "Select APK File",
            "",
            "APK Files (*.apk);;All Files (*)",
        )
        if not apk_path:
            self._emit_operation("install", False, "APK selection canceled")
            return None
        apk_name = os.path.basename(apk_path)
        return self._start_install_batch(
            "install",
            tuple(InstallRequest(device, apk_path, apk_name) for device in devices),
        )

    def batch_install_apk(self, devices: list) -> str | None:
        if not self._require_devices(devices, "batch_install"):
            return None
        apk_paths, _ = QFileDialog.getOpenFileNames(
            getattr(self, "window_owner", None),
            "Select APK files to install",
            "",
            "APK Files (*.apk);;All Files (*)",
        )
        if not apk_paths:
            self._emit_operation("batch_install", False, "APK selection canceled")
            return None
        requests = tuple(
            InstallRequest(device, apk_path, os.path.basename(apk_path))
            for apk_path in apk_paths
            for device in devices
        )
        return self._start_install_batch("batch_install", requests)

    def _start_install_batch(
        self,
        kind: str,
        requests: tuple[InstallRequest, ...],
        *,
        parent_operation_id: str | None = None,
    ) -> str:
        operation_id, ownership = self._reserve_install_start()
        try:
            started = self.install_batch_use_case.start(
                kind,
                requests,
                partial(self._submit_install_unit, owner_token=ownership),
                parent_operation_id=parent_operation_id,
                operation_id=operation_id,
                owner_token=ownership,
            )
        except Exception:
            self._discard_install_start(operation_id, ownership)
            raise
        operation_id = self._finish_install_start(started, ownership)
        self.log_service.log(
            "INFO",
            f"Queued {len(requests)} install task(s)",
            flush_immediately=True,
        )
        return operation_id

    def _reserve_install_start(self) -> tuple[str, object]:
        self._sweep_install_orphans()
        operation_id = self._generate_operation_id()
        manager_active = self.operation_manager.get(operation_id) is not None
        with self._install_terminal_lock:
            if (
                operation_id in self._install_owned_operations
                or operation_id in self._install_starting_operations
                or operation_id in self._install_result_callbacks
                or operation_id in self._install_deferred_terminals
                or manager_active
            ):
                raise OperationTransitionError(f"Duplicate operation id: {operation_id}")
            ownership = _InstallOperationOwner()
            self._install_owned_operations[operation_id] = ownership
            self._install_starting_operations.add(operation_id)
        return operation_id, ownership

    def _sweep_install_orphans(self) -> None:
        with self._install_terminal_lock:
            owned = tuple(self._install_owned_operations.items())
        for operation_id, ownership in owned:
            reconciled = self.install_batch_use_case.reconcile_inactive(
                operation_id,
                owner_token=ownership,
            )
            if not reconciled:
                continue
            with self._install_terminal_lock:
                if self._install_owned_operations.get(operation_id) is not ownership:
                    continue
                self._install_orphaned_operations[operation_id] = ownership
                if (
                    operation_id not in self._install_starting_operations
                    and operation_id not in self._install_result_callbacks
                    and operation_id not in self._install_deferred_terminals
                ):
                    self._install_owned_operations.pop(operation_id, None)
                    self._install_orphaned_operations.pop(operation_id, None)

    def _discard_install_start(self, operation_id: str, ownership: object) -> None:
        with self._install_terminal_lock:
            if self._install_owned_operations.get(operation_id) is not ownership:
                return
            self._install_owned_operations.pop(operation_id, None)
            self._install_starting_operations.discard(operation_id)
            self._install_deferred_terminals.pop(operation_id, None)
            self._install_orphaned_operations.pop(operation_id, None)

    def _submit_install_unit(
        self,
        operation_id: str,
        unit: InstallUnit,
        *,
        owner_token: object,
    ) -> None:
        operation = self.install_batch_use_case.active_snapshot(
            operation_id,
            owner_token=owner_token,
        )
        if operation is None:
            raise RuntimeError("Install operation is no longer active")
        request = unit.request
        legacy_operation = "install" if operation.kind == "install" else "batch_install"
        self.log_service.log(
            "INFO",
            f"Starting install task {unit.index}/{len(operation.unit_ids)}",
        )
        cast(Any, self.app_model).install_apk_async(
            request.device_id,
            request.apk_path,
            request.apk_name,
            unit.index,
            legacy_operation,
            _operation_id=operation_id,
            _operation_kind=operation.kind,
            _operation_task_id=unit.unit_id,
            _operation_unit_id=unit.unit_id,
            _operation_target_id=request.device_id,
            _operation_owner_token=owner_token,
            _operation_generation_token=operation.generation_token,
        )

    def _claim_operation_response(
        self,
        op_type: str,
        metadata: OperationMetadata,
    ) -> tuple[bool, object | None]:
        metadata_owner = metadata.owner_token
        install_marked = (
            isinstance(metadata_owner, _InstallOperationOwner)
            or op_type == "install_apk"
            or metadata.method_name == "install_apk"
            or metadata.operation_kind in {"install", "batch_install"}
        )
        with self._install_terminal_lock:
            ownership = self._install_owned_operations.get(metadata.operation_id)
            if ownership is not None and (
                metadata_owner is None or metadata_owner is not ownership
            ):
                accepted = False
            elif ownership is not None:
                accepted = True
                self._install_result_callbacks[metadata.operation_id] = (
                    self._install_result_callbacks.get(metadata.operation_id, 0) + 1
                )
            elif install_marked:
                accepted = False
            else:
                accepted = None
        if accepted is None:
            return super()._claim_operation_response(op_type, metadata)
        if not accepted:
            self.log_service.log(
                "DEBUG",
                "[install] Ignored stale generation result",
            )
            return False, None
        return True, ownership

    def _operation_metadata_matches(
        self,
        op_type: str,
        metadata: OperationMetadata,
        snapshot,
        response_claim: object | None,
    ) -> bool:
        if response_claim is not None and op_type != "install_apk":
            return False
        if (
            response_claim is not None
            and metadata.generation_token is not snapshot.generation_token
        ):
            return False
        return super()._operation_metadata_matches(
            op_type,
            metadata,
            snapshot,
            response_claim,
        )

    def _release_operation_response(
        self,
        op_type: str,
        metadata: OperationMetadata,
        response_claim: object | None,
        terminal,
    ) -> None:
        if response_claim is not None:
            reconciled = False
            if terminal is None:
                reconciled = self.install_batch_use_case.reconcile_inactive(
                    metadata.operation_id,
                    owner_token=response_claim,
                )
            self._finish_install_result_callback(
                metadata.operation_id,
                terminal,
                response_claim,
                release_orphan=reconciled,
            )
            return
        super()._release_operation_response(
            op_type,
            metadata,
            response_claim,
            terminal,
        )

    def _fail_claimed_operation_protocol(
        self,
        snapshot,
        message: str,
        op_type: str,
        metadata: OperationMetadata,
        response_claim: object | None,
    ):
        if response_claim is not None:
            return self.install_batch_use_case.fail(
                snapshot.operation_id,
                message,
                owner_token=response_claim,
            )
        return super()._fail_claimed_operation_protocol(
            snapshot,
            message,
            op_type,
            metadata,
            response_claim,
        )

    def _invoke_operation_handler(
        self,
        handler,
        op_type: str,
        result,
        metadata: OperationMetadata,
        response_claim: object | None,
    ):
        if op_type == "install_apk" and response_claim is not None:
            return handler(result, metadata, ownership=response_claim)
        return super()._invoke_operation_handler(
            handler,
            op_type,
            result,
            metadata,
            response_claim,
        )

    def _process_install_operation_result(
        self,
        result,
        metadata: OperationMetadata,
        *,
        ownership: object | None = None,
    ) -> InstallBatchOutcome | None:
        operation_id = metadata.operation_id
        claimed_here = ownership is None
        if claimed_here:
            accepted, ownership = self._claim_operation_response("install_apk", metadata)
            if not accepted or ownership is None:
                return None
        terminal = None
        try:
            unit = self.install_batch_use_case.active_unit(
                operation_id,
                metadata.unit_id or "",
                owner_token=ownership,
            )
            if unit is None:
                terminal = self.install_batch_use_case.fail(
                    operation_id,
                    "Install task identity mismatch",
                    owner_token=ownership,
                )
                return terminal
            snapshot = self.install_batch_use_case.active_snapshot(
                operation_id,
                owner_token=ownership,
            )
            if snapshot is None:
                return None
            if any(result.unit_id == unit.unit_id for result in snapshot.unit_results):
                self.log_service.log("DEBUG", "[install] Duplicate result ignored")
                return None
            request = unit.request
            valid_identity = (
                metadata.task_id == metadata.unit_id == unit.unit_id
                and metadata.target_id == request.device_id
                and isinstance(result, dict)
                and result.get("device_ip") == request.device_id
                and result.get("apk_path") == request.apk_path
                and result.get("apk_name") == request.apk_name
            )
            if not valid_identity:
                terminal = self.install_batch_use_case.fail(
                    operation_id,
                    "Install result identity mismatch",
                    owner_token=ownership,
                )
                return terminal

            succeeded = result.get("success") is True
            message = (
                "Install succeeded" if succeeded else str(result.get("error", "Install failed"))
            )
            terminal = self.install_batch_use_case.complete(
                operation_id,
                unit.unit_id,
                succeeded=succeeded,
                message=message,
                owner_token=ownership,
            )
            return terminal
        finally:
            if claimed_here:
                self._release_operation_response(
                    "install_apk",
                    metadata,
                    ownership,
                    terminal,
                )

    def _finish_install_result_callback(
        self,
        operation_id: str,
        terminal: InstallBatchOutcome | None,
        ownership: object,
        *,
        release_orphan: bool = False,
    ) -> None:
        emit_terminal = None
        with self._install_terminal_lock:
            if self._install_owned_operations.get(operation_id) is not ownership:
                return
            if terminal is not None:
                self._install_deferred_terminals[operation_id] = terminal
            if release_orphan:
                self._install_orphaned_operations[operation_id] = ownership
            remaining = self._install_result_callbacks.get(operation_id, 1) - 1
            if remaining > 0:
                self._install_result_callbacks[operation_id] = remaining
            else:
                self._install_result_callbacks.pop(operation_id, None)
                if operation_id not in self._install_starting_operations:
                    emit_terminal = self._install_deferred_terminals.pop(
                        operation_id,
                        None,
                    )
                    orphaned = self._install_orphaned_operations.get(operation_id) is ownership
                    if emit_terminal is None and orphaned:
                        self._install_owned_operations.pop(operation_id, None)
                        self._install_orphaned_operations.pop(operation_id, None)
        if emit_terminal is not None:
            self._emit_owned_install_terminal(emit_terminal, ownership)

    def _finish_install_start(self, started: InstallBatchStart, ownership: object) -> str:
        emit_terminal = None
        with self._install_terminal_lock:
            operation_id = started.operation_id
            if self._install_owned_operations.get(operation_id) is not ownership:
                raise OperationTransitionError(
                    f"Install operation ownership changed: {operation_id}"
                )
            self._install_starting_operations.discard(operation_id)
            if started.terminal is not None:
                self._install_deferred_terminals[operation_id] = started.terminal
            if operation_id not in self._install_result_callbacks:
                emit_terminal = self._install_deferred_terminals.pop(operation_id, None)
                if (
                    emit_terminal is None
                    and self._install_orphaned_operations.get(operation_id) is ownership
                ):
                    self._install_owned_operations.pop(operation_id, None)
                    self._install_orphaned_operations.pop(operation_id, None)
        if emit_terminal is not None:
            self._emit_owned_install_terminal(emit_terminal, ownership)
        return started.operation_id

    def _fail_install_operation(
        self,
        operation_id: str,
        message: str,
        *,
        ownership: object,
    ) -> InstallBatchOutcome | None:
        terminal = self.install_batch_use_case.fail(
            operation_id,
            message,
            owner_token=ownership,
        )
        self._publish_install_terminal(terminal, ownership)
        return terminal

    def _publish_install_terminal(
        self,
        terminal: InstallBatchOutcome | None,
        ownership: object | None,
    ) -> None:
        if terminal is None or ownership is None:
            return
        emit_terminal = None
        operation_id = terminal.snapshot.operation_id
        with self._install_terminal_lock:
            if self._install_owned_operations.get(operation_id) is not ownership:
                return
            if (
                operation_id in self._install_starting_operations
                or operation_id in self._install_result_callbacks
            ):
                self._install_deferred_terminals[operation_id] = terminal
            else:
                emit_terminal = terminal
        if emit_terminal is not None:
            self._emit_owned_install_terminal(emit_terminal, ownership)

    def _emit_owned_install_terminal(
        self,
        outcome: InstallBatchOutcome,
        ownership: object,
    ) -> None:
        operation_id = outcome.snapshot.operation_id
        try:
            self._emit_install_terminal(outcome)
        finally:
            with self._install_terminal_lock:
                if self._install_owned_operations.get(operation_id) is ownership:
                    self._install_owned_operations.pop(operation_id, None)
                    self._install_starting_operations.discard(operation_id)
                    self._install_deferred_terminals.pop(operation_id, None)
                    self._install_orphaned_operations.pop(operation_id, None)

    def cancel_install_batch(self, operation_id: str) -> bool:
        with self._install_terminal_lock:
            ownership = self._install_owned_operations.get(operation_id)
        if ownership is None:
            return False
        accepted, terminal = self.install_batch_use_case.cancel_owned(
            operation_id,
            owner_token=ownership,
        )
        if not accepted:
            return False
        self._publish_install_terminal(terminal, ownership)
        return True

    def retry_failed_install_batch(
        self,
        outcome: InstallBatchOutcome,
    ) -> str | None:
        operation_id, ownership = self._reserve_install_start()
        try:
            started = self.install_batch_use_case.retry_failed(
                outcome,
                partial(self._submit_install_unit, owner_token=ownership),
                operation_id=operation_id,
                owner_token=ownership,
            )
        except Exception:
            self._discard_install_start(operation_id, ownership)
            raise
        if started is None:
            self._discard_install_start(operation_id, ownership)
            return None
        return self._finish_install_start(started, ownership)

    def _fail_operation_protocol(self, snapshot, message: str):
        if snapshot.kind in {"install", "batch_install"}:
            accepted, ownership, terminal = self.install_batch_use_case.fail_snapshot(
                snapshot,
                message,
            )
            if not accepted:
                return None
            self._publish_install_terminal(terminal, ownership)
            return terminal
        return super()._fail_operation_protocol(snapshot, message)

    def _emit_install_terminal(self, outcome: InstallBatchOutcome) -> None:
        terminal = outcome.snapshot
        counts = Counter(result.state for result in terminal.unit_results)
        total = len(outcome.units)
        succeeded = counts[OperationState.SUCCEEDED]
        cancelled = counts[OperationState.CANCELLED]
        failed = max(
            counts[OperationState.FAILED],
            total - succeeded - cancelled,
        )
        label = "Install" if terminal.kind == "install" else "Batch Install"
        message = (
            f"{label} completed: {succeeded}/{total} succeeded, "
            f"{failed} failed, {cancelled} cancelled"
        )
        self._attempt_actions_preserving_first(
            (
                "install terminal completion",
                lambda: self._emit_operation(
                    terminal.kind,
                    terminal.state is OperationState.SUCCEEDED,
                    message,
                ),
            ),
            (
                "install terminal debug log",
                lambda: self.log_service.log(
                    "DEBUG",
                    (
                        f"[{terminal.kind}] operation finished: "
                        f"state={terminal.state.value} total={total} "
                        f"succeeded={succeeded} failed={failed} cancelled={cancelled}"
                    ),
                ),
            ),
        )

    def _reject_concurrent_batch(self, operation: str) -> bool:
        """同类批次尚未收口时拒绝新批次，避免 _batch_starts 按操作名覆盖导致结果串台。"""

        with self._pending_lock:
            start = self._batch_starts.get(operation)
        if start is not None and self.device_batches.active_start(start.operation_id) is not None:
            self._emit_operation(
                operation, False, f"Another {operation} batch is already in progress"
            )
            return True
        return False

    def uninstall_apk(self, devices: list, package_name: str):
        if not self._require_devices(devices, "uninstall"):
            return
        if not package_name:
            self._emit_operation("uninstall", False, "⚠️ No package name provided")
            return
        if self._reject_concurrent_batch("uninstall"):
            return
        start = self.device_batches.start("uninstall", devices, label="Uninstall App")
        with self._pending_lock:
            self._batch_starts["uninstall"] = start
        for idx, device_ip in enumerate(devices, 1):
            self._execute_uninstall_task(idx, device_ip, package_name)

    def _execute_uninstall_task(self, idx: int, device_ip: str, package_name: str):
        with self._pending_lock:
            start = self._batch_starts.get("uninstall")
        total = len(start.units) if start else "?"
        self._emit_operation(
            "uninstall", True, f"Start uninstall ({idx}/{total}) {package_name} on {device_ip} ..."
        )
        self.app_model.uninstall_app_async(device_ip, package_name, idx)

    def _process_uninstall_apk_result(self, result: dict):
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        success = result.get("success")
        progress = _record_device_batch_result(self, "uninstall", str(ip), bool(success))
        if success:
            self._emit_operation(
                "uninstall", True, f"✅ uninstall success {progress} {pkg} on {ip}"
            )
        else:
            self._emit_operation(
                "uninstall", False, f"❌ uninstall failed {progress} {pkg} on {ip}"
            )

    def clear_app_data(self, devices: list, package_name: str):
        if not self._require_devices(devices, "clear_data"):
            return
        if not package_name:
            self._emit_operation("clear_data", False, "⚠️ No package name provided")
            return
        if self._reject_concurrent_batch("clear_data"):
            return
        start = self.device_batches.start("clear_data", devices, label="Clear App Data")
        with self._pending_lock:
            self._batch_starts["clear_data"] = start
        for idx, device_ip in enumerate(devices, 1):
            self._emit_operation(
                "clear_data",
                True,
                f"Start clear data ({idx}/{len(devices)}) {package_name} on {device_ip} ...",
            )
            self.app_model.clear_app_data_async(device_ip, package_name, idx)

    def _process_clear_app_data_result(self, result: dict):
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        success = result.get("success")
        progress = _record_device_batch_result(self, "clear_data", str(ip), bool(success))
        if success:
            self._emit_operation(
                "clear_data", True, f"✅ clear data success {progress} {pkg} on {ip}"
            )
        else:
            self._emit_operation(
                "clear_data", False, f"❌ clear data failed {progress} {pkg} on {ip}"
            )

    def restart_app(self, devices: list, package_name: str):
        if not self._require_devices(devices, "restart_app"):
            return
        if not package_name:
            self._emit_operation("restart_app", False, "⚠️ No package name provided")
            return
        if self._reject_concurrent_batch("restart_app"):
            return
        start = self.device_batches.start("restart_app", devices, label="Restart App")
        with self._pending_lock:
            self._batch_starts["restart_app"] = start
        for idx, device_ip in enumerate(devices, 1):
            self._emit_operation(
                "restart_app",
                True,
                f"Start restart ({idx}/{len(devices)}) {package_name} on {device_ip} ...",
            )
            self.app_model.restart_app_async(device_ip, package_name, idx)

    def _process_restart_app_result(self, result: dict):
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        output = result.get("output", "").strip()
        success = result.get("success")
        progress = _record_device_batch_result(self, "restart_app", str(ip), bool(success))
        if success:
            msg = (
                f"✅ Restart Success {progress}\n"
                f"   📦 Package : {pkg}\n   🌐 Device  : {ip}\n"
                f"   📤 Output  :\n{self._indent_output(output)}"
            )
            self._emit_operation("restart_app", True, msg)
        else:
            msg = (
                f"❌ Restart Failed {progress}\n"
                f"   📦 Package : {pkg}\n   🌐 Device  : {ip}\n"
                f"   ⚠️ Error   :\n{self._indent_output(output)}"
            )
            self._emit_operation("restart_app", False, msg)

    def get_current_activity(self, devices: list[str]):
        if not devices:
            self._emit_operation("current_activity", False, "⚠️ No device selected")
            return
        if self._reject_concurrent_batch("current_activity"):
            return
        start = self.device_batches.start("current_activity", devices, label="Activity Info")
        with self._pending_lock:
            self._batch_starts["current_activity"] = start
        for idx, device_ip in enumerate(devices, 1):
            self._emit_operation(
                "current_activity",
                True,
                f"Start activity info ({idx}/{len(devices)}) on {device_ip} ...",
            )
            self.app_model.get_current_activity_async(device_ip, idx)

    def _process_get_current_activity_result(self, result: dict):
        device = result.get("device_ip", "unknown")
        idx = result.get("index", 0)
        success = result.get("success", False)
        focus = result.get("current_focus", "").strip()
        resumed = result.get("resumed_activity", "").strip()
        error = result.get("error", "").strip()
        progress = _record_device_batch_result(self, "current_activity", str(device), bool(success))
        if success:
            msg_lines = [f"📱 ({idx}) {device} {progress} - Activity Info"]
            if focus:
                msg_lines.append(f"   🔍 Current Focus   :\n{self._indent_output(focus)}")
            else:
                msg_lines.append("   ⚠️  No mCurrentFocus found")
            if resumed:
                msg_lines.append(f"   🎯 Resumed Activity:\n{self._indent_output(resumed)}")
            else:
                msg_lines.append("   ⚠️  No mResumedActivity found")
            self._emit_operation("current_activity", True, "\n".join(msg_lines))
        else:
            msg = (
                f"❌ Failed to get activity on ({idx}) {device} {progress}"
                f"\n{self._indent_output(error)}"
            )
            self._emit_operation("current_activity", False, msg)
