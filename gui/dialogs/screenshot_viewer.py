"""Screenshot preview dialog with zoom, navigation, and file tools."""

import os
import sys
from datetime import datetime

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

from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar

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
        self.setWindowIcon(get_themed_icon("camera.svg"))
        self.setMinimumSize(600, 400)
        self.resize(900, 650)
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
        BaseStyles.theme_changed.disconnect(self._apply_theme)
        super().closeEvent(event)

    def _apply_theme(self, _name: str = ""):
        apply_dark_title_bar(self)
        C = self._theme_color
        R = BaseStyles

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {C('PANEL_BG')};
            }}
            QPushButton {{
                background-color: {C('BUTTON_BG')};
                color: {C('TEXT_PRIMARY')};
                border: 1px solid {C('BORDER_COLOR')};
                border-radius: {R.RADIUS_SM}px;
                padding: 4px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {C('BUTTON_HOVER')};
                border-color: {C('BORDER_FOCUS')};
            }}
            QPushButton:pressed {{
                background-color: {C('BUTTON_PRESSED')};
            }}
            QLabel {{
                color: {C('TEXT_PRIMARY')};
                background: transparent;
            }}
        """)

        if hasattr(self, '_info_label'):
            self._info_label.setStyleSheet(
                f"color: {C('TEXT_SECONDARY')}; font-size: 11px; padding: 2px 0;"
            )
        if hasattr(self, '_scroll'):
            self._scroll.setStyleSheet(
                f"QScrollArea {{ background-color: {C('INPUT_BG')}; "
                f"border-radius: {BaseStyles.RADIUS_LG}px; border: none; }}"
            )
        if hasattr(self, '_nav_label'):
            self._nav_label.setStyleSheet(
                f"color: {C('TEXT_SECONDARY')}; font-size: 11px; font-weight: bold;"
            )
        if hasattr(self, '_close_btn'):
            self._close_btn.setStyleSheet(
                f"QPushButton {{ background-color: {C('BUTTON_ACCENT')}; color: white; "
                f"border: none; border-radius: {BaseStyles.RADIUS_SM}px; "
                f"padding: 5px 14px; font-size: 12px; font-weight: bold; }}"
                f"QPushButton:hover {{ background-color: {C('BUTTON_ACCENT_HOVER')}; }}"
                f"QPushButton:pressed {{ background-color: {C('BUTTON_ACCENT_PRESSED')}; }}"
            )

    # ── UI ──────────────────────────────────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(4)

        # Info bar
        self._info_label = QLabel()
        self._info_label.setStyleSheet(
            f"color: {self._theme_color('TEXT_SECONDARY')}; font-size: 11px; padding: 2px 0;"
        )
        root.addWidget(self._info_label)

        # Image area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignCenter)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {self._theme_color('INPUT_BG')}; "
            f"border-radius: {BaseStyles.RADIUS_LG}px; border: none; }}"
        )
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._image_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self._image_label.customContextMenuRequested.connect(self._on_context_menu)

        self._scroll.setWidget(self._image_label)
        root.addWidget(self._scroll, stretch=1)

        # Bottom bar
        root.addLayout(self._build_bottom_bar())

    def _build_bottom_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(4)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.setIcon(get_themed_icon("caret-left.svg"))
        self._prev_btn.setIconSize(QSize(14, 14))
        self._prev_btn.setFixedSize(30, 28)
        self._prev_btn.clicked.connect(self.navigate_prev)
        bar.addWidget(self._prev_btn)

        self._nav_label = QLabel("1 / 1")
        self._nav_label.setAlignment(Qt.AlignCenter)
        self._nav_label.setFixedWidth(44)
        self._nav_label.setStyleSheet(
            f"color: {self._theme_color('TEXT_SECONDARY')}; font-size: 11px; font-weight: bold;"
        )
        bar.addWidget(self._nav_label)

        self._next_btn = QPushButton("▶")
        self._next_btn.setIcon(get_themed_icon("caret-right.svg"))
        self._next_btn.setIconSize(QSize(14, 14))
        self._next_btn.setFixedSize(30, 28)
        self._next_btn.clicked.connect(self.navigate_next)
        bar.addWidget(self._next_btn)

        bar.addSpacing(8)

        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setIcon(get_themed_icon("magnifying-glass-minus.svg"))
        zoom_out_btn.setIconSize(QSize(14, 14))
        zoom_out_btn.setFixedSize(30, 28)
        zoom_out_btn.clicked.connect(self.zoom_out)
        bar.addWidget(zoom_out_btn)

        self._zoom_btn = QPushButton("Fit")
        self._zoom_btn.setIcon(get_themed_icon("frame-corners.svg"))
        self._zoom_btn.setIconSize(QSize(14, 14))
        self._zoom_btn.setFixedWidth(52)
        self._zoom_btn.setFixedHeight(28)
        self._zoom_btn.clicked.connect(self._reset_zoom)
        bar.addWidget(self._zoom_btn)

        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setIcon(get_themed_icon("magnifying-glass-plus.svg"))
        zoom_in_btn.setIconSize(QSize(14, 14))
        zoom_in_btn.setFixedSize(30, 28)
        zoom_in_btn.clicked.connect(self.zoom_in)
        bar.addWidget(zoom_in_btn)

        bar.addSpacing(8)

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setIcon(get_themed_icon("copy.svg"))
        self._copy_btn.setIconSize(QSize(14, 14))
        self._copy_btn.setFixedHeight(28)
        self._copy_btn.clicked.connect(self.copy_to_clipboard)
        bar.addWidget(self._copy_btn)

        self._save_btn = QPushButton("Save As")
        self._save_btn.setIcon(get_themed_icon("floppy-disk.svg"))
        self._save_btn.setIconSize(QSize(14, 14))
        self._save_btn.setFixedHeight(28)
        self._save_btn.clicked.connect(self.save_as)
        bar.addWidget(self._save_btn)

        self._folder_btn = QPushButton("Folder")
        self._folder_btn.setIcon(get_themed_icon("folder-open.svg"))
        self._folder_btn.setIconSize(QSize(14, 14))
        self._folder_btn.setFixedHeight(28)
        self._folder_btn.clicked.connect(self._open_file_location)
        bar.addWidget(self._folder_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setIcon(get_themed_icon("trash.svg"))
        self._delete_btn.setIconSize(QSize(14, 14))
        self._delete_btn.setFixedHeight(28)
        self._delete_btn.clicked.connect(self._delete_file)
        bar.addWidget(self._delete_btn)

        self._fit_btn = QPushButton("1:1")
        self._fit_btn.setIcon(get_themed_icon("number-square-one.svg"))
        self._fit_btn.setIconSize(QSize(14, 14))
        self._fit_btn.setFixedHeight(28)
        self._fit_btn.clicked.connect(self._toggle_fit)
        bar.addWidget(self._fit_btn)

        bar.addStretch()

        self._close_btn = QPushButton("Close")
        self._close_btn.setIcon(get_themed_icon("x.svg"))
        self._close_btn.setIconSize(QSize(14, 14))
        self._close_btn.setFixedHeight(28)
        self._close_btn.clicked.connect(self.close)
        bar.addWidget(self._close_btn)

        self._update_nav_visibility()
        return bar

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
        self._image_label.setText(text)
        self._image_label.setStyleSheet(
            f"color: {self._theme_color('TEXT_DISABLED')}; font-size: 14px; padding: 60px;"
        )

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

    def _toggle_fit(self):
        if self._fit_to_window:
            self._fit_to_window = False
            self._zoom_factor = 1.0
            self._apply_custom_zoom()
            self._fit_btn.setText("Fit")
        else:
            self._fit_to_window = True
            self._apply_fit()
            self._fit_btn.setText("1:1")

    def _update_zoom_label(self):
        if self._fit_to_window:
            pct = int(self._zoom_factor * 100)
            self._zoom_btn.setText(f"{pct}%" if pct != 100 else "Fit")
        else:
            self._zoom_btn.setText(f"{int(self._zoom_factor * 100)}%")
        self._fit_btn.setText("Fit" if not self._fit_to_window else "1:1")

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
        try:
            mtime = os.path.getmtime(path)
            time_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except OSError:
            time_str = "-"
        self._info_label.setText(f"{pw}x{ph}  |  {size_str}  |  {time_str}")

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
            self._copy_btn.setText("Copied!")
            QTimer.singleShot(2000, lambda: self._copy_btn.setText("Copy"))

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
            self._save_btn.setText("Saved!")
            QTimer.singleShot(2000, lambda: self._save_btn.setText("Save As"))
        except OSError as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))

    def _open_file_location(self):
        path = self._current_path()
        if not path or not os.path.exists(path):
            return
        folder = os.path.dirname(os.path.abspath(path))
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            import subprocess
            subprocess.Popen(["xdg-open", folder])

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
