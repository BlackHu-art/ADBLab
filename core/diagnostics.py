"""保留有界的应用异常和运行时诊断摘要，业务命令正文由所属功能结果单独管理。"""

from __future__ import annotations

import re
from collections import deque


def redact_diagnostic(text: str, private_values: tuple[str, ...] = ()) -> str:
    """在应用诊断边界移除已知设备身份、凭据和绝对路径，限制单条诊断大小。"""
    for value in sorted(private_values, key=len, reverse=True):
        if value:
            text = text.replace(value, "<device>")
    text = re.sub(
        r"(?i)\b(password|passwd|token|secret|authorization|serial)\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b", "<address>", text)
    text = re.sub(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", "<address>", text)
    text = re.sub(r"[A-Za-z]:[\\/][^\r\n]*|(?<!\w)/(?:[^\s/]+/)+[^\s]*", "<path>", text)
    return text[:2048]


class DiagnosticJournal:
    """由日志服务所在线程归并诊断；上限 200 条，不持有线程或进行文件 I/O。"""

    def __init__(self):
        self.entries: deque[tuple[str, str, str]] = deque(maxlen=200)
        self.private_values: tuple[str, ...] = ()

    def accept(self, batch: list[tuple[str, str, str]], *, include_info: bool = False) -> bool:
        """默认只接收异常；运行时诊断可显式纳入 INFO，返回是否需要通知和后台落盘。"""
        changed = False
        for timestamp, level, message in batch:
            if level in {"WARNING", "ERROR", "CRITICAL"} or (include_info and level == "INFO"):
                self.entries.append(
                    (timestamp, level, redact_diagnostic(message, self.private_values))
                )
                changed = True
        return changed

    def text(self) -> str:
        """导出当前会话保留的诊断摘要，不包含正常操作正文。"""
        return "\n".join(f"{stamp} [{level}] {message}" for stamp, level, message in self.entries)
