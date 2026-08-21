"""提供设备 Logcat 实时采集的工作线程、背压批处理与日志等级常量。"""

import re
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QThread, Signal

from core.exec import CommandRunner, ProcessRunner

THREADTIME_RE = re.compile(r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\d+\s+\d+\s+([VDIWEAFS])\s+")
FALLBACK_RE = re.compile(r"\b([VDIWEAFS])/[^\s:]+")

LEVEL_ORDER = {"V": 0, "D": 1, "I": 2, "W": 3, "E": 4, "F": 5, "S": 6}
LEVEL_LABELS = {
    "V": "Verbose+",
    "D": "Debug+",
    "I": "Info+",
    "W": "Warning+",
    "E": "Error+",
    "F": "Fatal",
    "S": "Silent",
}


class LogcatTerminationKind(str, Enum):
    CANCELLED = "cancelled"
    START_FAILED = "start_failed"
    UNEXPECTED_EXIT = "unexpected_exit"


@dataclass(frozen=True)
class LogcatTermination:
    kind: LogcatTerminationKind
    exit_code: int | None = None
    error_type: str = ""


@dataclass(frozen=True)
class LogcatBatch:
    lines: tuple[tuple[str, str, int], ...]
    dropped_before: int = 0


class LogcatWorker(QThread):
    BATCH_SIZE = 100
    BATCH_INTERVAL_SECONDS = 0.075
    MAX_INFLIGHT_BATCHES = 8

    line_ready = Signal(str, str, int)
    lines_ready = Signal(object)
    dropped_ready = Signal(int)
    status_changed = Signal(str)
    terminated = Signal(object)

    def __init__(self, device_ip: str, package: str = "", tag: str = ""):
        super().__init__()
        self.device_ip = device_ip
        self.package = package.strip()
        self.tag = tag.strip()
        self._process_key = f"logcat_{id(self)}"
        self._process_runner = ProcessRunner()
        self._proc = None
        self._stop_event = threading.Event()
        self._finished_event = threading.Event()
        self._launch_lock = threading.Lock()
        self._batch_lock = threading.Lock()
        self._inflight_batches = 0
        self._dropped_lines = 0

    def request_stop(self):
        """向 logcat 线程和受跟踪进程发送幂等停止请求。"""
        with self._launch_lock:
            self._stop_event.set()
            self._process_runner.request_stop(self._process_key)

    def force_stop(self, timeout_seconds: float) -> bool:
        """在给定预算内强制终止受跟踪进程。"""
        with self._launch_lock:
            self._stop_event.set()
            return self._process_runner.force_stop(self._process_key, timeout_seconds)

    def stop(self):
        """保留兼容停止入口；这里只请求停止，不等待进程退出。"""
        self.request_stop()

    def is_active(self) -> bool:
        try:
            thread_running = self.isRunning()
        except RuntimeError:
            # QThread 完成后 Qt 包装对象可能已延迟删除，但进程监督必须持续到被跟踪进程退出。
            thread_running = False
        return (
            thread_running
            or not self._finished_event.is_set()
            or self._process_key in self._process_runner.active_keys
        )

    def wait_for_stop(self, timeout_seconds: float) -> bool:
        """等待线程和进程均退出，但不超过调用方给定的预算。"""
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            if not self.is_active():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._finished_event.wait(min(remaining, 0.05))

    def acknowledge_batch(self) -> None:
        with self._batch_lock:
            self._inflight_batches = max(0, self._inflight_batches - 1)

    def run(self):
        termination = None
        batch = []
        last_batch_at = time.monotonic()
        cmd = ["adb", "-s", self.device_ip, "logcat", "-T", "1", "-v", "threadtime"]
        filter_pid = None
        try:
            if self._stop_event.is_set():
                termination = LogcatTermination(LogcatTerminationKind.CANCELLED)
                return
            if self.package:
                r = CommandRunner.run(
                    ["adb", "-s", self.device_ip, "shell", "pidof", self.package],
                    timeout=5,
                )
                if not r.success:
                    termination = LogcatTermination(
                        LogcatTerminationKind.START_FAILED,
                        error_type="PidProbeFailed",
                    )
                    self.status_changed.emit("Unable to start package-filtered logcat")
                    return
                pid = r.output.strip().split()[0] if r.output.strip() else ""
                if pid and pid.isdigit():
                    filter_pid = int(pid)
                    cmd.extend(["--pid", pid])
                    self.status_changed.emit("Package filter active")
                else:
                    self.status_changed.emit("Selected package is not running; showing all logs")
            if self._stop_event.is_set():
                termination = LogcatTermination(LogcatTerminationKind.CANCELLED)
                return
            self.status_changed.emit("Starting logcat...")
            with self._launch_lock:
                if self._stop_event.is_set():
                    termination = LogcatTermination(LogcatTerminationKind.CANCELLED)
                    return
                self._proc = self._process_runner.start(
                    self._process_key,
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="ignore",
                )
            self.status_changed.emit("Logcat running")
            while not self._stop_event.is_set():
                line = self._proc.stdout.readline()
                if not line:
                    if self._proc.poll() is not None:
                        break
                    continue
                text = line.rstrip("\r\n")
                if text:
                    batch.append((text, self._parse_level(text), filter_pid or 0))
                    now = time.monotonic()
                    if (
                        len(batch) >= self.BATCH_SIZE
                        or now - last_batch_at >= self.BATCH_INTERVAL_SECONDS
                    ):
                        self._emit_batch(batch)
                        batch = []
                        last_batch_at = now
            if self._stop_event.is_set():
                termination = LogcatTermination(LogcatTerminationKind.CANCELLED)
            else:
                termination = LogcatTermination(
                    LogcatTerminationKind.UNEXPECTED_EXIT,
                    exit_code=self._proc.poll(),
                )
        except Exception as exc:
            termination = LogcatTermination(
                (
                    LogcatTerminationKind.START_FAILED
                    if self._proc is None
                    else LogcatTerminationKind.UNEXPECTED_EXIT
                ),
                error_type=type(exc).__name__,
            )
            self.status_changed.emit("Logcat could not continue")
        finally:
            if batch:
                self._emit_batch(batch)
            self._emit_remaining_drop_count()
            try:
                process_exited = self._proc is None or self._proc.poll() is not None
            except OSError:
                process_exited = False
            if process_exited:
                self._process_runner.stop(self._process_key, timeout=0)
            else:
                self._process_runner.request_stop(self._process_key)
            if self._proc and self._proc.stdout:
                try:
                    self._proc.stdout.close()
                except Exception:
                    pass
            self._proc = None
            if termination is None:
                termination = LogcatTermination(
                    LogcatTerminationKind.CANCELLED
                    if self._stop_event.is_set()
                    else LogcatTerminationKind.UNEXPECTED_EXIT
                )
            self.terminated.emit(termination)
            self._finished_event.set()

    def _emit_batch(self, lines: list[tuple[str, str, int]]) -> None:
        with self._batch_lock:
            if self._inflight_batches >= self.MAX_INFLIGHT_BATCHES:
                self._dropped_lines += len(lines)
                return
            dropped = self._dropped_lines
            self._dropped_lines = 0
            self._inflight_batches += 1
        self.lines_ready.emit(LogcatBatch(tuple(lines), dropped))

    def _emit_remaining_drop_count(self) -> None:
        with self._batch_lock:
            dropped = self._dropped_lines
            self._dropped_lines = 0
        if dropped:
            self.dropped_ready.emit(dropped)

    @staticmethod
    def _parse_level(line: str) -> str:
        m = THREADTIME_RE.search(line) or FALLBACK_RE.search(line)
        return m.group(1) if m else "U"


class CurrentPackageWorker(QThread):
    package_ready = Signal(str)
    status_changed = Signal(str)

    def __init__(self, device_ip: str):
        super().__init__()
        self.device_ip = device_ip

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            r = CommandRunner.run(
                ["adb", "-s", self.device_ip, "shell", "dumpsys", "window"],
                timeout=5,
            )
            if self.isInterruptionRequested():
                return
            for line in r.output.splitlines():
                if "mCurrentFocus" in line:
                    m = re.search(r"Window\{.*?\s(\S+?)/", line)
                    if m:
                        self.package_ready.emit(m.group(1))
                        return
            self.status_changed.emit("No foreground app found")
        except Exception as e:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Error: {e}")
