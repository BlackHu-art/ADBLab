from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PySide6.QtCore import Qt, QTimer

from controllers._base import _ADBControllerBase
from core.log_service import LogService
from gui.dialogs.screenshot_viewer import ScreenshotViewer
from gui.panels.adb_control_signals import ADBControllerSignals
from models.adb_advanced import ADBAdvanced
from models.adb_testing import ADBTesting


class ADBMediaMixin(_ADBControllerBase):
    """Screenshot, screen recording, diagnostics (dumpsys, battery, logcat, processes, uptime)."""

    # ── Provided by _ADBControllerBase ──
    testing_model: ADBTesting
    advanced_model: ADBAdvanced
    signals: ADBControllerSignals
    log_service: LogService
    executor: ThreadPoolExecutor
    _pending_operations: dict
    _active_viewers: list
    last_save_dir: str | None

    _handlers = {
        "take_screenshot": "_process_screenshot_result",
        "start_screen_record": "_process_start_screen_record_result",
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

    # ── 截图 ──

    def take_screenshot(self, devices: list):
        valid = [d for d in devices if d]
        if not valid:
            self._emit_operation("screenshot", False, "⚠️ No devices selected")
            return
        screenshot_dir = self._get_screenshot_dir()
        self._screenshot_paths = []
        self._screenshot_remaining = len(valid)
        for device_ip in valid:
            self._start_screenshot_process(device_ip, screenshot_dir)

    def _start_screenshot_process(self, device_ip: str, save_dir: str):
        timestamp = datetime.now().strftime("%H%M%S")
        sanitized_ip = re.sub(r"\W+", "_", device_ip)
        filename = f"screenshot_{timestamp}_{sanitized_ip}.png"
        save_path = os.path.join(save_dir, filename)
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("screenshot", device_ip)
        self.testing_model.take_screenshot_async(device_ip, save_path)

    def _process_screenshot_result(self, result: dict):
        device_ip = result.get("device_ip", "")
        if result.get("success"):
            path = result["screenshot_path"]
            self.signals.screenshot_captured.emit(device_ip, path)
            self._emit_operation("screenshot", True, f"Screenshot saved to {path}")
            self._screenshot_paths.append(path)
        else:
            error = result.get("error", "Unknown error")
            self._emit_operation(
                "screenshot", False, f"Failed to capture screenshot on {device_ip}: {error}"
            )
        self._screenshot_remaining -= 1
        if self._screenshot_remaining <= 0 and self._screenshot_paths:
            paths = self._screenshot_paths
            self._screenshot_paths = []
            QTimer.singleShot(0, lambda: self._show_screenshot_viewer(paths))

    def _show_screenshot_viewer(self, image_paths: list):
        viewer = ScreenshotViewer(image_paths)
        viewer.setAttribute(Qt.WA_DeleteOnClose)
        self._active_viewers.append(viewer)
        viewer.destroyed.connect(
            lambda v=viewer: self._active_viewers.remove(v) if v in self._active_viewers else None
        )
        viewer.show()

    # ── 屏幕录制 ──

    def start_screen_record(self, devices: list, duration: int = 180):
        if not devices:
            self._emit_operation("screen_record", False, "⚠️ No devices selected")
            return
        save_dir = self._get_screenshot_dir()
        self._record_info = {}
        for ip in devices:
            self.advanced_model.start_screen_record_async(ip, save_dir, duration)

    def _process_start_screen_record_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._record_info[ip] = {
                "remote_path": result["remote_path"],
                "save_dir": result["save_dir"],
                "filename": result["filename"],
            }
            self._emit_operation(
                "screen_record", True, f"Recording started on {ip} ({result['filename']})"
            )
        else:
            self._emit_operation(
                "screen_record", False, f"Failed to start recording on {ip}: {result.get('error')}"
            )

    def pull_recordings(self, devices: list):
        if not devices:
            self._emit_operation("pull_recording", False, "⚠️ No devices selected")
            return
        for ip in devices:
            info = self._record_info.get(ip, {})
            if info:
                self.advanced_model.pull_recorded_video_async(
                    ip, info["remote_path"], info["save_dir"], info["filename"]
                )
            else:
                self._emit_operation("pull_recording", False, f"No recording info for {ip}")

    def _process_pull_recorded_video_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "pull_recording", True, f"Recording pulled from {ip}: {result.get('local_path')}"
            )
        else:
            self._emit_operation(
                "pull_recording",
                False,
                f"Failed to pull recording from {ip}: {result.get('error')}",
            )

    # ── 性能诊断 ──

    def dumpsys_meminfo(self, devices: list, package: str = ""):
        if not devices:
            self._emit_operation("dumpsys_meminfo", False, "⚠️ No devices selected")
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
        if not devices:
            self._emit_operation("dumpsys_cpuinfo", False, "⚠️ No devices selected")
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
        if not devices:
            self._emit_operation("dumpsys_battery", False, "⚠️ No devices selected")
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

    # ── 电池模拟 ──

    def battery_set(self, devices: list, param: str, value: str):
        if not devices:
            self._emit_operation("battery_set", False, "⚠️ No devices selected")
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
        if not devices:
            self._emit_operation("battery_reset", False, "⚠️ No devices selected")
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

    # ── Logcat ──

    def logcat_filtered(
        self,
        devices: list,
        buffer: str = "main",
        priority: str = "V",
        tag_filter: str = "",
        regex: str = "",
    ):
        if not devices:
            self._emit_operation("logcat_filtered", False, "⚠️ No devices selected")
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

    # ── 进程管理 ──

    def list_processes(self, devices: list):
        if not devices:
            self._emit_operation("list_processes", False, "⚠️ No devices selected")
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
        if not devices:
            self._emit_operation("kill_process", False, "⚠️ No devices selected")
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

    # ── Uptime ──

    def device_uptime(self, devices: list):
        if not devices:
            self._emit_operation("device_uptime", False, "⚠️ No devices selected")
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
