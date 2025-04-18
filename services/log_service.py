# services/log_service.py
import logging
from PySide6.QtCore import QObject, Signal, QTimer

class LogLevel:
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class LogService(QObject):
    log_received = Signal(str, str)  # 改为两个参数：level, message
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            super().__init__()
            self._initialized = True
            self._setup()

    def _setup(self):
        self._buffer = []
        self._timer = QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._flush_buffer)
        
        # 文件日志配置（保持不变）
        self.file_logger = logging.getLogger("app")
        self.file_logger.setLevel(logging.DEBUG)
        handler = logging.FileHandler("app.log", encoding="utf-8")
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.file_logger.addHandler(handler)

    def log(self, level: str, message: str):  # 移除category参数
        """线程安全的日志记录方法"""
        self._buffer.append((level, message))  # 仅存储level和message
        if not self._timer.isActive():
            self._timer.start()

    def _flush_buffer(self):
        """批量处理日志"""
        for level, message in self._buffer:
            self._write_file_log(level, message)
            self.log_received.emit(level, message)  # 发射两个参数
        self._buffer.clear()
        self._timer.stop()

    def _write_file_log(self, level: str, message: str):  # 保持原样
        level_mapping = {
            LogLevel.DEBUG: self.file_logger.debug,
            LogLevel.INFO: self.file_logger.info,
            LogLevel.WARNING: self.file_logger.warning,
            LogLevel.ERROR: self.file_logger.error,
            LogLevel.CRITICAL: self.file_logger.critical
        }
        level_mapping.get(level, self.file_logger.info)(message)