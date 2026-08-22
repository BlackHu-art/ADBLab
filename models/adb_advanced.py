"""提供录屏、输入、性能诊断、Logcat 和文件管理等高级 ADB 操作。

本类直接实现通用高级操作，并通过多重继承复用 ADBNetworkMixin 和 ADBSystemMixin
中的网络及系统能力。
"""

import os
import re
import shlex
import subprocess
import time
from datetime import datetime

from core.exec import ProcessRunner
from utils.atomic_text import atomic_write_text

from .adb_model import ADBModelCore, async_command
from .adb_network import ADBNetworkMixin
from .adb_system import ADBSystemMixin


class ADBAdvanced(ADBModelCore, ADBNetworkMixin, ADBSystemMixin):
    """组合核心、网络和系统级 ADB 操作。"""

    def __init__(self):
        super().__init__()
        self._rec_procs = ProcessRunner()
        self._adb_bridge = None

    # 屏幕录制

    @async_command
    def start_screen_record_async(
        self,
        device_ip: str,
        save_dir: str,
        duration: int = 30,
        width: str = "",
        height: str = "",
        bitrate: str = "8000000",
        batch_id: str = "",
    ) -> dict:
        try:
            sanitized = re.sub(r"\W+", "_", device_ip)
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"record_{sanitized}_{timestamp}.mp4"
            remote_path = f"/sdcard/{filename}"
            cmd = [
                "adb",
                "-s",
                device_ip,
                "shell",
                "screenrecord",
                "--time-limit",
                str(duration),
                "--bit-rate",
                bitrate,
            ]
            if width and height:
                cmd.extend(["--size", f"{width}x{height}"])
            cmd.append(remote_path)
            proc = self._rec_procs.start(
                f"record_{device_ip}",
                cmd,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.3)
            if proc.poll() is not None:
                err = (
                    proc.stderr.read().decode(errors="ignore").strip()
                    if proc.stderr is not None
                    else ""
                )
                return {
                    "success": False,
                    "device_ip": device_ip,
                    "error": err or "screenrecord exited immediately",
                    "batch_id": batch_id,
                }
            return {
                "success": True,
                "device_ip": device_ip,
                "remote_path": remote_path,
                "proc_pid": proc.pid,
                "filename": filename,
                "save_dir": save_dir,
                "duration": duration,
                "batch_id": batch_id,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e), "batch_id": batch_id}

    @async_command
    def stop_screen_record_async(self, device_ip: str, batch_id: str = "") -> dict:
        try:
            # 先给设备端 screenrecord 发 SIGINT 让其封口，避免残留进程与损坏 mp4。
            try:
                self._run(
                    ["adb", "-s", device_ip, "shell", "pkill", "-2", "screenrecord"],
                    timeout=5,
                )
            except Exception:
                pass
            ret = self._rec_procs.stop(f"record_{device_ip}")
            if ret is not None:
                result = {"success": True, "device_ip": device_ip, "message": "Recording stopped"}
            else:
                result = {"success": True, "device_ip": device_ip, "message": "No active recording"}
        except Exception as e:
            result = {"success": False, "device_ip": device_ip, "error": str(e)}
        if batch_id:
            result["batch_id"] = batch_id
        return result

    @async_command
    def pull_recorded_video_async(
        self,
        device_ip: str,
        remote_path: str,
        save_dir: str,
        filename: str,
        batch_id: str = "",
    ) -> dict:
        local_path = os.path.join(save_dir, filename)
        try:
            pull = self._run(
                ["adb", "-s", device_ip, "pull", remote_path, local_path],
                timeout=60,
            )
            if not pull["success"]:
                return {
                    "success": False,
                    "device_ip": device_ip,
                    "local_path": local_path,
                    "error": f"pull failed: {pull.get('error', 'unknown error')}",
                    "batch_id": batch_id,
                }
            cleanup = self._run(["adb", "-s", device_ip, "shell", "rm", remote_path])
            if not cleanup["success"]:
                return {
                    "success": False,
                    "device_ip": device_ip,
                    "local_path": local_path,
                    "error": f"cleanup failed: {cleanup.get('error', 'unknown error')}",
                    "batch_id": batch_id,
                }
            return {
                "success": True,
                "device_ip": device_ip,
                "local_path": local_path,
                "batch_id": batch_id,
            }
        except Exception as exc:
            return {
                "success": False,
                "device_ip": device_ip,
                "local_path": local_path,
                "error": str(exc),
                "batch_id": batch_id,
            }

    # 输入事件

    @async_command
    def input_tap_async(self, device_ip: str, x: int, y: int) -> dict:
        sent = self._send_input(device_ip, f"tap {int(x)} {int(y)}")
        return {"success": sent, "device_ip": device_ip, "x": x, "y": y}

    @async_command
    def input_swipe_async(
        self, device_ip: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> dict:
        sent = self._send_input(
            device_ip,
            f"swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
        )
        return {
            "success": sent,
            "device_ip": device_ip,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "duration_ms": duration_ms,
        }

    @async_command
    def input_keyevent_async(self, device_ip: str, keycode: str) -> dict:
        sent = self._send_input(device_ip, f"keyevent {keycode}")
        return {"success": sent, "device_ip": device_ip, "keycode": keycode}

    @async_command
    def input_longpress_async(self, device_ip: str, keycode: str) -> dict:
        sent = self._send_input(device_ip, f"keyevent --longpress {keycode}")
        return {"success": sent, "device_ip": device_ip, "keycode": keycode}

    @async_command
    def input_drag_async(
        self, device_ip: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> dict:
        sent = self._send_input(
            device_ip,
            f"draganddrop {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
        )
        return {"success": sent, "device_ip": device_ip}

    def _send_input(self, device_ip: str, input_args: str) -> bool:
        """复用持久 adb shell input 通道；失败时降级为有界同步命令并校验结果。"""
        try:
            return self._input_bridge().shell_input(input_args, device_id=device_ip)
        except Exception:
            return False

    def _input_bridge(self):
        if self._adb_bridge is None:
            from core.adb_bridge import ADBBridge

            self._adb_bridge = ADBBridge()
        return self._adb_bridge

    def close_input_sessions(self, device_ip: str | None = None):
        if self._adb_bridge is not None:
            self._adb_bridge.close_input_sessions(device_ip)

    def shutdown(self):
        """关闭高级功能持有的长生命周期进程，防止主窗口退出后残留。"""
        self._rec_procs.stop_all()
        self.close_input_sessions()

    # 性能诊断

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
            timeout=15,
            device_ip=device_ip,
        )

    @async_command
    def dumpsys_battery_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "battery"],
            timeout=15,
            device_ip=device_ip,
        )

    # Logcat 过滤

    @async_command
    def logcat_filtered_async(
        self,
        device_ip: str,
        log_path: str,
        buffer: str = "main",
        priority: str = "V",
        tag_filter: str = "",
        regex: str = "",
        max_lines: str = "",
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
            atomic_write_text(log_path, r["output"])
            return {
                "success": True,
                "device_ip": device_ip,
                "log_path": log_path,
                "line_count": len(r["output"].splitlines()),
            }
        return r

    @async_command
    def logcat_buffer_sizes_async(self, device_ip: str) -> dict:
        return self._run(["adb", "-s", device_ip, "logcat", "-g"], device_ip=device_ip)

    # 系统设置

    @async_command
    def settings_list_async(self, device_ip: str, namespace: str = "system") -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "settings", "list", namespace],
            timeout=15,
            device_ip=device_ip,
            namespace=namespace,
        )

    @async_command
    def settings_get_async(self, device_ip: str, namespace: str, key: str) -> dict:
        result = self._run(
            ["adb", "-s", device_ip, "shell", "settings", "get", namespace, key],
            device_ip=device_ip,
            key=key,
        )
        if result.get("success"):
            result["value"] = result.get("output", "")
        return result

    @async_command
    def settings_put_async(self, device_ip: str, namespace: str, key: str, value: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "settings", "put", namespace, key, value],
            device_ip=device_ip,
            key=key,
            value=value,
        )

    # 自定义 Shell 命令

    @async_command
    def run_shell_command_async(self, device_ip: str, command: str, timeout: int = 30) -> dict:
        full_cmd = ["adb", "-s", device_ip, "shell"] + shlex.split(command)
        return self._run(full_cmd, timeout=timeout, device_ip=device_ip, command=command)

    # 重启模式

    @async_command
    def reboot_mode_async(self, device_ip: str, mode: str) -> dict:
        cmd = ["adb", "-s", device_ip, "reboot"]
        if mode != "system":
            cmd.append(mode)
        r = self._run(cmd, timeout=3, device_ip=device_ip, mode=mode)
        # reboot 超时 = 设备正在重启 = 成功
        if r["success"] or "Timeout" in r.get("error", ""):
            return {
                "success": True,
                "device_ip": device_ip,
                "mode": mode,
                "output": f"Device rebooting to {mode}...",
            }
        return r

    # 文件管理

    @async_command
    def shell_ls_async(self, device_ip: str, path: str = "/sdcard") -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "ls", "-la", path],
            timeout=10,
            device_ip=device_ip,
            path=path,
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
            timeout=60,
            device_ip=device_ip,
        )

    @async_command
    def pull_file_async(self, device_ip: str, remote_path: str, local_path: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "pull", remote_path, local_path],
            timeout=60,
            device_ip=device_ip,
        )

    @async_command
    def shell_df_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "df", "-h"],
            device_ip=device_ip,
        )

    # 扩展系统信息

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
            timeout=15,
            device_ip=device_ip,
        )

    # 应用备份

    @async_command
    def backup_app_async(self, device_ip: str, package: str, save_path: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "backup", "-f", save_path, "-noapk", package],
            timeout=60,
            device_ip=device_ip,
        )
