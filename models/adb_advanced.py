"""
Advanced ADB operations: screen recording, input events, performance diagnostics,
logcat filtering, port forwarding, settings, shell commands, reboot modes,
file manager, app permissions, broadcast, wireless pairing, process management,
content provider, battery simulation, cmd tools, emulator, IME, deep links.

Imports only from adb_model (core) — no circular dependencies.
"""

import os
import subprocess
from datetime import datetime

from .adb_model import ADBModelCore, async_command


class ADBAdvanced(ADBModelCore):
    """Advanced ADB operations beyond basic device/app/testing management."""

    # ── Screen Recording ─────────────────────────────────────────────────

    @async_command
    def start_screen_record_async(
        self,
        device_ip: str,
        save_dir: str,
        duration: int = 180,
        width: str = "",
        height: str = "",
        bitrate: str = "8000000",
    ) -> dict:
        try:
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"record_{timestamp}.mp4"
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
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return {
                "success": True,
                "device_ip": device_ip,
                "remote_path": remote_path,
                "proc_pid": proc.pid,
                "filename": filename,
                "save_dir": save_dir,
                "process": id(proc),
            }
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
            result = self._execute_command(
                [
                    "adb",
                    "-s",
                    device_ip,
                    "shell",
                    "input",
                    "swipe",
                    str(x1),
                    str(y1),
                    str(x2),
                    str(y2),
                    str(duration_ms),
                ]
            )
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
            result = self._execute_command(
                [
                    "adb",
                    "-s",
                    device_ip,
                    "shell",
                    "input",
                    "draganddrop",
                    str(x1),
                    str(y1),
                    str(x2),
                    str(y2),
                    str(duration_ms),
                ]
            )
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
        self,
        device_ip: str,
        log_path: str,
        buffer: str = "main",
        priority: str = "V",
        tag_filter: str = "",
        regex: str = "",
        max_lines: str = "",
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
                "success": True,
                "device_ip": device_ip,
                "log_path": log_path,
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

    # ── Port Forwarding ──────────────────────────────────────────────────

    @async_command
    def forward_port_async(
        self, device_ip: str, local_port: str, remote_port: str, protocol: str = "tcp"
    ) -> dict:
        try:
            spec = f"{protocol}:{local_port}"
            remote_spec = f"{protocol}:{remote_port}"
            result = self._execute_command(["adb", "-s", device_ip, "forward", spec, remote_spec])
            return {
                "success": True,
                "device_ip": device_ip,
                "output": result,
                "local": spec,
                "remote": remote_spec,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def list_forwards_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "forward", "--list"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def remove_forward_async(self, device_ip: str, local_spec: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "forward", "--remove", local_spec]
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def remove_all_forwards_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "forward", "--remove-all"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def reverse_port_async(
        self, device_ip: str, remote_port: str, local_port: str, protocol: str = "tcp"
    ) -> dict:
        try:
            spec = f"{protocol}:{remote_port}"
            local_spec = f"{protocol}:{local_port}"
            result = self._execute_command(["adb", "-s", device_ip, "reverse", spec, local_spec])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def list_reverse_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "reverse", "--list"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def remove_all_reverse_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "reverse", "--remove-all"])
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
                "success": True,
                "device_ip": device_ip,
                "output": result,
                "namespace": namespace,
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
                "success": True,
                "device_ip": device_ip,
                "key": key,
                "value": value,
                "output": result,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Custom Shell Command ─────────────────────────────────────────────

    @async_command
    def run_shell_command_async(self, device_ip: str, command: str, timeout: int = 30) -> dict:
        try:
            full_cmd = ["adb", "-s", device_ip, "shell"] + command.split()
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
                "success": True,
                "device_ip": device_ip,
                "mode": mode,
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

    # ── App Permissions ─────────────────────────────────────────────────

    @async_command
    def grant_permission_async(self, device_ip: str, package: str, permission: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "grant", package, permission]
            )
            return {
                "success": True,
                "device_ip": device_ip,
                "package": package,
                "permission": permission,
                "output": result,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def revoke_permission_async(self, device_ip: str, package: str, permission: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "revoke", package, permission]
            )
            return {
                "success": True,
                "device_ip": device_ip,
                "package": package,
                "permission": permission,
                "output": result,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def reset_permissions_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "reset-permissions", package]
            )
            return {"success": True, "device_ip": device_ip, "package": package, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def list_permissions_async(self, device_ip: str, package: str = "") -> dict:
        try:
            if package:
                result = self._execute_command(
                    ["adb", "-s", device_ip, "shell", "pm", "dump", package], timeout=15
                )
            else:
                result = self._execute_command(
                    ["adb", "-s", device_ip, "shell", "pm", "list", "permissions"], timeout=15
                )
            return {"success": True, "device_ip": device_ip, "package": package, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── App Disable/Enable ──────────────────────────────────────────────

    @async_command
    def disable_package_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "disable", package]
            )
            return {"success": True, "device_ip": device_ip, "package": package, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def enable_package_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "enable", package]
            )
            return {"success": True, "device_ip": device_ip, "package": package, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def disable_package_user_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "disable-user", package]
            )
            return {"success": True, "device_ip": device_ip, "package": package, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Broadcast Intents ───────────────────────────────────────────────

    @async_command
    def send_broadcast_async(self, device_ip: str, action: str, extras: dict = None) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "am", "broadcast", "-a", action]
            if extras:
                for k, v in (extras or {}).items():
                    if isinstance(v, bool):
                        cmd.extend(["--ez", k, "true" if v else "false"])
                    elif isinstance(v, int):
                        cmd.extend(["--ei", k, str(v)])
                    elif isinstance(v, float):
                        cmd.extend(["--ef", k, str(v)])
                    else:
                        cmd.extend(["--es", k, str(v)])
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Advanced Activity Start ──────────────────────────────────────────

    @async_command
    def start_activity_async(
        self,
        device_ip: str,
        component: str = "",
        action: str = "",
        data_uri: str = "",
        mime_type: str = "",
        flags: str = "",
        wait: bool = False,
    ) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "am", "start"]
            if component:
                cmd.extend(["-n", component])
            if action:
                cmd.extend(["-a", action])
            if data_uri:
                cmd.extend(["-d", data_uri])
            if mime_type:
                cmd.extend(["-t", mime_type])
            if flags:
                cmd.extend(["-f", flags])
            if wait:
                cmd.append("-W")
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def open_deep_link_async(self, device_ip: str, uri: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "am", "start", "-d", uri], timeout=15
            )
            return {"success": True, "device_ip": device_ip, "uri": uri, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Wireless Debugging ──────────────────────────────────────────────

    @async_command
    def tcpip_mode_async(self, device_ip: str, port: str = "5555") -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "tcpip", port])
            return {"success": True, "device_ip": device_ip, "port": port, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pair_device_async(self, ip_address: str, port: str, pairing_code: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "pair", f"{ip_address}:{port}", pairing_code], timeout=15
            )
            return {"success": True, "ip": ip_address, "output": result}
        except Exception as e:
            return {"success": False, "ip": ip_address, "error": str(e)}

    # ── Process Management ──────────────────────────────────────────────

    @async_command
    def list_processes_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "ps", "-A"], timeout=10
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def top_snapshot_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "top", "-b", "-n", "1"], timeout=10
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def kill_process_async(self, device_ip: str, pid: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "kill", pid])
            return {"success": True, "device_ip": device_ip, "pid": pid, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Content Provider ────────────────────────────────────────────────

    @async_command
    def content_query_async(
        self, device_ip: str, uri: str, projection: str = "", where: str = "", sort: str = ""
    ) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "content", "query", "--uri", uri]
            if projection:
                cmd.extend(["--projection", projection])
            if where:
                cmd.extend(["--where", where])
            if sort:
                cmd.extend(["--sort", sort])
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def content_insert_async(self, device_ip: str, uri: str, binds: dict = None) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "content", "insert", "--uri", uri]
            for k, v in (binds or {}).items():
                cmd.extend(["--bind", f"{k}:s:{v}"])
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def content_delete_async(self, device_ip: str, uri: str, where: str = "") -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "content", "delete", "--uri", uri]
            if where:
                cmd.extend(["--where", where])
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Battery Simulation ──────────────────────────────────────────────

    @async_command
    def battery_set_level_async(self, device_ip: str, level: int) -> dict:
        try:
            self._execute_command(
                ["adb", "-s", device_ip, "shell", "dumpsys", "battery", "set", "level", str(level)]
            )
            return {"success": True, "device_ip": device_ip, "level": level}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def battery_set_status_async(self, device_ip: str, status: str) -> dict:
        try:
            self._execute_command(
                [
                    "adb",
                    "-s",
                    device_ip,
                    "shell",
                    "dumpsys",
                    "battery",
                    "set",
                    "status",
                    str(status),
                ]
            )
            return {"success": True, "device_ip": device_ip, "status": status}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def battery_reset_async(self, device_ip: str) -> dict:
        try:
            self._execute_command(["adb", "-s", device_ip, "shell", "dumpsys", "battery", "reset"])
            return {"success": True, "device_ip": device_ip}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── CMD Tools ───────────────────────────────────────────────────────

    @async_command
    def cmd_wifi_enable_async(self, device_ip: str, enable: bool) -> dict:
        try:
            action = "enable" if enable else "disable"
            self._execute_command(["adb", "-s", device_ip, "shell", "svc", "wifi", action])
            return {"success": True, "device_ip": device_ip, "action": action}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_data_enable_async(self, device_ip: str, enable: bool) -> dict:
        try:
            action = "enable" if enable else "disable"
            self._execute_command(["adb", "-s", device_ip, "shell", "svc", "data", action])
            return {"success": True, "device_ip": device_ip, "action": action}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_bluetooth_enable_async(self, device_ip: str, enable: bool) -> dict:
        try:
            action = "enable" if enable else "disable"
            self._execute_command(["adb", "-s", device_ip, "shell", "svc", "bluetooth", action])
            return {"success": True, "device_ip": device_ip, "action": action}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_nfc_enable_async(self, device_ip: str, enable: bool) -> dict:
        try:
            action = "enable" if enable else "disable"
            self._execute_command(["adb", "-s", device_ip, "shell", "svc", "nfc", action])
            return {"success": True, "device_ip": device_ip, "action": action}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_statusbar_expand_async(self, device_ip: str) -> dict:
        try:
            self._execute_command(
                ["adb", "-s", device_ip, "shell", "cmd", "statusbar", "expand-settings"]
            )
            return {"success": True, "device_ip": device_ip}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_uimode_night_async(self, device_ip: str, enable: bool) -> dict:
        try:
            mode = "yes" if enable else "no"
            self._execute_command(["adb", "-s", device_ip, "shell", "cmd", "uimode", "night", mode])
            return {"success": True, "device_ip": device_ip, "mode": mode}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_dumpsys_service_async(self, device_ip: str, service: str = "") -> dict:
        try:
            if service:
                result = self._execute_command(
                    ["adb", "-s", device_ip, "shell", "dumpsys", service], timeout=20
                )
            else:
                result = self._execute_command(
                    ["adb", "-s", device_ip, "shell", "service", "list"], timeout=10
                )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_launcher_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "cmd", "shortcut", "get-default-launcher"]
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Emulator Control ────────────────────────────────────────────────

    @async_command
    def emu_sms_send_async(self, device_ip: str, sender: str, text: str) -> dict:
        try:
            self._execute_command(["adb", "-s", device_ip, "emu", "sms", "send", sender, text])
            return {"success": True, "device_ip": device_ip, "sender": sender}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def emu_call_async(self, device_ip: str, number: str) -> dict:
        try:
            self._execute_command(["adb", "-s", device_ip, "emu", "call", number])
            return {"success": True, "device_ip": device_ip, "number": number}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def emu_geo_fix_async(
        self, device_ip: str, longitude: str, latitude: str, altitude: str = ""
    ) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "emu", "geo", "fix", longitude, latitude]
            if altitude:
                cmd.append(altitude)
            self._execute_command(cmd)
            return {
                "success": True,
                "device_ip": device_ip,
                "longitude": longitude,
                "latitude": latitude,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def emu_rotate_async(self, device_ip: str) -> dict:
        try:
            self._execute_command(["adb", "-s", device_ip, "emu", "rotate"])
            return {"success": True, "device_ip": device_ip}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── IME Management ──────────────────────────────────────────────────

    @async_command
    def ime_list_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "ime", "list", "-s"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def ime_set_async(self, device_ip: str, ime_id: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "ime", "set", ime_id])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Package Info Extended ───────────────────────────────────────────

    @async_command
    def pm_path_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "pm", "path", package])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pm_dump_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "dump", package], timeout=15
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pm_list_features_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "list", "features"], timeout=10
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pm_list_users_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "pm", "list", "users"])
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

    # ── Network ─────────────────────────────────────────────────────────

    @async_command
    def shell_ping_async(self, device_ip: str, host: str, count: str = "4") -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "ping", "-c", count, host], timeout=30
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def shell_netstat_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "netstat"], timeout=10)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── App Standby / Inactive ──────────────────────────────────────────

    @async_command
    def set_inactive_async(self, device_ip: str, package: str, inactive: bool) -> dict:
        try:
            state = "true" if inactive else "false"
            self._execute_command(
                ["adb", "-s", device_ip, "shell", "am", "set-inactive", package, state]
            )
            return {"success": True, "device_ip": device_ip, "package": package, "inactive": state}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def force_stop_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "am", "force-stop", package]
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Quick Settings ──────────────────────────────────────────────────

    @async_command
    def quick_setting_async(self, device_ip: str, action: str) -> dict:
        actions = {
            "anim_off": [
                "settings put global animator_duration_scale 0",
                "settings put global transition_animation_scale 0",
                "settings put global window_animation_scale 0",
            ],
            "anim_on": [
                "settings put global animator_duration_scale 1",
                "settings put global transition_animation_scale 1",
                "settings put global window_animation_scale 1",
            ],
            "stay_awake": [
                "settings put global stay_on_while_plugged_in 7",
            ],
        }
        try:
            if action in actions:
                for cmd_str in actions[action]:
                    shell_cmd = cmd_str.split()
                    full_cmd = ["adb", "-s", device_ip, "shell"] + shell_cmd
                    self._execute_command(full_cmd)
                return {"success": True, "device_ip": device_ip, "action": action}
            return {"success": False, "device_ip": device_ip, "error": f"Unknown action: {action}"}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Keycode dictionary for reference ─────────────────────────────────

    KEYCODES = {
        "HOME": "3",
        "BACK": "4",
        "CALL": "5",
        "ENDCALL": "6",
        "VOLUME_UP": "24",
        "VOLUME_DOWN": "25",
        "POWER": "26",
        "CAMERA": "27",
        "CLEAR": "28",
        "ENTER": "66",
        "DEL": "67",
        "MENU": "82",
        "SEARCH": "84",
        "DPAD_UP": "19",
        "DPAD_DOWN": "20",
        "DPAD_LEFT": "21",
        "DPAD_RIGHT": "22",
        "DPAD_CENTER": "23",
        "MEDIA_PLAY_PAUSE": "85",
        "MEDIA_STOP": "86",
        "MEDIA_NEXT": "87",
        "MEDIA_PREVIOUS": "88",
        "MEDIA_REWIND": "89",
        "MEDIA_FAST_FORWARD": "90",
        "MUTE": "91",
        "PAGE_UP": "92",
        "PAGE_DOWN": "93",
        "NOTIFICATION": "83",
        "SETTINGS": "176",
        "APP_SWITCH": "187",
        "ASSIST": "219",
        "CHANNEL_UP": "166",
        "CHANNEL_DOWN": "167",
        "TV_INPUT": "178",
        "TV_POWER": "177",
        "SLEEP": "223",
        "WAKEUP": "224",
        "BRIGHTNESS_UP": "221",
        "BRIGHTNESS_DOWN": "220",
    }
