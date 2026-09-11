"""在最终控制台显示层按日志级别着色，文件与机器读取的输出保持纯文本。"""

from __future__ import annotations

import os
import stat
import sys
from typing import TextIO

_LEVEL_COLORS = {
    "DEBUG": "90", "INFO": "36", "SUCCESS": "32",
    "WARNING": "33", "ERROR": "31", "CRITICAL": "35",
}


def _supports_color(stream: TextIO) -> bool:
    """仅识别终端及 PyCharm 的控制台管道，不修改系统控制台模式。"""
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


def colorize_console(level: str, text: str, stream: TextIO) -> str:
    """返回带级别颜色和复位标记的显示文本；不写流、不添换行、不改变业务正文。"""
    color = _LEVEL_COLORS.get(str(level).strip().upper())
    if color is None or not _supports_color(stream):
        return text
    return f"\x1b[{color}m{text}\x1b[0m"
