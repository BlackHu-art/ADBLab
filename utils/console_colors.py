"""在最终控制台显示层按日志级别过滤和着色，文件与机器读取的输出保持纯文本。"""

from __future__ import annotations

import logging
import os
import stat
import sys
from typing import TextIO

_LEVEL_COLORS = {
    "DEBUG": "90", "INFO": "36", "SUCCESS": "32",
    "WARNING": "33", "ERROR": "31", "CRITICAL": "35",
}

# 控制台级别白名单与排序：SUCCESS 与 INFO 同级；未登记的级别按 INFO 处理，
# 使第三方自定义级别不会被误判为错误，也不会被静默丢弃。
CONSOLE_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "OFF")
_LEVEL_RANK = {
    "DEBUG": 10, "INFO": 20, "SUCCESS": 20,
    "WARNING": 30, "ERROR": 40, "CRITICAL": 50,
}
_UNKNOWN_LEVEL_RANK = _LEVEL_RANK["INFO"]
_DEFAULT_CONSOLE_LEVEL = "DEBUG"

# 标准库根 logger 只允许"更安静"：DEBUG/INFO/WARNING 阈值保持 Python 默认的
# WARNING，避免顺带打开第三方库的 DEBUG 输出；ERROR/OFF 才进一步收紧。
_ROOT_LEVELS = {
    "DEBUG": logging.WARNING,
    "INFO": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "OFF": logging.CRITICAL + 1,
}

_console_level = _DEFAULT_CONSOLE_LEVEL

# 着色能力缓存：按流身份缓存判定结果，避免每条日志重复 isatty/fstat；持强引用
# 保证 id 不被复用，有界淘汰防止重定向或测试场景无限增长。
_COLOR_CACHE_LIMIT = 8
_color_cache: dict[int, tuple[TextIO, bool]] = {}


def normalise_console_level(value: object) -> str:
    """把任意输入规范为受支持的控制台级别；非法值回退默认级别。"""
    text = str(value).strip().upper() if value is not None else ""
    return text if text in CONSOLE_LEVELS else _DEFAULT_CONSOLE_LEVEL


def set_console_level(level: object) -> str:
    """设置进程级控制台级别并返回实际生效值；可从任意线程调用。"""
    global _console_level
    _console_level = normalise_console_level(level)
    return _console_level


def console_level() -> str:
    """返回当前进程级控制台级别。"""
    return _console_level


def should_emit(level: object) -> bool:
    """判断指定级别是否达到控制台阈值；OFF 恒为 False。"""
    if _console_level == "OFF":
        return False
    rank = _LEVEL_RANK.get(str(level).strip().upper(), _UNKNOWN_LEVEL_RANK)
    return rank >= _LEVEL_RANK[_console_level]


def stdlib_level(level: object) -> int:
    """返回与控制台级别对应的根 logger 级别，只收紧不放松默认策略。"""
    return _ROOT_LEVELS[normalise_console_level(level)]


def _detect_color(stream: TextIO) -> bool:
    """探测流是否支持颜色；不修改系统控制台模式。"""
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    try:
        if stream.isatty():
            return sys.platform != "win32" or bool(
                os.environ.get("PYCHARM_HOSTED") or os.environ.get("WT_SESSION")
                or os.environ.get("ANSICON") or os.environ.get("TERM")
                or os.environ.get("ConEmuANSI") == "ON"
            )
        # PyCharm 的 Run/Debug 控制台通常是管道；文件或内存捕获不能接收控制码。
        return bool(os.environ.get("PYCHARM_HOSTED")) and stat.S_ISFIFO(
            os.fstat(stream.fileno()).st_mode,
        )
    except (AttributeError, OSError, ValueError):
        # 输出代理或已关闭的描述符可能无法查询能力，降级为原文但不丢弃日志。
        return False


def _supports_color(stream: TextIO) -> bool:
    """返回流的颜色能力；同一流只探测一次，流被替换时按身份重新判定。"""
    cached = _color_cache.get(id(stream))
    if cached is not None and cached[0] is stream:
        return cached[1]
    supported = _detect_color(stream)
    if len(_color_cache) >= _COLOR_CACHE_LIMIT:
        _color_cache.pop(next(iter(_color_cache)))
    _color_cache[id(stream)] = (stream, supported)
    return supported


def colorize_console(level: str, text: str, stream: TextIO) -> str:
    """返回带级别颜色和复位标记的显示文本；不写流、不添换行、不改变业务正文。"""
    color = _LEVEL_COLORS.get(str(level).strip().upper())
    if color is None or not _supports_color(stream):
        return text
    return f"\x1b[{color}m{text}\x1b[0m"
