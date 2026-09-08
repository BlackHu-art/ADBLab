"""独立页面把过程说明送到任务中心，显式级别决定窗口通知。"""

from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from gui.notifications import ToastLevel, show_toast


def report_feedback(
    page: QWidget, source: str, title: str, message: str, *,
    level: ToastLevel = "info", notify: bool = False, target: str = "",
) -> None:
    """仅在 GUI 线程调用；脱离主窗口的独立页面仍可显示显式结果通知。"""
    if not isValid(page) or getattr(page, "_closing", False):
        return
    owner = page.window()
    presenter = getattr(owner, "_action_feedback", None)
    if presenter is not None:
        presenter.record_notice(source, title, message, level, target, notify=notify)
    elif notify:
        show_toast(page, title, message, level=level)
