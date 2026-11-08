"""组合共享任务投影、右侧阅读器和导航状态，不拥有执行资源。"""

from __future__ import annotations

import weakref
from collections.abc import Callable

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QPointF, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from gui.i18n import tr
from gui.pages.tasks_page import POLL_INTERVAL_MS, TaskCenterPage
from gui.session_tasks import SessionTaskRegistry
from gui.widgets.task_detail_drawer import TaskDetailDrawer
from gui.widgets.task_navigation import TaskNavigationButton

_SOURCE_LABELS = {
    "devices": "设备概览",
    "devices.files": "文件管理",
    "devices.remote": "远程控制",
    "remote": "远程控制",
    "apps": "应用与诊断",
    "apps.manager": "应用管理",
    "apps.packages": "应用与诊断",
    "apps.media": "截图与屏幕",
    "apps.reports": "应用与诊断",
    "apps.diagnostics": "应用与诊断",
    "apps.monkey": "应用与诊断",
    "system": "系统工具",
    "system.logcat": "实时 Logcat",
    "system.performance": "性能采集",
    "settings.maintenance": "设置",
}


class _OutsideDismissObserver(QObject):
    """只接管本主窗内容/导航的外侧首击；关闭后仍收完同一物理手势。

    应用过滤器仅在抽屉打开或有待收尾手势时存在。双击资格采用系统时间、距离和输入
    来源；新的普通按下立即结束旧资格，不以时间窗口禁用其他业务输入。
    """

    def __init__(self, owner: TaskFeedbackCoordinator, surface: QWidget,
                 navigation: QWidget) -> None:
        super().__init__(owner)
        self._owner = owner
        self._window_ref = weakref.ref(surface.window())
        self._scopes = (weakref.ref(surface), weakref.ref(navigation))
        self._installed = False
        self._closed = False
        self._pressed: tuple | None = None
        self._double: tuple | None = None
        self._context_position: QPointF | None = None
        self._double_timer = QTimer(self)
        self._double_timer.setSingleShot(True)
        self._double_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._double_clock = QElapsedTimer()
        self._double_interval = 0
        self._double_timer.timeout.connect(self._expire_double)
        window = surface.window()
        if window is not None:
            window.destroyed.connect(self.shutdown)
        surface.installEventFilter(self)

    @staticmethod
    def _belongs_to(widget: QObject, ancestor: QObject) -> bool:
        # Popup 是独立 window，isAncestorOf 不包含它；QObject 归属链仍保留阅读器。
        current: QObject | None = widget
        while current is not None and isValid(current):
            if current is ancestor:
                return True
            current = current.parent()
        return False

    @staticmethod
    def _identity(event: QMouseEvent) -> tuple:
        return event.button(), event.source(), event.pointingDevice()

    def refresh(self) -> None:
        """随呈现目标更新监听；已收起仍不能把按下对应的释放交还背景。"""
        window = self._window_ref()
        surface = self._scopes[0]()
        needed = (not self._closed and window is not None and isValid(window)
                  and window.isVisible() and not window.isMinimized()
                  and surface is not None and isValid(surface) and surface.isVisible()
                  and (self._owner.drawer.opened or self._pressed is not None
                       or self._double is not None or self._context_position is not None))
        app = QApplication.instance()
        if app is not None and needed != self._installed:
            if needed:
                app.installEventFilter(self)
            else:
                app.removeEventFilter(self)
            self._installed = needed

    def reset(self) -> None:
        """宿主隐藏/最小化时放弃悬空手势，恢复时不能接管旧释放。"""
        self._pressed = None
        self._double = None
        self._context_position = None
        self._double_timer.stop()
        self.refresh()

    def shutdown(self, *_args) -> None:
        """由 owner 或宿主析构封闭；不访问已销毁的控件树。"""
        self._closed = True
        self.reset()

    def _expire_double(self) -> None:
        self._double = None
        self._context_position = None
        self.refresh()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if not self._closed and watched is self._scopes[0]():
            if event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
                self.reset()
            elif event.type() == QEvent.Type.Show:
                self.refresh()
        if self._closed or not isinstance(watched, QWidget):
            return False
        window = self._window_ref()
        if window is None or not isValid(window):
            return False
        if isinstance(event, QContextMenuEvent):
            if watched.window() is window and event.reason() == QContextMenuEvent.Reason.Mouse:
                held_right = (self._pressed is not None
                              and bool(self._pressed[0] & Qt.MouseButton.RightButton))
                delta = (QPointF(event.globalPos()) - self._context_position
                         if self._context_position is not None else None)
                distance = QApplication.styleHints().mouseDoubleClickDistance()
                if held_right or (delta is not None
                                  and delta.x() ** 2 + delta.y() ** 2 <= distance ** 2):
                    self._context_position = None
                    self.refresh()
                    event.accept()
                    return True
            return False
        if not isinstance(event, QMouseEvent):
            return False
        kind = event.type()
        identity = self._identity(event)
        own_window = watched.window() is window
        if self._pressed is not None and identity[1:] == self._pressed[1:]:
            buttons, source, device = self._pressed
            if (kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
                    and event.buttons() & buttons):
                # 原按键未松开时，附加按键仍属于同一组合手势；只能全部释放后接收新意图。
                self._pressed = buttons | event.button(), source, device
                self._double = None
                if self._context_position is None:
                    self._double_timer.stop()
                if own_window:
                    event.accept()
                return own_window
            if kind == QEvent.Type.MouseButtonRelease and buttons & event.button():
                remaining = buttons & ~event.button()
                self._pressed = (remaining, source, device) if remaining else None
                if own_window and event.button() == Qt.MouseButton.RightButton:
                    # 系统可在释放之后另发鼠标菜单事件；组合按键和长按也须收完这段尾部。
                    self._context_position = event.globalPosition()
                    self._double_timer.start(QApplication.styleHints().mouseDoubleClickInterval())
                self.refresh()
                if own_window:
                    event.accept()
                return own_window
        if not own_window:
            # 跨窗释放结束本次观察，但输入仍交还原窗口，不能留下永久的待释放状态。
            if kind == QEvent.Type.MouseButtonPress and self._pressed is None:
                self.reset()
            return False
        if kind == QEvent.Type.MouseButtonPress:
            if self._pressed is not None and identity[1:] != self._pressed[1:]:
                return False
            # 普通 Press 是新的意图，即使紧接在上次关闭之后也不能被旧双击窗口吞掉。
            self._pressed = None
            self._double = None
            self._context_position = None
            self._double_timer.stop()
        elif kind == QEvent.Type.MouseButtonDblClick and self._double is not None:
            previous, position = self._double
            delta = event.globalPosition() - position
            distance = QApplication.styleHints().mouseDoubleClickDistance()
            if (identity == previous and self._double_clock.elapsed() <= self._double_interval
                    and delta.x() ** 2 + delta.y() ** 2 <= distance ** 2):
                self._pressed = identity
                self._double = None
                self._double_timer.stop()
                event.accept()
                return True
        elif kind == QEvent.Type.MouseMove and self._pressed is not None:
            button, source, device = self._pressed
            if (event.buttons() & button and event.source() == source
                    and event.pointingDevice() is device):
                event.accept()
                return True
        if kind != QEvent.Type.MouseButtonPress or not self._owner.drawer.opened:
            self.refresh()
            return False
        drawer = self._owner.drawer
        if (QApplication.activeModalWidget() is not None
                or QApplication.activePopupWidget() is not None
                or self._belongs_to(watched, drawer)
                or drawer.rect().contains(drawer.mapFromGlobal(event.globalPosition().toPoint()))
                or event.buttons() != event.button()
                or not any(scope is not None and isValid(scope)
                           and self._belongs_to(watched, scope)
                           for reference in self._scopes if (scope := reference()) is not None)):
            return False
        self._pressed = identity
        self._double = identity, event.globalPosition()
        self._context_position = (
            event.globalPosition() if event.button() == Qt.MouseButton.RightButton else None
        )
        self._double_interval = QApplication.styleHints().mouseDoubleClickInterval()
        self._double_clock.start()
        self._double_timer.start(self._double_interval)
        self._owner.dismiss()
        event.accept()
        return True


