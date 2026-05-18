from __future__ import annotations

import os
import re
import time
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

    # -- Screenshot --

    def take_screenshot(self, devices: list):
        valid = [d for d in devices if d]
        if not valid:
            self._emit_operation("screenshot", False, "⚠️ No devices selected")
            return
        screenshot_dir = self._get_screenshot_dir()
        self._screenshot_paths = []
        self._screenshot_remaining = len(valid)
        self._screenshot_devices = list(valid)
        self._emit_operation("screenshot", True,
            f"Capturing {len(valid)} device(s)...")
        for device_ip in valid:
            self._start_screenshot_process(device_ip, screenshot_dir)

    def _start_screenshot_process(self, device_ip: str, save_dir: str):
        timestamp = datetime.now().strftime("%H%M%S")
        sanitized_ip = re.sub(r"\W+", "_", device_ip)
        filename = f"screenshot_{timestamp}_{sanitized_ip}.png"
        save_path = os.path.normpath(os.path.join(save_dir, filename))
        operation_id = self._generate_operation_id()
        with self._pending_lock:
            self._pending_ops[operation_id] = ("screenshot", device_ip)
        self.testing_model.take_screenshot_async(device_ip, save_path)

    def _process_screenshot_result(self, result: dict):
        device_ip = result.get("device_ip", "")
        if result.get("success"):
            path = result["screenshot_path"]
            if os.path.isfile(path):
                self.signals.screenshot_captured.emit(device_ip, path)
                self._screenshot_paths.append(path)
            else:
                self._emit_operation(
                    "screenshot", False, f"Screenshot file missing for {device_ip}"
                )
        else:
            error = result.get("error", "Unknown error")
            self._emit_operation(
                "screenshot", False, f"Failed on {device_ip}: {error}"
            )
        self._screenshot_remaining -= 1
        if self._screenshot_remaining <= 0:
            paths = self._screenshot_paths
            self._screenshot_paths = []
            count = len(paths)
            if count:
                self._emit_operation("screenshot", True,
                    f"All done — {count} screenshot(s) ready")
                QTimer.singleShot(0, lambda: self._show_screenshot_viewer(paths))
            else:
                self._emit_operation("screenshot", False,
                    "No screenshots captured — check device connections")

    def _show_screenshot_viewer(self, image_paths: list):
        viewer = ScreenshotViewer(image_paths)
        viewer.setAttribute(Qt.WA_DeleteOnClose)
        self._active_viewers.append(viewer)
        viewer.destroyed.connect(
            lambda v=viewer: self._active_viewers.remove(v) if v in self._active_viewers else None
        )
        viewer.show()

    # -- Screen Recording --

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
            # Auto-pull after duration + 2s buffer
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
        # Auto-pull stopped recording
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

    # -- Performance --

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

    # -- Battery --

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

    # ── Logcat ──

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

    # -- Process --

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

    # ── Uptime ──

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
