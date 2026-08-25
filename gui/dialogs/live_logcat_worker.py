"""提供设备 Logcat 实时采集的工作线程、背压批处理与日志等级常量。"""

import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from queue import Empty, Full, Queue
from typing import Any

from PySide6.QtCore import QThread, Signal

from core.exec import CommandResult, CommandRunner, ProcessRunner
from models.base.focus_detector import detect_current_package
from utils.adb_values import normalize_android_package

THREADTIME_RE = re.compile(
    r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+"
    r"(?P<pid>\d+)\s+\d+\s+(?P<level>[VDIWEAFS])\s+"
)
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
    generation: int = 0


class LogcatWorker(QThread):
    BATCH_SIZE = 100
    BATCH_INTERVAL_SECONDS = 0.075
    MAX_INFLIGHT_BATCHES = 8
    PID_REFRESH_SECONDS = 1.0
    RAW_QUEUE_SIZE = 2048
    QUEUE_POLL_SECONDS = 0.05

    line_ready = Signal(str, str, int)
    lines_ready = Signal(object)
    dropped_ready = Signal(int)
    status_changed = Signal(str)
    terminated = Signal(object)

    # 对话框连接的回调句柄，由 LiveLogcatStream 写入，供断开时安全解绑。
    _dialog_lines_handler: Callable[..., Any] | None
    _dialog_dropped_handler: Callable[..., Any] | None
    _dialog_status_handler: Callable[..., Any] | None
    _dialog_ended_handler: Callable[..., Any] | None
    _dialog_finished_handler: Callable[..., Any] | None
    _supervisor_task_id: str | None

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
        self._package_lock = threading.Lock()
        self._package_changed_event = threading.Event()
        self._package_generation = 0
        self._filter_pids: frozenset[int] = frozenset()
        self._last_filter_status: tuple[str, str, tuple[int, ...]] | None = None
        self._reader_thread: threading.Thread | None = None
        self._pid_thread: threading.Thread | None = None
        self._reader_error: Exception | None = None
        self._inflight_batches = 0
        self._dropped_lines = 0

    def update_package(self, package: str) -> bool:
        """原子切换运行中的包过滤目标；非法包名保持原过滤目标不变。"""

        requested = package.strip()
        if requested:
            try:
                requested = normalize_android_package(requested)
            except ValueError:
                self.status_changed.emit("Invalid package name for logcat filter")
                return False
        with self._package_lock:
            self.package = requested
            self._package_generation += 1
            # 切换代次后先清空 PID，避免探测完成前泄漏旧包或全设备日志。
            self._filter_pids = frozenset()
            self._last_filter_status = None
            self._package_changed_event.set()
        return True

    def request_stop(self):
        """向 logcat 线程和受跟踪进程发送幂等停止请求。"""
        with self._launch_lock:
            self._stop_event.set()
            self._package_changed_event.set()
            self._process_runner.request_stop(self._process_key)

    def force_stop(self, timeout_seconds: float) -> bool:
        """在给定预算内强制终止受跟踪进程。"""
        with self._launch_lock:
            self._stop_event.set()
            self._package_changed_event.set()
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

    def _package_snapshot(self) -> tuple[str, int, frozenset[int]]:
        with self._package_lock:
            return self.package, self._package_generation, self._filter_pids

    @property
    def filter_generation(self) -> int:
        """返回当前过滤代次，供 GUI 丢弃切换前已经排队的旧批次。"""

        with self._package_lock:
            return self._package_generation

    def _commit_filter_pids(
        self,
        package: str,
        generation: int,
        pids: frozenset[int],
    ) -> bool:
        with self._package_lock:
            if package != self.package or generation != self._package_generation:
                return False
            self._filter_pids = pids
            return True

    def _publish_filter_status(
        self,
        state: str,
        package: str,
        generation: int,
        pids: frozenset[int],
        message: str,
    ) -> None:
        key = (state, package, tuple(sorted(pids)))
        with self._package_lock:
            if package != self.package or generation != self._package_generation:
                return
            if self._last_filter_status == key:
                return
            self._last_filter_status = key
        self.status_changed.emit(message)

    def _refresh_filter_pids(self, package: str, generation: int) -> None:
        if not package:
            if self._commit_filter_pids(package, generation, frozenset()):
                self._publish_filter_status(
                    "unfiltered",
                    package,
                    generation,
                    frozenset(),
                    "Logcat running; package filter cleared",
                )
            return
        try:
            result = CommandRunner.run(
                ["adb", "-s", self.device_ip, "shell", "pidof", package],
                timeout=2,
            )
        except Exception:
            result = None
        if self._stop_event.is_set():
            return
        pids = (
            frozenset(
                int(value)
                for value in result.output.split()
                if value.isdigit() and int(value) > 0
            )
            if result is not None and result.success
            else frozenset()
        )
        if not self._commit_filter_pids(package, generation, pids):
            return
        if result is None or not result.success:
            self._publish_filter_status(
                "probe_failed",
                package,
                generation,
                pids,
                "Logcat running; package PID lookup failed, retrying",
            )
        elif pids:
            self._publish_filter_status(
                "active",
                package,
                generation,
                pids,
                f"Logcat running; package filter active ({len(pids)} process(es))",
            )
        else:
            self._publish_filter_status(
                "waiting",
                package,
                generation,
                pids,
                "Logcat running; waiting for the selected app process",
            )

    def _refresh_package_loop(self) -> None:
        """周期刷新包对应的全部 PID，并在包切换时立即重查。"""

        while not self._stop_event.is_set():
            self._package_changed_event.clear()
            package, generation, _pids = self._package_snapshot()
            if package or generation > 0:
                self._refresh_filter_pids(package, generation)
            self._package_changed_event.wait(self.PID_REFRESH_SECONDS)

    def _read_stdout(
        self,
        stdout,
        raw_lines: Queue[tuple[int, str]],
        reader_done: threading.Event,
    ) -> None:
        """独占阻塞 stdout 读取；协调线程通过超时队列保证尾批按时刷新。"""

        try:
            while not self._stop_event.is_set():
                line = stdout.readline()
                if not line:
                    break
                with self._package_lock:
                    generation = self._package_generation
                while not self._stop_event.is_set():
                    try:
                        raw_lines.put((generation, line), timeout=self.QUEUE_POLL_SECONDS)
                        break
                    except Full:
                        continue
        except Exception as exc:
            if not self._stop_event.is_set():
                self._reader_error = exc
        finally:
            reader_done.set()

    def _filtered_line(
        self,
        text: str,
        queued_generation: int,
    ) -> tuple[str, str, int] | None:
        match = THREADTIME_RE.search(text)
        pid = int(match.group("pid")) if match else 0
        level = match.group("level") if match else self._parse_level(text)
        package, generation, pids = self._package_snapshot()
        if queued_generation != generation:
            return None
        if not package:
            return text, level, pid
        # 包过滤必须能把每一行明确归属到 PID；不推测无前缀文本，避免泄漏其他进程输出。
        if match is None or pid not in pids:
            return None
        return text, level, pid

    def run(self):
        termination = None
        batch: list[tuple[str, str, int]] = []
        batch_started_at: float | None = None
        batch_generation: int | None = None
        started_helpers: list[threading.Thread] = []
        raw_lines: Queue[tuple[int, str]] = Queue(maxsize=self.RAW_QUEUE_SIZE)
        reader_done = threading.Event()
        cmd = ["adb", "-s", self.device_ip, "logcat", "-T", "1", "-v", "threadtime"]
        try:
            if self._stop_event.is_set():
                termination = LogcatTermination(LogcatTerminationKind.CANCELLED)
                return
            package, _generation, _pids = self._package_snapshot()
            if package:
                try:
                    normalized = normalize_android_package(package)
                except ValueError:
                    termination = LogcatTermination(
                        LogcatTerminationKind.START_FAILED,
                        error_type="InvalidPackage",
                    )
                    self.status_changed.emit("Invalid package name for logcat filter")
                    return
                with self._package_lock:
                    if self.package == package:
                        self.package = normalized
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
            proc = self._proc
            assert proc is not None  # start() 返回后进程句柄非空
            stdout = proc.stdout
            assert stdout is not None  # stdout=PIPE 时输出句柄非空

            package, generation, _pids = self._package_snapshot()
            if package:
                # 在 reader 开始消费前先取得初始 PID，避免启动瞬间把目标日志当作未知进程丢弃。
                self._refresh_filter_pids(package, generation)
            else:
                self.status_changed.emit("Logcat running")
            self._reader_thread = threading.Thread(
                target=self._read_stdout,
                args=(stdout, raw_lines, reader_done),
                name=f"live-logcat-reader-{id(self)}",
            )
            self._pid_thread = threading.Thread(
                target=self._refresh_package_loop,
                name=f"live-logcat-pid-{id(self)}",
            )
            self._reader_thread.start()
            started_helpers.append(self._reader_thread)
            self._pid_thread.start()
            started_helpers.append(self._pid_thread)

            while not self._stop_event.is_set():
                now = time.monotonic()
                if batch_started_at is not None and (
                    now - batch_started_at >= self.BATCH_INTERVAL_SECONDS
                ):
                    self._emit_batch(batch, generation=batch_generation)
                    batch = []
                    batch_started_at = None
                    batch_generation = None
                if reader_done.is_set() and raw_lines.empty():
                    if self._reader_error is not None:
                        raise self._reader_error
                    break
                timeout = self.QUEUE_POLL_SECONDS
                if batch_started_at is not None:
                    timeout = min(
                        timeout,
                        max(
                            0.0,
                            self.BATCH_INTERVAL_SECONDS - (now - batch_started_at),
                        ),
                    )
                try:
                    queued_generation, line = raw_lines.get(timeout=timeout)
                except Empty:
                    continue
                text = line.rstrip("\r\n")
                if not text:
                    continue
                accepted_line = self._filtered_line(text, queued_generation)
                if accepted_line is None:
                    continue
                if batch and batch_generation != queued_generation:
                    batch = []
                    batch_started_at = None
                    batch_generation = None
                if not batch:
                    batch_started_at = time.monotonic()
                    batch_generation = queued_generation
                batch.append(accepted_line)
                if len(batch) >= self.BATCH_SIZE:
                    self._emit_batch(batch, generation=batch_generation)
                    batch = []
                    batch_started_at = None
                    batch_generation = None
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
            try:
                if termination is None:
                    termination = LogcatTermination(
                        LogcatTerminationKind.CANCELLED
                        if self._stop_event.is_set()
                        else LogcatTerminationKind.UNEXPECTED_EXIT
                    )
                self._stop_event.set()
                self._package_changed_event.set()
                if batch:
                    self._emit_batch(batch, generation=batch_generation)
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
                for helper in started_helpers:
                    helper.join()
                try:
                    if self._proc is not None and self._proc.poll() is not None:
                        self._process_runner.stop(self._process_key, timeout=0)
                except OSError:
                    pass
                self._proc = None
                self.terminated.emit(termination)
            finally:
                self._finished_event.set()

    def _emit_batch(
        self,
        lines: list[tuple[str, str, int]],
        *,
        generation: int | None = None,
    ) -> None:
        current_generation = self.filter_generation
        emission_generation = current_generation if generation is None else generation
        if emission_generation != current_generation:
            return
        with self._batch_lock:
            if self._inflight_batches >= self.MAX_INFLIGHT_BATCHES:
                self._dropped_lines += len(lines)
                return
            dropped = self._dropped_lines
            self._dropped_lines = 0
            self._inflight_batches += 1
        self.lines_ready.emit(LogcatBatch(tuple(lines), dropped, emission_generation))

    def _emit_remaining_drop_count(self) -> None:
        with self._batch_lock:
            dropped = self._dropped_lines
            self._dropped_lines = 0
        if dropped:
            self.dropped_ready.emit(dropped)

    @staticmethod
    def _parse_level(line: str) -> str:
        threadtime = THREADTIME_RE.search(line)
        if threadtime:
            return threadtime.group("level")
        fallback = FALLBACK_RE.search(line)
        return fallback.group(1) if fallback else "U"


