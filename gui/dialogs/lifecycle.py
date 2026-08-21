"""提供对话框信号断开、对象存活检查和 worker 清理辅助能力。"""

from __future__ import annotations

import threading
import time
import warnings
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QThread
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

_retained_qthreads: set[QThread] = set()
_retained_qthreads_lock = threading.Lock()
_FIT_ORIGINAL_MINIMUM_PROPERTY = "_adblab_fit_original_minimum"
_FIT_ORIGINAL_SIZE_PROPERTY = "_adblab_fit_original_size"
_FIT_WAS_CLAMPED_PROPERTY = "_adblab_fit_was_clamped"


def configure_independent_secondary_window(dialog: QWidget) -> None:
    """将受代码托管的二级窗口配置为可独立切换的非模态顶层窗口。"""
    if dialog.parentWidget() is not None:
        # 保留窗口类型和装饰，只解除操作系统层面的 transient owner 关系。
        dialog.setParent(None, dialog.windowFlags())
    # 通过 Qt API 单独清除置顶位，避免枚举取反截断高位的关闭按钮标志。
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
    dialog.setWindowModality(Qt.WindowModality.NonModal)
    dialog.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)


def fit_secondary_window_to_owner_screen(
    dialog: QWidget,
    owner: QWidget,
    *,
    margin: int = 24,
    minimum_floor: QSize = QSize(640, 420),
) -> None:
    """把二级窗口尺寸和位置限制在主窗口所在屏幕的可用区域内。"""

    try:
        screen = owner.screen()
        available = screen.availableGeometry() if screen is not None else QRect()
    except RuntimeError:
        available = QRect()
    if not available.isValid():
        return

    usable_width = max(1, available.width() - max(0, margin))
    usable_height = max(1, available.height() - max(0, margin))
    requested_minimum = dialog.property(_FIT_ORIGINAL_MINIMUM_PROPERTY)
    original_size = dialog.property(_FIT_ORIGINAL_SIZE_PROPERTY)
    if not isinstance(requested_minimum, QSize):
        requested_minimum = QSize(dialog.minimumSize())
        dialog.setProperty(_FIT_ORIGINAL_MINIMUM_PROPERTY, requested_minimum)
    if not isinstance(original_size, QSize):
        original_size = QSize(dialog.size())
        dialog.setProperty(_FIT_ORIGINAL_SIZE_PROPERTY, original_size)
    was_clamped = bool(dialog.property(_FIT_WAS_CLAMPED_PROPERTY))
    requested_minimum_width = requested_minimum.width() or minimum_floor.width()
    requested_minimum_height = requested_minimum.height() or minimum_floor.height()
    effective_minimum = QSize(
        min(usable_width, requested_minimum_width),
        min(usable_height, requested_minimum_height),
    )
    dialog.setMinimumSize(effective_minimum)

    current = original_size if was_clamped else dialog.size()
    desired = QSize(
        min(usable_width, max(effective_minimum.width(), current.width())),
        min(usable_height, max(effective_minimum.height(), current.height())),
    )
    dialog.resize(desired)
    dialog.setProperty(
        _FIT_WAS_CLAMPED_PROPERTY,
        desired.width() < current.width() or desired.height() < current.height(),
    )

    target = QRect(QPoint(), desired)
    try:
        target.moveCenter(owner.frameGeometry().center())
    except RuntimeError:
        target.moveCenter(available.center())
    maximum_left = available.right() - target.width() + 1
    maximum_top = available.bottom() - target.height() + 1
    target.moveLeft(max(available.left(), min(target.left(), maximum_left)))
    target.moveTop(max(available.top(), min(target.top(), maximum_top)))
    dialog.move(target.topLeft())


def is_qobject_alive(obj: Any) -> bool:
    if obj is None:
        return False
    try:
        return bool(isValid(obj))
    except RuntimeError:
        return False
    except TypeError:
        return obj is not None


def safe_disconnect(signal: Any, handler: Callable | None = None) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            if handler is None:
                signal.disconnect()
            else:
                signal.disconnect(handler)
    except (TypeError, ValueError, RuntimeError, SystemError):
        pass


