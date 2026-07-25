"""配置 MobilePerf 子进程的标准输出、开发诊断和文件日志。"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import sys
import tempfile

from mobileperf.common.utils import FileUtils

_LOGGER_NAME = "mobileperf"
_HANDLER_MARKER = "_adblab_mobileperf_handler"
_SENSITIVE_VALUES_ENV = "MOBILEPERF_REDACT_VALUES"
_FORMAT = "[%(asctime)s]%(levelname)s:%(name)s:%(module)s:%(message)s"


def _is_frozen_runtime() -> bool:
    """判断当前是否运行在 PyInstaller 打包进程中。"""
    return bool(getattr(sys, "frozen", False))


def _sensitive_values() -> tuple[str, ...]:
    """读取父进程提供的本次运行敏感值，解析失败时安全降级为空集合。"""
    raw = os.environ.get(_SENSITIVE_VALUES_ENV, "")
    if not raw:
        return ()
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        return ()
    if not isinstance(values, list):
        return ()
    return tuple(
        sorted(
            {str(value) for value in values if isinstance(value, str) and value},
            key=len,
            reverse=True,
        )
    )


def _redact_sensitive_text(message: str) -> str:
    """从日志文本中移除本次运行的设备、邮箱和本地路径。"""
    redacted = str(message)
    for value in _sensitive_values():
        redacted = redacted.replace(value, "<redacted>")
    return redacted


class _RedactingFormatter(logging.Formatter):
    """在最终格式化后统一脱敏，包括异常堆栈中的文本。"""

    def format(self, record: logging.LogRecord) -> str:
        return _redact_sensitive_text(super().format(record))


class _ExactDebugFilter(logging.Filter):
    """只允许 DEBUG 记录通过，避免 INFO 以上日志在两个流中重复。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == logging.DEBUG


def _mark_handler(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _HANDLER_MARKER, True)
    return handler


def _writable_stream(name: str):
    """返回可写的标准流；windowed 打包环境没有标准流时返回 None。"""
    stream = getattr(sys, name, None)
    return stream if callable(getattr(stream, "write", None)) else None


def _remove_owned_handlers(target: logging.Logger) -> None:
    """仅清理本模块创建的 handler，不影响宿主进程或第三方日志配置。"""
    for handler in list(target.handlers):
        if not getattr(handler, _HANDLER_MARKER, False):
            continue
        target.removeHandler(handler)
        handler.close()


def _create_file_handler(log_dir: str, formatter: logging.Formatter) -> logging.Handler | None:
    """按显式目录创建 INFO 级轮转文件，失败时不影响采集主流程。"""
    try:
        FileUtils.makedir(log_dir)
    except OSError:
        log_dir = os.path.join(tempfile.gettempdir(), "ADBLab", "logs")
        try:
            FileUtils.makedir(log_dir)
        except OSError:
            return None

    log_file = os.path.join(log_dir, "mobileperf_log")
    try:
        handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file,
            when="D",
            interval=1,
            backupCount=3,
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        return None
    handler.suffix = "%Y-%m-%d_%H-%M-%S.log"
    handler.extMatch = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log$")
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    return _mark_handler(handler)


def _configure_logger(target: logging.Logger) -> logging.Logger:
    """建立互斥日志通道：业务日志走 stdout，源码 DEBUG 只走 stderr。"""
    _remove_owned_handlers(target)
    frozen = _is_frozen_runtime()
    target.setLevel(logging.INFO if frozen else logging.DEBUG)
    target.propagate = False
    formatter = _RedactingFormatter(_FORMAT)

    stdout = _writable_stream("stdout")
    if stdout is not None:
        business_handler = _mark_handler(logging.StreamHandler(stdout))
        business_handler.setLevel(logging.INFO)
        business_handler.setFormatter(formatter)
        target.addHandler(business_handler)

    stderr = _writable_stream("stderr")
    if not frozen and stderr is not None:
        debug_handler = _mark_handler(logging.StreamHandler(stderr))
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.addFilter(_ExactDebugFilter())
        debug_handler.setFormatter(formatter)
        target.addHandler(debug_handler)

    # 只有父进程显式提供用户日志目录时才创建文件，避免普通 import 写文件。
    log_dir = os.environ.get("MOBILEPERF_LOG_DIR", "")
    if log_dir:
        file_handler = _create_file_handler(log_dir, formatter)
        if file_handler is not None:
            target.addHandler(file_handler)
    return target


logger = _configure_logger(logging.getLogger(_LOGGER_NAME))


if __name__ == "__main__":
    logger.debug("MobilePerf 调试日志通道自检")
