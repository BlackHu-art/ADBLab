"""
App management: install, uninstall, clear data, restart, query packages/activities.

Imports only from adb_model (core) — no circular dependencies.
"""

import re
import subprocess

from .adb_model import ADBModelCore, async_command
from utils.adb_resolver import CF


class ADBApp(ADBModelCore):
    """App lifecycle: install, uninstall, clear, restart, list, query."""

    @async_command
    def get_current_package_async(self, device_ip: str) -> dict:
        try:
            command = ["adb", "-s", device_ip, "shell", "dumpsys", "window"]
            result = self._execute_command(command)

            current_focus_line = ""
            for line in result.splitlines():
                if "mCurrentFocus" in line:
                    current_focus_line = line.strip()
                    break

            if not current_focus_line:
                return {"success": False, "device_ip": device_ip, "error": "No mCurrentFocus found"}

            match = re.search(r"mCurrentFocus=Window\{.*?\s(\S+?)/(\S+)\}", current_focus_line)
            if match:
                return {
                    "success": True,
                    "device_ip": device_ip,
                    "package_name": match.group(1),
                    "activity_name": match.group(2),
                }
            return {
                "success": False,
                "device_ip": device_ip,
                "error": "Could not parse package name",
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": f"CommandError: {str(e)}"}

    @async_command
    def install_apk_async(self, device_ip: str, apk_path: str, apk_name: str, idx: int):
        try:
            cmd = ["adb", "-s", device_ip, "install", "-r", apk_path]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
                creationflags=CF,
            )
            return {
                "success": True,
                "device_ip": device_ip,
                "apk_path": apk_path,
                "output": result.stdout.strip(),
                "index": idx,
                "apk_name": apk_name,
            }
        except subprocess.TimeoutExpired as e:
            return {"success": False, "device_ip": device_ip, "error": f"CommandError: {str(e)}"}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": f"CommandError: {str(e)}"}

    @async_command
    def uninstall_app_async(self, device_ip: str, package_name: str, idx: int) -> dict:
        try:
            result = subprocess.run(
                ["adb", "-s", device_ip, "uninstall", package_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                creationflags=CF,
            )
            return {
                "success": True,
                "output": result.stdout.strip(),
                "device_ip": device_ip,
                "package_name": package_name,
                "index": idx,
            }
        except subprocess.TimeoutExpired as e:
            return {
                "success": False,
                "output": f"Timeout after 30 seconds: {str(e)}",
                "device_ip": device_ip,
                "package_name": package_name,
            }
        except Exception as e:
            return {
                "success": False,
                "output": f"Execution failed: {str(e)}",
                "device_ip": device_ip,
                "package_name": package_name,
            }

    @async_command
    def clear_app_data_async(self, device_ip: str, package_name: str, idx: int):
        try:
            result = subprocess.run(
                ["adb", "-s", device_ip, "shell", "pm", "clear", package_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                creationflags=CF,
            )
            return {
                "success": True,
                "device_ip": device_ip,
                "package_name": package_name,
                "output": result.stdout.strip(),
                "index": idx,
            }
        except Exception as e:
            return {
                "success": False,
                "device_ip": device_ip,
                "package_name": package_name,
                "output": str(e),
                "index": idx,
            }

    @async_command
    def restart_app_async(self, device_ip: str, package_name: str, index: int):
        try:
            stop_cmd = ["adb", "-s", device_ip, "shell", "am", "force-stop", package_name]
            stop_output = self._execute_command(stop_cmd)

            start_cmd = [
                "adb",
                "-s",
                device_ip,
                "shell",
                "monkey",
                "-p",
                package_name,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ]
            start_output = self._execute_command(start_cmd)

            return {
                "success": True,
                "device_ip": device_ip,
                "package_name": package_name,
                "output": f"{stop_output}\n{start_output}",
                "index": index,
            }
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "device_ip": device_ip,
                "package_name": package_name,
                "output": e.output,
                "index": index,
            }
        except Exception as e:
            return {
                "success": False,
                "device_ip": device_ip,
                "package_name": package_name,
                "output": str(e),
                "index": index,
            }

    @async_command
    def get_current_activity_async(self, device_ip: str, index: int = 0) -> dict:
        try:
            current_cmd = ["adb", "-s", device_ip, "shell", "dumpsys", "window"]
            resumed_cmd = ["adb", "-s", device_ip, "shell", "dumpsys", "activity", "activities"]

            current_output = self._execute_command(current_cmd)
            resumed_output = self._execute_command(resumed_cmd)

            current_focus = ""
            resumed_activity = ""
            for line in current_output.splitlines():
                if "mCurrentFocus" in line:
                    current_focus = line.strip()
                    break
            for line in resumed_output.splitlines():
                if "mResumedActivity" in line:
                    resumed_activity = line.strip()
                    break

            return {
                "success": True,
                "device_ip": device_ip,
                "index": index,
                "current_focus": current_focus,
                "resumed_activity": resumed_activity,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "index": index, "error": str(e)}

    @async_command
    def parse_apk_info_async(self, apk_path: str) -> dict:
        try:
            command = ["aapt", "dump", "badging", apk_path]
            output = self._execute_command(command, timeout=15)
            return {"success": True, "apk_path": apk_path, "output": output}
        except Exception as e:
            return {"success": False, "apk_path": apk_path, "error": str(e)}

    @async_command
    def input_text_async(self, device_ip: str, text: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "input", "text", text])
            if result.startswith(("Error:", "Timeout:", "SystemError:")):
                return {"success": False, "device_ip": device_ip, "error": result, "text": text}
            return {"success": True, "device_ip": device_ip, "text": text, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e), "text": text}

    @async_command
    def list_installed_packages_async(self, device_ip: str, index: int) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "pm", "list", "packages"]
            output = subprocess.check_output(
                cmd, stderr=subprocess.STDOUT, text=True, creationflags=CF
            )
            packages = [
                line.replace("package:", "").strip()
                for line in output.splitlines()
                if line.startswith("package:")
            ]
            return {"device_ip": device_ip, "success": True, "packages": packages, "index": index}
        except subprocess.CalledProcessError as e:
            return {"device_ip": device_ip, "success": False, "message": e.output, "index": index}
