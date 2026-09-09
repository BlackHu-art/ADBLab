"""为 ADBLab 提供轻量的 ADB Shell 调用封装。

ADB 路径由 utils.adb_resolver 解析，内置 scrcpy ADB 的优先级高于系统 PATH。
"""

import subprocess
import threading
from collections.abc import Callable

from core.exec import CommandResult, CommandRunner, ExecHandle, ProcessRunner, adb_runtime
from utils.adb_resolver import adb_path, resolve_adb_path


class ADBInputSession:
    """维护持久化的 adb shell 会话，降低输入命令延迟。

    会话进程通过 ProcessRunner 注册进实例与全局跟踪表，关闭时先礼貌退出，
    再由 runner 兜底终止进程树（ADR-0003 Phase 1）。
    """

    def __init__(
        self,
        adb: str,
        device_id: str | None = None,
        runner: ProcessRunner | None = None,
    ):
        self.adb = adb
        self.device_id = device_id
        self._proc: ExecHandle | None = None
        self._lock = threading.Lock()
        self._runner = runner or ProcessRunner()

    @property
    def _key(self) -> str:
        return f"adb-input-session-{id(self)}"

    def send(
        self, command: str, *, cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        """写入持久管道；失败可能已部分发送，调用方不得据此重放输入。"""
        with self._lock:
            if cancelled is not None and cancelled():
                return False
            proc = self._ensure_process()
            if not proc or not proc.stdin or (cancelled is not None and cancelled()):
                return False
            try:
                proc.stdin.write(f"input {command}\n")
                proc.stdin.flush()
                return True
            except (BrokenPipeError, OSError, ValueError):
                # 写入失败可能留下部分缓冲，不能以 exit 再次刷新未知输入。
                self._close_locked(graceful=False)
                return False

    def close(self):
        with self._lock:
            self._close_locked()

    def warm(self, *, cancelled: Callable[[], bool] | None = None) -> bool:
        """在第一条真实输入命令前预先打开持久 Shell。"""
        with self._lock:
            if cancelled is not None and cancelled():
                return False
            proc = self._ensure_process()
            return bool(
                proc and proc.stdin and proc.poll() is None
                and not (cancelled is not None and cancelled())
            )

    def _ensure_process(self) -> ExecHandle | None:
        if self._proc and self._proc.poll() is None:
            return self._proc
        self._close_locked()
        cmd = [self.adb]
        if self.device_id:
            cmd.extend(["-s", self.device_id])
        cmd.append("shell")
        try:
            self._proc = self._runner.start(
                self._key,
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            return self._proc
        except Exception:
            self._proc = None
            return None

    def _close_locked(self, *, graceful: bool = True):
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if graceful and proc.stdin and proc.poll() is None:
                proc.stdin.write("exit\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            self._runner.stop(self._key, timeout=1)
        except Exception:
            pass


class ADBBridge:
    """封装 ADB Shell、输入、屏幕尺寸和设备列表命令。"""

    def __init__(self, path: str | None = None):
        self.path = path or adb_path()
        self._process_runner = ProcessRunner()
        self._input_sessions: dict[str, ADBInputSession] = {}
        self._input_sessions_lock = threading.Lock()
        if path is None and resolve_adb_path() is None:
            raise FileNotFoundError("ADB not found — install Android SDK Platform Tools")

    def shell(
        self, command: str, device_id: str | None = None,
        *, cancelled: Callable[[], bool] | None = None,
    ) -> CommandResult:
        """执行有界 Shell 命令，按调用方取消信号收口并返回标准化结果。"""
        cmd = [self.path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", command])
        if cancelled is None:
            return CommandRunner.run(cmd, timeout=15)
        return CommandRunner.run(cmd, timeout=15, cancelled=cancelled)

    def can_input_fast(self, device_id: str | None = None) -> bool:
        """读取应用运行实例对当前设备的直连选择，不隐式创建实例或探测设备。"""
        runtime = adb_runtime()
        return bool(device_id and runtime and runtime.can_shell_fast(self.path, device_id))

    def shell_input(
        self, command: str, device_id: str | None = None,
        *, cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        """向设备 Shell 发送 input 命令，例如 keyevent 或 swipe。

        已验证设备经统一执行器直连并按远端结果返回；其他设备复用持久会话。
        仅尚未写入输入的会话准备失败可以降级，写入或直连发送后的失败不重放。
        取消只阻止后续发送并收口在途请求，不表示已执行的设备操作被撤销。
        """
        if cancelled is not None and cancelled():
            return False
        cancel_options = {"cancelled": cancelled} if cancelled is not None else {}
        if not self.can_input_fast(device_id):
            session = self._input_session(device_id)
            if session.warm(**cancel_options):
                return session.send(command, **cancel_options)
        cmd = [self.path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", f"input {command}"])
        if cancelled is None:
            return CommandRunner.run(cmd, timeout=15).success
        return CommandRunner.run(cmd, timeout=15, cancelled=cancelled).success

    def warm_input_session(
        self, device_id: str | None = None,
        *, cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        """直连能力已就绪时直接返回；仅原生后端预建会话，始终不发送用户输入。"""
        if cancelled is not None and cancelled():
            return False
        if self.can_input_fast(device_id):
            return True
        cancel_options = {"cancelled": cancelled} if cancelled is not None else {}
        return self._input_session(device_id).warm(**cancel_options)

    def close_input_sessions(self, device_id: str | None = None):
        """关闭持久输入 Shell 会话，供面板或服务停止时清理资源。"""
        with self._input_sessions_lock:
            if device_id is None:
                sessions = list(self._input_sessions.values())
                self._input_sessions.clear()
            else:
                session = self._input_sessions.pop(self._session_key(device_id), None)
                sessions = [session] if session else []
        for session in sessions:
            session.close()

    def _input_session(self, device_id: str | None) -> ADBInputSession:
        key = self._session_key(device_id)
        with self._input_sessions_lock:
            session = self._input_sessions.get(key)
            if session is None:
                session = ADBInputSession(self.path, device_id, runner=self._process_runner)
                self._input_sessions[key] = session
            return session

    @staticmethod
    def _session_key(device_id: str | None) -> str:
        return device_id or "__default__"

    def get_dimensions(
        self, device_id: str | None = None,
        *, cancelled: Callable[[], bool] | None = None,
    ):
        """通过可取消的 wm size 获取屏幕尺寸，返回宽高列表或 None。"""
        try:
            result = (
                self.shell("wm size", device_id=device_id)
                if cancelled is None
                else self.shell("wm size", device_id=device_id, cancelled=cancelled)
            )
            raw = result.output if result.success else result.error
            for prefix in ("Physical size:", "Override size:"):
                if prefix in raw:
                    return raw[raw.find(prefix) :].split(":")[1].strip().split("x")
            return None
        except Exception:
            return None

    def devices(self) -> list[list[str]]:
        """返回由设备序列号和连接状态组成的设备列表。"""
        result = CommandRunner.run([self.path, "devices"], timeout=15)
        if not result.success:
            return []
        out = result.output
        return [line.split("\t") for line in out.strip().splitlines()[1:] if line.strip()]
