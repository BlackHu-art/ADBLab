import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QMutex, QObject, QThread, QTimer, Qt, Signal, Slot

from utils.resource_path import resource_path


@dataclass(frozen=True)
class LogLevel:
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    SUCCESS = "SUCCESS"


class LogService(QObject):
    """线程安全的日志服务，支持缓冲写入和多种输出方式"""

    log_received = Signal(str, str)  # level, message
    logs_received = Signal(list)  # [(level, message), ...]
    _flush_requested = Signal()
    _flush_now_requested = Signal()
    _stop_requested = Signal()
    _instance: Optional["LogService"] = None
    _lock = QMutex()  # 类级别的线程锁

    def __new__(cls):
        cls._lock.lock()  # 手动加锁替代with语句
        try:
            if not cls._instance:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
        finally:
            cls._lock.unlock()  # 确保锁释放

    def __init__(self):
        """初始化日志服务（Singleton pattern）"""
        if not self._initialized:
            super().__init__()
            self._initialized = True
            self._buffer = []
            self._buffer_lock = QMutex()
            self._max_buffer = 5000
            self._setup_logging()

    def _setup_logging(self) -> None:
        """配置日志记录器"""
        self._enable_file_log = False
        self._log_path = resource_path("resources/app.log")
        self._flush_interval = 200  # ms

        self._timer = QTimer()
        self._timer.setInterval(self._flush_interval)
        self._timer.timeout.connect(self._flush_buffer)
        self._flush_requested.connect(
            self._ensure_flush_timer, Qt.ConnectionType.QueuedConnection
        )
        self._flush_now_requested.connect(
            self._flush_buffer, Qt.ConnectionType.QueuedConnection
        )
        self._stop_requested.connect(
            self._stop_flush_timer, Qt.ConnectionType.QueuedConnection
        )

        logging.getLogger().handlers.clear()
        logging.getLogger().propagate = False
        self.logger = logging.getLogger("app")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        if self._enable_file_log:
            self._add_file_handler()

    def _add_file_handler(self) -> None:
        """添加文件日志处理器"""
        file_handler = logging.FileHandler(self._log_path, encoding="utf-8", delay=True)
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def log(self, level: str, message: str, *args, **kwargs) -> None:
        """线程安全的日志记录方法，支持立即刷新"""
        flush_immediately = kwargs.pop("flush_immediately", False)
        self._buffer_lock.lock()
        try:
            self._buffer.append((level, str(message)))
            # Drop oldest if buffer overflows
            if len(self._buffer) > self._max_buffer:
                self._buffer = self._buffer[-self._max_buffer:]
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
        """刷新缓冲区到所有输出"""
        self._buffer_lock.lock()
        try:
            current_batch = self._drain_buffer_locked()
        finally:
            self._buffer_lock.unlock()

        self._emit_batch(current_batch)

    def _drain_buffer_locked(self) -> list[tuple[str, str]]:
        if not self._buffer:
            self._request_stop_flush_timer()
            return []
        current_batch = self._buffer.copy()
        self._buffer.clear()
        return current_batch

    def _emit_batch(self, current_batch: list[tuple[str, str]]) -> None:
        if not current_batch:
            return
        for level, message in current_batch:
            self._write_file_log(level, message)
        # UI 层优先走批量信号，避免大量日志逐条触发 QTextEdit 重绘。
        self.logs_received.emit(current_batch)
        for level, message in current_batch:
            self.log_received.emit(level, message)

    def _write_file_log(self, level: str, message: str) -> None:
        """写入文件日志（如果启用）"""
        if not self._enable_file_log:
            return

        log_funcs: dict[str, Callable[[str], None]] = {
            LogLevel.DEBUG: self.logger.debug,
            LogLevel.INFO: self.logger.info,
            LogLevel.WARNING: self.logger.warning,
            LogLevel.ERROR: self.logger.error,
            LogLevel.CRITICAL: self.logger.critical,
            LogLevel.SUCCESS: self.logger.info,
        }

        log_func = log_funcs.get(level, self.logger.info)
        try:
            log_func(message)
        except (OSError, PermissionError) as e:
            print(f"Failed to write log: {e}")

    def enable_file_logging(self, enabled: bool) -> None:
        """动态启用/禁用文件日志"""
        self._buffer_lock.lock()
        try:
            self._enable_file_log = enabled
            if enabled and not any(
                isinstance(h, logging.FileHandler) for h in self.logger.handlers
            ):
                self._add_file_handler()
        finally:
            self._buffer_lock.unlock()

    def set_flush_interval(self, interval_ms: int) -> None:
        """设置缓冲区刷新间隔（毫秒）"""
        self._buffer_lock.lock()
        try:
            self._flush_interval = max(50, interval_ms)
            self._timer.setInterval(self._flush_interval)
        finally:
            self._buffer_lock.unlock()

    def shutdown(self) -> None:
        """安全关闭日志服务"""
        self._buffer_lock.lock()
        try:
            self._request_stop_flush_timer()
            current_batch = self._drain_buffer_locked()
            handlers = list(self.logger.handlers)
        finally:
            self._buffer_lock.unlock()

        self._emit_batch(current_batch)
        for handler in handlers:
            handler.close()
        self._release_singleton()

    def _release_singleton(self) -> None:
        LogService._lock.lock()
        try:
            if LogService._instance is self:
                LogService._instance = None
        finally:
            LogService._lock.unlock()
