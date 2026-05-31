"""Screenshot preview dialog with zoom, navigation, and file tools."""

import os
import sys

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import (
    QKeySequence,
    QPixmap,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
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


class ScreenshotViewer(QDialog):

    def __init__(self, image_paths: list, current_index: int = 0, parent=None):
        super().__init__(parent)
        self._image_paths = list(image_paths) if image_paths else []
        self._current_idx = (
            max(0, min(current_index, len(self._image_paths) - 1)) if self._image_paths else 0
        )
        self._zoom_factor = 1.0
        self._fit_to_window = True
        self._original_pixmap = None
        self._window_icon_name = "camera.svg"
        self._icon_buttons: list[QPushButton] = []

        self._init_window()
        self._init_shortcuts()
        self._init_ui()

        if self._image_paths:
            self._navigate_to(0)
        else:
            self._show_placeholder("No screenshot available")
        self._update_nav_visibility()

        BaseStyles.theme_changed.connect(self._apply_theme)

    def _init_window(self):
        self.setWindowTitle("Screenshot Viewer")
        self.setWindowIcon(get_themed_icon(self._window_icon_name))
        self.setFont(get_default_font())
        self.setMinimumSize(720, 460)
        self.resize(1040, 720)
        self._apply_theme()

    def _init_shortcuts(self):
        QShortcut(QKeySequence("Esc"), self, self.close)
        QShortcut(QKeySequence("Ctrl+C"), self, self.copy_to_clipboard)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_as)
        QShortcut(QKeySequence("Ctrl+="), self, self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, self._reset_zoom)
        QShortcut(QKeySequence("Left"), self, self.navigate_prev)
        QShortcut(QKeySequence("Right"), self, self.navigate_next)

    # ── Styles ──────────────────────────────────────────────────────────

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
        C = self._theme_color
        R = BaseStyles

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {C('WINDOW_BG')};
            }}
            QFrame#bottomBar {{
                background-color: {C('TOOLBAR_BG')};
                border: 1px solid {C('BORDER_COLOR')};
                border-radius: {R.RADIUS_MD}px;
            }}
            QFrame#canvasFrame {{
                background-color: {C('INPUT_BG')};
                border: 1px solid {C('BORDER_COLOR')};
                border-radius: {R.RADIUS_LG}px;
            }}
            QPushButton {{
                background-color: {C('BUTTON_BG')};
                color: {C('TEXT_PRIMARY')};
                border: 1px solid {C('BORDER_COLOR')};
                border-radius: {R.RADIUS_SM}px;
                padding: 0;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {C('BUTTON_HOVER')};
                border-color: {C('BORDER_FOCUS')};
            }}
            QPushButton:pressed {{
                background-color: {C('BUTTON_PRESSED')};
            }}
            QPushButton#danger:hover {{
                background-color: {C('BUTTON_DANGER')};
                border-color: {C('BUTTON_DANGER')};
                color: #ffffff;
            }}
            QPushButton#danger:pressed {{
                background-color: {C('BUTTON_DANGER_HOVER')};
                border-color: {C('BUTTON_DANGER_HOVER')};
                color: #ffffff;
            }}
            QLabel {{
                color: {C('TEXT_PRIMARY')};
                background: transparent;
            }}
            QLabel#metaLabel, QLabel#pathLabel, QLabel#navLabel, QLabel#zoomLabel {{
                color: {C('TEXT_SECONDARY')};
                font-size: 11px;
            }}
            QLabel#imageLabel {{
                background: transparent;
            }}
        """)

        if hasattr(self, '_info_label'):
            self._info_label.setStyleSheet(
                f"color: {C('TEXT_SECONDARY')}; font-size: 11px;"
            )
        if hasattr(self, '_scroll'):
            self._scroll.setStyleSheet(
                f"QScrollArea {{ background-color: transparent; border: none; }}"
                f"{BaseStyles.SCROLLBAR_STYLE()}"
            )
        if hasattr(self, '_nav_label'):
            self._nav_label.setStyleSheet(
                f"color: {C('TEXT_SECONDARY')}; font-size: 11px;"
            )
        self._refresh_button_icons()

    # ── UI ──────────────────────────────────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_canvas(), stretch=1)
        root.addWidget(self._build_bottom_bar())

    def _build_bottom_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("bottomBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        self._path_label = QLabel("")
        self._path_label.setObjectName("pathLabel")
        self._path_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._path_label.setMinimumWidth(160)
        self._path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._path_label.setToolTip("Screenshot file path")
        layout.addWidget(self._path_label, stretch=1)

        self._info_label = QLabel("")
        self._info_label.setObjectName("metaLabel")
        self._info_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._info_label.setMinimumWidth(96)
        self._info_label.setToolTip("Image size and file size")
        layout.addWidget(self._info_label, stretch=0)

        layout.addSpacing(6)

        self._prev_btn = self._tool_button("caret-left.svg", "Previous screenshot (Left)")
        self._prev_btn.clicked.connect(self.navigate_prev)
        layout.addWidget(self._prev_btn)

        self._nav_label = QLabel("1 / 1")
        self._nav_label.setObjectName("navLabel")
        self._nav_label.setAlignment(Qt.AlignCenter)
        self._nav_label.setFixedWidth(52)
        self._nav_label.setToolTip("Current screenshot index")
        layout.addWidget(self._nav_label)

        self._next_btn = self._tool_button("caret-right.svg", "Next screenshot (Right)")
        self._next_btn.clicked.connect(self.navigate_next)
        layout.addWidget(self._next_btn)

        layout.addSpacing(4)

        self._zoom_out_btn = self._tool_button("magnifying-glass-minus.svg", "Zoom out (Ctrl+-)")
        self._zoom_out_btn.clicked.connect(self.zoom_out)
        layout.addWidget(self._zoom_out_btn)

        self._zoom_label = QLabel("Fit")
        self._zoom_label.setObjectName("zoomLabel")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setFixedWidth(48)
        self._zoom_label.setToolTip("Current zoom")
        layout.addWidget(self._zoom_label)

        self._zoom_in_btn = self._tool_button("magnifying-glass-plus.svg", "Zoom in (Ctrl+=)")
        self._zoom_in_btn.clicked.connect(self.zoom_in)
        layout.addWidget(self._zoom_in_btn)

        self._fit_btn = self._tool_button("frame-corners.svg", "Fit to window (Ctrl+0)")
        self._fit_btn.clicked.connect(self._reset_zoom)
        layout.addWidget(self._fit_btn)

        self._actual_btn = self._tool_button("number-square-one.svg", "Actual size")
        self._actual_btn.clicked.connect(self._actual_size)
        layout.addWidget(self._actual_btn)

        layout.addSpacing(4)

        self._copy_btn = self._tool_button("copy.svg", "Copy to clipboard (Ctrl+C)")
        self._copy_btn.clicked.connect(self.copy_to_clipboard)
        layout.addWidget(self._copy_btn)

        self._save_btn = self._tool_button("floppy-disk.svg", "Save as (Ctrl+S)")
        self._save_btn.clicked.connect(self.save_as)
        layout.addWidget(self._save_btn)

        self._folder_btn = self._tool_button("folder-open.svg", "Open file location")
        self._folder_btn.clicked.connect(self._open_file_location)
        layout.addWidget(self._folder_btn)

        self._delete_btn = self._tool_button("trash.svg", "Delete screenshot")
        self._delete_btn.setObjectName("danger")
        self._delete_btn.clicked.connect(self._delete_file)
        layout.addWidget(self._delete_btn)

        self._update_nav_visibility()
        self._bottom_bar = bar
        return bar

    def _build_canvas(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("canvasFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignCenter)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(f"QScrollArea {{ background-color: transparent; border: none; }}")
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._image_label = QLabel()
        self._image_label.setObjectName("imageLabel")
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._image_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self._image_label.customContextMenuRequested.connect(self._on_context_menu)

        self._scroll.setWidget(self._image_label)
        layout.addWidget(self._scroll)
        return frame

    def _tool_button(self, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setIcon(get_themed_icon(icon_name))
        button.setIconSize(QSize(15, 15))
        button.setFixedSize(28, 26)
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

    # ── Image loading ───────────────────────────────────────────────────

    def _current_path(self) -> str:
        if 0 <= self._current_idx < len(self._image_paths):
            return self._image_paths[self._current_idx]
        return ""

    def _navigate_to(self, index: int):
        if not self._image_paths or index < 0 or index >= len(self._image_paths):
            return
        self._current_idx = index
        path = self._current_path()
        if not path or not os.path.exists(path):
            self._image_paths.pop(index)
            if self._image_paths:
                new_idx = min(index, len(self._image_paths) - 1)
                self._navigate_to(new_idx)
            else:
                self._show_placeholder("No valid screenshots")
            self._update_nav_visibility()
            return
        self._original_pixmap = QPixmap(path)
        if self._original_pixmap.isNull():
            self._image_paths.pop(index)
            if self._image_paths:
                new_idx = min(index, len(self._image_paths) - 1)
                self._navigate_to(new_idx)
            else:
                self._show_placeholder("Failed to load any screenshot")
            self._update_nav_visibility()
            return
        self._fit_to_window = True
        self._zoom_factor = 1.0
        self._apply_fit()
        self._update_info()
        self._update_nav_label()
        self._update_nav_visibility()

    def _apply_fit(self):
        if self._original_pixmap is None or self._original_pixmap.isNull():
            return
        scroll_size = self._scroll.viewport().size()
        max_w = max(scroll_size.width() - 8, 200)
        max_h = max(scroll_size.height() - 8, 150)
        pw, ph = self._original_pixmap.width(), self._original_pixmap.height()
        scale = min(max_w / pw, max_h / ph, 1.0)
        self._zoom_factor = scale
        self._fit_to_window = True
        scaled = self._original_pixmap.scaled(
            int(pw * scale), int(ph * scale),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self._image_label.adjustSize()
        self._update_zoom_label()

    def _apply_custom_zoom(self):
        if self._original_pixmap is None or self._original_pixmap.isNull():
            return
        pw, ph = self._original_pixmap.width(), self._original_pixmap.height()
        scaled = self._original_pixmap.scaled(
            int(pw * self._zoom_factor), int(ph * self._zoom_factor),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self._image_label.adjustSize()
        self._update_zoom_label()

    def _show_placeholder(self, text: str):
        self._original_pixmap = None
        self._info_label.setText(text)
        self._path_label.setText("")
        self._path_label.setToolTip("")
        self._image_label.setText(text)
        self._image_label.setStyleSheet(
            f"color: {self._theme_color('TEXT_DISABLED')}; font-size: 14px; padding: 60px;"
        )
        self._image_label.adjustSize()

    def navigate_prev(self):
        if len(self._image_paths) <= 1:
            return
        idx = self._current_idx - 1
        if idx < 0:
            idx = len(self._image_paths) - 1
        self._navigate_to(idx)

    def navigate_next(self):
        if len(self._image_paths) <= 1:
            return
        idx = self._current_idx + 1
        if idx >= len(self._image_paths):
            idx = 0
        self._navigate_to(idx)

    # ── Zoom ────────────────────────────────────────────────────────────

    def zoom_in(self):
        self._fit_to_window = False
        self._zoom_factor = min(MAX_ZOOM, self._zoom_factor + ZOOM_STEP)
        self._apply_custom_zoom()

    def zoom_out(self):
        self._fit_to_window = False
        self._zoom_factor = max(MIN_ZOOM, self._zoom_factor - ZOOM_STEP)
        self._apply_custom_zoom()

    def _reset_zoom(self):
        if self._fit_to_window and abs(self._zoom_factor - 1.0) < 0.001:
            return
        self._fit_to_window = True
        self._apply_fit()

    def _actual_size(self):
        self._fit_to_window = False
        self._zoom_factor = 1.0
        self._apply_custom_zoom()

    def _update_zoom_label(self):
        if self._fit_to_window:
            pct = int(self._zoom_factor * 100)
            self._zoom_label.setText(f"{pct}%" if pct != 100 else "Fit")
        else:
            self._zoom_label.setText(f"{int(self._zoom_factor * 100)}%")

    # ── Info ────────────────────────────────────────────────────────────

    def _update_info(self):
        path = self._current_path()
        if not path or self._original_pixmap is None:
            self._info_label.setText("")
            return
        pw = self._original_pixmap.width()
        ph = self._original_pixmap.height()
        try:
            size_bytes = os.path.getsize(path)
            if size_bytes >= 1_048_576:
                size_str = f"{size_bytes / 1_048_576:.1f} MB"
            elif size_bytes >= 1024:
                size_str = f"{size_bytes / 1024:.0f} KB"
            else:
                size_str = f"{size_bytes} B"
        except OSError:
            size_str = "-"
        self._info_label.setText(f"{pw} x {ph} | {size_str}")
        full_path = os.path.abspath(path)
        short_path = full_path if len(full_path) <= 76 else "..." + full_path[-73:]
        self._path_label.setText(short_path)
        self._path_label.setToolTip(full_path)

    # ── Navigation UI ───────────────────────────────────────────────────

    def _update_nav_visibility(self):
        visible = len(self._image_paths) > 1
        self._prev_btn.setVisible(visible)
        self._next_btn.setVisible(visible)
        self._nav_label.setVisible(visible)

    def _update_nav_label(self):
        if self._image_paths:
            self._nav_label.setText(f"{self._current_idx + 1} / {len(self._image_paths)}")

    # ── Actions ─────────────────────────────────────────────────────────

    def copy_to_clipboard(self):
        path = self._current_path()
        if not path:
            return
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            QApplication.clipboard().setPixmap(pixmap)
            self._flash_status("Copied")

    def save_as(self):
        path = self._current_path()
        if not path:
            return
        default_name = os.path.basename(path)
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot As", default_name,
            "PNG Images (*.png);;All Files (*)",
        )
        if not dest:
            return
        try:
            with open(path, "rb") as src, open(dest, "wb") as dst:
                dst.write(src.read())
            self._flash_status("Saved")
        except OSError as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))

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
        # Remove from list and stay open for remaining images
        del self._image_paths[self._current_idx]
        if self._image_paths:
            new_idx = min(self._current_idx, len(self._image_paths) - 1)
            self._current_idx = new_idx
            self._navigate_to(new_idx)
        else:
            self.close()

    # ── Context menu ────────────────────────────────────────────────────

    def _on_context_menu(self, pos):
        path = self._current_path()
        menu = QMenu(self)
        C = self._theme_color
        menu.setStyleSheet(
            f"QMenu {{ background: {C('PANEL_BG')}; border: 1px solid {C('BORDER_COLOR')}; "
            f"border-radius: {BaseStyles.RADIUS_SM}px; padding: 4px; color: {C('TEXT_PRIMARY')}; }}"
            f"QMenu::item {{ padding: 6px 24px; border-radius: 3px; }}"
            f"QMenu::item:selected {{ background: {C('BUTTON_HOVER')}; }}"
            f"QMenu::separator {{ height: 1px; background: {C('BORDER_COLOR')}; margin: 4px 8px; }}"
        )

        copy_action = menu.addAction("Copy to Clipboard\tCtrl+C")
        copy_action.triggered.connect(self.copy_to_clipboard)
        copy_action.setEnabled(bool(path))

        save_action = menu.addAction("Save As...\tCtrl+S")
        save_action.triggered.connect(self.save_as)
        save_action.setEnabled(bool(path))

        menu.addSeparator()

        folder_action = menu.addAction("Open File Location")
        folder_action.triggered.connect(self._open_file_location)
        folder_action.setEnabled(bool(path and os.path.exists(path)))

        delete_action = menu.addAction("Delete && Close")
        delete_action.triggered.connect(self._delete_file)
        delete_action.setEnabled(bool(path and os.path.exists(path)))

        menu.addSeparator()

        menu.addAction("Zoom In\tCtrl+=").triggered.connect(self.zoom_in)
        menu.addAction("Zoom Out\tCtrl+-").triggered.connect(self.zoom_out)
        menu.addAction("Fit to Window\tCtrl+0").triggered.connect(self._reset_zoom)

        menu.exec(self._image_label.mapToGlobal(pos))

    # ── Wheel zoom ──────────────────────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_to_window:
            QTimer.singleShot(0, self._apply_fit)
