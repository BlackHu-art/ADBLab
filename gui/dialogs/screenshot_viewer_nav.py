"""管理截图路径、主图变换及 FlipView 与圆点分页的同步。"""

import os
from datetime import datetime

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QImageReader, QPixmap, QTransform

from gui.dialogs.screenshot_viewer_tasks import ScreenshotImageCache, ScreenshotReadWorker
from gui.i18n import tr

MIN_ZOOM = 0.05
MAX_ZOOM = 5.0
ZOOM_STEP = 0.10


class ScreenshotViewerNav:
    """页面是索引唯一来源；控件同步阻塞信号，避免圆点重建递归或抢走当前图。"""

    def __init__(self, frame):
        self._frame = frame
        self._cache = ScreenshotImageCache()
        self._generation = 0
        self._worker: ScreenshotReadWorker | None = None
        self._pending = False
        self._suspended = False

    def _current_path(self) -> str:
        frame = self._frame
        if 0 <= frame._current_idx < len(frame._image_paths):
            return frame._image_paths[frame._current_idx]
        return ""

    def _navigate_to(self, index: int):
        frame = self._frame
        if frame._disposed or frame._disposing:
            return
        if not frame._image_paths:
            self._pending = False
            self._show_placeholder(tr("No screenshot available"))
            return
        if not 0 <= index < len(frame._image_paths):
            return
        frame._current_idx = index
        self._generation += 1
        self._pending = True
        if frame._display_path != self._current_path():
            had_image = frame._display_pixmap is not None
            frame._original_pixmap = frame._display_pixmap = None
            frame._display_path = ""
            frame._empty_label.setText(tr("Loading preview…"))
            if not had_image:
                frame._image_stack.setCurrentWidget(frame._empty_label)
        self._sync_image_selection()
        self._update_nav_visibility()
        self._start_read()

    def _start_read(self) -> None:
        """每页只启动一个解码线程，导航请求合并为最新目标。"""
        frame = self._frame
        if (self._worker is not None or not self._pending or self._suspended
                or frame._disposing or frame._disposed or not frame._image_paths):
            return
        index = frame._current_idx
        indices = (index, index - 1, index + 1)
        paths = tuple(frame._image_paths[i] for i in indices if 0 <= i < len(frame._image_paths))
        self._pending = False
        worker = ScreenshotReadWorker(
            self._generation, paths, dict(self._cache.images), QImageReader, frame,
        )
        self._worker = worker
        frame._start_io_worker(worker)

    def read_finished(self, worker: ScreenshotReadWorker) -> None:
        """已完成非阻塞 join 后启动最新排队目标，始终只有一个读取线程。"""
        if self._worker is not worker:
            return
        self._worker = None
        self._start_read()

    def image_ready(self, generation: int, result) -> None:
        """逐图消费后台结果；旧请求可贡献缓存，但不能替换当前导航目标。"""
        frame = self._frame
        if frame._disposing or frame._disposed:
            return
        path, key, image, error = result
        if path not in frame._image_paths:
            return
        if key is not None and not image.isNull():
            self._cache.add(key, image)
        if generation == self._generation and path == self._current_path():
            if error == "changed":
                self._pending = True
            elif image.isNull():
                if frame._delete_worker is not None and path in frame._delete_worker.paths:
                    # 删除批次拥有缺失文件的合并权，避免读取并发产生多次部分计数。
                    return
                frame._image_paths.remove(path)
                self._cache.remove_path(path)
                self._rebuild_images()
                self._navigate_to(min(frame._current_idx, max(0, len(frame._image_paths) - 1)))
                frame._notify_image_count()
            else:
                changed_image = frame._display_path != path
                frame._display_path = path
                if changed_image:
                    frame._fit_to_window = True
                    frame._view.reset_pan()
                self._show_pixmap(QPixmap.fromImage(image))
                self._sync_image_selection()
                self._update_info()
                self._update_nav_visibility()
                frame._notify_image_count()

    def dispose(self) -> None:
        """先封闭解码结果准入，再释放页面缓存。"""
        self._generation += 1
        self._pending = False
        self._cache.clear()

    def _show_pixmap(self, pixmap: QPixmap):
        frame = self._frame
        frame._original_pixmap = pixmap
        angle = frame._rotation_by_path.get(self._current_path(), 0)
        frame._display_pixmap = (
            pixmap.transformed(
                QTransform().rotate(angle), Qt.TransformationMode.SmoothTransformation
            )
            if angle else pixmap
        )
        # 当前像素只归页面持有，不能再写入每个历史 item 绕过页内缓存预算。
        frame._image_stack.setCurrentWidget(frame._view)
        if frame._fit_to_window:
            self._apply_fit()
        else:
            frame._view.viewport().update()
            self._update_zoom_label()

    def _show_placeholder(self, text: str):
        frame = self._frame
        frame._original_pixmap = frame._display_pixmap = None
        frame._display_path = ""
        frame._current_idx = 0
        frame._fit_to_window = True
        frame._zoom_factor = 1.0
        frame._view.stop_animations()
        frame._empty_label.setText(text)
        frame._image_stack.setCurrentWidget(frame._empty_label)
        frame._path_label.setProperty("screenshotFullFileName", "")
        for label in (frame._path_label, frame._info_label):
            label.setText("")
            label.setToolTip("")
            label.setAccessibleDescription("")
        frame._zoom_label.setText(tr("Fit"))
        frame._schedule_metadata_reflow()
        self._update_nav_visibility()

    def _rebuild_images(self):
        """仅登记文件路径，主图按需解码；重建圆点时保留页面期望的索引。"""

        frame = self._frame
        frame._rotation_by_path = {
            path: angle for path, angle in frame._rotation_by_path.items()
            if path in frame._image_paths
        }
        frame._current_idx = min(frame._current_idx, max(0, len(frame._image_paths) - 1))
        with QSignalBlocker(frame._view), QSignalBlocker(frame._pager):
            frame._view.clear()
            frame._view.addImages(frame._image_paths)
            frame._view.doItemsLayout()
            frame._pager.stop_animations()
            count = len(frame._image_paths)
            frame._pager.setVisibleNumber(min(count, 7))
            frame._pager.setPageNumber(count)
            frame._pager.doItemsLayout()
            for index, path in enumerate(frame._image_paths):
                text = f"{index + 1} · {os.path.basename(path)}"
                for widget in (frame._view, frame._pager):
                    item = widget.item(index)
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, text)
                    item.setToolTip(os.path.basename(path))
            if count:
                frame._view.scrollToIndex(frame._current_idx)
        self._sync_image_selection()
        self._update_nav_visibility()

    def append_images(self, start: int) -> None:
        """仅追加新的图片与圆点项，保留既有项、旋转和当前像素。"""
        frame = self._frame
        count = len(frame._image_paths)
        with QSignalBlocker(frame._view), QSignalBlocker(frame._pager):
            frame._view.addImages(frame._image_paths[start:])
            frame._pager.append_pages(count - frame._pager.count())
            frame._pager.setVisibleNumber(min(count, 7))
            for index in range(start, count):
                name = os.path.basename(frame._image_paths[index])
                for widget in (frame._view, frame._pager):
                    item = widget.item(index)
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{index + 1} · {name}")
                    item.setToolTip(name)
            frame._view.doItemsLayout()
            frame._pager.doItemsLayout()
        self._sync_image_selection()
        self._update_nav_visibility()

    def _sync_image_selection(self):
        frame = self._frame
        if not frame._image_paths:
            return
        with QSignalBlocker(frame._view), QSignalBlocker(frame._pager):
            frame._view.setCurrentRow(frame._current_idx)
            frame._view.setCurrentIndex(frame._current_idx)
            frame._pager.setCurrentIndex(frame._current_idx)
        frame._view.viewport().update()

    def navigate_prev(self):
        if self._frame._current_idx > 0:
            self._navigate_to(self._frame._current_idx - 1)

    def navigate_next(self):
        if self._frame._current_idx + 1 < len(self._frame._image_paths):
            self._navigate_to(self._frame._current_idx + 1)

    def _apply_fit(self):
        frame = self._frame
        pixmap = frame._display_pixmap
        if frame._disposed or not frame._fit_to_window or pixmap is None or pixmap.isNull():
            return
        size = frame._view.image_area_size()
        factor = min(size.width() / pixmap.width(), size.height() / pixmap.height(), 1.0)
        self._set_zoom(factor, fit=True)

    def _set_zoom(self, factor: float, *, fit: bool = False):
        frame = self._frame
        if frame._disposed or frame._display_pixmap is None:
            return
        frame._zoom_factor = float(factor) if fit else max(MIN_ZOOM, min(MAX_ZOOM, float(factor)))
        frame._fit_to_window = fit
        frame._view.reset_pan()
        frame._view.viewport().update()
        self._update_zoom_label()

    def _zoom_from_wheel(self, delta: int):
        if delta:
            factor = 1 + ZOOM_STEP if delta > 0 else 1 - ZOOM_STEP
            self._set_zoom(self._frame._zoom_factor * factor)

    def zoom_in(self):
        self._set_zoom(self._frame._zoom_factor + ZOOM_STEP)

    def zoom_out(self):
        self._set_zoom(self._frame._zoom_factor - ZOOM_STEP)

    def _reset_zoom(self):
        self._frame._fit_to_window = True
        self._apply_fit()

    def _actual_size(self):
        self._set_zoom(1.0)

    def toggle_fit_actual(self):
        if self._frame._fit_to_window:
            self._actual_size()
        else:
            self._reset_zoom()

    def _rotate_image(self):
        """旋转原始像素的显示副本，按路径保留角度；不覆写源文件。"""

        frame = self._frame
        path = self._current_path()
        if frame._disposed or not path or frame._original_pixmap is None:
            return
        frame._rotation_by_path[path] = (frame._rotation_by_path.get(path, 0) + 90) % 360
        frame._fit_to_window = True
        frame._view.reset_pan()
        self._show_pixmap(frame._original_pixmap)

    def _update_zoom_label(self):
        frame = self._frame
        pct = int(round(frame._zoom_factor * 100))
        frame._zoom_label.setText(
            (tr("Fit") if pct == 100 else tr("Fit {value0}%").format(value0=pct))
            if frame._fit_to_window else f"{pct}%"
        )
        frame._schedule_metadata_reflow()

    def _update_info(self):
        frame = self._frame
        path = self._current_path()
        if not path or frame._original_pixmap is None:
            return
        file_name = os.path.basename(path)
        absolute_path = os.path.abspath(path)
        frame._path_label.setProperty("screenshotFullFileName", file_name)
        frame._path_label.setText(file_name)
        frame._path_label.setToolTip(absolute_path)
        frame._path_label.setAccessibleDescription(absolute_path)
        metadata = (
            f"{frame._original_pixmap.width()} x {frame._original_pixmap.height()}"
            f" | {self._format_size(path)} | {self._format_modified_time(path)}"
        )
        frame._info_label.setText(metadata)
        frame._info_label.setToolTip(metadata)
        frame._info_label.setAccessibleDescription(metadata)
        frame._schedule_metadata_reflow()
        self._update_nav_label()

    @staticmethod
    def _format_size(path: str) -> str:
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            return "-"
        if size_bytes >= 1_048_576:
            return f"{size_bytes / 1_048_576:.1f} MB"
        if size_bytes >= 1024:
            return f"{size_bytes / 1024:.0f} KB"
        return f"{size_bytes} B"

    @staticmethod
    def _format_modified_time(path: str) -> str:
        try:
            return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%H:%M:%S")
        except OSError:
            return "-"

    def _update_nav_visibility(self):
        frame = self._frame
        has_image = bool(frame._image_paths and frame._display_pixmap is not None)
        multi = len(frame._image_paths) > 1
        frame._pager.setVisible(multi)
        frame._nav_label.setVisible(has_image)
        self._update_nav_label()
        self._update_actions_enabled(has_image)
        frame._schedule_metadata_reflow()

    def _update_nav_label(self):
        frame = self._frame
        frame._nav_label.setText(
            f"{frame._current_idx + 1} / {len(frame._image_paths)}"
            if frame._image_paths else "0 / 0"
        )

    def _update_actions_enabled(self, enabled: bool):
        """命令与溢出菜单共享 QAction 状态，空页只允许添加图片。"""

        frame = self._frame
        for action in (
            frame._rotate_action, frame._zoom_out_action, frame._zoom_in_action,
            frame._fit_action, frame._actual_action, frame._info_action,
            frame._copy_action, frame._folder_action,
            frame._delete_action, frame._delete_all_action,
        ):
            action.setEnabled(enabled and not frame._disposed and not frame._disposing)
        deleting = frame._delete_worker is not None
        frame._delete_action.setEnabled(enabled and not frame._disposing and not deleting)
        frame._delete_all_action.setEnabled(
            bool(frame._image_paths) and not frame._disposed
            and not frame._disposing and not deleting
        )
        frame._add_action.setEnabled(not frame._disposed and not frame._disposing)
