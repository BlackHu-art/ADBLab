"""提供可嵌入主窗口的截图浏览页面。"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap, QWheelEvent
from PySide6.QtWidgets import QBoxLayout, QWidget
from qfluentwidgets import HeaderCardWidget
from shiboken6 import isValid

from gui.dialogs.screenshot_viewer_actions import ScreenshotViewerActions
from gui.dialogs.screenshot_viewer_nav import ScreenshotViewerNav
from gui.dialogs.screenshot_viewer_ui import ScreenshotViewerUI
from gui.dialogs.screenshot_viewer_widgets import ScreenshotFlipView, ScreenshotPipsPager
from gui.i18n import tr
from gui.notifications import ToastLevel
from gui.styles import BaseStyles


class ScreenshotPage(QWidget):
    """浏览截图批次，并遵循 Workspace 功能页的同步生命周期契约。

    页面不拥有线程或外部进程；``request_dispose`` 因此可同步完成。
    ``activate`` 只增量追加新批次且默认聚焦首张新增截图，导航离开不会
    丢弃已加载结果。
    """

    dispose_ready = Signal(object)
    back_requested = Signal()
    image_count_changed = Signal(int)

    _view: ScreenshotFlipView
    _pager: ScreenshotPipsPager

    def __init__(
        self,
        image_paths: Iterable[str | os.PathLike[str]] | None = None,
        current_index: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ui_controller = ScreenshotViewerUI(self)
        self._nav_controller = ScreenshotViewerNav(self)
        self._actions_controller = ScreenshotViewerActions(self)
        self._image_paths = self._normalize_paths(image_paths)
        self._current_idx = (
            max(0, min(current_index, len(self._image_paths) - 1)) if self._image_paths else 0
        )
        self._zoom_factor = 1.0
        self._fit_to_window = True
        self._original_pixmap: QPixmap | None = None
        self._display_pixmap: QPixmap | None = None
        self._display_path = ""
        self._rotation_by_path: dict[str, int] = {}
        self._reported_image_count = 0
        self._active = False
        self._disposed = False
        self._style_signals_connected = False
        self._device_tools: QWidget | None = None
        self._device_tools_parking: QWidget | None = None
        self._device_tools_header_was_hidden = False

        self._init_page()
        self._init_shortcuts()
        self._init_ui()
        self._fit_resize_timer = QTimer(self)
        self._fit_resize_timer.setSingleShot(True)
        self._fit_resize_timer.timeout.connect(self._apply_fit)
        self._metadata_reflow_timer = QTimer(self)
        self._metadata_reflow_timer.setSingleShot(True)
        self._metadata_reflow_timer.timeout.connect(self._refresh_metadata)
        self._apply_theme()
        self._rebuild_images()

        if self._image_paths:
            self._navigate_to(self._current_idx)
        else:
            self._show_placeholder(tr("No screenshot available"))
        self._update_nav_visibility()
        self._apply_theme()
        self._connect_style_signals()

    @staticmethod
    def _normalize_paths(
        values: Iterable[str | os.PathLike[str]] | None,
    ) -> list[str]:
        """规范化路径并按绝对路径去重，同时保留输入顺序。"""

        if values is None:
            return []
        if isinstance(values, (str, os.PathLike)):
            values = (values,)
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            try:
                path = os.fspath(value).strip()
            except (TypeError, AttributeError):
                continue
            if not path:
                continue
            identity = os.path.normcase(os.path.abspath(path))
            if identity in seen:
                continue
            seen.add(identity)
            normalized.append(path)
        return normalized

    @classmethod
    def _paths_from_payload(cls, payload) -> tuple[list[str], int | None, bool]:
        """接受路径列表或路由字典，并返回路径、显式索引和聚焦策略。"""

        current_index: int | None = None
        focus_new = True
        values = payload
        if isinstance(payload, Mapping):
            values = payload.get("image_paths", payload.get("paths", payload.get("path")))
            raw_index = payload.get("current_index")
            if isinstance(raw_index, int) and not isinstance(raw_index, bool):
                current_index = raw_index
            focus_new = bool(payload.get("focus_new", True))
        if values is None:
            return [], current_index, focus_new
        if isinstance(values, (str, os.PathLike)):
            values = (values,)
        try:
            paths = cls._normalize_paths(values)
        except TypeError:
            paths = []
        return paths, current_index, focus_new

    def activate(self, payload=None) -> None:
        """激活页面并把一次新截图批次追加到现有会话。"""

        if self._disposed:
            return
        self._active = True
        self.receive_payload(payload)

    def prepare_for_workspace(self) -> None:
        """复用工作区页头，只调整呈现并保留截图与导航状态。"""

        self._ui_controller.prepare_for_workspace()

    def set_device_tools(self, tools: QWidget, parking: QWidget) -> None:
        """借用现有设备操作控件；清除截图时归还宿主，不重建信号或录屏状态。"""

        if self._disposed or self._device_tools is tools:
            return
        self._release_device_tools()
        self._device_tools = tools
        self._device_tools_parking = parking
        if isinstance(tools, HeaderCardWidget):
            self._device_tools_header_was_hidden = tools.headerView.isHidden()
            tools.headerView.hide()
        layout = self.layout()
        assert isinstance(layout, QBoxLayout)
        layout.insertWidget(1, tools)
        self._view.setMinimumHeight(160)
        self._view.viewport().installEventFilter(self)
        tools.show()

    def heightForWidth(self, width: int) -> int:
        """工具行按宽度换行，画布按剩余空间伸展，不用图像自然高度撑大宿主。"""

        layout = self.layout()
        if self._device_tools is not None and isinstance(layout, QBoxLayout):
            return layout.minimumHeightForWidth(width)
        return super().heightForWidth(width)

    def _release_device_tools(self) -> None:
        """截图页不拥有设备操作生命周期，销毁前将原控件移回隐藏宿主。"""

        tools, parking = self._device_tools, self._device_tools_parking
        self._device_tools = self._device_tools_parking = None
        if tools is not None and parking is not None and isValid(tools) and isValid(parking):
            tools.hide()
            if isinstance(tools, HeaderCardWidget):
                tools.headerView.setVisible(not self._device_tools_header_was_hidden)
            tools.setParent(parking)

    def receive_payload(self, payload=None) -> None:
        """接收后台完成的截图批次，不要求页面当前位于前台。"""

        if self._disposed:
            return
        incoming, explicit_index, focus_new = self._paths_from_payload(payload)
        existing = {
            os.path.normcase(os.path.abspath(path)) for path in self._image_paths
        }
        first_added_index: int | None = None
        for path in incoming:
            identity = os.path.normcase(os.path.abspath(path))
            if identity in existing:
                continue
            if first_added_index is None:
                first_added_index = len(self._image_paths)
            self._image_paths.append(path)
            existing.add(identity)

        if first_added_index is not None:
            self._rebuild_images()
            target_index = first_added_index if focus_new else self._current_idx
            if explicit_index is not None:
                target_index = max(0, min(explicit_index, len(self._image_paths) - 1))
            self._navigate_to(target_index)
        elif self._image_paths:
            self._navigate_to(self._current_idx)
        else:
            self._show_placeholder(tr("No screenshot available"))
        self._notify_image_count()
        self._apply_theme()
        self._schedule_metadata_reflow()

    def deactivate(self, reason: str = "navigation") -> None:
        """暂停瞬态 UI 工作；截图列表保留供同一会话再次激活。"""

        self._active = False
        self.setProperty("deactivation_reason", reason)
        self._fit_resize_timer.stop()
        self._metadata_reflow_timer.stop()
        self._view.stop_animations()
        self._pager.stop_animations()

    def request_dispose(self, reason: str = "user") -> bool:
        """同步释放页面资源；返回 ``True`` 表示宿主可立即移除页面。"""

        if self._disposed:
            return True
        self.deactivate(reason)
        self._disposed = True
        self._release_device_tools()
        self._disconnect_style_signals()
        self._original_pixmap = self._display_pixmap = None
        self._display_path = ""
        self._image_paths.clear()
        self._rotation_by_path.clear()
        self._view.clear()
        self._pager.clear()
        self._update_actions_enabled(False)
        self._notify_image_count()
        return True

    def register_shutdown_tasks(
        self,
        supervisor,
        *,
        owner_id: str,
        task_prefix: str,
    ) -> tuple[str, ...]:
        """截图页没有后台资源，因此无需向关闭协调器注册任务。"""

        return ()

    @property
    def is_disposed(self) -> bool:
        return self._disposed

    @property
    def image_paths(self) -> tuple[str, ...]:
        """返回当前批次快照，避免调用方依赖页面内部可变列表。"""

        return tuple(self._image_paths)

    def _connect_style_signals(self) -> None:
        if self._style_signals_connected:
            return
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)
        self._style_signals_connected = True

    def _disconnect_style_signals(self) -> None:
        if not self._style_signals_connected:
            return
        for signal in (BaseStyles.theme_changed, BaseStyles.fonts_changed):
            try:
                signal.disconnect(self._apply_theme)
            except (TypeError, RuntimeError):
                pass
        self._style_signals_connected = False

    def _notify_image_count(self) -> None:
        """每次实际数量变化只通知一次，批次过滤和删除共用此边界。"""

        count = len(self._image_paths)
        if count != self._reported_image_count:
            self._reported_image_count = count
            if not self._disposed:
                self._apply_theme()
            self.image_count_changed.emit(count)

    def _schedule_fit(self) -> None:
        """工具换行也会改变画布，适应模式在事件循环收敛后重新计算比例。"""

        timer = getattr(self, "_fit_resize_timer", None)
        if timer is not None and not self._disposed and self._fit_to_window:
            timer.start(0)

    def _init_page(self):
        return self._ui_controller._init_page()

    def _init_shortcuts(self):
        return self._ui_controller._init_shortcuts()

    def _init_ui(self):
        return self._ui_controller._init_ui()

    def _apply_theme(self, _value=None):
        return self._ui_controller._apply_theme(_value)

    def _refresh_metadata(self):
        return self._ui_controller._refresh_metadata()

    def _schedule_metadata_reflow(self):
        return self._ui_controller._schedule_metadata_reflow()

    def _current_path(self):
        return self._nav_controller._current_path()

    def _navigate_to(self, index: int):
        return self._nav_controller._navigate_to(index)

    def _show_pixmap(self, pixmap: QPixmap):
        return self._nav_controller._show_pixmap(pixmap)

    def _show_placeholder(self, text: str):
        return self._nav_controller._show_placeholder(text)

    def _rebuild_images(self):
        return self._nav_controller._rebuild_images()

    def _sync_image_selection(self):
        return self._nav_controller._sync_image_selection()

    def navigate_prev(self):
        return self._nav_controller.navigate_prev()

    def navigate_next(self):
        return self._nav_controller.navigate_next()

    def _apply_fit(self):
        return self._nav_controller._apply_fit()

    def _set_zoom(self, factor: float, *, fit: bool = False):
        return self._nav_controller._set_zoom(factor, fit=fit)

    def _zoom_from_wheel(self, delta: int):
        return self._nav_controller._zoom_from_wheel(delta)

    def zoom_in(self):
        return self._nav_controller.zoom_in()

    def zoom_out(self):
        return self._nav_controller.zoom_out()

    def _reset_zoom(self):
        return self._nav_controller._reset_zoom()

    def _actual_size(self):
        return self._nav_controller._actual_size()

    def toggle_fit_actual(self):
        return self._nav_controller.toggle_fit_actual()

    def _update_zoom_label(self):
        return self._nav_controller._update_zoom_label()

    def _update_info(self):
        return self._nav_controller._update_info()

    def _update_nav_visibility(self):
        return self._nav_controller._update_nav_visibility()

    def _update_nav_label(self):
        return self._nav_controller._update_nav_label()

    def _update_actions_enabled(self, enabled: bool):
        return self._nav_controller._update_actions_enabled(enabled)

    def _add_images(self):
        return self._actions_controller._add_images()

    def _rotate_image(self):
        return self._actions_controller._rotate_image()

    def _show_image_info(self):
        return self._actions_controller._show_image_info()

    def copy_to_clipboard(self):
        return self._actions_controller.copy_to_clipboard()

    def _delete_file(self):
        return self._actions_controller._delete_file()

    def _on_context_menu(self, pos):
        return self._actions_controller._on_context_menu(pos)

    def _open_file_location(self):
        return (
            getattr(self, "_actions_controller", None) or ScreenshotViewerActions(self)
        )._open_file_location()

    def _flash_status(
        self, text: str, timeout_ms: int | None = None, *, level: ToastLevel = "info",
    ):
        return self._actions_controller._flash_status(text, timeout_ms, level=level)

    @staticmethod
    def _format_size(path: str) -> str:
        return ScreenshotViewerNav._format_size(path)

    @staticmethod
    def _format_modified_time(path: str) -> str:
        return ScreenshotViewerNav._format_modified_time(path)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and watched is self._view.viewport():
            self._schedule_fit()
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        self.request_dispose("widget_close")
        super().closeEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._zoom_from_wheel(event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_details_bar"):
            self._schedule_metadata_reflow()
        self._schedule_fit()


__all__ = ["ScreenshotPage"]