def alive_callback(obj: Any, method_name: str, *args: Any, **kwargs: Any) -> Callable:
    obj_ref = weakref.ref(obj)

    def _callback(*_signal_args: Any) -> None:
        target = obj_ref()
        if not is_qobject_alive(target):
            return
        getattr(target, method_name)(*args, **kwargs)

    return _callback


def alive_forwarding_callback(obj: Any, method_name: str) -> Callable:
    """仅在 QObject 存活时把信号参数原样转发给指定方法。"""

    obj_ref = weakref.ref(obj)

    def _callback(*signal_args: Any, **signal_kwargs: Any) -> None:
        target = obj_ref()
        if not is_qobject_alive(target):
            return
        getattr(target, method_name)(*signal_args, **signal_kwargs)

    return _callback


def alive_signal_emitter(obj: Any, signal_name: str, *prefix_args: Any) -> Callable:
    """创建不持有窗口强引用的安全 Qt 信号发射回调。"""

    obj_ref = weakref.ref(obj)

    def _callback(*signal_args: Any) -> None:
        target = obj_ref()
        if not is_qobject_alive(target):
            return
        getattr(target, signal_name).emit(*prefix_args, *signal_args)

    return _callback


@dataclass
class WorkerSignalBinding:
    worker: Any
    handlers: tuple[tuple[Any, Callable], ...]
    finished_handler: Callable | None = None
    _connected: bool = field(default=False, init=False)

    def connect(self) -> None:
        if self._connected:
            return
        for signal_, handler in self.handlers:
            signal_.connect(handler)
        if self.finished_handler is not None:
            self.worker.finished.connect(self.finished_handler)
        self._connected = True

    def disconnect(self) -> None:
        if not self._connected:
            return
        for signal_, handler in self.handlers:
            safe_disconnect(signal_, handler)
        if self.finished_handler is not None and is_qobject_alive(self.worker):
            safe_disconnect(self.worker.finished, self.finished_handler)
        self._connected = False


def wait_for_thread_later(thread: QThread, timeout_ms: int) -> None:
    """后台等待线程结束，并在真正结束前持续保留 Qt 包装对象。"""

    wait_for_threads_later([thread], timeout_ms)


def wait_for_threads_later(threads: list[QThread], timeout_ms: int) -> None:
    """异步等待一组 QThread；单次超时不会释放仍在运行的对象。"""

    retained = []
    for thread in dict.fromkeys(threads):
        if not is_qobject_alive(thread):
            continue
        try:
            thread.setParent(None)
        except RuntimeError:
            continue
        retained.append(thread)
    if not retained:
        return

    with _retained_qthreads_lock:
        _retained_qthreads.update(retained)

    wait_slice_ms = max(50, int(timeout_ms or 0))

    def wait_until_stopped() -> None:
        for thread in retained:
            try:
                while thread.isRunning():
                    thread.wait(wait_slice_ms)
            except RuntimeError:
                pass
            finally:
                with _retained_qthreads_lock:
                    _retained_qthreads.discard(thread)
                try:
                    thread.deleteLater()
                except RuntimeError:
                    pass

    threading.Thread(
        target=wait_until_stopped,
        name="adblab-qthread-retention-wait",
        daemon=True,
    ).start()


class QThreadGroupShutdownTask:
    """将一组已捕获的 QThread 适配为应用资源监督协议。"""

    def __init__(self, threads: list[QThread]) -> None:
        self.threads = list(threads)

    @staticmethod
    def _running(thread: QThread) -> bool:
        try:
            return bool(thread.isRunning())
        except RuntimeError:
            return False

    def request_stop(self) -> None:
        for thread in self.threads:
            if not self._running(thread):
                continue
            try:
                abort = getattr(thread, "abort", None)
                if callable(abort):
                    abort()
                else:
                    thread.requestInterruption()
            except RuntimeError:
                continue

    def wait(self, timeout: float) -> bool:
        final_end = time.monotonic() + max(0.0, float(timeout))
        for thread in self.threads:
            if self._running(thread):
                remaining_ms = max(0, int((final_end - time.monotonic()) * 1000))
                try:
                    thread.wait(remaining_ms)
                except RuntimeError:
                    continue
        return not self.is_running()

    def is_running(self) -> bool:
        return any(self._running(thread) for thread in self.threads)
