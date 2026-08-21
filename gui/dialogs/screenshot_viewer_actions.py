"""提供截图查看器对话框的剪贴板、文件与右键菜单操作控制器。"""

import os
import sys

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from gui.styles import BaseStyles


class ScreenshotViewerActions:
    """组合进 ScreenshotViewer 的操作控制器，通过 ``self._frame`` 访问对话框。"""

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

    def _flash_status(self, text: str):
        if not self._frame._status_restore_timer.isActive():
            self._frame._status_restore_text = self._frame._info_label.text()
        self._frame._info_label.setText(text)
        self._frame._status_restore_timer.start(1800)

    def _restore_info_status(self) -> None:
        self._frame._info_label.setText(self._frame._status_restore_text)

    def _open_file_location(self):
        from gui.dialogs import screenshot_viewer as _sv

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
        _sv.ProcessRunner().spawn(command)

    def _delete_file(self):
        path = self._frame._current_path()
        if not path or not os.path.exists(path):
            return
        try:
            os.remove(path)
        except OSError as exc:
            QMessageBox.warning(
                self._frame,
                "Delete Failed",
                str(exc),
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        del self._frame._image_paths[self._frame._current_idx]
        if not self._frame._image_paths:
            self._frame.close()
            return
        self._frame._rebuild_thumbnails()
        self._frame._current_idx = min(
            self._frame._current_idx, len(self._frame._image_paths) - 1
        )
        self._frame._navigate_to(self._frame._current_idx)

    def _on_context_menu(self, pos):
        path = self._frame._current_path()
        has_file = bool(path and os.path.exists(path))
        menu = QMenu(self._frame)
        menu.setStyleSheet(BaseStyles.MENU_STYLE())

        copy_action = menu.addAction("Copy Image\tCtrl+C")
        copy_action.triggered.connect(self._frame.copy_to_clipboard)
        copy_action.setEnabled(has_file)

        menu.addSeparator()

        folder_action = menu.addAction("Open File Location")
        folder_action.triggered.connect(self._frame._open_file_location)
        folder_action.setEnabled(has_file)

        delete_action = menu.addAction("Delete Screenshot")
        delete_action.triggered.connect(self._frame._delete_file)
        delete_action.setEnabled(has_file)

        menu.addSeparator()

        menu.addAction("Zoom In\tCtrl+=").triggered.connect(self._frame.zoom_in)
        menu.addAction("Zoom Out\tCtrl+-").triggered.connect(self._frame.zoom_out)
        menu.addAction("Fit to Window\tCtrl+0").triggered.connect(self._frame._reset_zoom)
        menu.addAction("Actual Size\tCtrl+1").triggered.connect(self._frame._actual_size)

        menu.exec(self._frame._view.mapToGlobal(pos))
