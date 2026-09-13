"""保留有界的应用异常和运行时诊断摘要，业务命令正文由所属功能结果单独管理。"""

from __future__ import annotations

import re
from collections import deque


def _sorted_private_values(values) -> tuple[str, ...]:
    """把设备标识等私密值按长度降序排列，长值先替换，避免被短值截断后残留尾部。"""

    return tuple(sorted((value for value in values if value), key=len, reverse=True))


def _redact_with_sorted(text: str, sorted_values: tuple[str, ...]) -> str:
    """用已排序私密值执行替换、凭据/地址/路径遮蔽和单条长度截断。"""

    for value in sorted_values:
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


def redact_diagnostic(
    text: str,
    private_values: tuple[str, ...] = (),
    *,
    presorted: bool = False,
) -> str:
    """在应用诊断边界移除已知设备身份、凭据和绝对路径，限制单条诊断大小。

    presorted=True 表示调用方已提供按长度降序的私密值（如 DiagnosticJournal
    的排序缓存），可跳过重复排序；默认路径对任意顺序的入参保持原有输出。
    """

    values = private_values if presorted else _sorted_private_values(private_values)
    return _redact_with_sorted(text, values)


class DiagnosticJournal:
    """由日志服务所在线程归并诊断；上限 200 条，不持有线程或进行文件 I/O。"""

    def __init__(self):
        self.entries: deque[tuple[str, str, str]] = deque(maxlen=200)
        self._private_values: tuple[str, ...] = ()
        self._sorted_private: tuple[str, ...] = ()

    @property
    def private_values(self) -> tuple[str, ...]:
        """返回当前登记的私密值；赋值后由本类维护排序缓存。"""

        return self._private_values

    @private_values.setter
    def private_values(self, values) -> None:
        self._private_values = tuple(values or ())
        self._sorted_private = _sorted_private_values(self._private_values)

    @property
    def sorted_private_values(self) -> tuple[str, ...]:
        """返回按长度降序的私密值，供控制台脱敏复用，避免每条日志重新排序。"""

        return self._sorted_private

    def accept(self, batch: list[tuple[str, str, str]], *, include_info: bool = False) -> bool:
        """默认只接收异常；运行时诊断可显式纳入 INFO，返回是否需要通知和后台落盘。"""

        changed = False
        for timestamp, level, message in batch:
            if level in {"WARNING", "ERROR", "CRITICAL"} or (include_info and level == "INFO"):
                self.entries.append(
                    (timestamp, level, _redact_with_sorted(message, self._sorted_private))
                )
                changed = True
        return changed

    def text(self) -> str:
        """导出当前会话保留的诊断摘要，不包含正常操作正文。"""

        return "\n".join(f"{stamp} [{level}] {message}" for stamp, level, message in self.entries)
