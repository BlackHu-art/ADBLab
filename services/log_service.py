import logging
from PySide6.QtCore import QObject, Signal, QTimer

class LogLevel:
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class LogService(QObject):
    log_received = Signal(str, str)  # level, message
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
            self._enable_file_log = False  # ✅ 控制是否写入文件
            self._log_path = "resources/app.log"
            self._setup()

    def _setup(self):
        # 清除所有 console 日志
        logging.getLogger().handlers.clear()
        logging.getLogger().propagate = False

        self._buffer = []
        self._timer = QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._flush_buffer)

        # 专属日志记录器
        self.logger = logging.getLogger("app")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.logger.handlers.clear()

        if self._enable_file_log:
            file_handler = logging.FileHandler(self._log_path, encoding="utf-8")
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def log(self, level: str, message: str):
        """线程安全，支持缓冲的日志接口"""
        self._buffer.append((level, message))
        if not self._timer.isActive():
            self._timer.start()

    def _flush_buffer(self):
        for level, message in self._buffer:
            self._write_file_log(level, message)
            self.log_received.emit(level, message)  # 发射至 UI 控件
        self._buffer.clear()
        self._timer.stop()

    def _write_file_log(self, level: str, message: str):
        if not self._enable_file_log:
            return
        level_map = {
            LogLevel.DEBUG: self.logger.debug,
            LogLevel.INFO: self.logger.info,
            LogLevel.WARNING: self.logger.warning,
            LogLevel.ERROR: self.logger.error,
            LogLevel.CRITICAL: self.logger.critical
        }
        level_map.get(level, self.logger.info)(message)
