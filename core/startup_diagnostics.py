"""缓冲启动耗时和状态；界面就绪后转交日志，早期失败独立原子落盘。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from time import perf_counter

from core.diagnostics import DiagnosticJournal, redact_diagnostic


class StartupDiagnostics:
    """由 GUI 启动线程持有；最多保留 200 条脱敏记录，不拥有后台资源。"""

    def __init__(self, *, started_at: float | None = None) -> None:
        self.started_at = perf_counter() if started_at is None else started_at
        self._journal = DiagnosticJournal()
        self._sink: Callable[[str], None] | None = None

    def record(self, event: str, *, detail: str = "", elapsed_ms: float | None = None) -> None:
        """接收阶段名、错误类型及耗时；不传入设备标识或原始异常正文。"""
        message = f"startup {event} total_ms={(perf_counter() - self.started_at) * 1000:.1f}"
        if elapsed_ms is not None:
            message += f" elapsed_ms={elapsed_ms:.1f}"
        if detail:
            message += f" {detail}"
        message = redact_diagnostic(message)
        self._journal.accept(
            [(datetime.now().strftime("%H:%M:%S"), "INFO", message)], include_info=True,
        )
        if self._sink is not None:
            self._sink(message)

    def bind(self, sink: Callable[[str], None]) -> None:
        """日志服务在所属线程就绪后仅转交一次；后续记录直接交给同一接收器。"""
        if self._sink is not None:
            raise RuntimeError("startup diagnostics already bound")
        self._sink = sink
        for _timestamp, _level, message in self._journal.entries:
            sink(message)

    def text(self) -> str:
        """返回本次启动的有界脱敏摘要。"""
        return self._journal.text()

    def save_failure(self, path: Path | None = None) -> None:
        """退出事件循环后保存最近失败；不依赖主窗、日志线程或安装目录可写。"""
        from utils.atomic_text import atomic_write_text
        from utils.user_data import user_data_root

        target = path if path is not None else user_data_root() / "logs" / "startup-diagnostics.log"
        atomic_write_text(str(target), self.text() + "\n")
