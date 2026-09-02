"""提供截图浏览、缩放、复制和文件管理对话框。"""

from __future__ import annotations

import os  # noqa: F401  供测试通过本模块命名空间补丁。

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsPixmapItem,
    QListWidgetItem,
)
from qfluentwidgets import TransparentToolButton

from core.exec import ProcessRunner  # noqa: F401  供测试通过本模块命名空间补丁。
from gui.dialogs.screenshot_viewer_actions import ScreenshotViewerActions
from gui.dialogs.screenshot_viewer_nav import ScreenshotViewerNav
from gui.dialogs.screenshot_viewer_ui import ScreenshotViewerUI
from gui.dialogs.screenshot_viewer_widgets import (  # noqa: F401  供按名导入。
    ScreenshotBottomBar,
    ScreenshotGraphicsView,
)
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon  # noqa: F401  供测试通过本模块命名空间补丁。


class ScreenshotViewer(QDialog):
    """浏览截图批次，并管理当前图片的显示和文件操作。"""

    def __init__(self, image_paths: list, current_index: int = 0, parent=None):
        super().__init__(parent)
        self._ui_controller = ScreenshotViewerUI(self)
        self._nav_controller = ScreenshotViewerNav(self)
        self._actions_controller = ScreenshotViewerActions(self)
        self._image_paths = list(image_paths) if image_paths else []
        self._current_idx = (
            max(0, min(current_index, len(self._image_paths) - 1)) if self._image_paths else 0
        )
        self._zoom_factor = 1.0
        self._fit_to_window = True
        self._original_pixmap: QPixmap | None = None
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._window_icon_name = "camera.svg"
        self._icon_buttons: list[TransparentToolButton] = []
        self._reflowing_bottom_bar = False
        self._bottom_bar_plan_fingerprint: tuple[object, ...] | None = None

        self._init_window()
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
        self._apply_theme()
        self._rebuild_thumbnails()

        if self._image_paths:
            self._navigate_to(self._current_idx)
        else:
            self._show_placeholder("No screenshot available")
        self._update_nav_visibility()

        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)

    # ── 主题与界面控制器委托 wrapper ──────────────────────────────────────

    def _init_window(self):
        return (getattr(self, "_ui_controller", None) or ScreenshotViewerUI(self))._init_window()

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

    def _flash_status(self, text: str):
        return (
            getattr(self, "_actions_controller", None) or ScreenshotViewerActions(self)
        )._flash_status(text)

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

    def _on_context_menu(self, pos):
        return (
            getattr(self, "_actions_controller", None) or ScreenshotViewerActions(self)
        )._on_context_menu(pos)

    # ── 生命周期与事件 ─────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._status_restore_timer.stop()
        self._fit_resize_timer.stop()
        self._bottom_bar_reflow_timer.stop()
        try:
            BaseStyles.theme_changed.disconnect(self._apply_theme)
        except (TypeError, RuntimeError):
            pass
        try:
            BaseStyles.fonts_changed.disconnect(self._apply_theme)
        except (TypeError, RuntimeError):
            pass
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
