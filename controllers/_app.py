"""提供应用包查询、APK 信息解析、Bugreport、ANR 与设备日志控制能力。"""

from __future__ import annotations

import os
import re
from datetime import datetime

from PySide6.QtWidgets import QFileDialog

from controllers._app_install import ADBAppInstallMixin
from controllers._app_monkey import ADBAppMonkeyMixin
from controllers.signals import ADBControllerSignals
from core.log_service import LogLevel, LogService
from models.adb_app import ADBApp
from models.adb_testing import ADBTesting


class ADBAppMixin(ADBAppInstallMixin, ADBAppMonkeyMixin):
    """协调应用包查询、APK 信息、Bugreport、ANR 与设备日志操作。"""

    # 以下属性由 _ADBControllerBase 提供。
    app_model: ADBApp
    testing_model: ADBTesting
    signals: ADBControllerSignals
    log_service: LogService

    _handlers = {
        "get_current_package": "_process_get_package_result",
        "parse_apk_info": "_process_parse_apk_info_result",
        "list_installed_packages": "_process_list_installed_packages_result",
        "capture_bugreport": "_process_capture_bugreport_result",
        "pull_anr_files": "_process_pull_anr_result",
        "retrieve_device_logs": "_process_retrieve_logs_result",
        "cleanup_device_logs": "_process_cleanup_logs_result",
    }

    # 应用包查询与 APK 信息解析

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
                    "get_package", True, f"Current package on {device_ip}: {package_name}"
                )
                self.signals.current_package_received.emit(device_ip, package_name)
        else:
            error = result.get("error", "Unknown error")
            self._emit_operation(
                "get_package", False, f"Failed to get package on {device_ip}: {error}"
            )

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
                formatted = (
                    f"""
    🔹 App: {app_label}
    📦 Package: {package_name.group(1) if package_name else "N/A"}
    🔢 Version: {version_name.group(1) if version_name else "N/A"} """
                    f"""(Code: {version_code.group(1) if version_code else "N/A"})
    🎯 SDK: min={min_sdk.group(1) if min_sdk else "N/A"}, """
                    f"""target={target_sdk.group(1) if target_sdk else "N/A"}, """
                    f"""compile={compile_sdk.group(1) if compile_sdk else "N/A"}
    🛠️ Build: {build_version.group(1) if build_version else "N/A"}
    🖼️ Icon: {icon_path}
    🔐 Permissions: {len(permissions)} items
    ⚙️ Features: {", ".join(features) if features else "None"}
    🧬 Architectures: {", ".join(native_code) if native_code else "None"}
    """
                )
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
            formatted = "\n".join(f"{i + 1}. {pkg}" for i, pkg in enumerate(packages))
            msg = f"📦 {idx}. Installed packages on {device_ip}:\n{formatted or '(None found)'}"
            self._emit_operation("installed_packages", True, msg)
        else:
            msg = result.get("message", "Unknown error")
            self._emit_operation(
                "installed_packages",
                False,
                f"❌ {idx}. Failed to get packages from {device_ip}:\n{msg}",
            )

    # Bugreport 与 ANR 采集

    def capture_bugreport(self, devices: list):
        if not devices:
            self._emit_operation("bugreport", False, "No devices selected.")
            return
        save_dir = self._get_screenshot_dir()
        log = self.log_service.log
        for idx, device in enumerate(devices, 1):
            self.testing_model.capture_bugreport_async(
                device,
                save_dir,
                idx,
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
                device_ip,
                f"{sanitized_name}_anr_{timestamp}",
                save_dir,
                idx,
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

    # 设备日志获取与清理

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
