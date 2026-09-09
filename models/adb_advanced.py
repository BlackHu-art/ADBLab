"""提供录屏、输入、性能诊断、Logcat 和文件管理等高级 ADB 操作。

本类直接实现通用高级操作，并通过多重继承复用 ADBNetworkMixin 和 ADBSystemMixin
中的网络及系统能力。
"""

import os
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QThreadPool

from core.exec import ProcessRunner
from utils.atomic_text import atomic_write_text

from .adb_model import ADBModelCore, async_command
from .adb_network import ADBNetworkMixin
from .adb_system import ADBSystemMixin


@dataclass
class _RecordingSession:
    """固定录屏进程与批次归属；停止判定发布后才允许保存完整文件。"""

    proc: subprocess.Popen
    key: str
    batch_id: str
    remote_path: str
    deadline: float
    stop_pending: bool = False
    error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)


def _recording_positive_integer(value: object, label: str) -> int:
    """校验录屏数值参数，避免动态值被设备端 shell 再次解释。"""
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise ValueError(f"{label} must be a positive integer")
    number = int(text)
    if number <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return number


class ADBAdvanced(ADBModelCore, ADBNetworkMixin, ADBSystemMixin):
    """组合核心、网络和系统级 ADB 操作。"""

    def __init__(self):
        super().__init__()
        self._rec_procs = ProcessRunner()
        self._record_lifecycle_lock = threading.Lock()
        self._record_sessions: dict[str, _RecordingSession] = {}
        # 录屏等待可长达一小时，独立有界池避免阻塞通用传输；额外保存按提交顺序排队。
        self._record_pool = QThreadPool(self)
        self._record_pool.setMaxThreadCount(2)
        self._adb_bridge = None
        self._adb_bridge_lock = threading.Lock()

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
        """登记受控录屏请求；返回成功仅确认本机进程创建，不代表设备录制已就绪。"""
        try:
            duration = _recording_positive_integer(duration, "Recording duration")
            if duration > 3600:
                raise ValueError("Recording duration must be between 1 and 3600 seconds")
            bitrate = str(_recording_positive_integer(bitrate, "Recording bitrate"))
            if width or height:
                width = str(_recording_positive_integer(width, "Recording width"))
                height = str(_recording_positive_integer(height, "Recording height"))
            sanitized = re.sub(r"\W+", "_", device_ip)
            timestamp = datetime.now().strftime("%H%M%S_%f")
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
            with self._record_lifecycle_lock:
                if self.is_shutting_down():
                    return {
                        "success": False,
                        "cancelled": True,
                        "device_ip": device_ip,
                        "error": "Model is shutting down",
                        "batch_id": batch_id,
                    }
                if device_ip in self._record_sessions:
                    raise RuntimeError("Recording is already active")
                key = f"record_{device_ip}_{batch_id}"
                proc = self._rec_procs.start(
                    key,
                    cmd,
                    stderr=subprocess.DEVNULL,
                )
                session = _RecordingSession(
                    proc, key, batch_id, remote_path, time.monotonic() + duration + 30,
                )
                self._record_sessions[device_ip] = session
            if proc.poll() not in (None, 0):
                self._rec_procs.stop(key)
                with self._record_lifecycle_lock:
                    if self._record_sessions.get(device_ip) is session:
                        self._record_sessions.pop(device_ip)
                return {
                    "success": False,
                    "device_ip": device_ip,
                    "error": "screenrecord exited immediately",
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

    def _wait_recording_complete(self, session: _RecordingSession) -> dict:
        """后台等待所属进程自然退出；超时、关闭或设备停止失败均禁止拉取。"""
        while True:
            if self.is_shutting_down():
                return {"success": False, "cancelled": True, "error": "Model is shutting down"}
            with session.lock:
                if session.error:
                    return {"success": False, "error": session.error}
                code = session.proc.poll()
                if code is not None and not session.stop_pending:
                    if code == 0:
                        return {"success": True}
                    return {"success": False, "error": f"screenrecord exited with code {code}"}
                if time.monotonic() >= session.deadline and not session.stop_pending:
                    session.error = "Recording completion timed out; video completeness is unknown"
                    return {"success": False, "error": session.error}
            self._shutdown_started.wait(0.1)

    @async_command
    def stop_screen_record_async(self, device_ip: str, batch_id: str = "") -> dict:
        """停止原批次并等待设备封口；设备 SIGINT 失败不由本机清理结果覆盖。"""
        result = {"success": False, "device_ip": device_ip, "batch_id": batch_id}
        # Stop 可能先于排队中的 Start 执行；只等待同批次登记，不得停止其他批次。
        deadline = time.monotonic() + 30
        while True:
            with self._record_lifecycle_lock:
                session = self._record_sessions.get(device_ip)
            if session is not None or not batch_id or self.is_shutting_down():
                break
            if time.monotonic() >= deadline:
                break
            self._shutdown_started.wait(0.1)
        if session is None or session.batch_id != batch_id:
            return {**result, "error": "No matching active recording",
                    "message": "No matching active recording"}
        with session.lock:
            if session.error:
                return {**result, "error": session.error, "message": session.error}
            if session.stop_pending:
                return {**result, "error": "Recording stop is already pending"}
            if session.proc.poll() == 0:
                return {**result, "success": True, "message": "Recording already completed"}
            session.stop_pending = True
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self.is_shutting_down():
                raise RuntimeError("Recording stop cancelled or timed out")
            signal_result = self._run(
                ["adb", "-s", device_ip, "shell", "pkill", "-2", "screenrecord"],
                timeout=remaining, cancelled=self.is_shutting_down,
            )
            if not signal_result.get("success"):
                raise RuntimeError(signal_result.get("error") or "Device recording stop failed")
            # 成功发信号后继续等待原进程退出，不能用 terminate 的返回值证明设备已封口。
            while session.proc.poll() is None:
                if self.is_shutting_down():
                    raise RuntimeError("Model is shutting down")
                if time.monotonic() >= deadline:
                    raise RuntimeError("Recording stop timed out; video completeness is unknown")
                self._shutdown_started.wait(0.1)
            if session.proc.poll() != 0:
                raise RuntimeError(f"screenrecord exited with code {session.proc.poll()}")
            result.update(success=True, message="Recording stopped")
        except Exception as exc:
            # 先发布失败事实，再清理本机资源，避免保存线程将强停误判为自然结束。
            with session.lock:
                session.error = str(exc)
            self._rec_procs.stop(session.key)
            result.update(error=str(exc), message=str(exc))
        finally:
            with session.lock:
                session.stop_pending = False
        return result

    @async_command(long_running=True, pool_attribute="_record_pool")
    def pull_recorded_video_async(
        self,
        device_ip: str,
        remote_path: str,
        save_dir: str,
        filename: str,
        batch_id: str = "",
    ) -> dict:
        """在后台确认本批次完成后拉取，关闭取消等待但不删除未确认完整的远端文件。"""
        local_path = os.path.join(save_dir, filename)
        with self._record_lifecycle_lock:
            session = self._record_sessions.get(device_ip)
        if session is None or session.batch_id != batch_id or session.remote_path != remote_path:
            return {"success": False, "device_ip": device_ip, "batch_id": batch_id,
                    "error": "No matching recording process"}
        try:
            completion = self._wait_recording_complete(session)
            if not completion["success"]:
                return {**completion, "device_ip": device_ip, "batch_id": batch_id}
            pull = self._run(
                ["adb", "-s", device_ip, "pull", remote_path, local_path],
                timeout=60, cancelled=self.is_shutting_down,
            )
            if not pull["success"]:
                return {
                    "success": False,
                    "device_ip": device_ip,
                    "local_path": local_path,
                    "error": f"pull failed: {pull.get('error', 'unknown error')}",
                    "batch_id": batch_id,
                }
            cleanup = self._run(["adb", "-s", device_ip, "shell", "rm", shlex.quote(remote_path)])
            result = {
                "success": True,
                "device_ip": device_ip,
                "local_path": local_path,
                "batch_id": batch_id,
            }
            if not cleanup["success"]:
                result["cleanup_error"] = cleanup.get("error", "unknown error")
            return result
        except Exception as exc:
            return {
                "success": False,
                "device_ip": device_ip,
                "local_path": local_path,
                "error": str(exc),
                "batch_id": batch_id,
            }
        finally:
            # 清理失败时保留设备占用，防止新批次与残留的录屏进程并行。
            self._rec_procs.stop(session.key)
            with self._record_lifecycle_lock:
                if (self._record_sessions.get(device_ip) is session
                        and session.proc.poll() is not None):
                    self._record_sessions.pop(device_ip)

    # 输入事件

    @async_command
    def input_tap_async(self, device_ip: str, x: int, y: int) -> dict:
        sent, error = self._send_input(device_ip, f"tap {int(x)} {int(y)}")
        result = {"success": sent, "device_ip": device_ip, "x": x, "y": y}
        if error:
            result["error"] = error
        return result

    @async_command
    def input_swipe_async(
        self, device_ip: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> dict:
        sent, error = self._send_input(
            device_ip,
            f"swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
        )
        result = {
            "success": sent,
            "device_ip": device_ip,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "duration_ms": duration_ms,
        }
        if error:
            result["error"] = error
        return result

    @async_command
    def input_keyevent_async(self, device_ip: str, keycode: str) -> dict:
        sent, error = self._send_input(device_ip, f"keyevent {int(keycode)}")
        result = {"success": sent, "device_ip": device_ip, "keycode": keycode}
        if error:
            result["error"] = error
        return result

    def _send_input(self, device_ip: str, input_args: str) -> tuple[bool, str]:
        """复用持久 adb shell input 通道；失败时降级为有界同步命令并校验结果。

        返回 (是否成功, 错误信息)；成功时错误信息为空字符串。
        """
        try:
            sent = self._input_bridge().shell_input(input_args, device_id=device_ip)
            return sent, "" if sent else "input command failed"
        except Exception as exc:
            return False, str(exc)

    def _input_bridge(self):
        if self._adb_bridge is None:
            with self._adb_bridge_lock:
                if self._adb_bridge is None:
                    from core.adb_bridge import ADBBridge

                    self._adb_bridge = ADBBridge()
        return self._adb_bridge

    def close_input_sessions(self, device_ip: str | None = None):
        if self._adb_bridge is not None:
            self._adb_bridge.close_input_sessions(device_ip)

    def shutdown(self):
        """关闭高级功能持有的长生命周期进程，防止主窗口退出后残留。"""
        self.begin_shutdown()
        with self._record_lifecycle_lock:
            self._rec_procs.stop_all()
        self.close_input_sessions()

    def wait_for_commands(self) -> None:
        """后台关闭线程同时排空普通命令和录屏专用池，确保模型释放前不留回调。"""
        super().wait_for_commands()
        self._record_pool.waitForDone()

    # 性能诊断

    @async_command
    def dumpsys_meminfo_async(self, device_ip: str, package: str = "") -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "dumpsys", "meminfo"]
        if package:
            cmd.append(shlex.quote(package))
        return self._run_readonly(cmd, timeout=15, device_ip=device_ip, package=package)

    @async_command
    def dumpsys_cpuinfo_async(self, device_ip: str) -> dict:
        return self._run_readonly(
            ["adb", "-s", device_ip, "shell", "dumpsys", "cpuinfo"],
            timeout=15,
            device_ip=device_ip,
        )

    @async_command
    def dumpsys_battery_async(self, device_ip: str) -> dict:
        return self._run_readonly(
            ["adb", "-s", device_ip, "shell", "dumpsys", "battery"],
            timeout=15,
            device_ip=device_ip,
        )

    # Logcat 过滤

    @async_command(long_running=True)
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
        r = self._run_readonly(cmd, timeout=30, device_ip=device_ip)
        if r["success"]:
            atomic_write_text(log_path, r["output"])
            return {
                "success": True,
                "device_ip": device_ip,
                "log_path": log_path,
                "line_count": len(r["output"].splitlines()),
            }
        return r

    # 系统设置

    @async_command
    def settings_list_async(self, device_ip: str, namespace: str = "system") -> dict:
        return self._run_readonly(
            ["adb", "-s", device_ip, "shell", "settings", "list", shlex.quote(namespace)],
            timeout=15,
            device_ip=device_ip,
            namespace=namespace,
        )

    @async_command
    def settings_get_async(self, device_ip: str, namespace: str, key: str) -> dict:
        result = self._run_readonly(
            [
                "adb", "-s", device_ip, "shell", "settings", "get",
                shlex.quote(namespace), shlex.quote(key),
            ],
            device_ip=device_ip,
            key=key,
        )
        if result.get("success"):
            result["value"] = result.get("output", "")
        return result

    @async_command
    def settings_put_async(self, device_ip: str, namespace: str, key: str, value: str) -> dict:
        return self._run(
            [
                "adb", "-s", device_ip, "shell", "settings", "put",
                shlex.quote(namespace), shlex.quote(key), shlex.quote(value),
            ],
            device_ip=device_ip,
            key=key,
            value=value,
        )

    # 自定义 Shell 命令

    @async_command
    def run_shell_command_async(self, device_ip: str, command: str, timeout: int = 30) -> dict:
        """自定义命令可能依赖 stdin；在输入语义明确前保留原生执行。"""
        full_cmd = ["adb", "-s", device_ip, "shell", command]
        return self._run(
            full_cmd, timeout=timeout, native_only=True, device_ip=device_ip, command=command,
        )

    # 重启模式

    @async_command
    def reboot_mode_async(self, device_ip: str, mode: str) -> dict:
        """提交模式重启；超时表示结果未知，核实状态前不得自动重发。"""
        cmd = ["adb", "-s", device_ip, "reboot"]
        if mode != "system":
            cmd.append(mode)
        r = self._run(cmd, timeout=30, device_ip=device_ip, mode=mode)
        if r["success"]:
            return {
                "success": True,
                "device_ip": device_ip,
                "mode": mode,
                "requires_refresh": True,
                "output": (
                    f"Reboot request submitted for {mode}; device startup has not been verified"
                ),
            }
        if "timeout" in r.get("error", "").lower():
            return {
                "success": False, "device_ip": device_ip, "mode": mode,
                "requires_refresh": True,
                "error": "Reboot result unknown after timeout; check device status before retrying",
            }
        return {**r, "device_ip": device_ip, "mode": mode, "requires_refresh": False}

    # 文件管理

    @async_command
    def shell_ls_async(self, device_ip: str, path: str = "/sdcard") -> dict:
        return self._run_readonly(
            ["adb", "-s", device_ip, "shell", "ls", "-la", shlex.quote(path)],
            timeout=10,
            device_ip=device_ip,
            path=path,
        )

    @async_command(long_running=True)
    def push_file_async(self, device_ip: str, local_path: str, remote_path: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "push", local_path, remote_path],
            timeout=60,
            device_ip=device_ip,
        )

    @async_command(long_running=True)
    def pull_file_async(self, device_ip: str, remote_path: str, local_path: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "pull", remote_path, local_path],
            timeout=60,
            device_ip=device_ip,
        )

    # 扩展系统信息

    @async_command
    def get_device_uptime_async(self, device_ip: str) -> dict:
        return self._run_readonly(
            ["adb", "-s", device_ip, "shell", "uptime"],
            device_ip=device_ip,
        )

    @async_command
    def get_cpu_info_async(self, device_ip: str) -> dict:
        return self._run_readonly(
            ["adb", "-s", device_ip, "shell", "cat", "/proc/cpuinfo"],
            device_ip=device_ip,
        )

    @async_command
    def get_kernel_version_async(self, device_ip: str) -> dict:
        return self._run_readonly(
            ["adb", "-s", device_ip, "shell", "cat", "/proc/version"],
            device_ip=device_ip,
        )
