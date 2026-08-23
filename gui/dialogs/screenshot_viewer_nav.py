"""提供截图查看器对话框的导航、缩放与信息显示控制器。"""

import os
from datetime import datetime

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImageReader, QPixmap, QPixmapCache, QTransform
from PySide6.QtWidgets import QAbstractItemView, QGraphicsView, QListWidgetItem

from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.typography import FontRole

MIN_ZOOM = 0.10
MAX_ZOOM = 5.00
ZOOM_STEP = 0.10

THUMB_W = 86
THUMB_H = 58


def _image_cache_key(path: str, kind: str) -> str:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    return f"adblab:screenshot:{kind}:{path}:{mtime}"


def _load_pixmap(path: str, *, kind: str, max_size: QSize | None = None) -> QPixmap:
    """按 (path, mtime) 缓存解码结果；缩略图用 QImageReader 直接降采样。"""
    key = _image_cache_key(path, kind)
    cached = QPixmapCache.find(key)
    if cached is not None and not cached.isNull():
        return cached
    if max_size is not None:
        reader = QImageReader(path)
        native = reader.size()
        if native.isValid() and not native.isEmpty():
            reader.setScaledSize(
                native.scaled(
                    max_size.width(),
                    max_size.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                )
            )
        pixmap = QPixmap.fromImage(reader.read())
    else:
        pixmap = QPixmap(path)
    if not pixmap.isNull():
        QPixmapCache.insert(key, pixmap)
    return pixmap


