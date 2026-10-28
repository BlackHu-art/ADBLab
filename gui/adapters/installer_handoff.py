"""在 GUI 之外准备独立升级 helper，明确持有准备线程直到真实退出。"""

from __future__ import annotations

from threading import Event, Thread
from time import monotonic
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from core.log_service import LogService

if TYPE_CHECKING:
    from core.installer_handoff import InstallerHandoff
    from services.installer_update import VerifiedInstaller


class QtInstallerHandoff(QObject):
    """仅准备交接，不授权安装；主线程发布状态，关闭监督器在后台等待线程。"""

    changed = Signal(str)
    ready = Signal()

    def __init__(self, handoff: InstallerHandoff, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handoff = handoff
        self._thread: Thread | None = None
        self._cancel = Event()
        self._closing = False
        self._failed = False
        self._failure_kind = ""
        self._poll = QTimer(self)
        self._poll.setInterval(20)
        self._poll.timeout.connect(self._finish)

    def start(self, verified: VerifiedInstaller) -> bool:
        """合并重复请求；READY 仅在准备线程已 join 且未取消时交付一次。"""
        if self._closing or self.is_running() or self._poll.isActive():
            return False
        try:
            self._handoff.reset_attempt()
        except (OSError, RuntimeError) as error:
            LogService().log(
                "WARNING",
                f"installer handoff reset failed: {type(error).__name__}",
            )
            self.changed.emit("error")
            return False
        self._cancel.clear()
        self._failed = False
        self._failure_kind = ""

        def prepare() -> None:
            try:
                self._handoff.prepare(verified)
                self._failed = not self._handoff.prepared
            except Exception as error:
                # worker 不创建 QObject；仅记录类型，由 GUI 线程的 _finish 落日志。
                self._failure_kind = type(error).__name__
                self._failed = True
            finally:
                if self._cancel.is_set():
                    self._handoff.abort()

        self._thread = Thread(target=prepare, name="adblab-installer-prepare", daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            self._thread = None
            self._handoff.abort()
            self.changed.emit("error")
            return False
        # 先登记并启动再发布；同步信号槽可立即关闭或重复点击，不能漏掉等待义务。
        self._poll.start()
        self.changed.emit("preparing")
        return True

    def _finish(self) -> None:
        """GUI 轮询只观察已结束线程，不把线程中的结果直接投递给可销毁控件。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self.wait(0)
        self._poll.stop()
        if self._closing:
            return
        if self._cancel.is_set():
            self.changed.emit("cancelled")
        elif self._failed:
            LogService().log(
                "WARNING",
                "installer handoff preparation failed: "
                f"{self._failure_kind or 'UnknownError'}",
            )
            self.changed.emit("error")
        else:
            self.changed.emit("ready")
            self.ready.emit()

    def cancel(self) -> None:
        """撤销本次准备；不终止 helper 或其他进程，线程仍保留到实际退出。"""
        self._cancel.set()
        self._handoff.abort()

    def prepare_shutdown(self, *, preserve_prepared: bool = False) -> None:
        """主线程封闭回调；仅用户确认且 READY 后的升级关闭保留待授权 helper。"""
        self._closing = True
        self._poll.stop()
        if not preserve_prepared or self.is_running() or not self._handoff.prepared:
            self.cancel()

    def is_running(self) -> bool:
        """供关闭监督器观察线程及未授权 helper；正常 READY 交接不阻塞父应用退出。"""
        return ((self._thread is not None and self._thread.is_alive())
                or self._handoff.has_pending_helper())

    def wait(self, timeout: float) -> bool:
        """后台共享预算等待线程和未授权 helper；零预算只观察，超时保留资源归属。"""
        deadline = monotonic() + max(0.0, timeout)
        thread = self._thread
        if thread is not None:
            thread.join(max(0.0, timeout))
            if thread.is_alive():
                return False
        return self._handoff.wait_pending_helper(max(0.0, deadline - monotonic()))
