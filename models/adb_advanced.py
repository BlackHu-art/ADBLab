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
import time
from datetime import datetime

from .adb_model import ADBModelCore, async_command
from .adb_network import ADBNetworkMixin
from .adb_system import ADBSystemMixin
from .base.process_runner import ProcessRunner


class ADBAdvanced(ADBModelCore, ADBNetworkMixin, ADBSystemMixin):
    """Core + Networking + System ADB operations."""

    def __init__(self):
        super().__init__()
        self._rec_procs = ProcessRunner()

    # ── Screen Recording ─────────────────────────────────────────────────

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
            proc = self._rec_procs.start(
                f"record_{device_ip}", cmd,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.3)
            if proc.poll() is not None:
                err = proc.stderr.read().decode(errors="ignore").strip()
                return {"success": False, "device_ip": device_ip,
                        "error": err or "screenrecord exited immediately"}
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
            ret = self._rec_procs.stop(f"record_{device_ip}")
            if ret is not None:
                return {"success": True, "device_ip": device_ip,
                        "message": "Recording stopped"}
            return {"success": True, "device_ip": device_ip,
                    "message": "No active recording"}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pull_recorded_video_async(
        self, device_ip: str, remote_path: str, save_dir: str, filename: str
    ) -> dict:
        local_path = os.path.join(save_dir, filename)
        self._run(["adb", "-s", device_ip, "pull", remote_path, local_path], timeout=60)
        self._run(["adb", "-s", device_ip, "shell", "rm", remote_path])
        return {"success": True, "device_ip": device_ip, "local_path": local_path}

    # ── Input Events ─────────────────────────────────────────────────────

    @async_command
    def input_tap_async(self, device_ip: str, x: int, y: int) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "input", "tap", str(x), str(y)],
            device_ip=device_ip, x=x, y=y,
        )

    @async_command
    def input_swipe_async(self, device_ip: str, x1: int, y1: int,
                          x2: int, y2: int, duration_ms: int = 300) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "input", "swipe",
             str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            device_ip=device_ip,
        )

    @async_command
    def input_keyevent_async(self, device_ip: str, keycode: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "input", "keyevent", keycode],
            device_ip=device_ip, keycode=keycode,
        )

    @async_command
    def input_longpress_async(self, device_ip: str, keycode: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "input", "keyevent", "--longpress", keycode],
            device_ip=device_ip,
        )

    @async_command
    def input_drag_async(self, device_ip: str, x1: int, y1: int,
                         x2: int, y2: int, duration_ms: int = 300) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "input", "draganddrop",
             str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            device_ip=device_ip,
        )

    # ── Performance Diagnostics ──────────────────────────────────────────

    @async_command
    def dumpsys_meminfo_async(self, device_ip: str, package: str = "") -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "dumpsys", "meminfo"]
        if package:
            cmd.append(package)
        return self._run(cmd, timeout=15, device_ip=device_ip, package=package)

    @async_command
    def dumpsys_cpuinfo_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "cpuinfo"],
            timeout=15, device_ip=device_ip,
        )

    @async_command
    def dumpsys_battery_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "battery"],
            timeout=15, device_ip=device_ip,
        )

    # ── Logcat Filtering ─────────────────────────────────────────────────

    @async_command
    def logcat_filtered_async(
        self, device_ip: str, log_path: str, buffer: str = "main",
        priority: str = "V", tag_filter: str = "", regex: str = "", max_lines: str = "",
    ) -> dict:
        cmd = ["adb", "-s", device_ip, "logcat", "-d", "-b", buffer]
        if tag_filter:
            cmd.extend(["-s", tag_filter])
        if priority != "V" and not tag_filter:
            cmd.append(f"*:{priority}")
        if regex:
            cmd.extend(["-e", regex])
        if max_lines:
            cmd.extend(["-m", max_lines])
        r = self._run(cmd, timeout=30, device_ip=device_ip)
        if r["success"]:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(r["output"])
            return {"success": True, "device_ip": device_ip, "log_path": log_path,
                    "line_count": len(r["output"].splitlines())}
        return r

    @async_command
    def logcat_buffer_sizes_async(self, device_ip: str) -> dict:
        return self._run(["adb", "-s", device_ip, "logcat", "-g"], device_ip=device_ip)

    # ── Settings ─────────────────────────────────────────────────────────

    @async_command
    def settings_list_async(self, device_ip: str, namespace: str = "system") -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "settings", "list", namespace],
            timeout=15, device_ip=device_ip, namespace=namespace,
        )

    @async_command
    def settings_get_async(self, device_ip: str, namespace: str, key: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "settings", "get", namespace, key],
            device_ip=device_ip, key=key,
        )

    @async_command
    def settings_put_async(self, device_ip: str, namespace: str,
                           key: str, value: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "settings", "put", namespace, key, value],
            device_ip=device_ip, key=key, value=value,
        )

    # ── Custom Shell Command ─────────────────────────────────────────────

    @async_command
    def run_shell_command_async(self, device_ip: str, command: str,
                                timeout: int = 30) -> dict:
        full_cmd = ["adb", "-s", device_ip, "shell"] + shlex.split(command)
        return self._run(full_cmd, timeout=timeout, device_ip=device_ip, command=command)

    # ── Reboot Modes ─────────────────────────────────────────────────────

    @async_command
    def reboot_mode_async(self, device_ip: str, mode: str) -> dict:
        cmd = ["adb", "-s", device_ip, "reboot"]
        if mode != "system":
            cmd.append(mode)
        r = self._run(cmd, timeout=3, device_ip=device_ip, mode=mode)
        # reboot 超时 = 设备正在重启 = 成功
        if r["success"] or "Timeout" in r.get("error", ""):
            return {"success": True, "device_ip": device_ip, "mode": mode,
                    "output": f"Device rebooting to {mode}..."}
        return r

    # ── File Manager ─────────────────────────────────────────────────────

    @async_command
    def shell_ls_async(self, device_ip: str, path: str = "/sdcard") -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "ls", "-la", path],
            timeout=10, device_ip=device_ip, path=path,
        )

    @async_command
    def shell_rm_async(self, device_ip: str, path: str, recursive: bool = False) -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "rm"]
        if recursive:
            cmd.append("-r")
        cmd.append(path)
        return self._run(cmd, device_ip=device_ip)

    @async_command
    def shell_mkdir_async(self, device_ip: str, path: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "mkdir", "-p", path],
            device_ip=device_ip,
        )

    @async_command
    def push_file_async(self, device_ip: str, local_path: str, remote_path: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "push", local_path, remote_path],
            timeout=60, device_ip=device_ip,
        )

    @async_command
    def pull_file_async(self, device_ip: str, remote_path: str, local_path: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "pull", remote_path, local_path],
            timeout=60, device_ip=device_ip,
        )

    @async_command
    def shell_df_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "df", "-h"],
            device_ip=device_ip,
        )

    # ── System Info Extended ────────────────────────────────────────────

    @async_command
    def get_device_date_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "date"],
            device_ip=device_ip,
        )

    @async_command
    def get_device_uptime_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "uptime"],
            device_ip=device_ip,
        )

    @async_command
    def get_cpu_info_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "cat", "/proc/cpuinfo"],
            device_ip=device_ip,
        )

    @async_command
    def get_kernel_version_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "cat", "/proc/version"],
            device_ip=device_ip,
        )

    @async_command
    def getprop_all_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "getprop"],
            timeout=15, device_ip=device_ip,
        )

    # ── Backup ──────────────────────────────────────────────────────────

    @async_command
    def backup_app_async(self, device_ip: str, package: str, save_path: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "backup", "-f", save_path, "-noapk", package],
            timeout=60, device_ip=device_ip,
        )