class ScreenshotViewerNav:
    """组合进 ScreenshotViewer 的导航/缩放控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    def _current_path(self) -> str:
        if 0 <= self._frame._current_idx < len(self._frame._image_paths):
            return self._frame._image_paths[self._frame._current_idx]
        return ""

    def _navigate_to(self, index: int):
        if not self._frame._image_paths:
            self._show_placeholder("No screenshot available")
            return
        if index < 0 or index >= len(self._frame._image_paths):
            return
        self._frame._current_idx = index
        paths_changed = False
        while self._frame._image_paths:
            path = self._current_path()
            if not path or not os.path.exists(path):
                del self._frame._image_paths[self._frame._current_idx]
                paths_changed = True
            else:
                pixmap = _load_pixmap(path, kind="main")
                if not pixmap.isNull():
                    if paths_changed:
                        self._rebuild_thumbnails()
                    self._show_pixmap(pixmap)
                    self._update_info()
                    self._update_nav_visibility()
                    self._sync_thumbnail_selection()
                    return
                del self._frame._image_paths[self._frame._current_idx]
                paths_changed = True
            if self._frame._current_idx >= len(self._frame._image_paths):
                self._frame._current_idx = max(0, len(self._frame._image_paths) - 1)
        self._rebuild_thumbnails()
        self._show_placeholder("No valid screenshots")

    def _show_pixmap(self, pixmap: QPixmap):
        self._frame._scene.clear()
        self._frame._placeholder_text = None
        self._frame._original_pixmap = pixmap
        self._frame._pixmap_item = self._frame._scene.addPixmap(pixmap)
        self._frame._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._frame._scene.setSceneRect(QRectF(pixmap.rect()))
        self._frame._fit_to_window = True
        self._frame._zoom_factor = 1.0
        self._apply_fit()

    def _show_placeholder(self, text: str):
        self._frame._scene.clear()
        self._frame._original_pixmap = None
        self._frame._pixmap_item = None
        self._frame._placeholder_text = self._frame._scene.addText(text)
        self._frame._placeholder_text.setFont(
            BaseStyles.font_for_role(FontRole.UI, size=max(12, BaseStyles.DEFAULT_FONT_SIZE + 1))
        )
        self._frame._scene.setSceneRect(QRectF(0, 0, 420, 240))
        bounds = self._frame._placeholder_text.boundingRect()
        self._frame._placeholder_text.setPos(
            (420 - bounds.width()) / 2, (240 - bounds.height()) / 2
        )
        self._refresh_placeholder_color()
        self._frame._path_label.setText("")
        self._frame._path_label.setToolTip("")
        self._frame._path_label.setAccessibleDescription("")
        self._frame._info_label.setText(text)
        self._frame._info_label.setToolTip(text)
        self._frame._info_label.setAccessibleDescription(text)
        self._frame._zoom_label.setText("Fit")
        self._update_nav_visibility()

    def _refresh_placeholder_color(self):
        item = getattr(self._frame, "_placeholder_text", None)
        if item is not None:
            try:
                item.setDefaultTextColor(QColor(self._frame._theme_color("TEXT_DISABLED")))
            except RuntimeError:
                self._frame._placeholder_text = None

    def _rebuild_thumbnails(self):
        if not hasattr(self._frame, "_thumb_list"):
            return
        self._frame._thumb_list.clear()
        for index, path in enumerate(self._frame._image_paths):
            item = QListWidgetItem(self._thumbnail_icon(path), os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(os.path.abspath(path))
            item.setSizeHint(QSize(116, 78))
            self._frame._thumb_list.addItem(item)
        self._sync_thumbnail_selection()
        self._update_nav_visibility()

    def _thumbnail_icon(self, path: str) -> QIcon:
        thumb = _load_pixmap(path, kind="thumb", max_size=QSize(THUMB_W, THUMB_H))
        if thumb.isNull():
            return get_themed_icon("image-broken.svg")
        return QIcon(thumb)

    def _on_thumbnail_clicked(self, item: QListWidgetItem):
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int):
            self._navigate_to(index)

    def _sync_thumbnail_selection(self):
        if not hasattr(self._frame, "_thumb_list"):
            return
        self._frame._thumb_list.blockSignals(True)
        try:
            if 0 <= self._frame._current_idx < self._frame._thumb_list.count():
                self._frame._thumb_list.setCurrentRow(self._frame._current_idx)
                self._frame._thumb_list.scrollToItem(
                    self._frame._thumb_list.currentItem(),
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
            else:
                self._frame._thumb_list.clearSelection()
        finally:
            self._frame._thumb_list.blockSignals(False)

    def navigate_prev(self):
        if len(self._frame._image_paths) <= 1:
            return
        self._navigate_to((self._frame._current_idx - 1) % len(self._frame._image_paths))

    def navigate_next(self):
        if len(self._frame._image_paths) <= 1:
            return
        self._navigate_to((self._frame._current_idx + 1) % len(self._frame._image_paths))

    def _apply_fit(self):
        if (
            self._frame._original_pixmap is None
            or self._frame._original_pixmap.isNull()
            or self._frame._pixmap_item is None
        ):
            return
        viewport = self._frame._view.viewport().size()
        max_w = max(viewport.width() - 16, 200)
        max_h = max(viewport.height() - 16, 150)
        pw = max(1, self._frame._original_pixmap.width())
        ph = max(1, self._frame._original_pixmap.height())
        scale = min(max_w / pw, max_h / ph, 1.0)
        self._set_zoom(scale, fit=True)
        self._frame._view.centerOn(self._frame._pixmap_item)

    def _set_zoom(self, factor: float, *, fit: bool = False, anchor_under_mouse: bool = False):
        if self._frame._original_pixmap is None or self._frame._original_pixmap.isNull():
            return
        self._frame._zoom_factor = max(MIN_ZOOM, min(MAX_ZOOM, float(factor)))
        self._frame._fit_to_window = fit
        previous_anchor = self._frame._view.transformationAnchor()
        self._frame._view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
            if anchor_under_mouse
            else QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        self._frame._view.setTransform(
            QTransform().scale(self._frame._zoom_factor, self._frame._zoom_factor)
        )
        self._frame._view.setTransformationAnchor(previous_anchor)
        self._update_zoom_label()

    def _zoom_from_wheel(self, delta: int):
        if self._frame._original_pixmap is None or self._frame._original_pixmap.isNull():
            return
        multiplier = 1.0 + ZOOM_STEP if delta > 0 else 1.0 - ZOOM_STEP
        self._set_zoom(self._frame._zoom_factor * multiplier, anchor_under_mouse=True)

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

    def _update_zoom_label(self):
        pct = int(round(self._frame._zoom_factor * 100))
        if self._frame._fit_to_window:
            self._frame._zoom_label.setText("Fit" if pct == 100 else f"Fit {pct}%")
        else:
            self._frame._zoom_label.setText(f"{pct}%")

    def _update_info(self):
        path = self._current_path()
        if not path or self._frame._original_pixmap is None:
            self._frame._info_label.setText("")
            return
        pw = self._frame._original_pixmap.width()
        ph = self._frame._original_pixmap.height()
        size_str = self._format_size(path)
        modified = self._format_modified_time(path)
        self._frame._path_label.setText(os.path.basename(path))
        self._frame._path_label.setToolTip(os.path.abspath(path))
        self._frame._path_label.setAccessibleDescription(os.path.abspath(path))
        metadata = f"{pw} x {ph} | {size_str} | {modified}"
        self._frame._info_label.setText(metadata)
        self._frame._info_label.setToolTip(metadata)
        self._frame._info_label.setAccessibleDescription(metadata)
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
        has_image = bool(self._frame._image_paths and self._frame._original_pixmap is not None)
        multi = len(self._frame._image_paths) > 1
        self._frame._thumb_list.setVisible(multi)
        self._frame._prev_btn.setEnabled(multi)
        self._frame._next_btn.setEnabled(multi)
        self._update_nav_label()
        self._update_actions_enabled(has_image)

    def _update_nav_label(self):
        if self._frame._image_paths:
            self._frame._nav_label.setText(
                f"{self._frame._current_idx + 1} / {len(self._frame._image_paths)}"
            )
        else:
            self._frame._nav_label.setText("0 / 0")

    def _update_actions_enabled(self, enabled: bool):
        for button in (
            self._frame._zoom_out_btn,
            self._frame._zoom_in_btn,
            self._frame._fit_btn,
            self._frame._actual_btn,
            self._frame._copy_btn,
            self._frame._folder_btn,
            self._frame._delete_btn,
        ):
            button.setEnabled(enabled)
