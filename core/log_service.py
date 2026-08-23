"""提供面向界面和开发环境的线程安全日志服务。"""

import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QMutex, QObject, Qt, QThread, QTimer, Signal, Slot


@dataclass(frozen=True)
class LogLevel:
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    SUCCESS = "SUCCESS"


class LogService(QObject):
    """在线程间缓冲用户日志，并将开发调试日志隔离到标准错误流。"""

    log_received = Signal(str, str)  # 兼容信号：参数为日志级别、消息。
    logs_received = Signal(list)  # 批次信号：元素为 (时间戳, 级别, 消息) 三元组。
    _flush_requested = Signal()
    _flush_now_requested = Signal()
    _stop_requested = Signal()
    _shutdown_requested = Signal()
    _instance: Optional["LogService"] = None
    _lock = QMutex()
    _stderr_lock = threading.Lock()
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
        """记录日志；DEBUG 仅在源码运行时写入开发环境控制台。

        时间戳在记录产生时生成（而非界面接收时），使排队/背压场景下的
        显示时间仍反映真实发生时间。
        """
        flush_immediately = kwargs.pop("flush_immediately", False)
        normalized_level = str(level).upper()
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
            if normalized_level == LogLevel.DEBUG:
                self.write_developer_console(LogLevel.DEBUG, rendered_message)
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
        # 界面优先消费批次信号，兼容信号继续服务尚未迁移的调用方。
        self.logs_received.emit(current_batch)
        for _timestamp, level, message in current_batch:
            self.log_received.emit(level, message)

    @classmethod
    def write_developer_console(cls, level: str, message: str) -> None:
        """仅在源码模式下原子写入 IDE 可见的标准错误流。"""
        if getattr(sys, "frozen", False):
            return
        stream = getattr(sys, "stderr", None)
        if stream is None:
            return
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        thread_name = threading.current_thread().name
        line = f"{timestamp} [{level}] [{thread_name}] {message}\n"
        try:
            with cls._stderr_lock:
                stream.write(line)
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
