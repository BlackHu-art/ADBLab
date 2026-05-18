"""
Advanced ADB operations: screen recording, input events, performance diagnostics,
logcat filtering, shell commands, settings, reboot modes, file manager, system info.

Composes core operations directly; delegates networking to ADBNetworkMixin and
system-level ops to ADBSystemMixin via multiple inheritance.
"""

import os
import re
import shlex
import subprocess
import threading
import time
from datetime import datetime

from .adb_model import ADBModelCore, async_command
from .adb_network import ADBNetworkMixin
from .adb_system import ADBSystemMixin
from utils.adb_resolver import CF


class ADBAdvanced(ADBModelCore, ADBNetworkMixin, ADBSystemMixin):
    """Core + Networking + System ADB operations."""

    # ── Screen Recording ─────────────────────────────────────────────────

    def __init__(self):
        super().__init__()
        self._record_procs = {}   # device_ip → Popen
        self._record_lock = threading.Lock()

    @async_command
    def start_screen_record_async(
        self, device_ip: str, save_dir: str, duration: int = 30,
        width: str = "", height: str = "", bitrate: str = "8000000",
    ) -> dict:
        try:
            sanitized = re.sub(r"\W+", "_", device_ip)
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"record_{sanitized}_{timestamp}.mp4"
            remote_path = f"/sdcard/{filename}"
            cmd = [
                "adb", "-s", device_ip, "shell", "screenrecord",
                "--time-limit", str(duration), "--bit-rate", bitrate,
            ]
            if width and height:
                cmd.extend(["--size", f"{width}x{height}"])
            cmd.append(remote_path)
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=CF,
            )
            # Detect immediate failure (e.g. device doesn't support screenrecord)
            time.sleep(0.3)
            if proc.poll() is not None:
                err = proc.stderr.read().decode(errors="ignore").strip()
                return {"success": False, "device_ip": device_ip,
                        "error": err or "screenrecord exited immediately"}
            with self._record_lock:
                self._record_procs[device_ip] = proc
            return {
                "success": True, "device_ip": device_ip, "remote_path": remote_path,
                "proc_pid": proc.pid, "filename": filename, "save_dir": save_dir,
                "duration": duration,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def stop_screen_record_async(self, device_ip: str) -> dict:
        try:
            with self._record_lock:
                proc = self._record_procs.pop(device_ip, None)
            if proc and proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
                return {"success": True, "device_ip": device_ip,
                        "message": "Recording stopped"}
            return {"success": True, "device_ip": device_ip,
                    "message": "No active recording" if not proc else "Recording already finished"}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pull_recorded_video_async(
        self, device_ip: str, remote_path: str, save_dir: str, filename: str
    ) -> dict:
        try:
            local_path = os.path.join(save_dir, filename)
            self._execute_command(
                ["adb", "-s", device_ip, "pull", remote_path, local_path], timeout=60
            )
            self._execute_command(["adb", "-s", device_ip, "shell", "rm", remote_path])
            return {"success": True, "device_ip": device_ip, "local_path": local_path}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Input Events ─────────────────────────────────────────────────────

    @async_command
    def input_tap_async(self, device_ip: str, x: int, y: int) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "input", "tap", str(x), str(y)]
            )
            return {"success": True, "device_ip": device_ip, "output": result, "x": x, "y": y}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def input_swipe_async(
        self, device_ip: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> dict:
        try:
            result = self._execute_command([
                "adb", "-s", device_ip, "shell", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2), str(duration_ms),
            ])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def input_keyevent_async(self, device_ip: str, keycode: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "input", "keyevent", keycode]
            )
            return {"success": True, "device_ip": device_ip, "output": result, "keycode": keycode}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def input_longpress_async(self, device_ip: str, keycode: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "input", "keyevent", "--longpress", keycode]
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def input_drag_async(
        self, device_ip: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> dict:
        try:
            result = self._execute_command([
                "adb", "-s", device_ip, "shell", "input", "draganddrop",
                str(x1), str(y1), str(x2), str(y2), str(duration_ms),
            ])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Performance Diagnostics ──────────────────────────────────────────

    @async_command
    def dumpsys_meminfo_async(self, device_ip: str, package: str = "") -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "dumpsys", "meminfo"]
            if package:
                cmd.append(package)
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result, "package": package}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def dumpsys_cpuinfo_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "dumpsys", "cpuinfo"], timeout=15
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def dumpsys_battery_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "dumpsys", "battery"], timeout=15
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Logcat Filtering ─────────────────────────────────────────────────

    @async_command
    def logcat_filtered_async(
        self, device_ip: str, log_path: str, buffer: str = "main",
        priority: str = "V", tag_filter: str = "", regex: str = "", max_lines: str = "",
    ) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "logcat", "-d", "-b", buffer]
            if tag_filter:
                cmd.extend(["-s", tag_filter])
            if priority != "V" and not tag_filter:
                cmd.append(f"*:{priority}")
            if regex:
                cmd.extend(["-e", regex])
            if max_lines:
                cmd.extend(["-m", max_lines])
            log_content = self._execute_command(cmd, timeout=30)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(log_content)
            return {
                "success": True, "device_ip": device_ip, "log_path": log_path,
                "line_count": len(log_content.splitlines()),
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def logcat_buffer_sizes_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "logcat", "-g"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Settings ─────────────────────────────────────────────────────────

    @async_command
    def settings_list_async(self, device_ip: str, namespace: str = "system") -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "settings", "list", namespace], timeout=15
            )
            return {
                "success": True, "device_ip": device_ip,
                "output": result, "namespace": namespace,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def settings_get_async(self, device_ip: str, namespace: str, key: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "settings", "get", namespace, key]
            )
            return {"success": True, "device_ip": device_ip, "key": key, "value": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def settings_put_async(self, device_ip: str, namespace: str, key: str, value: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "settings", "put", namespace, key, value]
            )
            return {
                "success": True, "device_ip": device_ip,
                "key": key, "value": value, "output": result,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Custom Shell Command ─────────────────────────────────────────────

    @async_command
    def run_shell_command_async(self, device_ip: str, command: str, timeout: int = 30) -> dict:
        try:
            full_cmd = ["adb", "-s", device_ip, "shell"] + shlex.split(command)
            result = self._execute_command(full_cmd, timeout=timeout)
            return {"success": True, "device_ip": device_ip, "output": result, "command": command}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e), "command": command}

    # ── Reboot Modes ─────────────────────────────────────────────────────

    @async_command
    def reboot_mode_async(self, device_ip: str, mode: str) -> dict:
        try:
            if mode == "system":
                self._execute_command(["adb", "-s", device_ip, "reboot"], timeout=3)
            elif mode in ("bootloader", "recovery", "fastboot"):
                self._execute_command(["adb", "-s", device_ip, "reboot", mode], timeout=3)
            return {"success": True, "device_ip": device_ip, "mode": mode}
        except subprocess.TimeoutExpired:
            return {
                "success": True, "device_ip": device_ip, "mode": mode,
                "output": f"Device rebooting to {mode}...",
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e), "mode": mode}

    # ── File Manager ─────────────────────────────────────────────────────

    @async_command
    def shell_ls_async(self, device_ip: str, path: str = "/sdcard") -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "ls", "-la", path], timeout=10
            )
            return {"success": True, "device_ip": device_ip, "path": path, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def shell_rm_async(self, device_ip: str, path: str, recursive: bool = False) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "rm"]
            if recursive:
                cmd.append("-r")
            cmd.append(path)
            result = self._execute_command(cmd)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def shell_mkdir_async(self, device_ip: str, path: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "mkdir", "-p", path])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def push_file_async(self, device_ip: str, local_path: str, remote_path: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "push", local_path, remote_path], timeout=60
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pull_file_async(self, device_ip: str, remote_path: str, local_path: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "pull", remote_path, local_path], timeout=60
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def shell_df_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "df", "-h"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── System Info Extended ────────────────────────────────────────────

    @async_command
    def get_device_date_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "date"])
            return {"success": True, "device_ip": device_ip, "date": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def get_device_uptime_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "uptime"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def get_cpu_info_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "cat", "/proc/cpuinfo"]
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def get_kernel_version_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "cat", "/proc/version"]
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def getprop_all_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "getprop"], timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Backup ──────────────────────────────────────────────────────────

    @async_command
    def backup_app_async(self, device_ip: str, package: str, save_path: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "backup", "-f", save_path, "-noapk", package], timeout=60
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}
