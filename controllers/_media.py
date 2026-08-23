"""提供截图、录屏和设备诊断信息采集的控制能力。"""

from __future__ import annotations

import os
import re
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, cast

from PySide6.QtCore import Qt, QTimer

from adblab.application.envelope import OperationMetadata
from adblab.application.operations import (
    OperationArtifact,
    OperationSnapshot,
    OperationState,
    OperationUnitResult,
)
from controllers._base import _ADBControllerBase
from controllers.signals import ADBControllerSignals
from core.log_service import LogService
from gui.dialogs.lifecycle import (
    configure_independent_secondary_window,
    fit_secondary_window_to_owner_screen,
)
from gui.dialogs.screenshot_viewer import ScreenshotViewer
from models.adb_advanced import ADBAdvanced
from models.adb_testing import ADBTesting
from utils.adb_values import normalize_android_package, truncate_diagnostic_output


def _emit_readonly_diagnostic_result(
    controller,
    result: dict,
    *,
    operation: str,
    label: str,
    max_lines: int,
) -> None:
    """把固定命令的结果裁剪后发布到可见操作日志。"""

    ip = result.get("device_ip", "")
    if not result.get("success"):
        controller._emit_operation(
            operation,
            False,
            f"{label} failed on {ip}: {result.get('error')}",
        )
        return
    output, truncated = truncate_diagnostic_output(
        result.get("output", ""),
        max_lines=max_lines,
    )
    suffix = " [truncated]" if truncated else ""
    controller._emit_operation(
        operation,
        True,
        f"{label} ({ip}){suffix}:\n{output}",
    )


def _emit_record_target_finished(controller, batch_id: str, device: str) -> None:
    """发布带批次标识的录屏终态，并保留旧兼容通知。"""

    target_signal = getattr(getattr(controller, "signals", None), "record_target_finished", None)
    if target_signal is not None:
        target_signal.emit(batch_id, device)
    legacy_signal = getattr(getattr(controller, "signals", None), "record_finished", None)
    if legacy_signal is not None:
        legacy_signal.emit()


