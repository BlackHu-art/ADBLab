"""提供截图浏览、缩放、复制和文件管理对话框。"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from gui.styles import BaseStyles, get_default_font
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from models.base.process_runner import ProcessRunner

MIN_ZOOM = 0.10
MAX_ZOOM = 5.00
ZOOM_STEP = 0.10


class ScreenshotGraphicsView(QGraphicsView):
    """把滚轮和双击缩放操作委托给所属截图查看器。"""

    def __init__(self, owner: "ScreenshotViewer"):
        super().__init__()
        self._owner = owner
        self.setObjectName("imageView")
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            self._owner._zoom_from_wheel(event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._owner.toggle_fit_actual()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ScreenshotViewer(QDialog):
    """浏览截图批次，并管理当前图片的显示和文件操作。"""

    def __init__(self, image_paths: list, current_index: int = 0, parent=None):
        super().__init__(parent)
        self._image_paths = list(image_paths) if image_paths else []
        self._current_idx = (
            max(0, min(current_index, len(self._image_paths) - 1)) if self._image_paths else 0
        )
        self._zoom_factor = 1.0
        self._fit_to_window = True
        self._original_pixmap: QPixmap | None = None
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._window_icon_name = "camera.svg"
        self._icon_buttons: list[QPushButton] = []

        self._init_window()
        self._init_shortcuts()
        self._init_ui()
        self._apply_theme()
        self._rebuild_thumbnails()

        if self._image_paths:
            self._navigate_to(self._current_idx)
        else:
            self._show_placeholder("No screenshot available")
        self._update_nav_visibility()

        BaseStyles.theme_changed.connect(self._apply_theme)

    def _init_window(self):
        self.setWindowTitle("Screenshot Viewer")
        self.setWindowIcon(get_themed_icon(self._window_icon_name))
        self.setFont(get_default_font())
        self.setMinimumSize(760, 520)
        self.resize(1100, 760)

    def _init_shortcuts(self):
        QShortcut(QKeySequence("Esc"), self, self.close)
        QShortcut(QKeySequence("Ctrl+C"), self, self.copy_to_clipboard)
        QShortcut(QKeySequence("Ctrl+="), self, self.zoom_in)
        QShortcut(QKeySequence("Ctrl++"), self, self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, self._reset_zoom)
        QShortcut(QKeySequence("Ctrl+1"), self, self._actual_size)
        QShortcut(QKeySequence("Left"), self, self.navigate_prev)
        QShortcut(QKeySequence("Right"), self, self.navigate_next)

    @staticmethod
    def _theme_color(key: str) -> str:
        return BaseStyles.color(key)

    def closeEvent(self, event):
        try:
            BaseStyles.theme_changed.disconnect(self._apply_theme)
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)

    def _apply_theme(self, _name: str = ""):
        apply_dark_title_bar(self)
        self.setFont(get_default_font())
        c = self._theme_color
        r = BaseStyles
        small_size = max(10, BaseStyles.DEFAULT_FONT_SIZE - 1)

        self.setStyleSheet(
            BaseStyles.SCROLLBAR_STYLE()
            + f"""
            QDialog {{
                background-color: {c('WINDOW_BG')};
                color: {c('TEXT_PRIMARY')};
                font-family: '{BaseStyles.DEFAULT_FONT_FAMILY}';
                font-size: {BaseStyles.DEFAULT_FONT_SIZE}px;
            }}
            QFrame#canvasFrame {{
                background-color: {c('INPUT_BG')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r.RADIUS_LG}px;
            }}
            QGraphicsView#imageView {{
                background-color: {c('INPUT_BG')};
                border: none;
            }}
            QFrame#bottomDock {{
                background-color: {c('TOOLBAR_BG')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r.RADIUS_MD}px;
            }}
            QFrame#bottomBar {{
                background-color: transparent;
                border: none;
            }}
            QListWidget#thumbnailStrip {{
                background-color: {c('INPUT_BG')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r.RADIUS_SM}px;
                color: {c('TEXT_PRIMARY')};
                padding: 4px;
                outline: none;
            }}
            QListWidget#thumbnailStrip::item {{
                border: 1px solid transparent;
                border-radius: {r.RADIUS_SM}px;
                padding: 3px;
                margin: 1px;
            }}
            QListWidget#thumbnailStrip::item:selected {{
                background-color: {c('SELECTION_BG')};
                border-color: {c('BORDER_FOCUS')};
                color: {c('SELECTION_TEXT')};
            }}
            QLabel {{
                color: {c('TEXT_PRIMARY')};
                background: transparent;
            }}
            QLabel#metaLabel,
            QLabel#pathLabel,
            QLabel#navLabel,
            QLabel#zoomLabel {{
                color: {c('TEXT_SECONDARY')};
                font-size: {small_size}px;
            }}
            QPushButton {{
                background-color: {c('BUTTON_BG')};
                color: {c('TEXT_PRIMARY')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r.RADIUS_SM}px;
                padding: 0;
                font-size: {BaseStyles.DEFAULT_FONT_SIZE}px;
            }}
            QPushButton:hover {{
                background-color: {c('BUTTON_HOVER')};
                border-color: {c('BORDER_FOCUS')};
            }}
            QPushButton:pressed {{
                background-color: {c('BUTTON_PRESSED')};
            }}
            QPushButton:disabled {{
                color: {c('TEXT_DISABLED')};
                background-color: {c('INPUT_BG')};
                border-color: {c('BORDER_COLOR')};
            }}
            QPushButton#danger:hover {{
                background-color: {c('BUTTON_DANGER')};
                border-color: {c('BUTTON_DANGER')};
                color: #ffffff;
            }}
            QPushButton#danger:pressed {{
                background-color: {c('BUTTON_DANGER_HOVER')};
                border-color: {c('BUTTON_DANGER_HOVER')};
                color: #ffffff;
            }}
            """
        )
        self._refresh_button_icons()
        if hasattr(self, "_placeholder_text"):
            self._refresh_placeholder_color()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_canvas(), stretch=1)
        root.addWidget(self._build_bottom_dock())

    def _build_canvas(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("canvasFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        self._scene = QGraphicsScene(self)
        self._view = ScreenshotGraphicsView(self)
        self._view.setScene(self._scene)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._view)
        return frame

    def _build_bottom_dock(self) -> QFrame:
        dock = QFrame()
        dock.setObjectName("bottomDock")
        layout = QVBoxLayout(dock)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._thumb_list = QListWidget()
        self._thumb_list.setObjectName("thumbnailStrip")
        self._thumb_list.setViewMode(QListView.IconMode)
        self._thumb_list.setFlow(QListView.LeftToRight)
        self._thumb_list.setMovement(QListView.Static)
        self._thumb_list.setResizeMode(QListView.Adjust)
        self._thumb_list.setWrapping(False)
        self._thumb_list.setUniformItemSizes(True)
        self._thumb_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._thumb_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._thumb_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._thumb_list.setIconSize(QSize(86, 58))
        self._thumb_list.setFixedHeight(92)
        self._thumb_list.itemClicked.connect(self._on_thumbnail_clicked)
        layout.addWidget(self._thumb_list)

        layout.addWidget(self._build_bottom_bar())
        self._bottom_dock = dock
        return dock

    def _build_bottom_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("bottomBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._path_label = QLabel("")
        self._path_label.setObjectName("pathLabel")
        self._path_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._path_label.setMinimumWidth(120)
        self._path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._path_label.setToolTip("Screenshot file path")
        layout.addWidget(self._path_label, stretch=1)

        self._info_label = QLabel("")
        self._info_label.setObjectName("metaLabel")
        self._info_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._info_label.setMinimumWidth(150)
        self._info_label.setToolTip("Image size, file size, and modified time")
        layout.addWidget(self._info_label, stretch=0)

        self._prev_btn = self._tool_button("caret-left.svg", "Previous screenshot (Left)")
        self._prev_btn.clicked.connect(self.navigate_prev)
        layout.addWidget(self._prev_btn)

        self._nav_label = QLabel("0 / 0")
        self._nav_label.setObjectName("navLabel")
        self._nav_label.setAlignment(Qt.AlignCenter)
        self._nav_label.setFixedWidth(52)
        self._nav_label.setToolTip("Current screenshot index")
        layout.addWidget(self._nav_label)

        self._next_btn = self._tool_button("caret-right.svg", "Next screenshot (Right)")
        self._next_btn.clicked.connect(self.navigate_next)
        layout.addWidget(self._next_btn)

        self._zoom_out_btn = self._tool_button("magnifying-glass-minus.svg", "Zoom out (Ctrl+-)")
        self._zoom_out_btn.clicked.connect(self.zoom_out)
        layout.addWidget(self._zoom_out_btn)

        self._zoom_label = QLabel("Fit")
        self._zoom_label.setObjectName("zoomLabel")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setFixedWidth(56)
        self._zoom_label.setToolTip("Current zoom")
        layout.addWidget(self._zoom_label)

        self._zoom_in_btn = self._tool_button("magnifying-glass-plus.svg", "Zoom in (Ctrl+=)")
        self._zoom_in_btn.clicked.connect(self.zoom_in)
        layout.addWidget(self._zoom_in_btn)

        self._fit_btn = self._tool_button("frame-corners.svg", "Fit to window (Ctrl+0)")
        self._fit_btn.clicked.connect(self._reset_zoom)
        layout.addWidget(self._fit_btn)

        self._actual_btn = self._tool_button("number-square-one.svg", "Actual size (Ctrl+1)")
        self._actual_btn.clicked.connect(self._actual_size)
        layout.addWidget(self._actual_btn)

        self._copy_btn = self._tool_button("copy.svg", "Copy image to clipboard (Ctrl+C)")
        self._copy_btn.clicked.connect(self.copy_to_clipboard)
        layout.addWidget(self._copy_btn)

        self._folder_btn = self._tool_button("folder-open.svg", "Open file location")
        self._folder_btn.clicked.connect(self._open_file_location)
        layout.addWidget(self._folder_btn)

        self._delete_btn = self._tool_button("trash.svg", "Delete screenshot")
        self._delete_btn.setObjectName("danger")
        self._delete_btn.clicked.connect(self._delete_file)
        layout.addWidget(self._delete_btn)

        self._bottom_bar = bar
        return bar

    def _tool_button(self, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setIcon(get_themed_icon(icon_name))
        button.setIconSize(QSize(14, 14))
        button.setFixedSize(28, 28)
        button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        button.setProperty("iconName", icon_name)
        self._icon_buttons.append(button)
        return button

    def _refresh_button_icons(self):
        self.setWindowIcon(get_themed_icon(self._window_icon_name))
        for button in getattr(self, "_icon_buttons", []):
            icon_name = button.property("iconName")
            if icon_name:
                button.setIcon(get_themed_icon(icon_name))

    def _current_path(self) -> str:
        if 0 <= self._current_idx < len(self._image_paths):
            return self._image_paths[self._current_idx]
        return ""

    def _navigate_to(self, index: int):
        if not self._image_paths:
            self._show_placeholder("No screenshot available")
            return
        if index < 0 or index >= len(self._image_paths):
            return
        self._current_idx = index
        while self._image_paths:
            path = self._current_path()
            if not path or not os.path.exists(path):
                del self._image_paths[self._current_idx]
            else:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    self._show_pixmap(pixmap)
                    self._update_info()
                    self._update_nav_visibility()
                    self._sync_thumbnail_selection()
                    return
                del self._image_paths[self._current_idx]
            if self._current_idx >= len(self._image_paths):
                self._current_idx = max(0, len(self._image_paths) - 1)
        self._rebuild_thumbnails()
        self._show_placeholder("No valid screenshots")

    def _show_pixmap(self, pixmap: QPixmap):
        self._scene.clear()
        self._placeholder_text = None
        self._original_pixmap = pixmap
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._fit_to_window = True
        self._zoom_factor = 1.0
        self._apply_fit()

    def _show_placeholder(self, text: str):
        self._scene.clear()
        self._original_pixmap = None
        self._pixmap_item = None
        self._placeholder_text = self._scene.addText(text)
        self._placeholder_text.setFont(BaseStyles.get_default_font(max(12, BaseStyles.DEFAULT_FONT_SIZE + 1)))
        self._scene.setSceneRect(QRectF(0, 0, 420, 240))
        bounds = self._placeholder_text.boundingRect()
        self._placeholder_text.setPos((420 - bounds.width()) / 2, (240 - bounds.height()) / 2)
        self._refresh_placeholder_color()
        self._path_label.setText("")
        self._path_label.setToolTip("")
        self._info_label.setText(text)
        self._zoom_label.setText("Fit")
        self._update_nav_visibility()

    def _refresh_placeholder_color(self):
        item = getattr(self, "_placeholder_text", None)
        if item is not None:
            try:
                item.setDefaultTextColor(QColor(self._theme_color("TEXT_DISABLED")))
            except RuntimeError:
                self._placeholder_text = None

    def _rebuild_thumbnails(self):
        if not hasattr(self, "_thumb_list"):
            return
        self._thumb_list.clear()
        for index, path in enumerate(self._image_paths):
            item = QListWidgetItem(self._thumbnail_icon(path), os.path.basename(path))
            item.setData(Qt.UserRole, index)
            item.setToolTip(os.path.abspath(path))
            item.setSizeHint(QSize(116, 78))
            self._thumb_list.addItem(item)
        self._sync_thumbnail_selection()
        self._update_nav_visibility()

    def _thumbnail_icon(self, path: str) -> QIcon:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return get_themed_icon("image-broken.svg")
        thumb = pixmap.scaled(86, 58, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return QIcon(thumb)

    def _on_thumbnail_clicked(self, item: QListWidgetItem):
        index = item.data(Qt.UserRole)
        if isinstance(index, int):
            self._navigate_to(index)

    def _sync_thumbnail_selection(self):
        if not hasattr(self, "_thumb_list"):
            return
        self._thumb_list.blockSignals(True)
        try:
            if 0 <= self._current_idx < self._thumb_list.count():
                self._thumb_list.setCurrentRow(self._current_idx)
                self._thumb_list.scrollToItem(self._thumb_list.currentItem(), QAbstractItemView.PositionAtCenter)
            else:
                self._thumb_list.clearSelection()
        finally:
            self._thumb_list.blockSignals(False)

    def navigate_prev(self):
        if len(self._image_paths) <= 1:
            return
        self._navigate_to((self._current_idx - 1) % len(self._image_paths))

    def navigate_next(self):
        if len(self._image_paths) <= 1:
            return
        self._navigate_to((self._current_idx + 1) % len(self._image_paths))

    def _apply_fit(self):
        if self._original_pixmap is None or self._original_pixmap.isNull() or self._pixmap_item is None:
            return
        viewport = self._view.viewport().size()
        max_w = max(viewport.width() - 16, 200)
        max_h = max(viewport.height() - 16, 150)
        pw = max(1, self._original_pixmap.width())
        ph = max(1, self._original_pixmap.height())
        scale = min(max_w / pw, max_h / ph, 1.0)
        self._set_zoom(scale, fit=True)
        self._view.centerOn(self._pixmap_item)

    def _set_zoom(self, factor: float, *, fit: bool = False, anchor_under_mouse: bool = False):
        if self._original_pixmap is None or self._original_pixmap.isNull():
            return
        self._zoom_factor = max(MIN_ZOOM, min(MAX_ZOOM, float(factor)))
        self._fit_to_window = fit
        previous_anchor = self._view.transformationAnchor()
        self._view.setTransformationAnchor(
            QGraphicsView.AnchorUnderMouse if anchor_under_mouse else QGraphicsView.AnchorViewCenter
        )
        self._view.setTransform(QTransform().scale(self._zoom_factor, self._zoom_factor))
        self._view.setTransformationAnchor(previous_anchor)
        self._update_zoom_label()

    def _zoom_from_wheel(self, delta: int):
        if self._original_pixmap is None or self._original_pixmap.isNull():
            return
        multiplier = 1.0 + ZOOM_STEP if delta > 0 else 1.0 - ZOOM_STEP
        self._set_zoom(self._zoom_factor * multiplier, anchor_under_mouse=True)

    def zoom_in(self):
        self._set_zoom(self._zoom_factor + ZOOM_STEP)

    def zoom_out(self):
        self._set_zoom(self._zoom_factor - ZOOM_STEP)

    def _reset_zoom(self):
        self._fit_to_window = True
        self._apply_fit()

    def _actual_size(self):
        self._set_zoom(1.0)

    def toggle_fit_actual(self):
        if self._fit_to_window:
            self._actual_size()
        else:
            self._reset_zoom()

    def _update_zoom_label(self):
        pct = int(round(self._zoom_factor * 100))
        if self._fit_to_window:
            self._zoom_label.setText("Fit" if pct == 100 else f"Fit {pct}%")
        else:
            self._zoom_label.setText(f"{pct}%")

    def _update_info(self):
        path = self._current_path()
        if not path or self._original_pixmap is None:
            self._info_label.setText("")
            return
        pw = self._original_pixmap.width()
        ph = self._original_pixmap.height()
        size_str = self._format_size(path)
        modified = self._format_modified_time(path)
        self._path_label.setText(os.path.basename(path))
        self._path_label.setToolTip(os.path.abspath(path))
        self._info_label.setText(f"{pw} x {ph} | {size_str} | {modified}")
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
        has_image = bool(self._image_paths and self._original_pixmap is not None)
        multi = len(self._image_paths) > 1
        self._thumb_list.setVisible(multi)
        self._prev_btn.setEnabled(multi)
        self._next_btn.setEnabled(multi)
        self._update_nav_label()
        self._update_actions_enabled(has_image)

    def _update_nav_label(self):
        if self._image_paths:
            self._nav_label.setText(f"{self._current_idx + 1} / {len(self._image_paths)}")
        else:
            self._nav_label.setText("0 / 0")

    def _update_actions_enabled(self, enabled: bool):
        for button in (
            self._zoom_out_btn,
            self._zoom_in_btn,
            self._fit_btn,
            self._actual_btn,
            self._copy_btn,
            self._folder_btn,
            self._delete_btn,
        ):
            button.setEnabled(enabled)

    def copy_to_clipboard(self):
        path = self._current_path()
        if not path:
            return
        pixmap = self._original_pixmap or QPixmap(path)
        if not pixmap.isNull():
            QApplication.clipboard().setPixmap(pixmap)
            self._flash_status("Image copied")

    def _flash_status(self, text: str):
        previous = self._info_label.text()
        self._info_label.setText(text)
        QTimer.singleShot(1800, lambda: self._info_label.setText(previous))

    def _open_file_location(self):
        path = self._current_path()
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
        path = self._current_path()
        if not path or not os.path.exists(path):
            return
        try:
            os.remove(path)
        except OSError as exc:
            QMessageBox.warning(self, "Delete Failed", str(exc))
            return
        del self._image_paths[self._current_idx]
        if not self._image_paths:
            self.close()
            return
        self._rebuild_thumbnails()
        self._current_idx = min(self._current_idx, len(self._image_paths) - 1)
        self._navigate_to(self._current_idx)

    def _on_context_menu(self, pos):
        path = self._current_path()
        has_file = bool(path and os.path.exists(path))
        menu = QMenu(self)
        c = self._theme_color
        menu.setStyleSheet(
            f"QMenu {{ background: {c('PANEL_BG')}; border: 1px solid {c('BORDER_COLOR')}; "
            f"border-radius: {BaseStyles.RADIUS_SM}px; padding: 4px; color: {c('TEXT_PRIMARY')}; }}"
            f"QMenu::item {{ padding: 6px 24px; border-radius: 3px; }}"
            f"QMenu::item:selected {{ background: {c('BUTTON_HOVER')}; }}"
            f"QMenu::separator {{ height: 1px; background: {c('BORDER_COLOR')}; margin: 4px 8px; }}"
        )

        copy_action = menu.addAction("Copy Image\tCtrl+C")
        copy_action.triggered.connect(self.copy_to_clipboard)
        copy_action.setEnabled(has_file)

        menu.addSeparator()

        folder_action = menu.addAction("Open File Location")
        folder_action.triggered.connect(self._open_file_location)
        folder_action.setEnabled(has_file)

        delete_action = menu.addAction("Delete Screenshot")
        delete_action.triggered.connect(self._delete_file)
        delete_action.setEnabled(has_file)

        menu.addSeparator()

        menu.addAction("Zoom In\tCtrl+=").triggered.connect(self.zoom_in)
        menu.addAction("Zoom Out\tCtrl+-").triggered.connect(self.zoom_out)
        menu.addAction("Fit to Window\tCtrl+0").triggered.connect(self._reset_zoom)
        menu.addAction("Actual Size\tCtrl+1").triggered.connect(self._actual_size)

        menu.exec(self._view.mapToGlobal(pos))

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            self._zoom_from_wheel(event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_fit_to_window", False):
            QTimer.singleShot(0, self._apply_fit)