class TaskFeedbackCoordinator(QObject):
    """由主窗口拥有；自动提示不抢阅读目标，关闭意图立即屏蔽同任务晚到提示。"""

    def __init__(
        self,
        page: TaskCenterPage,
        surface: QWidget,
        *,
        navigation_parent: QWidget | None = None,
        show_task_center: Callable[[], None],
        open_source: Callable[[str], None],
        is_task_center: Callable[[], bool],
        parent: QWidget | None = None,
        session_registry: SessionTaskRegistry | None = None,
        open_session_source: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__(parent or surface)
        self.page = page
        self._closed = False
        self.drawer = TaskDetailDrawer(surface)
        self.drawer.set_content(page.reader_for_drawer(interaction_guard=self._reader_interaction_allowed))
        self.navigation_button = TaskNavigationButton(navigation_parent or surface)
        self._show_task_center = show_task_center
        self._open_source = open_source
        self._is_task_center = is_task_center
        self._sessions = session_registry
        self._open_session_source = open_session_source
        self._automatic = False
        self._origin: QWidget | None = None
        self._dismissed: set[str] = set()
        self._window_ref = weakref.ref(surface.window())
        self._outside = _OutsideDismissObserver(self, surface, navigation_parent or surface)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(POLL_INTERVAL_MS)
        self.refresh_timer.timeout.connect(self._refresh_hidden_page)
        page.session_stop_requested.connect(self._stop_session)
        page.detail_requested.connect(self._on_detail_requested)
        page.detail_changed.connect(self._on_detail_changed)
        page.detail_closed.connect(self._on_page_detail_closed)
        page.navigation_snapshot_changed.connect(self.navigation_button.set_snapshot)
        self.drawer.task_requested.connect(self.open_entry)
        self.drawer.cancel_requested.connect(page.cancel_entry)
        self.drawer.stop_requested.connect(page.request_session_stop)
        self.drawer.source_requested.connect(self._return_to_source)
        self.drawer.locate_requested.connect(self._locate_in_task_center)
        self.drawer.opened_changed.connect(self._on_opened_changed)
        self.drawer.closed.connect(self._on_drawer_closed)
        self.navigation_button.set_snapshot(page.navigation_snapshot())
        window = self._window_ref()
        if window is not None:
            window.installEventFilter(self)
            self.navigation_button.set_presentation_enabled(
                window.isVisible() and not window.isMinimized(),
            )
            if window.isVisible() and not window.isMinimized():
                self.refresh_timer.start()

    def _reader_interaction_allowed(self) -> bool:
        """阅读保护延续到末帧，但新的用户动作只在当前正文实际打开时允许。"""
        return (not self._closed and self.drawer.accepts_user_actions()
                and self.page.selected_key == self.drawer.selected_key)

    def open_request(
        self, request_id: str, *, automatic: bool = False, origin: QWidget | None = None,
    ) -> bool:
        """按提交时请求定位；不导航、不重新读取表单，也不执行或改向设备。"""
        return self.open_entry(f"action:{request_id}", automatic=automatic, origin=origin)

    def open_entry(
        self, key: str, *, automatic: bool = False, origin: QWidget | None = None,
    ) -> bool:
        """显式查看消费已读；自动打开不抢其他任务或把可见误当作用户已经查看。"""
        if self._closed or not isValid(self.page):
            return False
        if automatic:
            window = self._window_ref()
            if (
                not self.page.allows_automatic_details(key)
                or key in self._dismissed
                or window is None or not isValid(window)
                or not window.isVisible() or window.isMinimized()
                or self.drawer.opened and self.drawer.selected_key != key
            ):
                return False
        else:
            self._dismissed.discard(key)
        self._automatic = automatic
        self._origin = None if automatic else origin or QApplication.focusWidget()
        try:
            return self.page.select_entry(key, clear_filters=not automatic, mark_read=not automatic)
        finally:
            self._automatic = False
            self._origin = None

    def _present(self, key: str) -> bool:
        row = self.page.detail_row(key)
        if row is None:
            return False
        source = self.page.detail_source(key)
        source_label = _SOURCE_LABELS.get(source, _SOURCE_LABELS.get(source.split(".")[0], ""))
        self.drawer.present(
            row,
            source_label=tr(source_label) if source_label else "",
            archived=row.scope == tr("已归档"),
        )
        return True

    def _on_detail_requested(self, key: str) -> None:
        if self._closed or not self._present(key):
            return
        origin = None if self._automatic else self._origin or QApplication.focusWidget()
        if origin is None and not self._automatic and self._is_task_center():
            row = self.page.table.rows.get(key)
            if row is not None and row.title.isVisible():
                # AX 激活不保证 Qt 已移焦；以实际行入口归还键盘位置。
                origin = row.title
        self.drawer.open_drawer(origin)

    def _on_detail_changed(self, key: str) -> None:
        if not self._closed and key == self.drawer.selected_key:
            self._present(key)

    def _on_opened_changed(self, opened: bool) -> None:
        # 新呈现前同样清除关闭期间被拒绝、却已进入原生动画的输入。
        self.page.revoke_reader_interactions()
        self._outside.refresh()
        if not self._closed and not opened and self.drawer.selected_key:
            self._dismissed.add(self.drawer.selected_key)

    def _on_drawer_closed(self) -> None:
        # 阅读器保留到最后一个动画帧，快速反向不能清掉新选择的正文。
        if (not self._closed and not self.drawer.opened
                and self.page.selected_key == self.drawer.selected_key):
            self.page.close_detail()

    def _on_page_detail_closed(self) -> None:
        if not self._closed:
            self.drawer.close_drawer()

    def dismiss(self, *_args) -> None:
        """切页或用户收起只结束呈现；任务、停止屏障和结果存储均保持原归属。"""
        if not self._closed:
            self.drawer.close_drawer()

    def _return_to_source(self, key: str) -> None:
        if self._closed:
            return
        if key.startswith("session:"):
            if self._open_session_source is not None and self._open_session_source(key):
                self.dismiss()
            return
        source = self.page.detail_source(key)
        if source:
            self.dismiss()
            self._open_source(source)

    def _locate_in_task_center(self, key: str) -> None:
        if not self._closed:
            self._show_task_center()
            self.open_entry(key)

    def _refresh_hidden_page(self) -> None:
        """隐藏页继续读取内存快照；可见页已有自己的轮询，不重复渲染或发设备命令。"""
        if self._closed:
            return
        if self._sessions is not None:
            self.page.set_session_snapshots(self._sessions.collect())
        if not self.page.isVisible():
            self.page.refresh()
        retained = {row.key for row in self.page.recent_rows()}
        self._dismissed.intersection_update(retained)

    def _stop_session(self, key: str, revision: str) -> None:
        """停止前由登记表复核原 owner 和运行版本；受理后立即重新读取真实资源状态。"""
        if not self._closed and self._sessions is not None:
            self._sessions.request_stop(key, revision)
            self._refresh_hidden_page()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() not in (
            QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.WindowStateChange,
        ):
            return super().eventFilter(watched, event)
        window = self._window_ref()
        if not self._closed and window is not None and isValid(window) and watched is window:
            if window.isVisible() and not window.isMinimized():
                self._outside.refresh()
                self.page.revoke_reader_interactions()
                # 恢复时先在关门状态消费后台终态，再仅恢复当前活动图标。
                self._refresh_hidden_page()
                self.navigation_button.set_presentation_enabled(True)
                self.refresh_timer.start()
            else:
                self._outside.reset()
                self.navigation_button.set_presentation_enabled(False)
                self.refresh_timer.stop()
                self.drawer.close_drawer(animated=False)
        return super().eventFilter(watched, event)

    def shutdown(self) -> None:
        """在主窗口资源关闭前封闭入口并停止所有呈现时钟，不解释或修改业务终态。"""
        if self._closed:
            return
        self._closed = True
        self._outside.shutdown()
        self.page.revoke_reader_interactions()
        self.refresh_timer.stop()
        if self._sessions is not None:
            self._sessions.shutdown()
        self.navigation_button.shutdown()
        self.drawer.shutdown()
        self._origin = None
        self._dismissed.clear()