class ADBMediaMixin(_ADBControllerBase):
    """协调截图、录屏、dumpsys、电池、Logcat、进程和运行时长操作。"""

    # 以下属性由 _ADBControllerBase 提供。
    testing_model: ADBTesting
    advanced_model: ADBAdvanced
    signals: ADBControllerSignals
    log_service: LogService
    executor: ThreadPoolExecutor
    _active_viewers: list
    last_save_dir: str | None

    _handlers = {
        "start_screen_record": "_process_start_screen_record_result",
        "stop_screen_record": "_process_stop_screen_record_result",
        "pull_recorded_video": "_process_pull_recorded_video_result",
        "dumpsys_meminfo": "_process_dumpsys_meminfo_result",
        "dumpsys_cpuinfo": "_process_dumpsys_cpuinfo_result",
        "dumpsys_battery": "_process_dumpsys_battery_result",
        "top_snapshot": "_process_top_snapshot_result",
        "gfxinfo": "_process_gfxinfo_result",
        "wakelocks": "_process_wakelocks_result",
        "netstats_detail": "_process_netstats_detail_result",
        "battery_set_level": "_process_battery_set_level_result",
        "battery_set_status": "_process_battery_set_status_result",
        "battery_reset": "_process_battery_reset_result",
        "logcat_filtered": "_process_logcat_filtered_result",
        "list_processes": "_process_list_processes_result",
        "kill_process": "_process_kill_process_result",
        "get_device_uptime": "_process_get_device_uptime_result",
    }
    _operation_handlers = {
        "take_screenshot": "_process_screenshot_operation_result",
    }

    # 截图

    def take_screenshot(self, devices: list) -> str | None:
        valid = tuple(dict.fromkeys(device for device in devices if device))
        if not valid:
            self._emit_operation("screenshot", False, "⚠️ No devices selected")
            return None
        try:
            screenshot_dir = self._get_screenshot_dir()
        except Exception:
            self._emit_operation(
                "screenshot",
                False,
                "Unable to prepare screenshot directory",
            )
            return None

        operation_id = self._generate_operation_id()
        tasks = [
            (
                self._generate_operation_id(),
                device,
                self._screenshot_path(screenshot_dir, device),
            )
            for device in valid
        ]
        operation = self.operation_manager.begin(
            "screenshot",
            operation_id=operation_id,
            unit_ids=(task_id for task_id, _device, _path in tasks),
        )
        running = self.operation_manager.mark_running(
            operation.operation_id,
            expected_kind=operation.kind,
            expected_generation=operation.generation_token,
        )
        if running is None:
            return operation.operation_id
        self.log_service.log(
            "DEBUG",
            f"[screenshot] operation started: target_count={len(tasks)}",
        )
        self.log_service.log(
            "INFO",
            f"Capturing screenshots for {len(tasks)} selected target(s)",
            flush_immediately=True,
        )
        for task_id, device, save_path in tasks:
            try:
                self._start_screenshot_process(
                    device,
                    save_path,
                    operation.operation_id,
                    task_id,
                    operation.generation_token,
                )
            except Exception:
                self.log_service.log(
                    "ERROR",
                    "[screenshot] Failed to queue one capture task",
                )
                self.operation_manager.record_unit_result(
                    operation.operation_id,
                    OperationUnitResult(
                        task_id,
                        OperationState.FAILED,
                        "Screenshot task submission failed",
                    ),
                    expected_kind=operation.kind,
                    expected_generation=operation.generation_token,
                )
        self._finish_screenshot_if_complete(
            operation.operation_id,
            operation.generation_token,
        )
        return operation.operation_id

    def _screenshot_path(self, save_dir: str, device_ip: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        device_name = re.sub(r"\W+", "_", device_ip).strip("_") or "device"
        filename_stem = f"{device_name}_{timestamp}"

        # 同一秒内连续截图时追加简短序号，避免覆盖已有或尚未落盘的截图。
        if getattr(self, "_screenshot_name_timestamp", None) != timestamp:
            self._screenshot_name_timestamp = timestamp
            self._allocated_screenshot_paths = set()
        allocated_paths = self._allocated_screenshot_paths

        sequence = 1
        while True:
            suffix = "" if sequence == 1 else f"_{sequence}"
            path = os.path.normpath(os.path.join(save_dir, f"{filename_stem}{suffix}.png"))
            path_key = os.path.normcase(os.path.abspath(path))
            if path_key not in allocated_paths and not os.path.exists(path):
                allocated_paths.add(path_key)
                return path
            sequence += 1

    def _start_screenshot_process(
        self,
        device_ip: str,
        save_path: str,
        operation_id: str,
        task_id: str,
        generation_token: object,
    ):
        cast(Any, self.testing_model).take_screenshot_async(
            device_ip,
            save_path,
            _operation_id=operation_id,
            _operation_kind="screenshot",
            _operation_task_id=task_id,
            _operation_unit_id=task_id,
            _operation_target_id=device_ip,
            _operation_expected_artifact_path=save_path,
            _operation_generation_token=generation_token,
        )

    def _process_screenshot_operation_result(
        self,
        result,
        metadata: OperationMetadata,
    ) -> OperationSnapshot | None:
        operation_id = metadata.operation_id
        snapshot = self.operation_manager.get(
            operation_id,
            expected_kind="screenshot",
            expected_generation=metadata.generation_token,
        )
        if snapshot is None:
            return None
        task_id = metadata.unit_id
        if not task_id or task_id != metadata.task_id:
            return self._fail_screenshot_operation(
                operation_id,
                "Screenshot task identity mismatch",
                expected_generation=metadata.generation_token,
            )
        if any(item.unit_id == task_id for item in snapshot.unit_results):
            self.log_service.log("DEBUG", "[screenshot] Duplicate result ignored")
            return None

        valid, message, path = self._classify_screenshot_result(result, metadata)
        unit_state = OperationState.SUCCEEDED if valid else OperationState.FAILED
        if valid and path:
            if any(artifact.path == path for artifact in snapshot.artifacts):
                return self._fail_screenshot_operation(
                    operation_id,
                    "Screenshot artifact identity conflict",
                    expected_generation=metadata.generation_token,
                )
            artifact_snapshot = self.operation_manager.add_artifact(
                operation_id,
                OperationArtifact(path, "screenshot", task_id),
                expected_kind="screenshot",
                expected_generation=metadata.generation_token,
            )
            if artifact_snapshot is None:
                return None
        result_snapshot = self.operation_manager.record_unit_result(
            operation_id,
            OperationUnitResult(task_id, unit_state, message),
            expected_kind="screenshot",
            expected_generation=metadata.generation_token,
        )
        if result_snapshot is None:
            return None
        if valid and path:
            self.signals.screenshot_captured.emit(metadata.target_id, path)
        return self._finish_screenshot_if_complete(
            operation_id,
            metadata.generation_token,
        )

    def _operation_metadata_matches(
        self,
        op_type: str,
        metadata: OperationMetadata,
        snapshot,
        response_claim: object | None,
    ) -> bool:
        if snapshot.kind == "screenshot" and metadata.generation_token is None:
            return False
        return super()._operation_metadata_matches(
            op_type,
            metadata,
            snapshot,
            response_claim,
        )

    @staticmethod
    def _classify_screenshot_result(
        result,
        metadata: OperationMetadata,
    ) -> tuple[bool, str, str]:
        if not isinstance(result, dict):
            return False, "Screenshot returned an invalid result", ""
        if not metadata.target_id or result.get("device_ip") != metadata.target_id:
            return False, "Screenshot target identity mismatch", ""
        if not result.get("success"):
            return False, "Screenshot command failed", ""
        path = result.get("screenshot_path")
        expected = metadata.expected_artifact_path
        if not isinstance(path, str) or not path or not expected:
            return False, "Screenshot artifact path missing", ""
        actual_path = os.path.normcase(os.path.abspath(path))
        expected_path = os.path.normcase(os.path.abspath(expected))
        if actual_path != expected_path:
            return False, "Screenshot artifact path mismatch", ""
        if not ADBTesting._is_valid_png(path):
            return False, "Screenshot artifact missing or invalid", ""
        return True, "Screenshot captured", path

    def _finish_screenshot_if_complete(
        self,
        operation_id: str,
        generation_token: object,
    ) -> OperationSnapshot | None:
        snapshot = self.operation_manager.get(
            operation_id,
            expected_kind="screenshot",
            expected_generation=generation_token,
        )
        if snapshot is None or len(snapshot.unit_results) != len(snapshot.unit_ids):
            return None
        terminal = self.operation_manager.finish_from_unit_results(
            operation_id,
            expected_kind="screenshot",
            expected_generation=generation_token,
        )
        if terminal is not None:
            self._emit_screenshot_terminal(terminal)
        return terminal

    def _fail_screenshot_operation(
        self,
        operation_id: str,
        message: str,
        *,
        expected_generation: object,
    ) -> OperationSnapshot | None:
        terminal = self.operation_manager.finish(
            operation_id,
            OperationState.FAILED,
            message=message,
            expected_kind="screenshot",
            expected_generation=expected_generation,
        )
        if terminal is not None:
            self._emit_screenshot_terminal(terminal)
        return terminal

    def _fail_operation_protocol(self, snapshot, message: str):
        if snapshot.kind == "screenshot":
            return self._fail_screenshot_operation(
                snapshot.operation_id,
                message,
                expected_generation=snapshot.generation_token,
            )
        return super()._fail_operation_protocol(snapshot, message)

    def cancel_screenshot(self, operation_id: str) -> bool:
        snapshot = self.operation_manager.get(
            operation_id,
            expected_kind="screenshot",
        )
        if snapshot is None:
            return False
        generation_token = snapshot.generation_token
        terminal = self.operation_manager.cancel_pending_units(
            operation_id,
            unit_message="Screenshot cancelled",
            expected_kind="screenshot",
            expected_generation=generation_token,
        )
        if terminal is None:
            return False
        self._emit_screenshot_terminal(terminal)
        return True

    def _emit_screenshot_terminal(self, terminal: OperationSnapshot):
        counts = Counter(result.state for result in terminal.unit_results)
        total = len(terminal.unit_ids)
        succeeded = counts[OperationState.SUCCEEDED]
        failed = max(
            counts[OperationState.FAILED],
            total - succeeded - counts[OperationState.CANCELLED],
        )
        cancelled = counts[OperationState.CANCELLED]
        self.log_service.log(
            "DEBUG",
            (
                "[screenshot] operation finished: "
                f"state={terminal.state.value} total={total} "
                f"succeeded={succeeded} failed={failed} cancelled={cancelled}"
            ),
        )
        message = (
            f"Screenshot completed: {succeeded}/{total} succeeded, "
            f"{failed} failed, {cancelled} cancelled"
        )
        self._emit_operation(
            "screenshot",
            terminal.state is OperationState.SUCCEEDED,
            message,
        )
        succeeded_units = {
            result.unit_id
            for result in terminal.unit_results
            if result.state is OperationState.SUCCEEDED
        }
        paths_by_unit = {
            artifact.unit_id: artifact.path
            for artifact in terminal.artifacts
            if artifact.kind == "screenshot" and artifact.unit_id in succeeded_units
        }
        paths = [
            paths_by_unit[unit_id] for unit_id in terminal.unit_ids if unit_id in paths_by_unit
        ]
        if paths:
            QTimer.singleShot(
                0,
                self.signals,
                lambda captured=tuple(paths): self._show_screenshot_viewer(list(captured)),
            )

    def _show_screenshot_viewer(self, image_paths: list):
        if getattr(self, "_shutting_down", False):
            return
        viewer = ScreenshotViewer(image_paths)
        configure_independent_secondary_window(viewer)
        viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if self.window_owner is not None:
            fit_secondary_window_to_owner_screen(viewer, self.window_owner)
            viewer.installEventFilter(self.window_owner)
        self._active_viewers.append(viewer)
        log_service = getattr(self, "log_service", None)
        if log_service is not None:
            log_service.log(
                "DEBUG",
                (
                    "ui.secondary_window "
                    f"active_count={len(self._active_viewers)} "
                    "dialog=ScreenshotViewer phase=created"
                ),
            )
        viewer.destroyed.connect(
            lambda _obj=None, v=viewer: self._on_screenshot_viewer_destroyed(v)
        )
        viewer.show()

    def _on_screenshot_viewer_destroyed(self, viewer):
        """移除已销毁截图窗口并记录关闭完成。"""
        if viewer in self._active_viewers:
            self._active_viewers.remove(viewer)
        log_service = getattr(self, "log_service", None)
        if log_service is not None:
            log_service.log(
                "DEBUG",
                (
                    "ui.secondary_window "
                    f"active_count={len(self._active_viewers)} "
                    "dialog=ScreenshotViewer phase=closed"
                ),
            )

    # 屏幕录制

    def start_screen_record(self, devices: list, duration: int = 30, batch_id: str = ""):
        devices = list(dict.fromkeys(device for device in devices if device))
        if not self._require_devices(devices, "screen_record"):
            return
        requested_batch_id = str(batch_id).strip()
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            self._emit_operation("screen_record", False, "Invalid recording duration")
            for ip in devices:
                _emit_record_target_finished(self, requested_batch_id, ip)
            return
        if not 1 <= duration <= 3600:
            self._emit_operation(
                "screen_record", False, "Recording duration must be between 1 and 3600 seconds"
            )
            for ip in devices:
                _emit_record_target_finished(self, requested_batch_id, ip)
            return
        batch_id = requested_batch_id or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch_id):
            self._emit_operation("screen_record", False, "Invalid recording batch identifier")
            for ip in devices:
                _emit_record_target_finished(self, batch_id, ip)
            return
        try:
            save_dir = self._get_screenshot_dir()
        except (OSError, RuntimeError, ValueError) as exc:
            self._emit_operation(
                "screen_record",
                False,
                f"Failed to prepare recording directory: {exc}",
            )
            for ip in devices:
                _emit_record_target_finished(self, batch_id, ip)
            return
        now = time.time()
        for ip in devices:
            if not self.screen_records.start(ip, batch_id, save_dir, duration, start_time=now):
                self._emit_operation("screen_record", False, f"Recording is already active on {ip}")
                _emit_record_target_finished(self, batch_id, ip)
                continue
            try:
                self.advanced_model.start_screen_record_async(
                    ip,
                    save_dir,
                    duration,
                    batch_id=batch_id,
                )
            except Exception as exc:
                self.screen_records.finish(ip, batch_id)
                self._emit_operation(
                    "screen_record",
                    False,
                    f"Failed to submit recording for {ip}: {exc}",
                )
                _emit_record_target_finished(self, batch_id, ip)

    def _process_start_screen_record_result(self, result: dict):
        ip = result.get("device_ip", "")
        info = self.screen_records.active(ip)
        batch_id = result.get("batch_id") or (info or {}).get("batch_id", "")
        if info is None or batch_id != info.get("batch_id", ""):
            return
        if result.get("success"):
            dur = result.get("duration", 30)
            self.screen_records.mark_started(
                ip, batch_id, result["remote_path"], result["filename"]
            )
            self._emit_operation(
                "screen_record", True, f"Recording {dur}s on {ip} → {result['filename']}"
            )
            if self.screen_records.is_stop_succeeded(ip, batch_id):
                self._auto_pull(ip, batch_id)
            else:
                # 录制时长结束后预留两秒，让设备完成文件收尾再自动拉取。
                QTimer.singleShot(
                    (dur + 2) * 1000,
                    self.signals,
                    lambda ip=ip, batch_id=batch_id: self._auto_pull(ip, batch_id),
                )
        else:
            self.screen_records.finish(ip, batch_id)
            self.screen_records.clear_stop_request(ip, batch_id)
            self._emit_operation(
                "screen_record", False, f"Failed to start recording on {ip}: {result.get('error')}"
            )
            _emit_record_target_finished(self, batch_id, ip)

    def _submit_recording_pull(self, device_ip: str, info: dict) -> bool:
        """每个设备批次只提交一次录屏拉取；提交失败时立即释放终态。"""

        batch_id = str(info.get("batch_id", ""))
        # Stop 结果和自动定时器都在 GUI 线程进入此入口；use case 内原子标记阻断重入。
        if not self.screen_records.mark_pull_submitted(device_ip, batch_id):
            return False
        try:
            self.advanced_model.pull_recorded_video_async(
                device_ip,
                info["remote_path"],
                info["save_dir"],
                info["filename"],
                batch_id=batch_id,
            )
            return True
        except Exception as exc:
            self.screen_records.finish(device_ip, batch_id)
            self.screen_records.clear_stop_request(device_ip, batch_id)
            self._emit_operation(
                "pull_recording",
                False,
                f"Failed to submit recording pull for {device_ip}: {exc}",
            )
            _emit_record_target_finished(self, batch_id, device_ip)
            return False

    def _auto_pull(self, device_ip: str, batch_id: str = ""):
        if getattr(self, "_shutting_down", False):
            return
        info = self.screen_records.active(device_ip) or {}
        if batch_id and info.get("batch_id") != batch_id:
            return
        if info.get("remote_path") and not info.get("pull_submitted"):
            submitted = ADBMediaMixin._submit_recording_pull(self, device_ip, info)
            if not submitted:
                return
            self._emit_operation(
                "screen_record", True, f"Auto-pulling recording from {device_ip}..."
            )

    def stop_screen_record(self, devices: list, batch_id: str = ""):
        devices = list(dict.fromkeys(device for device in devices if device))
        if not self._require_devices(devices, "stop_recording"):
            return
        for ip in devices:
            info = self.screen_records.active(ip) or {}
            current_batch = str(info.get("batch_id", ""))
            requested_batch = str(batch_id).strip() or current_batch
            if batch_id and requested_batch != current_batch:
                continue
            if not self.screen_records.request_stop(ip, requested_batch):
                continue
            try:
                self.advanced_model.stop_screen_record_async(ip, batch_id=requested_batch)
            except Exception as exc:
                self.screen_records.clear_stop_request(ip, requested_batch)
                self._emit_operation(
                    "stop_recording",
                    False,
                    f"Failed to submit recording stop for {ip}: {exc}",
                )

    def _process_stop_screen_record_result(self, result: dict):
        ip = result.get("device_ip", "")
        result_batch = str(result.get("batch_id", ""))
        info = self.screen_records.active(ip) or {}
        current_batch = str(info.get("batch_id", ""))
        self.screen_records.clear_stop_request(ip, result_batch)
        if current_batch and result_batch != current_batch:
            return
        if result_batch and not current_batch:
            return
        self._emit_operation(
            "stop_recording",
            result.get("success", False),
            f"Recording on {ip}: {result.get('message', '')}",
        )
        if not result.get("success", False):
            return
        # 主动停止录制后也要拉取已经生成的文件。
        if info.get("remote_path"):
            ADBMediaMixin._submit_recording_pull(self, ip, info)
        elif info:
            self.screen_records.mark_stop_succeeded(ip, current_batch)

    def _process_pull_recorded_video_result(self, result: dict):
        ip = result.get("device_ip", "")
        info = self.screen_records.active(ip)
        batch_id = result.get("batch_id") or (info or {}).get("batch_id", "")
        if info is None or batch_id != info.get("batch_id", ""):
            return
        self.screen_records.finish(ip, batch_id)
        self.screen_records.clear_stop_request(ip, batch_id)
        if result.get("success"):
            self._emit_operation(
                "pull_recording", True, f"Recording saved: {result.get('local_path')}"
            )
        else:
            self._emit_operation(
                "pull_recording",
                False,
                f"Failed to pull recording from {ip}: {result.get('error')}",
            )
        _emit_record_target_finished(self, batch_id, ip)

    # 性能诊断

    def dumpsys_meminfo(self, devices: list, package: str = ""):
        if not self._require_devices(devices, "dumpsys_meminfo"):
            return
        for ip in devices:
            self.advanced_model.dumpsys_meminfo_async(ip, package)

    def _process_dumpsys_meminfo_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "dumpsys_meminfo",
                True,
                f"📊 Memory info ({ip}):\n{result.get('output', '')[:2000]}",
            )
        else:
            self._emit_operation(
                "dumpsys_meminfo", False, f"Meminfo failed on {ip}: {result.get('error')}"
            )

    def dumpsys_cpuinfo(self, devices: list):
        if not self._require_devices(devices, "dumpsys_cpuinfo"):
            return
        for ip in devices:
            self.advanced_model.dumpsys_cpuinfo_async(ip)

    def _process_dumpsys_cpuinfo_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "dumpsys_cpuinfo", True, f"📊 CPU info ({ip}):\n{result.get('output', '')[:2000]}"
            )
        else:
            self._emit_operation(
                "dumpsys_cpuinfo", False, f"CPU info failed on {ip}: {result.get('error')}"
            )

    def dumpsys_battery(self, devices: list):
        if not self._require_devices(devices, "dumpsys_battery"):
            return
        for ip in devices:
            self.advanced_model.dumpsys_battery_async(ip)

    def _process_dumpsys_battery_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "dumpsys_battery",
                True,
                f"🔋 Battery info ({ip}):\n{result.get('output', '')[:1000]}",
            )
        else:
            self._emit_operation(
                "dumpsys_battery", False, f"Battery info failed on {ip}: {result.get('error')}"
            )

    def top_snapshot(self, devices: list):
        if not self._require_devices(devices, "top_snapshot"):
            return
        for ip in devices:
            self.advanced_model.top_snapshot_async(ip)

    def _process_top_snapshot_result(self, result: dict):
        _emit_readonly_diagnostic_result(
            self,
            result,
            operation="top_snapshot",
            label="Top snapshot",
            max_lines=20,
        )

    def gfxinfo(self, devices: list, package: str):
        if not self._require_devices(devices, "gfxinfo"):
            return
        try:
            package = normalize_android_package(package)
        except ValueError as exc:
            self._emit_operation("gfxinfo", False, str(exc))
            return
        for ip in devices:
            self.advanced_model.gfxinfo_async(ip, package)

    def _process_gfxinfo_result(self, result: dict):
        _emit_readonly_diagnostic_result(
            self,
            result,
            operation="gfxinfo",
            label="GFX info",
            max_lines=60,
        )

    def wakelocks(self, devices: list):
        if not self._require_devices(devices, "wakelocks"):
            return
        for ip in devices:
            self.advanced_model.wakelocks_async(ip)

    def _process_wakelocks_result(self, result: dict):
        _emit_readonly_diagnostic_result(
            self,
            result,
            operation="wakelocks",
            label="Wakelocks",
            max_lines=40,
        )

    def netstats_detail(self, devices: list):
        if not self._require_devices(devices, "netstats_detail"):
            return
        for ip in devices:
            self.advanced_model.netstats_detail_async(ip)

    def _process_netstats_detail_result(self, result: dict):
        _emit_readonly_diagnostic_result(
            self,
            result,
            operation="netstats_detail",
            label="Network statistics",
            max_lines=60,
        )

    # 电池状态

    def battery_set(self, devices: list, param: str, value: str):
        if not self._require_devices(devices, "battery_set"):
            return
        try:
            numeric_value = int(str(value).strip())
        except (TypeError, ValueError):
            self._emit_operation("battery_set", False, "Battery value must be an integer")
            return
        if param == "level" and not 0 <= numeric_value <= 100:
            self._emit_operation("battery_set", False, "Battery level must be between 0 and 100")
            return
        if param == "status" and not 1 <= numeric_value <= 5:
            self._emit_operation("battery_set", False, "Battery status must be between 1 and 5")
            return
        if param not in {"level", "status"}:
            self._emit_operation("battery_set", False, "Unsupported battery parameter")
            return
        for ip in devices:
            if param == "level":
                self.advanced_model.battery_set_level_async(ip, numeric_value)
            elif param == "status":
                self.advanced_model.battery_set_status_async(ip, str(numeric_value))

    def _process_battery_set_level_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "battery_set", True, f"Battery level set to {result.get('level')}% on {ip}"
            )
        else:
            self._emit_operation(
                "battery_set", False, f"Battery set failed on {ip}: {result.get('error')}"
            )

    def _process_battery_set_status_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "battery_set", True, f"Battery status set to '{result.get('status')}' on {ip}"
            )
        else:
            self._emit_operation(
                "battery_set", False, f"Battery set failed on {ip}: {result.get('error')}"
            )

    def battery_reset(self, devices: list):
        if not self._require_devices(devices, "battery_reset"):
            return
        for ip in devices:
            self.advanced_model.battery_reset_async(ip)

    def _process_battery_reset_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("battery_reset", True, f"Battery reset on {ip}")
        else:
            self._emit_operation(
                "battery_reset", False, f"Battery reset failed on {ip}: {result.get('error')}"
            )

    # Logcat 日志

    def logcat_filtered(
        self,
        devices: list,
        buffer: str = "main",
        priority: str = "V",
        tag_filter: str = "",
        regex: str = "",
    ):
        if not self._require_devices(devices, "logcat_filtered"):
            return
        try:
            save_dir = self._get_screenshot_dir()
        except (OSError, RuntimeError, ValueError) as exc:
            self._emit_operation(
                "logcat_filtered", False, f"Failed to prepare logcat directory: {exc}"
            )
            return
        for ip in devices:
            timestamp = datetime.now().strftime("%H%M%S")
            sanitized = re.sub(r"\W+", "_", ip)
            log_path = os.path.join(save_dir, f"logcat_{timestamp}_{sanitized}.txt")
            self.advanced_model.logcat_filtered_async(
                ip, log_path, buffer, priority, tag_filter, regex
            )

    def _process_logcat_filtered_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "logcat_filtered",
                True,
                f"Filtered log saved for {ip} ({result.get('line_count', 0)} lines)",
            )
        else:
            self._emit_operation(
                "logcat_filtered", False, f"Logcat filter failed on {ip}: {result.get('error')}"
            )

    # 设备进程

    def list_processes(self, devices: list):
        if not self._require_devices(devices, "list_processes"):
            return
        for ip in devices:
            self.advanced_model.list_processes_async(ip)

    def _process_list_processes_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "list_processes", True, f"Processes ({ip}):\n{result.get('output', '')[:2000]}"
            )
        else:
            self._emit_operation(
                "list_processes", False, f"Process list failed on {ip}: {result.get('error')}"
            )

    def kill_process(self, devices: list, pid: str):
        if not self._require_devices(devices, "kill_process"):
            return
        text = str(pid).strip()
        if not text.isdigit() or not 1 <= int(text) <= 2_147_483_647:
            self._emit_operation("kill_process", False, "PID must be a positive integer")
            return
        for ip in devices:
            self.advanced_model.kill_process_async(ip, text)

    def _process_kill_process_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("kill_process", True, f"Killed PID {result.get('pid')} on {ip}")
        else:
            self._emit_operation(
                "kill_process", False, f"Kill failed on {ip}: {result.get('error')}"
            )

    # 设备运行时长

    def device_uptime(self, devices: list):
        if not self._require_devices(devices, "device_uptime"):
            return
        for ip in devices:
            self.advanced_model.get_device_uptime_async(ip)

    def _process_get_device_uptime_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "device_uptime", True, f"Uptime ({ip}): {result.get('output', '')}"
            )
        else:
            self._emit_operation(
                "device_uptime", False, f"Uptime failed on {ip}: {result.get('error')}"
            )
