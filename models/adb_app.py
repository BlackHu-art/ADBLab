"""
App management: install, uninstall, clear data, restart, query packages/activities.

Imports only from adb_model (core) — no circular dependencies.
"""

import os
import shutil

from .adb_model import ADBModelCore, async_command
from .base.focus_detector import detect_current_package


class ADBApp(ADBModelCore):
    """App lifecycle: install, uninstall, clear, restart, list, query."""

    def get_current_package(self, device_ip: str) -> dict:
        return detect_current_package(device_ip)

    @async_command
    def get_current_package_async(self, device_ip: str) -> dict:
        return self.get_current_package(device_ip)

    def install_apk(
        self,
        device_ip: str,
        apk_path: str,
        apk_name: str,
        idx: int,
        operation: str = "install",
    ) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "install", "-r", apk_path],
            timeout=120,
            device_ip=device_ip,
            apk_path=apk_path,
            index=idx,
            apk_name=apk_name,
            operation=operation,
        )

    @async_command
    def install_apk_async(
        self,
        device_ip: str,
        apk_path: str,
        apk_name: str,
        idx: int,
        operation: str = "install",
    ):
        return self.install_apk(device_ip, apk_path, apk_name, idx, operation=operation)

    def uninstall_app(self, device_ip: str, package_name: str, idx: int) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "uninstall", package_name],
            timeout=30,
            device_ip=device_ip,
            package_name=package_name,
            index=idx,
        )

    @async_command
    def uninstall_app_async(self, device_ip: str, package_name: str, idx: int) -> dict:
        return self.uninstall_app(device_ip, package_name, idx)

    @async_command
    def clear_app_data_async(self, device_ip: str, package_name: str, idx: int) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "clear", package_name],
            timeout=30, device_ip=device_ip, package_name=package_name, index=idx,
        )

    @async_command
    def restart_app_async(self, device_ip: str, package_name: str, index: int) -> dict:
        r1 = self._run(
            ["adb", "-s", device_ip, "shell", "am", "force-stop", package_name],
            device_ip=device_ip,
        )
        r2 = self._run(
            ["adb", "-s", device_ip, "shell", "monkey", "-p", package_name,
             "-c", "android.intent.category.LAUNCHER", "1"],
            device_ip=device_ip,
        )
        return {
            "success": r1["success"] and r2["success"],
            "device_ip": device_ip, "package_name": package_name, "index": index,
            "output": f"{r1.get('output', r1.get('error', ''))}\n{r2.get('output', r2.get('error', ''))}",
        }

    @async_command
    def get_current_activity_async(self, device_ip: str, index: int = 0) -> dict:
        r1 = self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "window"],
            device_ip=device_ip,
        )
        r2 = self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "activity", "activities"],
            device_ip=device_ip,
        )
        current_focus = ""
        resumed_activity = ""
        if r1["success"]:
            for line in r1["output"].splitlines():
                if "mCurrentFocus" in line:
                    current_focus = line.strip()
                    break
        if r2["success"]:
            for line in r2["output"].splitlines():
                if "mResumedActivity" in line:
                    resumed_activity = line.strip()
                    break
        return {
            "success": True, "device_ip": device_ip, "index": index,
            "current_focus": current_focus, "resumed_activity": resumed_activity,
        }

    @async_command
    def parse_apk_info_async(self, apk_path: str) -> dict:
        if not os.path.isfile(apk_path):
            return {"success": False, "error": f"APK file not found: {apk_path}", "apk_path": apk_path}
        aapt = shutil.which("aapt")
        if not aapt:
            return {"success": False, "error": "aapt executable not found in PATH", "apk_path": apk_path}
        return self._run([aapt, "dump", "badging", apk_path], timeout=15, apk_path=apk_path)

    @async_command
    def input_text_async(self, device_ip: str, text: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "input", "text", text],
            device_ip=device_ip, text=text,
        )

    def list_installed_packages(self, device_ip: str, index: int) -> dict:
        r = self._run(["adb", "-s", device_ip, "shell", "pm", "list", "packages"], device_ip=device_ip)
        if not r["success"]:
            return {"device_ip": device_ip, "success": False, "message": r["error"], "index": index}
        packages = [
            line.replace("package:", "").strip()
            for line in r["output"].splitlines()
            if line.startswith("package:")
        ]
        return {"device_ip": device_ip, "success": True, "packages": packages, "index": index}

    @async_command
    def list_installed_packages_async(self, device_ip: str, index: int) -> dict:
        return self.list_installed_packages(device_ip, index)
