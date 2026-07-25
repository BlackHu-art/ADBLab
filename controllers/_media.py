"""提供截图、录屏和设备诊断信息采集的控制能力。"""

from __future__ import annotations

import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PySide6.QtCore import Qt, QTimer

from adblab.application.envelope import OperationMetadata
from adblab.application.operations import (
    OperationArtifact,
    OperationSnapshot,
    OperationState,
    OperationUnitResult,
)
from controllers._base import _ADBControllerBase
from core.log_service import LogService
from gui.dialogs.screenshot_viewer import ScreenshotViewer
from gui.panels.adb_control_signals import ADBControllerSignals
from models.adb_advanced import ADBAdvanced
from models.adb_testing import ADBTesting


class ADBMediaMixin(_ADBControllerBase):
    """协调截图、录屏、dumpsys、电池、Logcat、进程和运行时长操作。"""

    # 以下属性由 _ADBControllerBase 提供。
    testing_model: ADBTesting
    advanced_model: ADBAdvanced
    signals: ADBControllerSignals
    log_service: LogService
    executor: ThreadPoolExecutor
    _pending_ops: dict
    _active_viewers: list
    last_save_dir: str | None

    _handlers = {
        "take_screenshot": "_process_screenshot_result",
        "start_screen_record": "_process_start_screen_record_result",
        "stop_screen_record": "_process_stop_screen_record_result",
        "pull_recorded_video": "_process_pull_recorded_video_result",
        "dumpsys_meminfo": "_process_dumpsys_meminfo_result",
        "dumpsys_cpuinfo": "_process_dumpsys_cpuinfo_result",
        "dumpsys_battery": "_process_dumpsys_battery_result",
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
                self._screenshot_path(screenshot_dir, operation_id, device),
            )
            for device in valid
        ]
        operation = self.operation_manager.begin(
            "screenshot",
            operation_id=operation_id,
            unit_ids=(task_id for task_id, _device, _path in tasks),
        )
        self.operation_manager.mark_running(operation.operation_id)
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
                )
        self._finish_screenshot_if_complete(operation.operation_id)
        return operation.operation_id

    def _screenshot_path(self, save_dir: str, operation_id: str, device_ip: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        sanitized_ip = re.sub(r"\W+", "_", device_ip)
        filename = f"screenshot_{timestamp}_{operation_id[:12]}_{sanitized_ip}.png"
        return os.path.normpath(os.path.join(save_dir, filename))

    def _start_screenshot_process(
        self,
        device_ip: str,
        save_path: str,
        operation_id: str,
        task_id: str,
    ):
        self.testing_model.take_screenshot_async(
            device_ip,
            save_path,
            _operation_id=operation_id,
            _operation_kind="screenshot",
            _operation_task_id=task_id,
            _operation_unit_id=task_id,
            _operation_target_id=device_ip,
            _operation_expected_artifact_path=save_path,
        )

    def _process_screenshot_result(self, result: dict):
        """处理未携带 operation envelope 的旧版兼容结果。"""
        device_ip = result.get("device_ip", "")
        path = result.get("screenshot_path", "")
        if result.get("success") and ADBTesting._is_valid_png(path):
            self.signals.screenshot_captured.emit(device_ip, path)
            self._emit_operation("screenshot", True, "Screenshot captured")
        else:
            self._emit_operation(
                "screenshot",
                False,
                "Screenshot capture failed",
            )

    def _process_screenshot_operation_result(
        self,
        result,
        metadata: OperationMetadata,
    ) -> OperationSnapshot | None:
        operation_id = metadata.operation_id
        snapshot = self.operation_manager.get(operation_id)
        if snapshot is None:
            return None
        task_id = metadata.unit_id
        if not task_id or task_id != metadata.task_id:
            return self._fail_screenshot_operation(
                operation_id,
                "Screenshot task identity mismatch",
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
                )
            self.operation_manager.add_artifact(
                operation_id,
                OperationArtifact(path, "screenshot", task_id),
            )
        self.operation_manager.record_unit_result(
            operation_id,
            OperationUnitResult(task_id, unit_state, message),
        )
        if valid and path:
            self.signals.screenshot_captured.emit(metadata.target_id, path)
        return self._finish_screenshot_if_complete(operation_id)

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
    ) -> OperationSnapshot | None:
        snapshot = self.operation_manager.get(operation_id)
        if snapshot is None or len(snapshot.unit_results) != len(snapshot.unit_ids):
            return None
        terminal = self.operation_manager.finish_from_unit_results(operation_id)
        if terminal is not None:
            self._emit_screenshot_terminal(terminal)
        return terminal

    def _fail_screenshot_operation(
        self,
        operation_id: str,
        message: str,
    ) -> OperationSnapshot | None:
        terminal = self.operation_manager.finish(
            operation_id,
            OperationState.FAILED,
            message=message,
        )
        if terminal is not None:
            self._emit_screenshot_terminal(terminal)
        return terminal

    def _fail_operation_protocol(self, snapshot, message: str):
        if snapshot.kind == "screenshot":
            return self._fail_screenshot_operation(snapshot.operation_id, message)
        return super()._fail_operation_protocol(snapshot, message)

    def cancel_screenshot(self, operation_id: str) -> bool:
        if not self.operation_manager.request_cancel(operation_id):
            return False
        snapshot = self.operation_manager.get(operation_id)
        if snapshot is None:
            return False
        completed_units = {result.unit_id for result in snapshot.unit_results}
        for unit_id in snapshot.unit_ids:
            if unit_id not in completed_units:
                self.operation_manager.record_unit_result(
                    operation_id,
                    OperationUnitResult(
                        unit_id,
                        OperationState.CANCELLED,
                        "Screenshot cancelled",
                    ),
                )
        self._finish_screenshot_if_complete(operation_id)
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
        paths_by_unit = {
            artifact.unit_id: artifact.path
            for artifact in terminal.artifacts
            if artifact.kind == "screenshot"
        }
        paths = [
            paths_by_unit[unit_id]
            for unit_id in terminal.unit_ids
            if unit_id in paths_by_unit
        ]
        if paths:
            QTimer.singleShot(
                0,
                lambda captured=tuple(paths): self._show_screenshot_viewer(list(captured)),
            )

    def _show_screenshot_viewer(self, image_paths: list):
        viewer = ScreenshotViewer(image_paths, parent=self.window_parent)
        viewer.setAttribute(Qt.WA_DeleteOnClose)
        if self.window_parent is not None:
            viewer.installEventFilter(self.window_parent)
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

    def start_screen_record(self, devices: list, duration: int = 30):
        if not self._require_devices(devices, "screen_record"):
            return
        save_dir = self._get_screenshot_dir()
        now = time.time()
        if not hasattr(self, '_record_info'):
            self._record_info = {}
        for ip in devices:
            self._record_info[ip] = {
                "start_time": now, "duration": duration, "save_dir": save_dir,
            }
            self.advanced_model.start_screen_record_async(ip, save_dir, duration)

    def _process_start_screen_record_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            dur = result.get("duration", 30)
            self._record_info[ip].update({
                "remote_path": result["remote_path"],
                "filename": result["filename"],
            })
            self._emit_operation(
                "screen_record", True, f"Recording {dur}s on {ip} → {result['filename']}"
            )
            # 录制时长结束后预留两秒，让设备完成文件收尾再自动拉取。
            QTimer.singleShot((dur + 2) * 1000, lambda ip=ip: self._auto_pull(ip))
        else:
            self._record_info.pop(ip, None)
            self._emit_operation(
                "screen_record", False, f"Failed to start recording on {ip}: {result.get('error')}"
            )
            self.signals.record_finished.emit()

    def _auto_pull(self, device_ip: str):
        info = self._record_info.get(device_ip, {})
        if info.get("remote_path"):
            self._emit_operation("screen_record", True, f"Auto-pulling recording from {device_ip}...")
            self.advanced_model.pull_recorded_video_async(
                device_ip, info["remote_path"], info["save_dir"], info["filename"]
            )

    def stop_screen_record(self, devices: list):
        if not self._require_devices(devices, "stop_recording"):
            return
        for ip in devices:
            self.advanced_model.stop_screen_record_async(ip)

    def _process_stop_screen_record_result(self, result: dict):
        ip = result.get("device_ip", "")
        self._emit_operation(
            "stop_recording", result.get("success", False),
            f"Recording on {ip}: {result.get('message', '')}"
        )
        # 主动停止录制后也要拉取已经生成的文件。
        info = self._record_info.get(ip, {})
        if info.get("remote_path"):
            self.advanced_model.pull_recorded_video_async(
                ip, info["remote_path"], info["save_dir"], info["filename"]
            )

    def _process_pull_recorded_video_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._record_info.pop(ip, None)
            self._emit_operation(
                "pull_recording", True, f"Recording saved: {result.get('local_path')}"
            )
        else:
            self._emit_operation(
                "pull_recording", False,
                f"Failed to pull recording from {ip}: {result.get('error')}",
            )
        self.signals.record_finished.emit()

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

    # 电池状态

    def battery_set(self, devices: list, param: str, value: str):
        if not self._require_devices(devices, "battery_set"):
            return
        for ip in devices:
            if param == "level":
                self.advanced_model.battery_set_level_async(ip, int(value))
            elif param == "status":
                self.advanced_model.battery_set_status_async(ip, value)

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
        save_dir = self._get_screenshot_dir()
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
        for ip in devices:
            self.advanced_model.kill_process_async(ip, pid)

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
