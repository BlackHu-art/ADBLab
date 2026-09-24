"""在 Qt 事件循环中推进启动阶段，并管理首帧交接及失败清理。"""

from __future__ import annotations

import logging
from collections.abc import Generator
from time import perf_counter
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QTimer, Signal

if TYPE_CHECKING:
    from gui.main_frame import MainFrame
    from gui.widgets.startup_splash import StartupSplash


class StartupController(QObject):
    """拥有单次启动调度；退出信号只在已建窗口资源收口后交付。

    阶段生成器只在主线程执行，每次推进后返回事件循环。主窗由调用方在创建后立即
    登记，确保后续阶段失败时仍可关闭部分构建的对象；启动图标不拥有业务资源。
    """

    ready = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    settled = Signal()

    def __init__(self, splash: StartupSplash, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._splash = splash
        self._window: MainFrame | None = None
        self._steps: Generator[tuple[str, int], None, None] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)
        self._started = False
        self._advancing = False
        self._stopping = False
        self._cleanup_started = False
        self._done = False
        self._waiting_for_paint = False
        self._progress = 0
        self._started_at = perf_counter()
        self.error: BaseException | None = None
        splash.first_painted.connect(self._begin)
        splash.cancelled.connect(self.cancel)

    @property
    def is_settled(self) -> bool:
        """返回交接或中止清理是否已完成，用于事件循环退出兜底。"""
        return self._done

    def set_window(self, window: MainFrame) -> None:
        """登记本次启动拥有的唯一主窗，早于任何可失败的页面初始化。"""
        if self._window is not None or self._stopping or self._done:
            raise RuntimeError("startup window is already registered or startup has stopped")
        self._window = window

    def start(self, steps: Generator[tuple[str, int], None, None]) -> None:
        """显示启动图标；首次真实绘制之前不导入或创建重型界面。"""
        if self._steps is not None or self._done:
            raise RuntimeError("startup has already started")
        self._steps = steps
        self._splash.show()

    def _begin(self) -> None:
        if self._started or self._stopping or self._done:
            return
        self._started = True
        logging.getLogger(__name__).debug(
            "GUI startup splash painted: elapsed_ms=%.1f",
            (perf_counter() - self._started_at) * 1000,
        )
        self._timer.start(0)

    def _advance(self) -> None:
        if self._stopping or self._done or self._steps is None:
            return
        started_at = perf_counter()
        self._advancing = True
        try:
            try:
                name, progress = next(self._steps)
            except StopIteration:
                if not self._stopping:
                    if self._window is None:
                        raise RuntimeError("startup finished without a main window")
                    self._waiting_for_paint = True
                    self._window.installEventFilter(self)
                    self._window.show()
                return
            if not self._stopping:
                self._progress = max(self._progress, min(95, progress))
                self._splash.set_progress(self._progress)
                logging.getLogger(__name__).debug(
                    "GUI startup stage: %s elapsed_ms=%.1f total_ms=%.1f",
                    name, (perf_counter() - started_at) * 1000,
                    (perf_counter() - self._started_at) * 1000,
                )
                # 不等待动画走完，下一阶段仍在下一轮事件循环尽早执行。
                self._timer.start(0)
        except BaseException as error:
            self._stop(error)
        finally:
            self._advancing = False
            if self._stopping:
                self._abort()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._window and not self._stopping and not self._done:
            if event.type() == QEvent.Type.Paint and self._waiting_for_paint:
                self._waiting_for_paint = False
                # 事件过滤器发生在绘制之前，排队到本次绘制返回后再收起启动画面。
                QTimer.singleShot(0, self, self._handoff)
            elif event.type() == QEvent.Type.Close:
                self.cancel()
        return super().eventFilter(watched, event)

    def _handoff(self) -> None:
        if self._stopping or self._done or self._window is None:
            return
        if not self._window.isVisible():
            self.cancel()
            return
        self._window.removeEventFilter(self)
        self._splash.set_progress(100, animate=False)
        self._splash.finish()
        self._done = True
        logging.getLogger(__name__).debug(
            "GUI startup main window painted: elapsed_ms=%.1f",
            (perf_counter() - self._started_at) * 1000,
        )
        self.ready.emit(self._window)
        self.settled.emit()

    def cancel(self) -> None:
        """停止调度并收口已建资源；重复取消及交接后的取消均无副作用。"""
        self._stop(None)

    def _stop(self, error: BaseException | None) -> None:
        if self._stopping or self._done:
            return
        self.error = error
        self._stopping = True
        self._timer.stop()
        self._waiting_for_paint = False
        self._splash.finish()
        if not self._advancing:
            self._abort()

    def _abort(self) -> None:
        if self._cleanup_started:
            return
        self._cleanup_started = True
        if self._steps is not None:
            try:
                self._steps.close()
            except BaseException as error:
                # 阶段收尾失败也必须继续释放窗口；原始启动错误优先保留。
                if self.error is None:
                    self.error = error
                logging.getLogger(__name__).error(
                    "GUI startup stage cleanup failed: %s", type(error).__name__,
                )
        if self._window is None:
            self._aborted()
        else:
            self._window.removeEventFilter(self)
            self._window.startup_aborted.connect(self._aborted)
            self._window.abort_startup()

    def _aborted(self) -> None:
        if self._done:
            return
        self._done = True
        if self.error is not None:
            self.failed.emit(self.error)
        else:
            self.cancelled.emit()
        self.settled.emit()
