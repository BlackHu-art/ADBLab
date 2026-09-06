"""通过串行后台队列读写测试库，GUI 仅接收已落盘的不可变快照。"""

from __future__ import annotations

import copy
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from gui.dialogs.lifecycle import alive_signal_emitter
from gui.i18n import tr
from services.run_library import RunLibrary, RunPreset, RunRecord


class _LibraryQueue:
    """队列空闲即退出线程；关闭只等待已提交的有界本地写入。"""

    def __init__(
        self, library: RunLibrary, publish: Callable, report: Callable, open_ready: Callable
    ):
        self.library = library
        self._publish = publish
        self._report = report
        self._open_ready = open_ready
        self._lock = threading.Lock()
        self._jobs: deque[tuple[str, tuple]] = deque()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._write_error = False

    def submit(self, method: str, *args) -> bool:
        with self._lock:
            if self._closed:
                return False
            self._jobs.append((method, copy.deepcopy(args)))
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._drain, name="adblab-run-library", daemon=True
                )
                self._thread.start()
        return True

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._jobs:
                    self._thread = None
                    return
                method, args = self._jobs.popleft()
            try:
                if method == "open_artifact":
                    path, folder = args
                    target = Path(path)
                    if not target.is_absolute() or not target.exists():
                        raise ValueError("附件不可用")
                    if folder and target.is_file():
                        target = target.parent
                    self._open_ready(str(target))
                else:
                    getattr(self.library, method)(*args)
            except (OSError, ValueError, TypeError, RecursionError, OverflowError) as exc:
                # 文件路径和底层异常留在边界内，用户只看到可操作且不泄露设备信息的提示。
                self._report(f"{method}:{type(exc).__name__}")
                if method != "open_artifact":
                    self._write_error = True
            else:
                if method != "open_artifact":
                    self._publish((self.library.records, self.library.presets))

    def close(self, timeout: float = 5.0) -> bool:
        """停止接收写入；由应用收尾线程调用，等待队列排空。"""
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is not None:
            thread.join(max(0.0, timeout))
        with self._lock:
            return (
                not self._jobs
                and not self._write_error
                and (thread is None or not thread.is_alive())
            )


class RunLibraryController(QObject):
    """主窗口拥有的测试库接口；页面不直接读取用户文件或拥有写入线程。"""

    changed = Signal()
    error = Signal(str)
    _snapshot_ready = Signal(object)
    _write_failed = Signal(str)
    _open_ready = Signal(str)

    def __init__(self, library: RunLibrary, parent: QObject | None = None):
        super().__init__(parent)
        self._records: tuple[RunRecord, ...] = ()
        self._presets: tuple[RunPreset, ...] = ()
        self._snapshot_ready.connect(self._apply_snapshot, Qt.ConnectionType.QueuedConnection)
        self._write_failed.connect(self._report_error, Qt.ConnectionType.QueuedConnection)
        self._open_ready.connect(self._open_local_path, Qt.ConnectionType.QueuedConnection)
        self._queue = _LibraryQueue(
            library,
            alive_signal_emitter(self, "_snapshot_ready"),
            alive_signal_emitter(self, "_write_failed"),
            alive_signal_emitter(self, "_open_ready"),
        )
        queue = self._queue
        self.destroyed.connect(lambda: queue.close(0))
        self._queue.submit("load")

    @property
    def records(self) -> tuple[RunRecord, ...]:
        return copy.deepcopy(self._records)

    @property
    def presets(self) -> tuple[RunPreset, ...]:
        return copy.deepcopy(self._presets)

    def _apply_snapshot(self, snapshot) -> None:
        self._records, self._presets = snapshot
        self.changed.emit()

    def _report_error(self, _error_type: str) -> None:
        if _error_type.startswith("open_artifact:"):
            self.error.emit(tr("结果文件不可用，可能已被移动或删除，请检查原输出目录。"))
        else:
            self.error.emit(
                tr("测试记录或方案未能保存，请检查用户数据目录的可写权限和记录文件；原文件已保留。")
            )

    def _open_local_path(self, path: str) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self.error.emit(tr("无法打开结果文件，请检查系统是否安装了对应程序。"))

    def open_artifact(self, path: str, folder: bool = False) -> None:
        """后台检查单个本地附件；回到 GUI 线程后调用系统关联程序。"""
        self._queue.submit("open_artifact", path, folder)

    def record_run(self, record: RunRecord) -> None:
        self._queue.submit("record_run", record)

    def save_preset(self, name: str, kind: str, parameters: dict) -> None:
        self._queue.submit("save_preset", name, kind, parameters)

    def delete_preset(self, preset_id: str) -> None:
        self._queue.submit("delete_preset", preset_id)

    def shutdown(self, timeout: float = 5.0) -> bool:
        """由后台关闭收尾调用；返回 False 表示落盘未结束或发生过保存错误。"""
        return self._queue.close(timeout)
