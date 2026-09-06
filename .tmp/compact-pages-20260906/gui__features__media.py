"""提供可嵌入主窗口的截图浏览页面。"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QListWidgetItem,
    QWidget,
)
from qfluentwidgets import TransparentToolButton

from gui.dialogs.screenshot_viewer_actions import ScreenshotViewerActions
from gui.dialogs.screenshot_viewer_nav import ScreenshotViewerNav
from gui.dialogs.screenshot_viewer_ui import ScreenshotViewerUI
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

    DELETE_CONFIRM_TIMEOUT_MS = 4000
    _scene: QGraphicsScene

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
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._icon_buttons: list[TransparentToolButton] = []
        self._reflowing_bottom_bar = False
        self._bottom_bar_plan_fingerprint: tuple[object, ...] | None = None
        self._active = False
        self._disposed = False
        self._style_signals_connected = False
        self._pending_delete_path = ""

        self._init_page()
        self._init_shortcuts()
        self._init_ui()
        self._status_restore_text = ""
        self._status_restore_timer = QTimer(self)
        self._status_restore_timer.setSingleShot(True)
        self._status_restore_timer.timeout.connect(self._restore_info_status)
        self._fit_resize_timer = QTimer(self)
        self._fit_resize_timer.setSingleShot(True)
        self._fit_resize_timer.timeout.connect(self._apply_fit)
        self._bottom_bar_reflow_timer = QTimer(self)
        self._bottom_bar_reflow_timer.setSingleShot(True)
        self._bottom_bar_reflow_timer.timeout.connect(self._reflow_bottom_bar)
        self._delete_confirm_timer = QTimer(self)
        self._delete_confirm_timer.setSingleShot(True)
        self._delete_confirm_timer.timeout.connect(self._reset_delete_confirmation)
        self._apply_theme()
        self._rebuild_thumbnails()

        if self._image_paths:
            self._navigate_to(self._current_idx)
        else:
            self._show_placeholder("No screenshot available")
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

    def receive_payload(self, payload=None) -> None:
        """接收后台完成的截图批次，不要求页面当前位于前台。"""

        if self._disposed:
            return
        previous_count = len(self._image_paths)
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
            self._rebuild_thumbnails()
            target_index = first_added_index if focus_new else self._current_idx
            if explicit_index is not None:
                target_index = max(0, min(explicit_index, len(self._image_paths) - 1))
            self._navigate_to(target_index)
        elif self._image_paths:
            self._navigate_to(self._current_idx)
        else:
            self._show_placeholder("No screenshot available")
        if len(self._image_paths) != previous_count:
            self.image_count_changed.emit(len(self._image_paths))
        self._apply_theme()
        self._schedule_bottom_bar_reflow()

    def deactivate(self, reason: str = "navigation") -> None:
        """暂停瞬态 UI 工作；截图列表保留供同一会话再次激活。"""

        self._active = False
        self.setProperty("deactivation_reason", reason)
        self._status_restore_timer.stop()
        self._fit_resize_timer.stop()
        self._bottom_bar_reflow_timer.stop()
        self._reset_delete_confirmation()

    def request_dispose(self, reason: str = "user") -> bool:
        """同步释放页面资源；返回 ``True`` 表示宿主可立即移除页面。"""

        if self._disposed:
            return True
        self.deactivate(reason)
        self._disposed = True
        self._disconnect_style_signals()
        self._scene.clear()
        self._placeholder_text = None
        self._original_pixmap = None
        self._pixmap_item = None
        self._image_paths.clear()
        self.image_count_changed.emit(0)
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

    # ── 主题与界面控制器委托 wrapper ──────────────────────────────────────

    def _init_page(self):
        return (getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self))._init_page()

    def _init_shortcuts(self):
        return (
            getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self)
        )._init_shortcuts()

    @staticmethod
    def _theme_color(key: str) -> str:
        return ScreenshotViewerUI._theme_color(key)

    def _apply_theme(self, _value=None):
        return (
            getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self)
        )._apply_theme(_value)

    def _init_ui(self):
        return (getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self))._init_ui()

    def _build_canvas(self) -> QFrame:
        return (
            getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self)
        )._build_canvas()

    def _build_bottom_dock(self) -> QFrame:
        return (
            getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self)
        )._build_bottom_dock()

    def _build_bottom_bar(self) -> QFrame:
        return (
            getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self)
        )._build_bottom_bar()

    @staticmethod
    def _bottom_bar_group(object_name: str) -> QFrame:
        return ScreenshotViewerUI._bottom_bar_group(object_name)

    @staticmethod
    def _group_minimum_size(group: QFrame) -> QSize:
        return ScreenshotViewerUI._group_minimum_size(group)

    def _reflow_bottom_bar(self) -> None:
        return (
            getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self)
        )._reflow_bottom_bar()

    def _schedule_bottom_bar_reflow(self) -> None:
        return (
            getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self)
        )._schedule_bottom_bar_reflow()

    def _tool_button(self, icon_name: str, tooltip: str) -> TransparentToolButton:
        return (
            getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self)
        )._tool_button(icon_name, tooltip)

    def _refresh_button_icons(self):
        return (
            getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self)
        )._refresh_button_icons()

    # ── 导航/缩放控制器委托 wrapper ───────────────────────────────────────

    def _current_path(self) -> str:
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._current_path()

    def _navigate_to(self, index: int):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._navigate_to(index)

    def _show_pixmap(self, pixmap: QPixmap):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._show_pixmap(pixmap)

    def _show_placeholder(self, text: str):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._show_placeholder(text)

    def _refresh_placeholder_color(self):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._refresh_placeholder_color()

    def _rebuild_thumbnails(self):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._rebuild_thumbnails()

    def _thumbnail_icon(self, path: str) -> QIcon:
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._thumbnail_icon(path)

    def _on_thumbnail_clicked(self, item: QListWidgetItem):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._on_thumbnail_clicked(item)

    def _sync_thumbnail_selection(self):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._sync_thumbnail_selection()

    def navigate_prev(self):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        ).navigate_prev()

    def navigate_next(self):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        ).navigate_next()

    def _apply_fit(self):
        return (getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self))._apply_fit()

    def _set_zoom(self, factor: float, *, fit: bool = False, anchor_under_mouse: bool = False):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._set_zoom(factor, fit=fit, anchor_under_mouse=anchor_under_mouse)

    def _zoom_from_wheel(self, delta: int):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._zoom_from_wheel(delta)

    def zoom_in(self):
        return (getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)).zoom_in()

    def zoom_out(self):
        return (getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)).zoom_out()

    def _reset_zoom(self):
        return (getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self))._reset_zoom()

    def _actual_size(self):
        return (getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self))._actual_size()

    def toggle_fit_actual(self):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        ).toggle_fit_actual()

    def _update_zoom_label(self):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._update_zoom_label()

    def _update_info(self):
        return (getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self))._update_info()

    @staticmethod
    def _format_size(path: str) -> str:
        return ScreenshotViewerNav._format_size(path)

    @staticmethod
    def _format_modified_time(path: str) -> str:
        return ScreenshotViewerNav._format_modified_time(path)

    def _update_nav_visibility(self):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._update_nav_visibility()

    def _update_nav_label(self):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._update_nav_label()

    def _update_actions_enabled(self, enabled: bool):
        return (
            getattr(self, "_nav_controller", None) or ScreenshotViewerNav(self)
        )._update_actions_enabled(enabled)

    # ── 操作控制器委托 wrapper ─────────────────────────────────────────────

    def copy_to_clipboard(self):
        return (
            getattr(self, "_actions_controller", None) or ScreenshotViewerActions(self)
        ).copy_to_clipboard()

    def _flash_status(self, text: str, timeout_ms: int = 1800):
        return (
            getattr(self, "_actions_controller", None) or ScreenshotViewerActions(self)
        )._flash_status(text, timeout_ms)

    def _restore_info_status(self) -> None:
        return (
            getattr(self, "_actions_controller", None) or ScreenshotViewerActions(self)
        )._restore_info_status()

    def _open_file_location(self):
        return (
            getattr(self, "_actions_controller", None) or ScreenshotViewerActions(self)
        )._open_file_location()

    def _delete_file(self):
        return (
            getattr(self, "_actions_controller", None) or ScreenshotViewerActions(self)
        )._delete_file()

    def _reset_delete_confirmation(self) -> None:
        return (
            getattr(self, "_actions_controller", None) or ScreenshotViewerActions(self)
        )._reset_delete_confirmation()

    def _on_context_menu(self, pos):
        return (
            getattr(self, "_actions_controller", None) or ScreenshotViewerActions(self)
        )._on_context_menu(pos)

    # ── 生命周期与事件 ─────────────────────────────────────────────────────

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
        if hasattr(self, "_bottom_bar"):
            self._schedule_bottom_bar_reflow()
        if getattr(self, "_fit_to_window", False):
            self._fit_resize_timer.start(0)

__all__ = ["ScreenshotPage"]
