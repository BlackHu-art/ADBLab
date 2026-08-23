"""为 ADBLab 提供轻量的 ADB Shell 调用封装。

ADB 路径由 utils.adb_resolver 解析，内置 scrcpy ADB 的优先级高于系统 PATH。
"""

import logging
import subprocess
import threading

from core.exec import CommandResult, CommandRunner, ExecHandle, ProcessRunner
from utils.adb_resolver import adb_path

logger = logging.getLogger("adb_bridge")


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

    def send(self, command: str) -> bool:
        """通过标准输入发送命令；返回 False 时由调用方执行降级路径。"""
        with self._lock:
            proc = self._ensure_process()
            if not proc or not proc.stdin:
                return False
            try:
                proc.stdin.write(f"input {command}\n")
                proc.stdin.flush()
                return True
            except (BrokenPipeError, OSError, ValueError):
                self._close_locked()
                return False

    def close(self):
        with self._lock:
            self._close_locked()

    def warm(self) -> bool:
        """在第一条真实输入命令前预先打开持久 Shell。"""
        with self._lock:
            proc = self._ensure_process()
            return bool(proc and proc.stdin and proc.poll() is None)

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

    def _close_locked(self):
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin and proc.poll() is None:
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
        if not self.path:
            raise FileNotFoundError("ADB not found — install Android SDK Platform Tools")

    def shell(self, command: str, device_id: str | None = None) -> CommandResult:
        """执行 ADB Shell 命令并返回标准化结果。"""
        cmd = [self.path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", command])
        return CommandRunner.run(cmd, timeout=15)

    def shell_input(self, command: str, device_id: str | None = None) -> bool:
        """向设备 Shell 发送 input 命令，例如 keyevent 或 swipe。

        优先复用持久会话；会话失效时降级为有界同步命令并校验退出码，
        避免产生无人跟踪、关闭时不被清理的独立进程。
        """
        session = self._input_session(device_id)
        if session.send(command):
            return True
        cmd = [self.path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", f"input {command}"])
        return CommandRunner.run(cmd, timeout=15).success

    def warm_input_session(self, device_id: str | None = None) -> bool:
        """预热持久输入 Shell，缩短首条真实输入命令的等待时间。"""
        return self._input_session(device_id).warm()

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

    def get_dimensions(self, device_id: str | None = None):
        """通过 wm size 获取设备屏幕尺寸，返回宽高列表或 None。"""
        try:
            result = self.shell("wm size", device_id=device_id)
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
