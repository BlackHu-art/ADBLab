import logging
from typing import Optional, Dict, Callable
from PySide6.QtCore import QObject, Signal, QTimer, QMutex, QThread
from dataclasses import dataclass


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
    _instance: Optional['LogService'] = None
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
        """初始化日志服务（单例模式）"""
        if not self._initialized:
            super().__init__()
            self._initialized = True
            self._buffer = []
            self._buffer_lock = QMutex()
            self._setup_logging()

    def _setup_logging(self) -> None:
        """配置日志记录器"""
        self._enable_file_log = False
        self._log_path = "resources/app.log"
        self._flush_interval = 200  # ms
        
        self._timer = QTimer()
        self._timer.setInterval(self._flush_interval)
        self._timer.timeout.connect(self._flush_buffer)
        
        logging.getLogger().handlers.clear()
        logging.getLogger().propagate = False
        self.logger = logging.getLogger("app")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        if self._enable_file_log:
            self._add_file_handler()

    def _add_file_handler(self) -> None:
        """添加文件日志处理器"""
        file_handler = logging.FileHandler(
            self._log_path, 
            encoding="utf-8",
            delay=True
        )
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def log(self, level: str, message: str, *args, **kwargs) -> None:
        """线程安全的日志记录方法，支持立即刷新"""
        flush_immediately = kwargs.pop("flush_immediately", False)

        self._buffer_lock.lock()
        try:
            self._buffer.append((level, str(message)))

            if flush_immediately:
                self._flush_buffer()
            elif QThread.currentThread() == self.thread() and not self._timer.isActive():
                self._timer.start()
        finally:
            self._buffer_lock.unlock()

    def _flush_buffer(self) -> None:
        """刷新缓冲区到所有输出"""
        self._buffer_lock.lock()
        try:
            if not self._buffer:
                self._timer.stop()
                return

            current_batch = self._buffer.copy()
            self._buffer.clear()
        finally:
            self._buffer_lock.unlock()

        for level, message in current_batch:
            self._write_file_log(level, message)
            self.log_received.emit(level, message)

    def _write_file_log(self, level: str, message: str) -> None:
        """写入文件日志（如果启用）"""
        if not self._enable_file_log:
            return

        log_funcs: Dict[str, Callable[[str], None]] = {
            LogLevel.DEBUG: self.logger.debug,
            LogLevel.INFO: self.logger.info,
            LogLevel.WARNING: self.logger.warning,
            LogLevel.ERROR: self.logger.error,
            LogLevel.CRITICAL: self.logger.critical,
            LogLevel.SUCCESS: self.logger.info
        }
        
        log_func = log_funcs.get(level, self.logger.info)
        try:
            log_func(message)
        except (IOError, PermissionError) as e:
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
            self._timer.stop()
            self._flush_buffer()
            for handler in self.logger.handlers:
                handler.close()
        finally:
            self._buffer_lock.unlock()