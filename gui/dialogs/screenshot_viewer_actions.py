"""提供截图页面的剪贴板、文件与右键菜单操作控制器。"""

import os
import sys

from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication, QFileDialog
from qfluentwidgets import RoundMenu
from shiboken6 import isValid

from core.exec import ProcessRunner
from gui.i18n import tr
from gui.notifications import ToastLevel, show_toast
from gui.styles import BaseStyles, FontRole


class ScreenshotViewerActions:
    """组合进 ScreenshotPage 的操作控制器。"""

    def __init__(self, frame):
        self._frame = frame
        self._image_dialog_open = False

    def _add_images(self) -> None:
        """本地多选只追加可解码图片；弹窗取消、重入或页面释放后不再改变会话。"""

        frame = self._frame
        if self._image_dialog_open or frame._disposed or not isValid(frame):
            return
        self._image_dialog_open = True
        frame._add_action.setEnabled(False)
        try:
            paths, _selected_filter = QFileDialog.getOpenFileNames(
                frame,
                tr("Add images"),
                os.path.dirname(frame._current_path()),
                tr("Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff);;All files (*)"),
            )
            if not isValid(frame) or frame._disposed or not paths:
                return
            accepted = [
                path for path in paths if os.path.isfile(path) and QImageReader(path).canRead()
            ]
            if accepted:
                frame.receive_payload({"paths": accepted, "focus_new": True})
            if len(accepted) != len(paths):
                self._flash_status(
                    tr("Some selected files could not be opened as images"), level="warning"
                )
        finally:
            self._image_dialog_open = False
            if isValid(frame) and not frame._disposed:
                frame._add_action.setEnabled(True)

    def _rotate_image(self) -> None:
        """旋转只影响当前预览与复制方向，原始文件保持不变。"""

        if not self._frame._disposed:
            self._frame._nav_controller._rotate_image()

    def _show_image_info(self) -> None:
        """信息动作在命令栏和更多菜单中共享勾选状态，不替换当前图片。"""

        if self._frame._disposed:
            return
        self._frame._info_label.setVisible(self._frame._info_action.isChecked())
        self._frame._schedule_metadata_reflow()

    def copy_to_clipboard(self):
        """复制当前浏览方向的完整图像，不使用降采样后的翻页预览。"""

        if self._frame._disposed:
            return
        path = self._frame._current_path()
        if not path:
            return
        pixmap = self._frame._display_pixmap
        if pixmap is not None and not pixmap.isNull():
            QApplication.clipboard().setPixmap(pixmap)
            self._flash_status(tr("Image copied"), level="success")

    def _flash_status(
        self, text: str, timeout_ms: int | None = None, *, level: ToastLevel = "info",
    ):
        """完整反馈交给窗口 Toast，图片详情始终保留当前截图元数据。"""

        return show_toast(
            self._frame, tr("截图"), text, level=level, duration=timeout_ms,
        )

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
        """单次触发删除当前截图文件；失败保留图片，成功后同步图库和圆点分页。"""

        if self._frame._disposed:
            return
        path = self._frame._current_path()
        if not path or not os.path.exists(path):
            return
        try:
            os.remove(path)
        except OSError as exc:
            show_toast(
                self._frame,
                tr("Delete Failed"),
                str(exc),
                level="error",
            )
            return
        del self._frame._image_paths[self._frame._current_idx]
        self._frame._current_idx = max(
            0, min(self._frame._current_idx, len(self._frame._image_paths) - 1)
        )
        self._frame._rebuild_images()
        if not self._frame._image_paths:
            self._frame._show_placeholder(tr("No screenshot available"))
        else:
            self._frame._navigate_to(self._frame._current_idx)
        self._frame._notify_image_count()
        self._frame._apply_theme()

    def _on_context_menu(self, pos):
        """上下文菜单复用同一批 Action，不额外连接回调或产生独立启用状态。"""

        if self._frame._disposed:
            return
        menu = RoundMenu(parent=self._frame)
        menu.setFont(BaseStyles.font_for_role(FontRole.UI))
        menu.addAction(self._frame._copy_action)
        menu.addAction(self._frame._folder_action)
        menu.addSeparator()
        menu.addAction(self._frame._rotate_action)
        menu.addAction(self._frame._zoom_in_action)
        menu.addAction(self._frame._zoom_out_action)
        menu.addAction(self._frame._fit_action)
        menu.addAction(self._frame._actual_action)
        menu.addSeparator()
        menu.addAction(self._frame._delete_action)
        menu.exec(self._frame._view.viewport().mapToGlobal(pos))
