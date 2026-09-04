"""提供截图页面的剪贴板、文件与右键菜单操作控制器。"""

import os
import sys

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from qfluentwidgets import RoundMenu

from core.exec import ProcessRunner
from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import add_menu_action


class ScreenshotViewerActions:
    """组合进 ScreenshotPage 的操作控制器。"""

    def __init__(self, frame):
        self._frame = frame

    def copy_to_clipboard(self):
        path = self._frame._current_path()
        if not path:
            return
        pixmap = self._frame._original_pixmap or QPixmap(path)
        if not pixmap.isNull():
            QApplication.clipboard().setPixmap(pixmap)
            self._flash_status("Image copied")

    def _flash_status(self, text: str, timeout_ms: int = 1800):
        if not self._frame._status_restore_timer.isActive():
            self._frame._status_restore_text = self._frame._info_label.text()
        self._frame._info_label.setText(text)
        self._frame._status_restore_timer.start(max(1, int(timeout_ms)))

    def _restore_info_status(self) -> None:
        self._frame._info_label.setText(self._frame._status_restore_text)

    def _open_file_location(self):
        path = self._frame._current_path()
        if not path or not os.path.exists(path):
            return
        folder = os.path.dirname(os.path.abspath(path))
        if os.name == "nt":
            command = ["explorer", folder]
        elif sys.platform == "darwin":
            command = ["open", folder]
        else:
            command = ["xdg-open", folder]
        ProcessRunner().spawn(command)

    def _delete_file(self):
        path = self._frame._current_path()
        if not path or not os.path.exists(path):
            return
        if self._frame._pending_delete_path != path:
            self._reset_delete_confirmation()
            self._frame._pending_delete_path = path
            self._frame._delete_btn.setToolTip("Click again to confirm deletion")
            self._frame._delete_btn.setAccessibleName("Confirm screenshot deletion")
            self._frame._delete_confirm_timer.start(self._frame.DELETE_CONFIRM_TIMEOUT_MS)
            self._flash_status(
                "Click Delete again to confirm",
                self._frame.DELETE_CONFIRM_TIMEOUT_MS,
            )
            return

        self._reset_delete_confirmation()
        self._frame._status_restore_timer.stop()
        try:
            os.remove(path)
        except OSError as exc:
            FluentMessageBox.warning(
                self._frame,
                "Delete Failed",
                str(exc),
            )
            return
        del self._frame._image_paths[self._frame._current_idx]
        self._frame.image_count_changed.emit(len(self._frame._image_paths))
        if not self._frame._image_paths:
            self._frame._current_idx = 0
            self._frame._rebuild_thumbnails()
            self._frame._show_placeholder("No screenshot available")
            self._frame._apply_theme()
            return
        self._frame._rebuild_thumbnails()
        self._frame._current_idx = min(self._frame._current_idx, len(self._frame._image_paths) - 1)
        self._frame._navigate_to(self._frame._current_idx)
        self._frame._apply_theme()

    def _reset_delete_confirmation(self) -> None:
        """撤销尚未二次确认的删除意图，并恢复按钮语义。"""

        self._frame._pending_delete_path = ""
        timer = getattr(self._frame, "_delete_confirm_timer", None)
        if timer is not None:
            timer.stop()
        button = getattr(self._frame, "_delete_btn", None)
        if button is not None:
            button.setToolTip("Delete screenshot")
            button.setAccessibleName("Delete screenshot")

    def _on_context_menu(self, pos):
        path = self._frame._current_path()
        has_file = bool(path and os.path.exists(path))
        menu = RoundMenu(parent=self._frame)
        menu.setFont(BaseStyles.font_for_role(FontRole.UI))

        copy_action = add_menu_action(menu, "Copy Image\tCtrl+C")
        copy_action.triggered.connect(self._frame.copy_to_clipboard)
        copy_action.setEnabled(has_file)

        menu.addSeparator()

        folder_action = add_menu_action(menu, "Open File Location")
        folder_action.triggered.connect(self._frame._open_file_location)
        folder_action.setEnabled(has_file)

        delete_action = add_menu_action(menu, "Delete Screenshot")
        delete_action.triggered.connect(self._frame._delete_file)
        delete_action.setEnabled(has_file)

        menu.addSeparator()

        add_menu_action(menu, "Zoom In\tCtrl+=").triggered.connect(self._frame.zoom_in)
        add_menu_action(menu, "Zoom Out\tCtrl+-").triggered.connect(self._frame.zoom_out)
        add_menu_action(menu, "Fit to Window\tCtrl+0").triggered.connect(self._frame._reset_zoom)
        add_menu_action(menu, "Actual Size\tCtrl+1").triggered.connect(self._frame._actual_size)

        menu.exec(self._frame._view.mapToGlobal(pos))
