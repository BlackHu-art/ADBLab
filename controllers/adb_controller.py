import os
import re
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer, Slot, QThreadPool
from PySide6.QtWidgets import QFileDialog

from core.mail.email_task import GetRandomEmailTask
from gui.panels.adb_control_signals import ADBControllerSignals
from gui.dialogs.screenshot_viewer import ScreenshotViewer
from models.adb_device import ADBDevice
from models.adb_app import ADBApp
from models.adb_testing import ADBTesting
from models.adb_advanced import ADBAdvanced
from models.device_store import DeviceStore
from core.log_service import LogLevel, LogService
from core.settings_manager import AppSettings
from utils.batch_tracker import BatchOperationTracker


class ADBController:
    """Fully decoupled ADB controller communicating via signals."""

    def __init__(self, log_service: LogService):
        self.signals = ADBControllerSignals()
        self.log_service = log_service
        self.device_model = ADBDevice()
        self.app_model = ADBApp()
        self.testing_model = ADBTesting()
        self.advanced_model = ADBAdvanced()
        self.connected_devices_file = "resources/connected_devices.yaml"
        self.package_info = "resources/package_info.yaml"
        self.thread_pool = QThreadPool.globalInstance()
        self._pending_operations = {}
        # Wire all four model signals to the same handler
        self.device_model.command_finished.connect(self._handle_async_response)
        self.app_model.command_finished.connect(self._handle_async_response)
        self.testing_model.command_finished.connect(self._handle_async_response)
        self.advanced_model.command_finished.connect(self._handle_async_response)
        self.last_save_dir = None
        self._active_viewers = []
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._batch_trackers = {}

        try:
            DeviceStore.load()
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to load DeviceStore: {str(e)}")
            DeviceStore.initialize_empty()

    def __del__(self):
        self.executor.shutdown(wait=False)

    def _generate_operation_id(self) -> str:
        return str(uuid.uuid4())

    # ═══════════════════════════════════════════════════════════════════════
    # Device Operations (existing)
    # ═══════════════════════════════════════════════════════════════════════

    def connect_device(self, ip: str):
        if not ip:
            self._emit_operation("connect", False, "⚠️ IP address cannot be empty")
            return
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("connect", ip)
        self.device_model.connect_device_async(ip)

    def _process_connect_device_result(self, result: str):
        ip = None
        found_key = None
        for key, (op_name, op_ip) in self._pending_operations.items():
            if op_name == "connect":
                ip = op_ip
                found_key = key
                break
        if found_key:
            del self._pending_operations[found_key]
        if not ip:
            self._emit_operation("connect", False, "⚠️ Unknown device connection")
            return
        if "connected" in result:
            self._save_device_info(ip)
            self.refresh_devices()
            self._emit_operation("connect", True, f"Successfully connected to {ip}")
        elif "already connected" in result:
            self._emit_operation("connect", True, f"{ip} is already connected")
        else:
            self._emit_operation("connect", False, f"Connection failed: {result}")

    def _process_device_list(self, devices: list):
        self._emit_operation("refresh", True, f"Found {len(devices)} connected devices")
        self._async_update_devices(devices)

    def refresh_devices(self):
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("refresh", None)
        try:
            self.device_model.get_connected_devices_async()
        except Exception as e:
            self._emit_operation("refresh", False, f"Failed to refresh devices: {str(e)}")
            self.signals.devices_updated.emit([])

    def _async_update_devices(self, devices: list):
        def _update():
            for ip in devices:
                try:
                    info = ADBDevice.get_devices_basic_info(ip)
                    DeviceStore.add_device(
                        alias=f"device_{ip}", ip=ip,
                        brand=info.get("Brand", "Unknown"),
                        model=info.get("Model", "Unknown"),
                        aversion=info.get("Aversion", "Unknown"))
                except Exception as e:
                    self._emit_operation("refresh", False,
                                         f"Failed to get info for {ip}: {str(e)}")
            self.signals.devices_updated.emit(devices)
        self.executor.submit(_update)

    def _save_device_info(self, ip: str):
        try:
            info = ADBDevice.get_devices_basic_info(ip)
            DeviceStore.add_device(
                alias=f"device_{ip}", ip=ip,
                brand=info.get("Brand", "Unknown"),
                model=info.get("Model", "Unknown"),
                aversion=info.get("Aversion", "Unknown"))
        except Exception as e:
            self.log_service.log("ERROR", f"Failed to save device info for {ip}: {str(e)}")
            raise

    def get_device_info(self, devices: list):
        if not devices:
            self._emit_operation("get_info", False, "Please select at least one device")
            return
        for ip in devices:
            self.device_model.get_device_info_async(ip)

    def _process_device_info_result(self, result: dict):
        device_ip = result.get("ip", "Unknown")
        log = self.log_service.log
        log(LogLevel.INFO, f"📱 Device Info - {device_ip}")
        log(LogLevel.INFO, f"  🧭 Model            : {result.get('Model', '-')}")
        log(LogLevel.INFO, f"  🏷️ Brand            : {result.get('Brand', '-')}")
        log(LogLevel.INFO, f"  🤖 Android Version  : {result.get('Android Version', '-')}")
        log(LogLevel.INFO, f"  🧪 SDK Version      : {result.get('SDK Version', '-')}")
        log(LogLevel.INFO, f"  🧬 CPU Architecture : {result.get('CPU Architecture', '-')}")
        log(LogLevel.INFO, f"  🔧 Hardware         : {result.get('Hardware', '-')}")
        log(LogLevel.INFO, f"  🖼️ Resolution       : {result.get('Resolution', '-')}".replace("Physical size: ", ""))
        log(LogLevel.INFO, f"  🧮 Density          : {result.get('Density', '-')}".replace("Physical density: ", ""))
        log(LogLevel.INFO, f"  🌐 Timezone         : {result.get('Timezone', '-')}")
        log(LogLevel.INFO, f"  🆔 Serial Number    : {result.get('Serial Number', '-')}")
        log(LogLevel.INFO, f"  💾 Total Memory     : {result.get('Total Memory', '-')}")
        log(LogLevel.INFO, f"  📉 Available Memory : {result.get('Available Memory', '-')}")
        log(LogLevel.INFO, f"  📂 Storage          :")
        for line in result.get("Storage", "").splitlines():
            log(LogLevel.INFO, f"    {line}")
        log(LogLevel.INFO, f"  📡 MAC / IP Info    :")
        for line in result.get("Mac", "").splitlines():
            log(LogLevel.INFO, f"    {line}")
        log(LogLevel.INFO, f"  ✅ complete\n")

    def disconnect_devices(self, devices: list):
        if not devices:
            self._emit_operation("disconnect", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.device_model.disconnect_device_async(ip)

    def _process_disconnect_result(self, result: dict):
        ip = result["ip"]
        if result.get("success"):
            self.refresh_devices()
            self._emit_operation("disconnect", True, f"Successfully disconnected {ip}")
        else:
            self._emit_operation("disconnect", False,
                                 f"Disconnect failed: {result.get('error', 'unknown error')}")

    def restart_devices(self, devices: list):
        if not devices:
            self._emit_operation("restart", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.device_model.restart_device_async(ip)

    def _process_restart_devices_result(self, result: dict):
        ip = result.get("ip", "unknown device")
        if result.get("success"):
            QTimer.singleShot(10_000, lambda: (
                self.refresh_devices(),
                self._emit_operation("restart", True, f"{ip} Restart completed, device list refreshed")))
            self._emit_operation("restart", True, f"{ip} Restarting in progress...")
        else:
            self._emit_operation("restart", False,
                                 f"{ip} Restart failed: {result.get('error', 'unknown device')}")

    def restart_adb(self):
        self.device_model.restart_adb_async()

    def _process_restart_adb_result(self, result: dict):
        if result.get("success"):
            QTimer.singleShot(3000, self.refresh_devices)
            self._emit_operation("restart_adb", True,
                                 f"ADB service has been restarted: {result.get('raw_output', '')}")
        else:
            self._emit_operation("restart_adb", False,
                                 f"ADB restart failed: {result.get('error', 'unknown error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Reboot Modes (new)
    # ═══════════════════════════════════════════════════════════════════════

    def reboot_mode(self, devices: list, mode: str):
        if not devices:
            self._emit_operation("reboot_mode", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.reboot_mode_async(ip, mode)

    def _process_reboot_mode_result(self, result: dict):
        ip = result.get("device_ip", "unknown")
        mode = result.get("mode", "?")
        if result.get("success"):
            QTimer.singleShot(10_000, self.refresh_devices)
            self._emit_operation("reboot_mode", True,
                                 f"{ip} rebooting to {mode}...")
        else:
            self._emit_operation("reboot_mode", False,
                                 f"{ip} reboot failed: {result.get('error', '')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Screenshot & Screen Recording (recording new)
    # ═══════════════════════════════════════════════════════════════════════

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

    def _get_screenshot_dir(self) -> str:
        if self.last_save_dir and os.path.exists(self.last_save_dir):
            return self.last_save_dir
        settings = AppSettings.instance()
        default_dir = settings.save_directory
        os.makedirs(default_dir, exist_ok=True)
        self.last_save_dir = default_dir
        return default_dir

    def _start_screenshot_process(self, device_ip: str, save_dir: str):
        timestamp = datetime.now().strftime("%H%M%S")
        sanitized_ip = re.sub(r'\W+', '_', device_ip)
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
            self._emit_operation("screenshot", False,
                                 f"Failed to capture screenshot on {device_ip}: {error}")
        self._screenshot_remaining -= 1
        if self._screenshot_remaining <= 0 and self._screenshot_paths:
            paths = self._screenshot_paths
            self._screenshot_paths = []
            QTimer.singleShot(0, lambda: self._show_screenshot_viewer(paths))

    def _show_screenshot_viewer(self, image_paths: list):
        viewer = ScreenshotViewer(image_paths)
        viewer.setAttribute(Qt.WA_DeleteOnClose)
        self._active_viewers.append(viewer)
        viewer.destroyed.connect(lambda v=viewer: self._active_viewers.remove(v)
                                 if v in self._active_viewers else None)
        viewer.show()

    # ── Screen Recording ─────────────────────────────────────────────────

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
            self._emit_operation("screen_record", True,
                                 f"Recording started on {ip} ({result['filename']})")
        else:
            self._emit_operation("screen_record", False,
                                 f"Failed to start recording on {ip}: {result.get('error')}")

    def pull_recordings(self, devices: list):
        if not devices:
            self._emit_operation("pull_recording", False, "⚠️ No devices selected")
            return
        for ip in devices:
            info = self._record_info.get(ip, {})
            if info:
                self.advanced_model.pull_recorded_video_async(
                    ip, info["remote_path"], info["save_dir"], info["filename"])
            else:
                self._emit_operation("pull_recording", False,
                                     f"No recording info for {ip}")

    def _process_pull_recorded_video_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("pull_recording", True,
                                 f"Recording pulled from {ip}: {result.get('local_path')}")
        else:
            self._emit_operation("pull_recording", False,
                                 f"Failed to pull recording from {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Input Events (new)
    # ═══════════════════════════════════════════════════════════════════════

    def input_tap(self, devices: list, x: int, y: int):
        if not devices:
            self._emit_operation("input_tap", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.input_tap_async(ip, x, y)

    def _process_input_tap_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("input_tap", True,
                                 f"Tap ({result.get('x')},{result.get('y')}) on {ip}")
        else:
            self._emit_operation("input_tap", False,
                                 f"Tap failed on {ip}: {result.get('error')}")

    def input_swipe(self, devices: list, x1: int, y1: int,
                    x2: int, y2: int, duration_ms: int = 300):
        if not devices:
            self._emit_operation("input_swipe", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.input_swipe_async(ip, x1, y1, x2, y2, duration_ms)

    def _process_input_swipe_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("input_swipe", True, f"Swipe on {ip} completed")
        else:
            self._emit_operation("input_swipe", False,
                                 f"Swipe failed on {ip}: {result.get('error')}")

    def input_keyevent(self, devices: list, keycode: str):
        if not devices:
            self._emit_operation("input_keyevent", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.input_keyevent_async(ip, keycode)

    def _process_input_keyevent_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("input_keyevent", True,
                                 f"Key {result.get('keycode')} sent to {ip}")
        else:
            self._emit_operation("input_keyevent", False,
                                 f"Key event failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Performance Diagnostics (new)
    # ═══════════════════════════════════════════════════════════════════════

    def dumpsys_meminfo(self, devices: list, package: str = ""):
        if not devices:
            self._emit_operation("dumpsys_meminfo", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.dumpsys_meminfo_async(ip, package)

    def _process_dumpsys_meminfo_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("dumpsys_meminfo", True,
                                 f"📊 Memory info ({ip}):\n{result.get('output', '')[:2000]}")
        else:
            self._emit_operation("dumpsys_meminfo", False,
                                 f"Meminfo failed on {ip}: {result.get('error')}")

    def dumpsys_cpuinfo(self, devices: list):
        if not devices:
            self._emit_operation("dumpsys_cpuinfo", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.dumpsys_cpuinfo_async(ip)

    def _process_dumpsys_cpuinfo_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("dumpsys_cpuinfo", True,
                                 f"📊 CPU info ({ip}):\n{result.get('output', '')[:2000]}")
        else:
            self._emit_operation("dumpsys_cpuinfo", False,
                                 f"CPU info failed on {ip}: {result.get('error')}")

    def dumpsys_battery(self, devices: list):
        if not devices:
            self._emit_operation("dumpsys_battery", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.dumpsys_battery_async(ip)

    def _process_dumpsys_battery_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("dumpsys_battery", True,
                                 f"🔋 Battery info ({ip}):\n{result.get('output', '')[:1000]}")
        else:
            self._emit_operation("dumpsys_battery", False,
                                 f"Battery info failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Battery Simulation (new)
    # ═══════════════════════════════════════════════════════════════════════

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
            self._emit_operation("battery_set", True,
                                 f"Battery level set to {result.get('level')}% on {ip}")
        else:
            self._emit_operation("battery_set", False,
                                 f"Battery set failed on {ip}: {result.get('error')}")

    def _process_battery_set_status_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("battery_set", True,
                                 f"Battery status set to '{result.get('status')}' on {ip}")
        else:
            self._emit_operation("battery_set", False,
                                 f"Battery set failed on {ip}: {result.get('error')}")

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
            self._emit_operation("battery_reset", False,
                                 f"Battery reset failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Logcat Filtering (new)
    # ═══════════════════════════════════════════════════════════════════════

    def logcat_filtered(self, devices: list, buffer: str = "main",
                        priority: str = "V", tag_filter: str = "",
                        regex: str = ""):
        if not devices:
            self._emit_operation("logcat_filtered", False, "⚠️ No devices selected")
            return
        save_dir = self._get_screenshot_dir()
        for ip in devices:
            timestamp = datetime.now().strftime("%H%M%S")
            sanitized = re.sub(r'\W+', '_', ip)
            log_path = os.path.join(save_dir, f"logcat_{timestamp}_{sanitized}.txt")
            self.advanced_model.logcat_filtered_async(
                ip, log_path, buffer, priority, tag_filter, regex)

    def _process_logcat_filtered_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("logcat_filtered", True,
                                 f"Filtered log saved for {ip} ({result.get('line_count', 0)} lines)")
        else:
            self._emit_operation("logcat_filtered", False,
                                 f"Logcat filter failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Port Forwarding (new)
    # ═══════════════════════════════════════════════════════════════════════

    def forward_port(self, devices: list, local_port: str, remote_port: str):
        if not devices:
            self._emit_operation("forward_port", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.forward_port_async(ip, local_port, remote_port)

    def _process_forward_port_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("forward_port", True,
                                 f"Forwarded {result.get('local')} → {result.get('remote')} on {ip}")
        else:
            self._emit_operation("forward_port", False,
                                 f"Forward failed on {ip}: {result.get('error')}")

    def list_forwards(self, devices: list):
        if not devices:
            self._emit_operation("list_forwards", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.list_forwards_async(ip)

    def _process_list_forwards_result(self, result: dict):
        ip = result.get("device_ip", "")
        output = result.get("output", "")
        if result.get("success"):
            self._emit_operation("list_forwards", True,
                                 f"Forward rules ({ip}):\n{output}" if output else f"No forward rules on {ip}")
        else:
            self._emit_operation("list_forwards", False,
                                 f"List forwards failed on {ip}: {result.get('error')}")

    def remove_forwards(self, devices: list):
        if not devices:
            self._emit_operation("remove_forwards", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.remove_all_forwards_async(ip)

    def _process_remove_all_forwards_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("remove_forwards", True, f"All forward rules removed on {ip}")
        else:
            self._emit_operation("remove_forwards", False,
                                 f"Remove forwards failed on {ip}: {result.get('error')}")

    def reverse_port(self, devices: list, remote_port: str, local_port: str):
        if not devices:
            self._emit_operation("reverse_port", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.reverse_port_async(ip, remote_port, local_port)

    def _process_reverse_port_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("reverse_port", True,
                                 f"Reverse forwarded on {ip}")
        else:
            self._emit_operation("reverse_port", False,
                                 f"Reverse forward failed on {ip}: {result.get('error')}")

    def list_reverse(self, devices: list):
        if not devices:
            self._emit_operation("list_reverse", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.list_reverse_async(ip)

    def _process_list_reverse_result(self, result: dict):
        ip = result.get("device_ip", "")
        output = result.get("output", "")
        if result.get("success"):
            self._emit_operation("list_reverse", True,
                                 f"Reverse rules ({ip}):\n{output}" if output else f"No reverse rules on {ip}")
        else:
            self._emit_operation("list_reverse", False,
                                 f"List reverse failed on {ip}: {result.get('error')}")

    def remove_reverse(self, devices: list):
        if not devices:
            self._emit_operation("remove_reverse", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.remove_all_reverse_async(ip)

    def _process_remove_all_reverse_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("remove_reverse", True,
                                 f"All reverse rules removed on {ip}")
        else:
            self._emit_operation("remove_reverse", False,
                                 f"Remove reverse failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Settings (new)
    # ═══════════════════════════════════════════════════════════════════════

    def settings_list(self, devices: list, namespace: str = "system"):
        if not devices:
            self._emit_operation("settings_list", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.settings_list_async(ip, namespace)

    def _process_settings_list_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            ns = result.get("namespace", "")
            self._emit_operation("settings_list", True,
                                 f"Settings [{ns}] ({ip}):\n{result.get('output', '')[:2000]}")
        else:
            self._emit_operation("settings_list", False,
                                 f"Settings list failed on {ip}: {result.get('error')}")

    def settings_get(self, devices: list, namespace: str, key: str):
        if not devices:
            self._emit_operation("settings_get", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.settings_get_async(ip, namespace, key)

    def _process_settings_get_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("settings_get", True,
                                 f"Setting [{result.get('key')}] = {result.get('value')} on {ip}")
        else:
            self._emit_operation("settings_get", False,
                                 f"Settings get failed on {ip}: {result.get('error')}")

    def settings_put(self, devices: list, namespace: str, key: str, value: str):
        if not devices:
            self._emit_operation("settings_put", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.settings_put_async(ip, namespace, key, value)

    def _process_settings_put_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("settings_put", True,
                                 f"Set {result.get('key')}={result.get('value')} on {ip}")
        else:
            self._emit_operation("settings_put", False,
                                 f"Settings put failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Shell Command (new)
    # ═══════════════════════════════════════════════════════════════════════

    def run_shell_command(self, devices: list, command: str):
        if not devices:
            self._emit_operation("shell_command", False, "⚠️ No devices selected")
            return
        if not command.strip():
            self._emit_operation("shell_command", False, "⚠️ Command cannot be empty")
            return
        for ip in devices:
            self.advanced_model.run_shell_command_async(ip, command)

    def _process_run_shell_command_result(self, result: dict):
        ip = result.get("device_ip", "")
        cmd = result.get("command", "")
        if result.get("success"):
            self._emit_operation("shell_command", True,
                                 f"Shell [{ip}] `{cmd}`:\n{result.get('output', '')}")
        else:
            self._emit_operation("shell_command", False,
                                 f"Shell failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # File Manager (new)
    # ═══════════════════════════════════════════════════════════════════════

    def file_list(self, devices: list, path: str = "/sdcard"):
        if not devices:
            self._emit_operation("file_list", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.shell_ls_async(ip, path)

    def _process_shell_ls_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("file_list", True,
                                 f"📁 {result.get('path', '')} ({ip}):\n{result.get('output', '')[:2000]}")
        else:
            self._emit_operation("file_list", False,
                                 f"File list failed on {ip}: {result.get('error')}")

    def file_push(self, devices: list, local_path: str, remote_path: str):
        if not devices:
            self._emit_operation("file_push", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.push_file_async(ip, local_path, remote_path)

    def _process_push_file_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("file_push", True,
                                 f"File pushed to {ip}: {result.get('output', '')}")
        else:
            self._emit_operation("file_push", False,
                                 f"Push failed on {ip}: {result.get('error')}")

    def file_pull(self, devices: list, remote_path: str):
        if not devices:
            self._emit_operation("file_pull", False, "⚠️ No devices selected")
            return
        save_dir = self._get_screenshot_dir()
        for ip in devices:
            filename = os.path.basename(remote_path) or f"pulled_{datetime.now().strftime('%H%M%S')}"
            local_path = os.path.join(save_dir, filename)
            self.advanced_model.pull_file_async(ip, remote_path, local_path)

    def _process_pull_file_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("file_pull", True,
                                 f"File pulled from {ip}: {result.get('output', '')}")
        else:
            self._emit_operation("file_pull", False,
                                 f"Pull failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # App Permissions (new)
    # ═══════════════════════════════════════════════════════════════════════

    def grant_permission(self, devices: list, package: str, permission: str):
        if not devices:
            self._emit_operation("grant_permission", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.grant_permission_async(ip, package, permission)

    def _process_grant_permission_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("grant_permission", True,
                                 f"Granted {result.get('permission')} to {result.get('package')} on {ip}")
        else:
            self._emit_operation("grant_permission", False,
                                 f"Grant failed on {ip}: {result.get('error')}")

    def revoke_permission(self, devices: list, package: str, permission: str):
        if not devices:
            self._emit_operation("revoke_permission", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.revoke_permission_async(ip, package, permission)

    def _process_revoke_permission_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("revoke_permission", True,
                                 f"Revoked {result.get('permission')} from {result.get('package')} on {ip}")
        else:
            self._emit_operation("revoke_permission", False,
                                 f"Revoke failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # App Disable/Enable (new)
    # ═══════════════════════════════════════════════════════════════════════

    def disable_app(self, devices: list, package: str):
        if not devices:
            self._emit_operation("disable_app", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.disable_package_async(ip, package)

    def _process_disable_package_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("disable_app", True,
                                 f"Disabled {result.get('package')} on {ip}")
        else:
            self._emit_operation("disable_app", False,
                                 f"Disable failed on {ip}: {result.get('error')}")

    def enable_app(self, devices: list, package: str):
        if not devices:
            self._emit_operation("enable_app", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.enable_package_async(ip, package)

    def _process_enable_package_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("enable_app", True,
                                 f"Enabled {result.get('package')} on {ip}")
        else:
            self._emit_operation("enable_app", False,
                                 f"Enable failed on {ip}: {result.get('error')}")

    def force_stop(self, devices: list, package: str):
        if not devices:
            self._emit_operation("force_stop", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.force_stop_async(ip, package)

    def _process_force_stop_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("force_stop", True, f"Force stopped app on {ip}")
        else:
            self._emit_operation("force_stop", False,
                                 f"Force stop failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Broadcast & Activity (new)
    # ═══════════════════════════════════════════════════════════════════════

    def send_broadcast(self, devices: list, action: str):
        if not devices:
            self._emit_operation("send_broadcast", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.send_broadcast_async(ip, action)

    def _process_send_broadcast_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("send_broadcast", True,
                                 f"Broadcast sent on {ip}:\n{result.get('output', '')}")
        else:
            self._emit_operation("send_broadcast", False,
                                 f"Broadcast failed on {ip}: {result.get('error')}")

    def start_activity(self, devices: list, component_or_action: str):
        if not devices:
            self._emit_operation("start_activity", False, "⚠️ No devices selected")
            return
        spec = component_or_action.strip()
        for ip in devices:
            if "/" in spec:
                self.advanced_model.start_activity_async(ip, component=spec)
            elif spec.startswith("http"):
                self.advanced_model.open_deep_link_async(ip, spec)
            else:
                self.advanced_model.start_activity_async(ip, action=spec)

    def _process_start_activity_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("start_activity", True,
                                 f"Activity started on {ip}:\n{result.get('output', '')}")
        else:
            self._emit_operation("start_activity", False,
                                 f"Start activity failed on {ip}: {result.get('error')}")

    def open_deep_link(self, devices: list, uri: str):
        if not devices:
            self._emit_operation("deep_link", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.open_deep_link_async(ip, uri)

    def _process_open_deep_link_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("deep_link", True,
                                 f"Deep link opened on {ip}: {result.get('uri')}")
        else:
            self._emit_operation("deep_link", False,
                                 f"Deep link failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Wireless Pairing (new)
    # ═══════════════════════════════════════════════════════════════════════

    def pair_device(self, ip: str, port: str, pairing_code: str):
        if not ip:
            self._emit_operation("pair_device", False, "⚠️ IP address cannot be empty")
            return
        self.advanced_model.pair_device_async(ip, port, pairing_code)

    def _process_pair_device_result(self, result: dict):
        ip = result.get("ip", "")
        if result.get("success"):
            self._emit_operation("pair_device", True,
                                 f"Paired with {ip}: {result.get('output', '')}")
        else:
            self._emit_operation("pair_device", False,
                                 f"Pairing failed: {result.get('error')}")

    def tcpip_mode(self, devices: list, port: str = "5555"):
        if not devices:
            self._emit_operation("tcpip_mode", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.tcpip_mode_async(ip, port)

    def _process_tcpip_mode_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("tcpip_mode", True,
                                 f"ADB over TCP/IP enabled on {ip}:{result.get('port')}")
        else:
            self._emit_operation("tcpip_mode", False,
                                 f"TCP/IP mode failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Process Management (new)
    # ═══════════════════════════════════════════════════════════════════════

    def list_processes(self, devices: list):
        if not devices:
            self._emit_operation("list_processes", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.list_processes_async(ip)

    def _process_list_processes_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("list_processes", True,
                                 f"Processes ({ip}):\n{result.get('output', '')[:2000]}")
        else:
            self._emit_operation("list_processes", False,
                                 f"Process list failed on {ip}: {result.get('error')}")

    def kill_process(self, devices: list, pid: str):
        if not devices:
            self._emit_operation("kill_process", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.kill_process_async(ip, pid)

    def _process_kill_process_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("kill_process", True,
                                 f"Killed PID {result.get('pid')} on {ip}")
        else:
            self._emit_operation("kill_process", False,
                                 f"Kill failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Content Provider (new)
    # ═══════════════════════════════════════════════════════════════════════

    def content_query(self, devices: list, uri: str):
        if not devices:
            self._emit_operation("content_query", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.content_query_async(ip, uri)

    def _process_content_query_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("content_query", True,
                                 f"Content query ({ip}):\n{result.get('output', '')[:2000]}")
        else:
            self._emit_operation("content_query", False,
                                 f"Content query failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Quick Settings (new)
    # ═══════════════════════════════════════════════════════════════════════

    def quick_setting(self, devices: list, action: str):
        if not devices:
            self._emit_operation("quick_setting", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.quick_setting_async(ip, action)

    def _process_quick_setting_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("quick_setting", True,
                                 f"Quick setting '{result.get('action')}' applied on {ip}")
        else:
            self._emit_operation("quick_setting", False,
                                 f"Quick setting failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # IME Management (new)
    # ═══════════════════════════════════════════════════════════════════════

    def ime_list(self, devices: list):
        if not devices:
            self._emit_operation("ime_list", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.ime_list_async(ip)

    def _process_ime_list_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("ime_list", True,
                                 f"IME list ({ip}):\n{result.get('output', '')}")
        else:
            self._emit_operation("ime_list", False,
                                 f"IME list failed on {ip}: {result.get('error')}")

    def ime_set(self, devices: list, ime_id: str):
        if not devices:
            self._emit_operation("ime_set", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.ime_set_async(ip, ime_id)

    def _process_ime_set_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("ime_set", True, f"IME set on {ip}")
        else:
            self._emit_operation("ime_set", False,
                                 f"IME set failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Emulator Control (new)
    # ═══════════════════════════════════════════════════════════════════════

    def emu_sms(self, devices: list, sender: str, text: str):
        if not devices:
            self._emit_operation("emu_sms", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.emu_sms_send_async(ip, sender, text)

    def _process_emu_sms_send_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("emu_sms", True,
                                 f"SMS from {result.get('sender')} sent to {ip}")
        else:
            self._emit_operation("emu_sms", False,
                                 f"Emu SMS failed on {ip}: {result.get('error')}")

    def emu_call(self, devices: list, number: str):
        if not devices:
            self._emit_operation("emu_call", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.emu_call_async(ip, number)

    def _process_emu_call_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("emu_call", True, f"Call to {result.get('number')} on {ip}")
        else:
            self._emit_operation("emu_call", False,
                                 f"Emu call failed on {ip}: {result.get('error')}")

    def emu_geo(self, devices: list, longitude: str, latitude: str):
        if not devices:
            self._emit_operation("emu_geo", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.emu_geo_fix_async(ip, longitude, latitude)

    def _process_emu_geo_fix_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("emu_geo", True,
                                 f"GPS set on {ip}: {result.get('longitude')},{result.get('latitude')}")
        else:
            self._emit_operation("emu_geo", False,
                                 f"Emu geo failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Package Info Extended (new)
    # ═══════════════════════════════════════════════════════════════════════

    def pm_features(self, devices: list):
        if not devices:
            self._emit_operation("pm_features", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.pm_list_features_async(ip)

    def _process_pm_list_features_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("pm_features", True,
                                 f"Features ({ip}):\n{result.get('output', '')[:2000]}")
        else:
            self._emit_operation("pm_features", False,
                                 f"Features list failed on {ip}: {result.get('error')}")

    def device_uptime(self, devices: list):
        if not devices:
            self._emit_operation("device_uptime", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.get_device_uptime_async(ip)

    def _process_get_device_uptime_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("device_uptime", True,
                                 f"Uptime ({ip}): {result.get('output', '')}")
        else:
            self._emit_operation("device_uptime", False,
                                 f"Uptime failed on {ip}: {result.get('error')}")

    # ═══════════════════════════════════════════════════════════════════════
    # Existing App Operations (keep as-is)
    # ═══════════════════════════════════════════════════════════════════════

    def retrieve_device_logs(self, devices: list):
        if not devices:
            self._emit_operation("retrieve_device_logs", False, "⚠️ No devices selected")
            return
        save_dir = self._get_screenshot_dir()
        if not save_dir:
            self._emit_operation("retrieve_device_logs", False, "No directory selected")
            return
        for device_ip in devices:
            self._save_single_device_log(device_ip, save_dir)

    def _save_single_device_log(self, device_ip: str, save_dir: str):
        timestamp = datetime.now().strftime("%H%M%S")
        sanitized_ip = re.sub(r'\W+', '_', device_ip)
        log_path = os.path.join(save_dir, f"log_{timestamp}_{sanitized_ip}.txt")
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("retrieve_device_logs", device_ip)
        self.testing_model.retrieve_device_logs_async(device_ip, log_path)

    def _process_retrieve_logs_result(self, result: dict):
        device_ip = result.get("device_ip")
        log_path = result.get("log_path")
        if result.get("success"):
            self._emit_operation("retrieve_device_logs", True,
                                 f"✅ Log saved for {device_ip} at {log_path}")
            self.signals.logs_retrieved.emit(device_ip, log_path)
        else:
            error = result.get("error", "Unknown error")
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            self._emit_operation("retrieve_device_logs", False,
                                 f"Failed to save log for {device_ip}: {error_msg}")

    def cleanup_device_logs(self, devices: list):
        if not devices:
            self._emit_operation("cleanup_device_logs", False, "⚠️ No devices selected")
            return
        for device_ip in devices:
            operation_id = self._generate_operation_id()
            self._pending_operations[operation_id] = ("cleanup_device_logs", device_ip)
            self.testing_model.cleanup_device_logs_async(device_ip)

    def _process_cleanup_logs_result(self, result: dict):
        device_ip = result.get("device_ip")
        if result.get("success"):
            self._emit_operation("cleanup_device_logs", True, f"✅ Log cleared for {device_ip}")
        else:
            error = result.get("error", "Unknown error")
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            self._emit_operation("cleanup_device_logs", False,
                                 f"Failed to clear log for {device_ip}: {error_msg}")

    def input_text(self, devices: list, text: str):
        if not devices:
            self._emit_operation("input_text", False, "⚠️ No devices selected")
            return
        if not text.strip():
            self._emit_operation("input_text", False, "⚠️ Input text cannot be empty")
            return
        for device_ip in devices:
            self._send_text_to_device(device_ip, text)

    def _send_text_to_device(self, device_ip: str, text: str):
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("input_text", device_ip)
        self.app_model.input_text_async(device_ip, text)

    def _process_input_text_result(self, result: dict):
        device_ip = result.get("device_ip")
        text = result.get("text", "")
        if result.get("success"):
            self._emit_operation("input_text", True, f"Text '{text}' input on {device_ip}")
            self.signals.text_input.emit(device_ip, text)
        else:
            error = result.get("error", "Unknown error")
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            self._emit_operation("input_text", False,
                                 f"Failed to input text on {device_ip}: {error_msg}")

    def get_current_package(self, devices: list):
        if not devices:
            self._emit_operation("get_package", False, "⚠️ No devices selected")
            return
        for device_ip in devices:
            self.executor.submit(self._get_single_device_package, device_ip)

    def _get_single_device_package(self, device_ip: str):
        operation_id = self._generate_operation_id()
        self._pending_operations[operation_id] = ("get_package", device_ip)
        self.app_model.get_current_package_async(device_ip)

    def _process_get_package_result(self, result: dict):
        device_ip = result.get("device_ip")
        if result.get("success"):
            package_name = result["package_name"]
            self._emit_operation("get_package", True,
                                 f"Current package on {device_ip}: {package_name}")
            self.signals.current_package_received.emit(device_ip, package_name)
        else:
            error = result.get("error", "Unknown error")
            self._emit_operation("get_package", False,
                                 f"Failed to get package on {device_ip}: {error}")

    def install_apk(self, devices: list):
        if not devices:
            self._emit_operation("install", False, "⚠️ No devices selected")
            return
        apk_path, _ = QFileDialog.getOpenFileName(
            None, "Select APK File", "", "APK Files (*.apk);;All Files (*)")
        if not apk_path:
            self._emit_operation("install", False, "APK selection canceled")
            return
        apk_name = os.path.basename(apk_path)
        self._batch_trackers["install"] = BatchOperationTracker(
            len(devices), "Install App", self._emit_operation)
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self._install_single_device, idx, device_ip, apk_path, apk_name)

    def batch_install_apk(self, devices: list):
        if not devices:
            self._emit_operation("batch_install", False, "⚠️ No devices selected")
            return
        apk_paths, _ = QFileDialog.getOpenFileNames(
            None, "Select APK files to install", "", "APK Files (*.apk);;All Files (*)")
        if not apk_paths:
            self._emit_operation("batch_install", False, "APK selection canceled")
            return
        total_tasks = len(devices) * len(apk_paths)
        self._batch_trackers["batch_install"] = BatchOperationTracker(
            total_tasks, "Batch Install", self._emit_operation)
        for apk_path in apk_paths:
            apk_name = os.path.basename(apk_path)
            for idx, device_ip in enumerate(devices, 1):
                self.executor.submit(self._install_single_device, idx, device_ip, apk_path, apk_name)
        self._emit_operation("batch_install", True,
                             f"Queued {len(apk_paths)} APKs → {len(devices)} devices ({total_tasks} tasks)")

    def _install_single_device(self, idx: int, device_ip: str, apk_path: str, apk_name: str):
        tracker = self._batch_trackers.get("install")
        total = tracker.total if tracker else "?"
        self._emit_operation("install", True,
                             f"Start install ({idx}/{total}) {apk_name} on {device_ip} ...")
        self.app_model.install_apk_async(device_ip, apk_path, apk_name, idx)

    def _process_install_apk_result(self, result: dict):
        apk_name = result.get("apk_name")
        device_ip = result.get("device_ip")
        idx = result.get("index", 1)
        success = result.get("success")
        tracker = self._batch_trackers.get("install")
        progress = tracker.record(success) if tracker else ""
        if success:
            self._emit_operation("install", True,
                                 f"✅ install success {progress} {apk_name} on {device_ip}")
        else:
            self._emit_operation("install", False,
                                 f"❌ install failed {progress} {apk_name} on {device_ip}\n"
                                 f"Error: {result.get('error', 'Unknown error')}")

    def uninstall_apk(self, devices: list, package_name: str):
        if not devices:
            self._emit_operation("uninstall", False, "⚠️ No devices selected")
            return
        if not package_name:
            self._emit_operation("uninstall", False, "⚠️ No package name provided")
            return
        self._batch_trackers["uninstall"] = BatchOperationTracker(
            len(devices), "Uninstall App", self._emit_operation)
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self._execute_uninstall_task, idx, device_ip, package_name)

    def _execute_uninstall_task(self, idx: int, device_ip: str, package_name: str):
        tracker = self._batch_trackers.get("uninstall")
        total = tracker.total if tracker else "?"
        self._emit_operation("uninstall", True,
                             f"Start uninstall ({idx}/{total}) {package_name} on {device_ip} ...")
        self.app_model.uninstall_app_async(device_ip, package_name, idx)

    def _process_uninstall_apk_result(self, result: dict):
        idx = result.get("index", 1)
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        success = result.get("success")
        tracker = self._batch_trackers.get("uninstall")
        progress = tracker.record(success) if tracker else ""
        if success:
            self._emit_operation("uninstall", True,
                                 f"✅ uninstall success {progress} {pkg} on {ip}")
        else:
            self._emit_operation("uninstall", False,
                                 f"❌ uninstall failed {progress} {pkg} on {ip}")

    def clear_app_data(self, devices: list, package_name: str):
        if not devices:
            self._emit_operation("clear_data", False, "⚠️ No devices selected")
            return
        if not package_name:
            self._emit_operation("clear_data", False, "⚠️ No package name provided")
            return
        self._batch_trackers["clear_data"] = BatchOperationTracker(
            len(devices), "Clear App Data", self._emit_operation)
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.app_model.clear_app_data_async, device_ip, package_name, idx)

    def _process_clear_app_data_result(self, result: dict):
        idx = result.get("index", 1)
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        success = result.get("success")
        tracker = self._batch_trackers.get("clear_data")
        progress = tracker.record(success) if tracker else ""
        if success:
            self._emit_operation("clear_data", True,
                                 f"✅ clear data success {progress} {pkg} on {ip}")
        else:
            self._emit_operation("clear_data", False,
                                 f"❌ clear data failed {progress} {pkg} on {ip}")

    def restart_app(self, devices: list, package_name: str):
        if not devices:
            self._emit_operation("restart_app", False, "⚠️ No devices selected")
            return
        if not package_name:
            self._emit_operation("restart_app", False, "⚠️ No package name provided")
            return
        self._batch_trackers["restart_app"] = BatchOperationTracker(
            len(devices), "Restart App", self._emit_operation)
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.app_model.restart_app_async, device_ip, package_name, idx)

    def _process_restart_app_result(self, result: dict):
        idx = result.get("index", 1)
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        output = result.get("output", "").strip()
        success = result.get("success")
        tracker = self._batch_trackers.get("restart_app")
        progress = tracker.record(success) if tracker else ""
        if success:
            msg = (f"✅ Restart Success {progress}\n"
                   f"   📦 Package : {pkg}\n   🌐 Device  : {ip}\n"
                   f"   📤 Output  :\n{self._indent_output(output)}")
            self._emit_operation("restart_app", True, msg)
        else:
            msg = (f"❌ Restart Failed {progress}\n"
                   f"   📦 Package : {pkg}\n   🌐 Device  : {ip}\n"
                   f"   ⚠️ Error   :\n{self._indent_output(output)}")
            self._emit_operation("restart_app", False, msg)

    def _indent_output(self, text: str, prefix: str = "     ") -> str:
        return "\n".join(f"{prefix}{line}" for line in text.splitlines() if line.strip())

    def get_current_activity(self, devices: list[str]):
        if not devices:
            self._emit_operation("current_activity", False, "⚠️ No device selected")
            return
        self._batch_trackers["current_activity"] = BatchOperationTracker(
            len(devices), "Activity Info", self._emit_operation)
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.app_model.get_current_activity_async, device_ip, idx)

    def _process_get_current_activity_result(self, result: dict):
        device = result.get("device_ip", "unknown")
        idx = result.get("index", 0)
        success = result.get("success", False)
        focus = result.get("current_focus", "").strip()
        resumed = result.get("resumed_activity", "").strip()
        error = result.get("error", "").strip()
        tracker = self._batch_trackers.get("current_activity")
        progress = tracker.record(success) if tracker else ""
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
            msg = f"❌ Failed to get activity on ({idx}) {device} {progress}\n{self._indent_output(error)}"
            self._emit_operation("current_activity", False, msg)

    def parse_apk_info(self):
        apk_path, _ = QFileDialog.getOpenFileName(
            None, "Select APK File", "", "APK Files (*.apk);;All Files (*)")
        if not apk_path:
            self._emit_operation("apk_info", False, "⚠️ APK file selection cancelled")
            return
        if not apk_path.endswith(".apk"):
            self._emit_operation("apk_info", False, f"❌ Invalid APK file selected: {apk_path}")
            return
        self._emit_operation("apk_info", True, f"📦 Selected APK: {apk_path}")
        self.executor.submit(self.app_model.parse_apk_info_async, apk_path)

    def _process_parse_apk_info_result(self, result: dict):
        apk_path = result.get("apk_path", "unknown")
        if result.get("success"):
            raw_output = result.get("output", "")
            try:
                package_name = re.search(r"package: name='(.*?)'", raw_output)
                version_code = re.search(r"versionCode='(.*?)'", raw_output)
                version_name = re.search(r"versionName='(.*?)'", raw_output)
                min_sdk = re.search(r"sdkVersion:'(.*?)'", raw_output)
                target_sdk = re.search(r"targetSdkVersion:'(.*?)'", raw_output)
                compile_sdk = re.search(r"compileSdkVersion='(.*?)'", raw_output)
                build_version = re.search(r"platformBuildVersionName='(.*?)'", raw_output)
                label_match = re.search(r"application-label(?:-[\w\-]+)?:'(.*?)'", raw_output)
                app_label = label_match.group(1) if label_match else "N/A"
                icon_match = re.search(r"application: label='.*?' icon='(.*?)'", raw_output)
                icon_path = icon_match.group(1) if icon_match else "N/A"
                permissions = re.findall(r"uses-permission: name='(.*?)'", raw_output)
                features = re.findall(r"uses-feature(?:-not-required)?: name='(.*?)'", raw_output)
                native_code = re.findall(r"native-code: '(.*?)'", raw_output)
                formatted = f"""
    🔹 App: {app_label}
    📦 Package: {package_name.group(1) if package_name else 'N/A'}
    🔢 Version: {version_name.group(1) if version_name else 'N/A'} (Code: {version_code.group(1) if version_code else 'N/A'})
    🎯 SDK: min={min_sdk.group(1) if min_sdk else 'N/A'}, target={target_sdk.group(1) if target_sdk else 'N/A'}, compile={compile_sdk.group(1) if compile_sdk else 'N/A'}
    🛠️ Build: {build_version.group(1) if build_version else 'N/A'}
    🖼️ Icon: {icon_path}
    🔐 Permissions: {len(permissions)} items
    ⚙️ Features: {", ".join(features) if features else "None"}
    🧬 Architectures: {", ".join(native_code) if native_code else "None"}
    """
                self._emit_operation("apk_info", True, formatted)
            except Exception as e:
                self._emit_operation("apk_info", False,
                                     f"⚠️ APK Field parsing exception: {apk_path}\nError: {str(e)}")
        else:
            error = result.get("error", "Unknown error")
            self._emit_operation("apk_info", False,
                                 f"❌ APK Analysis failed: {apk_path}\nError: {error}")

    def kill_monkey(self, devices: list):
        if not devices:
            self._emit_operation("kill_monkey", False, "⚠️ No devices selected")
            return
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.testing_model.kill_monkey_async, device_ip, idx)

    def _process_kill_monkey_result(self, result: dict):
        device_ip = result.get("device_ip")
        idx = result.get("index")
        if result.get("success"):
            self._emit_operation("kill_monkey", True,
                                 f"✅ {idx}. Monkey process killed on {device_ip}")
        else:
            self._emit_operation("kill_monkey", False,
                                 f"❌ {idx}. Failed to kill monkey on {device_ip}:\nError: {result['message']}")

    def list_installed_packages(self, devices: list[str]):
        if not devices:
            self._emit_operation("installed_packages", False, "⚠️ No devices selected")
            return
        for idx, device_ip in enumerate(devices, 1):
            self.executor.submit(self.app_model.list_installed_packages_async, device_ip, idx)

    def _process_list_installed_packages_result(self, result: dict):
        device_ip = result.get("device_ip")
        idx = result.get("index")
        if result.get("success"):
            packages = result.get("packages", [])
            formatted = "\n".join(f"{i+1}. {pkg}" for i, pkg in enumerate(packages))
            msg = f"📦 {idx}. Installed packages on {device_ip}:\n{formatted or '(None found)'}"
            self._emit_operation("installed_packages", True, msg)
        else:
            msg = result.get("message", "Unknown error")
            self._emit_operation("installed_packages", False,
                                 f"❌ {idx}. Failed to get packages from {device_ip}:\n{msg}")

    def capture_bugreport(self, devices: list):
        if not devices:
            self._emit_operation("bugreport", False, "⚠️ No devices selected.")
            return
        save_dir = QFileDialog.getExistingDirectory(None, "Select directory to save ANR files")
        log = self.log_service.log
        for idx, device in enumerate(devices, 1):
            self.executor.submit(
                self.testing_model.capture_bugreport_async, device, save_dir, idx,
                callback=lambda msg: log(LogLevel.INFO, msg))

    def _process_capture_bugreport_result(self, result: dict):
        device_ip = result.get("device_ip")
        idx = result.get("index")
        success = result.get("success", False)
        message = result.get("message", "")
        if success:
            bug_path = result.get("bugreport_path")
            self._emit_operation("bugreport", True,
                                 f"✅ {idx}. Bugreport saved from {device_ip}:\n{bug_path}")
        else:
            self._emit_operation("bugreport", False,
                                 f"❌ {idx}. Failed on {device_ip}:\n{message}")

    def pull_anr_files(self, devices: list[str]):
        if not devices:
            self._emit_operation("pull_anr", False, "⚠️ No devices selected")
            return
        save_dir = QFileDialog.getExistingDirectory(None, "Select directory to save ANR files")
        if not save_dir:
            self._emit_operation("pull_anr", False, "⚠️ No target directory selected")
            return
        timestamp = datetime.now().strftime("%H%M%S")
        for idx, device_ip in enumerate(devices, 1):
            sanitized_name = re.sub(r'\W+', '_', device_ip)
            self.executor.submit(
                self.testing_model.pull_anr_files_async,
                device_ip, f"{sanitized_name}_anr_{timestamp}", save_dir, idx)

    def _process_pull_anr_result(self, result: dict):
        device_ip = result.get("device_ip", "unknown")
        idx = result.get("index", "?")
        if result.get("success"):
            self._emit_operation("pull_anr", True,
                                 f"✅ {idx}. Pulled ANR files from {device_ip}:\n{result['message']}")
        else:
            self._emit_operation("pull_anr", False,
                                 f"❌ {idx}. Failed to pull ANR from {device_ip}:\n{result['message']}")

    def run_monkey_test(self, devices: list, device_type: str, package_name: str, count: str):
        if not devices:
            return self._emit_operation("monkey", False, "⚠️ No devices selected")
        if not device_type:
            return self._emit_operation("monkey", False, "⚠️ No device type selected")
        if not package_name:
            return self._emit_operation("monkey", False, "⚠️ No package name provided")
        if not count:
            return self._emit_operation("monkey", False, "⚠️ No monkey count provided")
        save_dir = QFileDialog.getExistingDirectory(None, "Select directory to save Monkey logs")
        if not save_dir:
            return self._emit_operation("monkey", False, "⚠️ No target directory selected")
        log = self.log_service.log
        log(LogLevel.INFO, f"📦 Starting Monkey tests on {len(devices)} devices...")
        log(LogLevel.INFO, f"📁 Log save directory: {save_dir}")
        for idx, device_ip in enumerate(devices, 1):
            sanitized_name = re.sub(r'\W+', '_', device_ip)
            self.executor.submit(
                self.testing_model.run_monkey_test_async,
                device_ip, package_name, count, device_type,
                sanitized_name, save_dir, idx,
                callback=lambda msg: self.log_service.log(LogLevel.INFO, msg))

    def _process_run_monkey_test_result(self, result: dict):
        device_ip = result.get("device_ip", "unknown")
        duration = result.get("duration", "N/A")
        monkey_log = result.get("monkey_log", "")
        logcat_log = result.get("logcat_log", "")
        error = result.get("error", "None")
        if result.get("success"):
            message = (
                "\n╔════════════════════════════════════════════════════════════════╗\n"
                f"║ ✅ Monkey Test Report - Device: {device_ip}\n"
                "╠════════════════════════════════════════════════════════════════╣\n"
                f"║ ⏱️ Duration: {duration}\n"
                f"║ 📄 Monkey Log: {monkey_log}\n"
                f"║ 📄 Logcat Log: {logcat_log}\n"
                "╚════════════════════════════════════════════════════════════════╝")
        else:
            message = (
                "\n╔════════════════════════════════════════════════════════════════╗\n"
                f"║ ❌ Monkey Test Failed - Device: {device_ip}\n"
                "╠════════════════════════════════════════════════════════════════╣\n"
                f"║ ⏱️ Duration: {duration}\n"
                f"║ 💥 Error: {error[:200]}{'...' if len(error)>200 else ''}\n"
                f"║ 🔍 Detailed Log: {monkey_log}\n"
                "╚════════════════════════════════════════════════════════════════╝")
        return self._emit_operation("monkey", result.get("success"), message)

    def get_random_email_and_code(self):
        task = GetRandomEmailTask()
        self._email_task = task
        task.signals.log_signal.connect(self.log_service.log)
        task.signals.email_updated.connect(self.signals.email_updated)
        task.signals.vercode_updated.connect(self.signals.vercode_updated)
        self.thread_pool.start(task)

    # ═══════════════════════════════════════════════════════════════════════
    # Signal & Handler Infrastructure
    # ═══════════════════════════════════════════════════════════════════════

    @Slot(str, bool, str)
    def _emit_operation(self, operation: str, success: bool, message: str):
        level = "INFO" if success else "ERROR"
        if not message.strip():
            return
        self.log_service.log(level, f"{message}")
        self.signals.operation_completed.emit(operation, success, message)

    def _handle_async_response(self, method_name: str, result):
        op_type = method_name.replace("_async", "")

        if isinstance(result, str) and result.startswith("AsyncError:"):
            error_msg = result[11:]
            self.log_service.log("ERROR", f"[{op_type}] {error_msg}")
            self._emit_operation(op_type, False, error_msg)
            return

        if op_type == "get_connected_devices":
            if isinstance(result, list):
                self._process_device_list(result)
            else:
                self._emit_operation(op_type, False, "Invalid device list format")
            return

        handler_map = {
            # Existing
            "connect_device": self._process_connect_device_result,
            "disconnect_device": self._process_disconnect_result,
            "get_device_info": self._process_device_info_result,
            "restart_device": self._process_restart_devices_result,
            "restart_adb": self._process_restart_adb_result,
            "take_screenshot": self._process_screenshot_result,
            "retrieve_device_logs": self._process_retrieve_logs_result,
            "cleanup_device_logs": self._process_cleanup_logs_result,
            "input_text": self._process_input_text_result,
            "get_current_package": self._process_get_package_result,
            "install_apk": self._process_install_apk_result,
            "uninstall_app": self._process_uninstall_apk_result,
            "clear_app_data": self._process_clear_app_data_result,
            "restart_app": self._process_restart_app_result,
            "get_current_activity": self._process_get_current_activity_result,
            "parse_apk_info": self._process_parse_apk_info_result,
            "run_monkey_test": self._process_run_monkey_test_result,
            "kill_monkey": self._process_kill_monkey_result,
            "list_installed_packages": self._process_list_installed_packages_result,
            "capture_bugreport": self._process_capture_bugreport_result,
            "pull_anr_files": self._process_pull_anr_result,
            # New - Reboot
            "reboot_mode": self._process_reboot_mode_result,
            # New - Screen Record
            "start_screen_record": self._process_start_screen_record_result,
            "pull_recorded_video": self._process_pull_recorded_video_result,
            # New - Input
            "input_tap": self._process_input_tap_result,
            "input_swipe": self._process_input_swipe_result,
            "input_keyevent": self._process_input_keyevent_result,
            # New - Performance
            "dumpsys_meminfo": self._process_dumpsys_meminfo_result,
            "dumpsys_cpuinfo": self._process_dumpsys_cpuinfo_result,
            "dumpsys_battery": self._process_dumpsys_battery_result,
            # New - Battery Sim
            "battery_set_level": self._process_battery_set_level_result,
            "battery_set_status": self._process_battery_set_status_result,
            "battery_reset": self._process_battery_reset_result,
            # New - Logcat
            "logcat_filtered": self._process_logcat_filtered_result,
            # New - Port Forward
            "forward_port": self._process_forward_port_result,
            "list_forwards": self._process_list_forwards_result,
            "remove_all_forwards": self._process_remove_all_forwards_result,
            "reverse_port": self._process_reverse_port_result,
            "list_reverse": self._process_list_reverse_result,
            "remove_all_reverse": self._process_remove_all_reverse_result,
            # New - Settings
            "settings_list": self._process_settings_list_result,
            "settings_get": self._process_settings_get_result,
            "settings_put": self._process_settings_put_result,
            # New - Shell
            "run_shell_command": self._process_run_shell_command_result,
            # New - File
            "shell_ls": self._process_shell_ls_result,
            "push_file": self._process_push_file_result,
            "pull_file": self._process_pull_file_result,
            # New - Permissions
            "grant_permission": self._process_grant_permission_result,
            "revoke_permission": self._process_revoke_permission_result,
            # New - Disable/Enable
            "disable_package": self._process_disable_package_result,
            "enable_package": self._process_enable_package_result,
            "force_stop": self._process_force_stop_result,
            # New - Broadcast/Activity
            "send_broadcast": self._process_send_broadcast_result,
            "start_activity": self._process_start_activity_result,
            "open_deep_link": self._process_open_deep_link_result,
            # New - Wireless
            "pair_device": self._process_pair_device_result,
            "tcpip_mode": self._process_tcpip_mode_result,
            # New - Process
            "list_processes": self._process_list_processes_result,
            "kill_process": self._process_kill_process_result,
            # New - Content
            "content_query": self._process_content_query_result,
            # New - Quick Settings
            "quick_setting": self._process_quick_setting_result,
            # New - IME
            "ime_list": self._process_ime_list_result,
            "ime_set": self._process_ime_set_result,
            # New - Emulator
            "emu_sms_send": self._process_emu_sms_send_result,
            "emu_call": self._process_emu_call_result,
            "emu_geo_fix": self._process_emu_geo_fix_result,
            # New - PM Features
            "pm_list_features": self._process_pm_list_features_result,
            # New - Misc
            "get_device_uptime": self._process_get_device_uptime_result,
        }

        handler = handler_map.get(op_type)
        if handler:
            try:
                handler(result)
            except Exception as e:
                self.log_service.log("ERROR", f"[{op_type}] Handler error: {str(e)}")
                self._emit_operation(op_type, False, f"Handler error: {str(e)}")
        else:
            self._default_async_handler(op_type, result)

    def _default_async_handler(self, op_type: str, result):
        if isinstance(result, dict):
            if 'ip' in result:
                self.signals.device_info_updated.emit(result['ip'], result)
            if result.get('success', False):
                self._emit_operation(op_type, True, f"{op_type} completed")
            else:
                error_msg = result.get('error', 'Unknown error')
                self._emit_operation(op_type, False, error_msg)
        else:
            self._emit_operation(op_type, True, f"{op_type} completed")
