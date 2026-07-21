from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PySide6.QtWidgets import QFileDialog

from controllers._base import _ADBControllerBase
from core.log_service import LogLevel, LogService
from gui.panels.adb_control_signals import ADBControllerSignals
from models.adb_app import ADBApp
from models.adb_testing import ADBTesting
from utils.batch_tracker import BatchOperationTracker


class ADBAppMixin(_ADBControllerBase):
    """App management: install, uninstall, package queries, monkey test, bugreport, logs."""

    # ── Provided by _ADBControllerBase ──
    app_model: ADBApp
    testing_model: ADBTesting
    signals: ADBControllerSignals
    log_service: LogService
    executor: ThreadPoolExecutor
    _batch_trackers: dict
    _pending_ops: dict

    _handlers = {
        "get_current_package": "_process_get_package_result",
        "install_apk": "_process_install_apk_result",
        "uninstall_app": "_process_uninstall_apk_result",
        "clear_app_data": "_process_clear_app_data_result",
        "restart_app": "_process_restart_app_result",
        "get_current_activity": "_process_get_current_activity_result",
        "parse_apk_info": "_process_parse_apk_info_result",
        "list_installed_packages": "_process_list_installed_packages_result",
        "run_monkey_test": "_process_run_monkey_test_result",
        "kill_monkey": "_process_kill_monkey_result",
        "capture_bugreport": "_process_capture_bugreport_result",
        "pull_anr_files": "_process_pull_anr_result",
        "retrieve_device_logs": "_process_retrieve_logs_result",
        "cleanup_device_logs": "_process_cleanup_logs_result",
    }

    # -- Package / Install / Uninstall --

    def get_current_package(self, devices: list):
        if not self._require_devices(devices, "get_package"):
            return
        for device_ip in devices:
            self.app_model.get_current_package_async(device_ip)

    def _process_get_package_result(self, result: dict):
        if not isinstance(result, dict):
            return
        device_ip = result.get("device_ip", "")
        if result.get("success"):
            package_name = result.get("package_name", "")
            if package_name:
                self._emit_operation(
                    "get_package", True,
                    f"Current package on {device_ip}: {package_name}"
                )
                self.signals.current_package_received.emit(device_ip, package_name)
        else:
            error = result.get("error", "Unknown error")
            self._emit_operation(
                "get_package", False,
                f"Failed to get package on {device_ip}: {error}"
            )

    def install_apk(self, devices: list):
        if not self._require_devices(devices, "install"):
            return
        apk_path, _ = QFileDialog.getOpenFileName(
            None, "Select APK File", "", "APK Files (*.apk);;All Files (*)"
        )
        if not apk_path:
            self._emit_operation("install", False, "APK selection canceled")
            return
        apk_name = os.path.basename(apk_path)
        self._batch_trackers["install"] = BatchOperationTracker(
            len(devices), "Install App", self._emit_operation
        )
        for idx, device_ip in enumerate(devices, 1):
            self._install_single_device(idx, device_ip, apk_path, apk_name, "install")

    def batch_install_apk(self, devices: list):
        if not self._require_devices(devices, "batch_install"):
            return
        apk_paths, _ = QFileDialog.getOpenFileNames(
            None, "Select APK files to install", "", "APK Files (*.apk);;All Files (*)"
        )
        if not apk_paths:
            self._emit_operation("batch_install", False, "APK selection canceled")
            return
        total_tasks = len(devices) * len(apk_paths)
        self._batch_trackers["batch_install"] = BatchOperationTracker(
            total_tasks, "Batch Install", self._emit_operation
        )
        task_index = 0
        for apk_path in apk_paths:
            apk_name = os.path.basename(apk_path)
            for device_ip in devices:
                task_index += 1
                self._install_single_device(
                    task_index, device_ip, apk_path, apk_name, "batch_install"
                )
        self._emit_operation(
            "batch_install",
            True,
            f"Queued {len(apk_paths)} APKs → {len(devices)} devices ({total_tasks} tasks)",
        )

    def _install_single_device(
        self,
        idx: int,
        device_ip: str,
        apk_path: str,
        apk_name: str,
        operation: str,
    ):
        with self._pending_lock:
            tracker = self._batch_trackers.get(operation)
        total = tracker.total if tracker else "?"
        self._emit_operation(
            operation, True, f"Start install ({idx}/{total}) {apk_name} on {device_ip} ..."
        )
        self.app_model.install_apk_async(device_ip, apk_path, apk_name, idx, operation)

    def _process_install_apk_result(self, result: dict):
        apk_name = result.get("apk_name")
        device_ip = result.get("device_ip")
        result.get("index", 1)
        success = result.get("success")
        operation = result.get("operation", "install")
        with self._pending_lock:
            tracker = self._batch_trackers.get(operation)
        progress = tracker.record(success) if tracker else ""
        if success:
            self._emit_operation(
                operation, True, f"✅ install success {progress} {apk_name} on {device_ip}"
            )
        else:
            self._emit_operation(
                operation,
                False,
                f"❌ install failed {progress} {apk_name} on {device_ip}\n"
                f"Error: {result.get('error', 'Unknown error')}",
            )

    def uninstall_apk(self, devices: list, package_name: str):
        if not self._require_devices(devices, "uninstall"):
            return
        if not package_name:
            self._emit_operation("uninstall", False, "⚠️ No package name provided")
            return
        self._batch_trackers["uninstall"] = BatchOperationTracker(
            len(devices), "Uninstall App", self._emit_operation
        )
        for idx, device_ip in enumerate(devices, 1):
            self._execute_uninstall_task(idx, device_ip, package_name)

    def _execute_uninstall_task(self, idx: int, device_ip: str, package_name: str):
        tracker = self._batch_trackers.get("uninstall")
        total = tracker.total if tracker else "?"
        self._emit_operation(
            "uninstall", True, f"Start uninstall ({idx}/{total}) {package_name} on {device_ip} ..."
        )
        self.app_model.uninstall_app_async(device_ip, package_name, idx)

    def _process_uninstall_apk_result(self, result: dict):
        result.get("index", 1)
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        success = result.get("success")
        tracker = self._batch_trackers.get("uninstall")
        progress = tracker.record(success) if tracker else ""
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
        self._batch_trackers["clear_data"] = BatchOperationTracker(
            len(devices), "Clear App Data", self._emit_operation
        )
        for idx, device_ip in enumerate(devices, 1):
            self._emit_operation(
                "clear_data",
                True,
                f"Start clear data ({idx}/{len(devices)}) {package_name} on {device_ip} ...",
            )
            self.app_model.clear_app_data_async(device_ip, package_name, idx)

    def _process_clear_app_data_result(self, result: dict):
        result.get("index", 1)
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        success = result.get("success")
        tracker = self._batch_trackers.get("clear_data")
        progress = tracker.record(success) if tracker else ""
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
        self._batch_trackers["restart_app"] = BatchOperationTracker(
            len(devices), "Restart App", self._emit_operation
        )
        for idx, device_ip in enumerate(devices, 1):
            self._emit_operation(
                "restart_app",
                True,
                f"Start restart ({idx}/{len(devices)}) {package_name} on {device_ip} ...",
            )
            self.app_model.restart_app_async(device_ip, package_name, idx)

    def _process_restart_app_result(self, result: dict):
        result.get("index", 1)
        ip = result.get("device_ip", "unknown")
        pkg = result.get("package_name", "unknown")
        output = result.get("output", "").strip()
        success = result.get("success")
        tracker = self._batch_trackers.get("restart_app")
        progress = tracker.record(success) if tracker else ""
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
        self._batch_trackers["current_activity"] = BatchOperationTracker(
            len(devices), "Activity Info", self._emit_operation
        )
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
            None, "Select APK File", "", "APK Files (*.apk);;All Files (*)"
        )
        if not apk_path:
            self._emit_operation("apk_info", False, "⚠️ APK file selection cancelled")
            return
        if not apk_path.lower().endswith(".apk") or not os.path.isfile(apk_path):
            self._emit_operation("apk_info", False, f"❌ Invalid APK file selected: {apk_path}")
            return
        self._emit_operation("apk_info", True, f"📦 Selected APK: {apk_path}")
        self.app_model.parse_apk_info_async(apk_path)

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
                self._emit_operation(
                    "apk_info",
                    False,
                    f"⚠️ APK Field parsing exception: {apk_path}\nError: {str(e)}",
                )
        else:
            error = result.get("error", "Unknown error")
            self._emit_operation(
                "apk_info", False, f"❌ APK Analysis failed: {apk_path}\nError: {error}"
            )

    def kill_monkey(self, devices: list):
        if not self._require_devices(devices, "kill_monkey"):
            return
        for idx, device_ip in enumerate(devices, 1):
            self.testing_model.kill_monkey_async(device_ip, idx)

    def _process_kill_monkey_result(self, result: dict):
        device_ip = result.get("device_ip")
        idx = result.get("index")
        self._monkey_running.discard(device_ip)
        if result.get("already_stopped"):
            self._emit_operation(
                "kill_monkey", True, f"ℹ️ {idx}. Monkey was not running on {device_ip}"
            )
            return
        if result.get("success"):
            self._emit_operation(
                "kill_monkey", True, f"✅ {idx}. Monkey process killed on {device_ip}"
            )
        else:
            self._emit_operation(
                "kill_monkey", False,
                f"❌ {idx}. Failed to kill monkey on {device_ip}:\nError: {result.get('message', '')}",
            )

    def list_installed_packages(self, devices: list[str]):
        if not self._require_devices(devices, "installed_packages"):
            return
        for idx, device_ip in enumerate(devices, 1):
            self.app_model.list_installed_packages_async(device_ip, idx)

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
            self._emit_operation(
                "installed_packages",
                False,
                f"❌ {idx}. Failed to get packages from {device_ip}:\n{msg}",
            )

    def capture_bugreport(self, devices: list):
        if not devices:
            self._emit_operation("bugreport", False, "No devices selected.")
            return
        save_dir = self._get_screenshot_dir()
        log = self.log_service.log
        for idx, device in enumerate(devices, 1):
            self.testing_model.capture_bugreport_async(
                device, save_dir, idx,
                callback=lambda msg: log(LogLevel.INFO, msg),
            )

    def _process_capture_bugreport_result(self, result: dict):
        device_ip = result.get("device_ip")
        idx = result.get("index")
        success = result.get("success", False)
        message = result.get("message", "")
        if success:
            bug_path = result.get("bugreport_path")
            self._emit_operation(
                "bugreport", True, f"✅ {idx}. Bugreport saved from {device_ip}:\n{bug_path}"
            )
        else:
            self._emit_operation("bugreport", False, f"❌ {idx}. Failed on {device_ip}:\n{message}")

    def pull_anr_files(self, devices: list[str]):
        if not self._require_devices(devices, "pull_anr"):
            return
        save_dir = self._get_screenshot_dir()
        timestamp = datetime.now().strftime("%H%M%S")
        for idx, device_ip in enumerate(devices, 1):
            sanitized_name = re.sub(r"\W+", "_", device_ip)
            self.testing_model.pull_anr_files_async(
                device_ip, f"{sanitized_name}_anr_{timestamp}", save_dir, idx,
            )

    def _process_pull_anr_result(self, result: dict):
        device_ip = result.get("device_ip", "unknown")
        idx = result.get("index", "?")
        if result.get("success"):
            self._emit_operation(
                "pull_anr",
                True,
                f"✅ {idx}. Pulled ANR files from {device_ip}:\n{result['message']}",
            )
        else:
            self._emit_operation(
                "pull_anr",
                False,
                f"❌ {idx}. Failed to pull ANR from {device_ip}:\n{result['message']}",
            )

    def run_monkey_test(self, devices: list, params: dict):
        if not devices:
            return self._emit_operation("monkey", False, "No devices selected")
        package_name = params.get("package_name", "")
        if not package_name:
            return self._emit_operation("monkey", False, "No package name provided")
        # Guard against duplicate starts
        dupes = [d for d in devices if d in self._monkey_running]
        if dupes:
            self._emit_operation("monkey", False, f"Monkey already running on: {', '.join(dupes)}")
            return
        for d in devices:
            self._monkey_running.add(d)
        save_dir = self._get_screenshot_dir()
        log = self.log_service.log
        pct_keys = ["touch", "motion", "trackball", "nav", "majornav", "syskeys", "appswitch", "anyevent", "pinch"]
        pct_str = " ".join(f"{k}={params.get(k, '?')}%" for k in pct_keys)
        log(LogLevel.INFO,
            f"Monkey start: {len(devices)} device(s) → {package_name} | "
            f"events={params.get('events')} throttle={params.get('throttle')}ms | "
            f"{pct_str} | "
            f"crash_ignore={params.get('ignore_crashes')} "
            f"timeout_ignore={params.get('ignore_timeouts')} "
            f"security_ignore={params.get('ignore_security')} | "
            f"save_dir={save_dir}")
        for idx, device_ip in enumerate(devices, 1):
            sanitized_name = re.sub(r"\W+", "_", device_ip)
            self.testing_model.run_monkey_test_async(
                device_ip, package_name, params,
                sanitized_name, save_dir, idx,
                callback=lambda msg: self.log_service.log(LogLevel.INFO, msg),
            )

    def _process_run_monkey_test_result(self, result: dict):
        device_ip = result.get("device_ip", "unknown")
        self._monkey_running.discard(device_ip)
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
                "╚════════════════════════════════════════════════════════════════╝"
            )
        else:
            message = (
                "\n╔════════════════════════════════════════════════════════════════╗\n"
                f"║ ❌ Monkey Test Failed - Device: {device_ip}\n"
                "╠════════════════════════════════════════════════════════════════╣\n"
                f"║ ⏱️ Duration: {duration}\n"
                f"║ 💥 Error: {error[:200]}{'...' if len(error)>200 else ''}\n"
                f"║ 🔍 Detailed Log: {monkey_log}\n"
                "╚════════════════════════════════════════════════════════════════╝"
            )
        return self._emit_operation("monkey", result.get("success"), message)

    # -- Log Retrieval --

    def retrieve_device_logs(self, devices: list):
        if not self._require_devices(devices, "retrieve_device_logs"):
            return
        save_dir = self._get_screenshot_dir()
        if not save_dir:
            self._emit_operation("retrieve_device_logs", False, "No directory selected")
            return
        for device_ip in devices:
            self._save_single_device_log(device_ip, save_dir)

    def _save_single_device_log(self, device_ip: str, save_dir: str):
        timestamp = datetime.now().strftime("%H%M%S")
        sanitized_ip = re.sub(r"\W+", "_", device_ip)
        log_path = os.path.join(save_dir, f"log_{timestamp}_{sanitized_ip}.txt")
        operation_id = self._generate_operation_id()
        with self._pending_lock:
            self._pending_ops[operation_id] = ("retrieve_device_logs", device_ip)
        self.testing_model.retrieve_device_logs_async(device_ip, log_path)

    def _process_retrieve_logs_result(self, result: dict):
        device_ip = result.get("device_ip")
        log_path = result.get("log_path")
        if result.get("success"):
            self._emit_operation(
                "retrieve_device_logs", True, f"✅ Log saved for {device_ip} at {log_path}"
            )
            self.signals.logs_retrieved.emit(device_ip, log_path)
        else:
            error = result.get("error", "Unknown error")
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            self._emit_operation(
                "retrieve_device_logs", False, f"Failed to save log for {device_ip}: {error_msg}"
            )

    def cleanup_device_logs(self, devices: list):
        if not self._require_devices(devices, "cleanup_device_logs"):
            return
        for device_ip in devices:
            operation_id = self._generate_operation_id()
            with self._pending_lock:
                self._pending_ops[operation_id] = ("cleanup_device_logs", device_ip)
            self.testing_model.cleanup_device_logs_async(device_ip)

    def _process_cleanup_logs_result(self, result: dict):
        device_ip = result.get("device_ip")
        if result.get("success"):
            self._emit_operation("cleanup_device_logs", True, f"✅ Log cleared for {device_ip}")
        else:
            error = result.get("error", "Unknown error")
            error_msg = error.split(":")[-1].strip() if ":" in error else error
            self._emit_operation(
                "cleanup_device_logs", False, f"Failed to clear log for {device_ip}: {error_msg}"
            )

