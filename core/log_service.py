"""提供面向界面和开发环境的线程安全日志服务。"""

import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QMutex, QObject, Qt, QThread, QTimer, Signal, Slot

from core.diagnostics import DiagnosticJournal, redact_diagnostic
from utils.console_colors import colorize_console


@dataclass(frozen=True)
class LogLevel:
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    SUCCESS = "SUCCESS"


class LogService(QObject):
    """在线程间缓冲用户日志，并按级别将开发诊断输出到控制台。"""

    log_received = Signal(str, str)  # 兼容信号：参数为日志级别、消息。
    logs_received = Signal(list)  # 批次信号：元素为 (时间戳, 级别, 消息) 三元组。
    diagnostics_changed = Signal()
    _flush_requested = Signal()
    _flush_now_requested = Signal()
    _stop_requested = Signal()
    _shutdown_requested = Signal()
    _instance: Optional["LogService"] = None
    _lock = QMutex()
    _console_lock = threading.Lock()
    _STATE_ACCEPTING = "accepting"
    _STATE_STOPPING = "stopping"
    _STATE_STOPPED = "stopped"

    def __new__(cls):
        cls._lock.lock()
        try:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
        finally:
            cls._lock.unlock()

    def __init__(self):
        """初始化进程内唯一的日志服务。"""
        if not getattr(self, "_initialized", False):
            super().__init__()
            self._initialized = True
            self._buffer: list[tuple[str, str, str]] = []
            self._buffer_lock = QMutex()
            self._max_buffer = 5000
            self._dropped_count = 0
            self._pending_dropped_count = 0
            self._state = self._STATE_ACCEPTING
            self.diagnostics = DiagnosticJournal()
            self._setup_logging()

    def _setup_logging(self) -> None:
        """配置日志缓冲刷新定时器与关闭信号。"""

        self._timer = QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._flush_buffer)
        self._flush_requested.connect(self._ensure_flush_timer, Qt.ConnectionType.QueuedConnection)
        self._flush_now_requested.connect(self._flush_buffer, Qt.ConnectionType.QueuedConnection)
        self._stop_requested.connect(self._stop_flush_timer, Qt.ConnectionType.QueuedConnection)
        self._shutdown_requested.connect(
            self._complete_shutdown,
            Qt.ConnectionType.QueuedConnection,
        )

    def log(self, level: str, message: str, *args, **kwargs) -> None:
        """各级别在源码控制台输出一次；DEBUG 不进入界面和诊断文件。

        时间戳在记录产生时生成（而非界面接收时），使排队/背压场景下的
        显示时间仍反映真实发生时间。控制台复用应用诊断脱敏边界，界面保留原文。
        """
        flush_immediately = kwargs.pop("flush_immediately", False)
        normalized_level = str(level).strip().upper()
        rendered_message = str(message)
        if args:
            try:
                rendered_message = rendered_message % args
            except (TypeError, ValueError):
                rendered_message = str(message)
        timestamp = datetime.now().strftime("%H:%M:%S")

        self._buffer_lock.lock()
        try:
            if self._state != self._STATE_ACCEPTING:
                return
            self.write_developer_console(
                normalized_level,
                redact_diagnostic(rendered_message, self.diagnostics.private_values),
            )
            if normalized_level == LogLevel.DEBUG:
                return
            self._buffer.append((timestamp, normalized_level, rendered_message))
            # 缓冲区达到上限时保留最近的用户可见日志，避免持续占用内存。
            if len(self._buffer) > self._max_buffer:
                dropped = len(self._buffer) - self._max_buffer
                self._dropped_count += dropped
                self._pending_dropped_count += dropped
                self._buffer = self._buffer[-self._max_buffer :]
        finally:
            self._buffer_lock.unlock()

        is_owner_thread = QThread.currentThread() == self.thread()
        if flush_immediately:
            if is_owner_thread:
                self._flush_buffer()
            else:
                self._flush_now_requested.emit()
        elif is_owner_thread:
            self._ensure_flush_timer()
        else:
            self._flush_requested.emit()

    def record_runtime_diagnostic(self, message: str) -> None:
        """仅由 GUI 中的对象所属线程接收已脱敏的运行时诊断。

        INFO 摘要复用有界诊断日志及后台持久化通知，不进入用户操作日志；
        源码运行仍输出 DEBUG。关闭请求后拒收，后台调用方必须先经 Qt 投递。
        """
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Runtime diagnostics must run on the LogService owner thread")
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._buffer_lock.lock()
        try:
            if self._state != self._STATE_ACCEPTING:
                return
            accepted = self.diagnostics.accept(
                [(timestamp, LogLevel.INFO, str(message))], include_info=True,
            )
        finally:
            self._buffer_lock.unlock()
        if accepted:
            self.write_developer_console(LogLevel.DEBUG, self.diagnostics.entries[-1][2])
            self.diagnostics_changed.emit()

    @Slot()
    def _ensure_flush_timer(self) -> None:
        """确保刷新定时器只在 LogService 所在线程启动，避免跨线程操作 QTimer。"""
        self._buffer_lock.lock()
        try:
            accepting = self._state == self._STATE_ACCEPTING
        finally:
            self._buffer_lock.unlock()
        if not accepting:
            return
        if not self._timer.isActive():
            self._timer.start()

    @Slot()
    def _stop_flush_timer(self) -> None:
        """停止定时器也必须回到所属线程，后台线程只负责追加和搬运缓冲区。"""
        if self._timer.isActive():
            self._timer.stop()

    def _request_stop_flush_timer(self) -> None:
        """后台线程需要停止定时器时，通过 Qt 信号投递回所属线程。"""
        if QThread.currentThread() == self.thread():
            self._stop_flush_timer()
        else:
            self._stop_requested.emit()

    @Slot()
    def _flush_buffer(self) -> None:
        """在对象所属线程中取出并发布当前用户日志批次。"""
        self._buffer_lock.lock()
        try:
            if self._state != self._STATE_ACCEPTING:
                current_batch = []
            else:
                current_batch = self._drain_buffer_locked()
        finally:
            self._buffer_lock.unlock()

        if not current_batch:
            self._request_stop_flush_timer()
            return
        self._emit_batch(current_batch)

    def _drain_buffer_locked(self) -> list[tuple[str, str, str]]:
        if not self._buffer and self._pending_dropped_count <= 0:
            return []
        current_batch = self._buffer.copy()
        self._buffer.clear()
        if self._pending_dropped_count > 0:
            current_batch.insert(
                0,
                (
                    datetime.now().strftime("%H:%M:%S"),
                    LogLevel.WARNING,
                    (
                        "Log buffer overflow: dropped "
                        f"{self._pending_dropped_count} records "
                        f"({self._dropped_count} total dropped)"
                    ),
                ),
            )
            self._pending_dropped_count = 0
        return current_batch

    @property
    def dropped_count(self) -> int:
        """返回本次服务生命周期内因背压被丢弃的累计记录数。"""

        self._buffer_lock.lock()
        try:
            return int(self._dropped_count)
        finally:
            self._buffer_lock.unlock()

    def _emit_batch(self, current_batch: list[tuple[str, str, str]]) -> None:
        """通过兼容信号将单个批次发布给界面。"""
        if not current_batch:
            return
        if self.diagnostics.accept(current_batch):
            self.diagnostics_changed.emit()
        # 界面优先消费批次信号，兼容信号继续服务尚未迁移的调用方。
        self.logs_received.emit(current_batch)
        for _timestamp, level, message in current_batch:
            self.log_received.emit(level, message)

    @classmethod
    def write_developer_console(cls, level: str, message: str) -> None:
        """源码诊断按级别原子写入控制台，避免普通日志被 IDE 标为错误。

        WARNING、ERROR、CRITICAL 使用 stderr，其余级别使用 stdout；打包模式及
        对应流不可用时静默。颜色仅在最终控制台显示层添加，不进入界面或文件。
        """
        if getattr(sys, "frozen", False):
            return
        normalized_level = str(level).strip().upper()
        stream_name = (
            "stderr"
            if normalized_level in {LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL}
            else "stdout"
        )
        stream = getattr(sys, stream_name, None)
        if stream is None:
            return
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        thread_name = threading.current_thread().name
        line = f"{timestamp} [{normalized_level}] [{thread_name}] {message}"
        try:
            with cls._console_lock:
                stream.write(colorize_console(normalized_level, line, stream) + "\n")
                stream.flush()
        except Exception:
            # 诊断输出不可用时必须静默，不能反向破坏业务流程。
            return

    def request_shutdown(self) -> bool:
        """从任意线程非阻塞请求关闭，并立即拒绝请求后的晚到日志。

        返回值表示本次调用是否首次提交关闭请求。实际排空缓冲区、停止 Qt
        定时器和关闭文件处理器均由对象所属线程完成。
        """
        if QThread.currentThread() == self.thread():
            self._buffer_lock.lock()
            try:
                accepted = self._state == self._STATE_ACCEPTING
            finally:
                self._buffer_lock.unlock()
            self.shutdown()
            return accepted

        self._buffer_lock.lock()
        try:
            if self._state != self._STATE_ACCEPTING:
                return False
            self._state = self._STATE_STOPPING
        finally:
            self._buffer_lock.unlock()
        self._shutdown_requested.emit()
        return True

    def shutdown(self) -> None:
        """在对象所属线程幂等关闭服务；后台线程应调用 ``request_shutdown``。"""
        if QThread.currentThread() != self.thread():
            raise RuntimeError(
                "LogService.shutdown() must run on its owner thread; "
                "use request_shutdown() from worker threads"
            )
        self._complete_shutdown()

    @Slot()
    def _complete_shutdown(self) -> None:
        """在对象所属线程排空日志并同步停止全部 Qt 和文件资源。"""
        self._buffer_lock.lock()
        try:
            if self._state == self._STATE_STOPPED:
                return
            self._state = self._STATE_STOPPING
            current_batch = self._drain_buffer_locked()
        finally:
            self._buffer_lock.unlock()

        self._stop_flush_timer()
        self._emit_batch(current_batch)

        self._buffer_lock.lock()
        try:
            self._state = self._STATE_STOPPED
        finally:
            self._buffer_lock.unlock()
