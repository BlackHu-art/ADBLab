"""通过 owner 的停止入口清理测试窗口，活线程退出前保留其 QObject 树。"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEvent, QEventLoop, Qt, QThread, QTimer
from PySide6.QtWidgets import QWidget
from shiboken6 import delete, isValid

_RETAINED_WINDOWS: dict[int, tuple[QWidget, tuple[QThread, ...]]] = {}


def _claim_window_deletion(window: QWidget) -> None:
    """接管关闭自动删除和先前 deleteLater 请求；线程屏障完成后才真正释放。"""
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    QCoreApplication.removePostedEvents(window, QEvent.Type.DeferredDelete)


def _stop_timers(window: QWidget) -> list[QTimer]:
    timers = window.findChildren(QTimer)
    for timer in timers:
        if timer.isActive():
            timer.stop()
    return timers


def _request_owner_stop(window: QWidget) -> Callable[[], bool] | None:
    """只调用已定义的生命周期边界；测试不能直接终止线程或伪造关闭完成。"""
    if getattr(window, "_startup_complete", None) is False:
        from gui.main_frame import MainFrame

        if isinstance(window, MainFrame):
            # 分段启动尚未装配完整字段，必须沿真实启动中止边界收口已创建资源。
            window.abort_startup()
            return lambda: not isValid(window) or window._startup_abort_reported
    for name in ("shutdown", "_prepare_ui_for_shutdown", "request_dispose", "prepare_shutdown"):
        callback = getattr(window, name, None)
        if callable(callback):
            if name == "request_dispose":
                callback("test_cleanup")
            else:
                callback()
            return None
    return None


def _wait_child_threads(
    window: QWidget, timeout_ms: int, owner_ready: Callable[[], bool] | None,
) -> tuple[QThread, ...]:
    """整个窗口共用一个期限；推进必要 GUI 回调并以实际 join 确认线程结束。"""
    deadline = QDeadlineTimer(max(0, timeout_ms))
    observed: dict[int, QThread] = {}
    while isValid(window):
        for thread in window.findChildren(QThread):
            observed[id(thread)] = thread
        pending = tuple(
            thread for thread in observed.values()
            if isValid(thread) and (thread.isRunning() or not thread.wait(0))
        )
        owner_pending = owner_ready is not None and not owner_ready()
        if not pending and not owner_pending:
            return pending
        if deadline.hasExpired():
            if owner_pending:
                raise TimeoutError("UI cleanup timed out waiting for startup abort")
            return pending
        QCoreApplication.processEvents(
            QEventLoop.ProcessEventsFlag.AllEvents, min(10, deadline.remainingTime()),
        )
        if pending and isValid(pending[0]) and not deadline.hasExpired():
            pending[0].wait(min(5, deadline.remainingTime()))
    return ()


def cleanup_ui_windows(
    windows: Iterable[QWidget], *, cleanup_records: dict, timeout_ms: int = 2000,
) -> list[Exception]:
    """停止并释放独立窗口；超时保留 owner/线程并返回错误，继续清理其他窗口。

    仅由 GUI 线程的测试 teardown 安全边界调用，不能从控件自身的事件处理回调中调用。
    停止回调和有界事件推进返回、原生线程 join 后直接释放，避免已撤销 deleteLater 的内部标志
    阻止再次排队。每次也重试此前保留的窗口；不因 shutdown/close 异常跳过线程屏障。
    """
    errors: list[Exception] = []
    candidates = {key: owner for key, (owner, _threads) in _RETAINED_WINDOWS.items()}
    candidates.update((id(window), window) for window in windows)
    for window in candidates.values():
        if not isValid(window):
            _RETAINED_WINDOWS.pop(id(window), None)
            continue
        _claim_window_deletion(window)
        record = {
            "timer_was_active": any(timer.isActive() for timer in window.findChildren(QTimer)),
        }
        cleanup_records[id(window)] = record
        _stop_timers(window)
        owner_ready = None
        try:
            owner_ready = _request_owner_stop(window)
        except Exception as error:
            errors.append(error)
        if not isValid(window):
            _RETAINED_WINDOWS.pop(id(window), None)
            continue
        record["post_shutdown_timer_was_active"] = any(
            timer.isActive() for timer in window.findChildren(QTimer)
        )
        try:
            if window.isVisible():
                window.close()
        except Exception as error:
            errors.append(error)
        if not isValid(window):
            _RETAINED_WINDOWS.pop(id(window), None)
            continue
        _claim_window_deletion(window)
        wait_failed = False
        try:
            pending = _wait_child_threads(window, timeout_ms, owner_ready)
        except Exception as error:
            # 不确定线程状态时同样保全对象树，不能在错误处理路径重新引入析构 fatal。
            errors.append(error)
            wait_failed = True
            pending = tuple(window.findChildren(QThread)) if isValid(window) else ()
        if not isValid(window):
            _RETAINED_WINDOWS.pop(id(window), None)
            continue
        timers = _stop_timers(window)
        record["timer_stopped"] = all(not timer.isActive() for timer in timers)
        record["retained"] = bool(pending) or wait_failed
        if record["retained"]:
            _claim_window_deletion(window)
            _RETAINED_WINDOWS[id(window)] = (window, pending)
            if not wait_failed:
                errors.append(TimeoutError(
                    f"UI cleanup timed out waiting for {len(pending)} QThread(s)",
                ))
            continue
        _RETAINED_WINDOWS.pop(id(window), None)
        delete(window)
    return errors