class _InterruptiblePackageRunner:
    """为共享前台包检测器提供有界、可在命令间取消的执行边界。"""

    def __init__(self, worker: "CurrentPackageWorker"):
        self._worker = worker

    def run(self, command: list[str], timeout: int = 5) -> CommandResult:
        if self._worker.isInterruptionRequested():
            return CommandResult(False, error="cancelled", returncode=-1)
        return CommandRunner.run(
            command,
            timeout=min(timeout, self._worker.PROBE_COMMAND_TIMEOUT_SECONDS),
        )


class CurrentPackageWorker(QThread):
    PROBE_COMMAND_TIMEOUT_SECONDS = 1

    package_ready = Signal(str)
    status_changed = Signal(str)

    # 对话框连接的回调句柄，由 LiveLogcatStream 写入，供断开时安全解绑。
    _dialog_finished_handler: Callable[..., Any] | None
    _supervisor_task_id: str | None

    def __init__(self, device_ip: str):
        super().__init__()
        self.device_ip = device_ip

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            result = detect_current_package(
                self.device_ip,
                runner=_InterruptiblePackageRunner(self),
            )
            if self.isInterruptionRequested():
                return
            if result.get("success") and result.get("package_name"):
                self.package_ready.emit(str(result["package_name"]))
            else:
                self.status_changed.emit("No foreground app found")
        except Exception as e:
            if not self.isInterruptionRequested():
                self.status_changed.emit(f"Error: {e}")
