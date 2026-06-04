"""Lightweight ADB shell wrapper for ADBLab.

Path resolution: delegates to utils.adb_resolver (bundled scrcpy ADB > system PATH).
"""

import logging
import subprocess
import threading

from models.base.command_runner import CommandResult, CommandRunner
from models.base.process_runner import ProcessRunner
from utils.adb_resolver import adb_path

logger = logging.getLogger("adb_bridge")


class ADBInputSession:
    """Persistent `adb shell` session for low-latency input commands."""

    def __init__(self, adb: str, device_id: str | None = None):
        self.adb = adb
        self.device_id = device_id
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def send(self, command: str) -> bool:
        """Write an input command through stdin; False lets caller fall back."""
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
        """Open the persistent shell before the first real input command."""
        with self._lock:
            proc = self._ensure_process()
            return bool(proc and proc.stdin and proc.poll() is None)

    def _ensure_process(self) -> subprocess.Popen | None:
        if self._proc and self._proc.poll() is None:
            return self._proc
        self._close_locked()
        cmd = [self.adb]
        if self.device_id:
            cmd.extend(["-s", self.device_id])
        cmd.append("shell")
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except Exception:
            pass


class ADBBridge:
    """Thin wrapper around ADB shell/input/dimensions commands."""

    def __init__(self, path: str | None = None):
        self.path = path or adb_path()
        self._process_runner = ProcessRunner()
        self._input_sessions: dict[str, ADBInputSession] = {}
        self._input_sessions_lock = threading.Lock()
        if not self.path:
            raise FileNotFoundError("ADB not found — install Android SDK Platform Tools")

    # -- public API ------------------------------------------------------

    def shell(self, command: str, device_id: str | None = None) -> CommandResult:
        """Run an ADB shell command and return a standardized result."""
        cmd = [self.path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", command])
        return CommandRunner.run(cmd, timeout=15)

    def shell_input(self, command: str, device_id: str | None = None):
        """Send an 'input' command to the device shell (keyevent, swipe, etc.)."""
        session = self._input_session(device_id)
        if session.send(command):
            return session
        cmd = [self.path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", f"input {command}"])
        return self._process_runner.spawn(cmd)

    def warm_input_session(self, device_id: str | None = None) -> bool:
        """Prepare the persistent input shell so first real input is faster."""
        return self._input_session(device_id).warm()

    def close_input_sessions(self, device_id: str | None = None):
        """Close persistent input shell sessions, used on panel/service shutdown."""
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
                session = ADBInputSession(self.path, device_id)
                self._input_sessions[key] = session
            return session

    @staticmethod
    def _session_key(device_id: str | None) -> str:
        return device_id or "__default__"

    def get_dimensions(self, device_id: str | None = None):
        """Get device screen [width, height] via 'wm size'. Returns list or None."""
        try:
            result = self.shell("wm size", device_id=device_id)
            raw = result.output if result.success else result.error
            for prefix in ("Physical size:", "Override size:"):
                if prefix in raw:
                    return raw[raw.find(prefix):].split(":")[1].strip().split("x")
            return None
        except Exception:
            return None

    def devices(self) -> list[list[str]]:
        """List connected devices as [[serial, status], ...]."""
        result = CommandRunner.run([self.path, "devices"], timeout=15)
        out = result.output if result.success else result.error
        return [line.split("\t") for line in out.strip().splitlines()[1:] if line.strip()]
