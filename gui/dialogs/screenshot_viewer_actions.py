"""提供截图页面的剪贴板、文件与右键菜单操作控制器。"""

import os
import sys

from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication, QFileDialog
from shiboken6 import isValid

from core.exec import ProcessRunner
from gui.dialogs.screenshot_viewer_tasks import ScreenshotDeleteWorker, ScreenshotValidateWorker
from gui.i18n import tr
from gui.notifications import ToastLevel, show_toast
from gui.styles.fluent import create_transient_menu
from gui.widgets.transient_menu import add_shared_menu_action


class ScreenshotViewerActions:
    """组合进 ScreenshotPage 的操作控制器。"""

    def __init__(self, frame):
        self._frame = frame
        self._image_dialog_open = False

    def _add_images(self) -> None:
        """本地多选只追加可解码图片；弹窗取消、重入或页面释放后不再改变会话。"""

        frame = self._frame
        if (self._image_dialog_open or frame._add_worker is not None
                or frame._disposed or frame._disposing or not isValid(frame)):
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
            if not isValid(frame) or frame._disposed or frame._disposing or not paths:
                return
            worker = ScreenshotValidateWorker(tuple(paths), QImageReader, frame)
            frame._add_worker = worker
            frame._start_io_worker(worker)
        finally:
            self._image_dialog_open = False
            if isValid(frame) and not frame._disposed:
                frame._update_nav_visibility()

    def add_finished(self, worker: ScreenshotValidateWorker) -> None:
        """只消费当前校验任务；关闭或取消后释放忙碌状态但不追加晚到结果。"""
        frame = self._frame
        if frame._add_worker is not worker:
            return
        frame._add_worker = None
        if frame._disposed or frame._disposing:
            return
        frame._update_nav_visibility()
        if worker.cancelled:
            return
        if worker.accepted:
            frame.receive_payload({"paths": worker.accepted, "focus_new": True})
        if worker.rejected:
            self._flash_status(
                tr("Some selected files could not be opened as images"), level="warning",
            )

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
        """单张删除与批量删除共享后台快照、取消和结果合并边界。"""
        path = self._frame._current_path()
        if path:
            self._start_delete((path,))

    def _delete_all_files(self):
        """后台删除当前图库快照；忙碌时拒绝重复删除，新到图片不加入旧任务。"""
        self._start_delete(tuple(self._frame._image_paths))

    def _start_delete(self, paths: tuple[str, ...]) -> None:
        """固定删除目标，重复点击不扩大当前批次。"""
        frame = self._frame
        if (frame._disposed or frame._disposing or not paths
                or frame._delete_worker is not None):
            return
        worker = ScreenshotDeleteWorker(
            paths, dict(frame._path_versions), frame,
        )
        frame._delete_worker = worker
        frame._update_nav_visibility()
        frame._start_io_worker(worker)

    def delete_finished(self, worker: ScreenshotDeleteWorker) -> None:
        """仅移除确实删除的快照项，失败与取消剩余项保留在当前图库。"""
        frame = self._frame
        if frame._delete_worker is not worker:
            return
        frame._delete_worker = None
        if frame._disposed or frame._disposing:
            return
        current = frame._current_path()
        deleted = {
            path for path in worker.deleted
            if frame._path_versions.get(path) == worker.versions.get(path)
        }
        frame._image_paths[:] = [path for path in frame._image_paths if path not in deleted]
        for path in deleted:
            frame._nav_controller._cache.remove_path(path)
        frame._current_idx = (
            frame._image_paths.index(current) if current in frame._image_paths
            else min(frame._current_idx, max(0, len(frame._image_paths) - 1))
        )
        frame._rebuild_images()
        frame._navigate_to(frame._current_idx)
        frame._notify_image_count()
        frame._apply_theme()
        if worker.failed:
            if len(worker.paths) == 1:
                show_toast(
                    frame, tr("Delete Failed"), worker.errors[worker.failed[0]], level="error",
                )
            else:
                self._flash_status(
                    tr("Could not delete {value0} image(s)").format(value0=len(worker.failed)),
                    level="error",
                )

    def _on_context_menu(self, pos):
        """临时菜单独占代理，启用状态和触发行为仍由页面动作统一提供。"""

        if self._frame._disposed:
            return
        menu = create_transient_menu(self._frame)
        add_shared_menu_action(menu, self._frame._copy_action)
        add_shared_menu_action(menu, self._frame._folder_action)
        menu.addSeparator()
        add_shared_menu_action(menu, self._frame._rotate_action)
        add_shared_menu_action(menu, self._frame._zoom_in_action)
        add_shared_menu_action(menu, self._frame._zoom_out_action)
        add_shared_menu_action(menu, self._frame._fit_action)
        add_shared_menu_action(menu, self._frame._actual_action)
        menu.addSeparator()
        add_shared_menu_action(menu, self._frame._delete_action)
        menu.exec(self._frame._view.viewport().mapToGlobal(pos))
