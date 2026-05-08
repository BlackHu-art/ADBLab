"""
Screenshot preview dialog with zoom, navigation, and editing tools.

Features:
- Zoom with Ctrl+Wheel / buttons (0.1x – 5.0x)
- Multi-image navigation (arrow keys, buttons)
- Keyboard shortcuts (Esc, Ctrl+C, Ctrl+S, Ctrl+=, Ctrl+-, Ctrl+0, ←, →)
- Right-click context menu on image
- Info bar (resolution, file size, modification time)
- Save As, Open Folder, Delete File
- Pin / Unpin (toggle always-on-top)
- Fit-to-window / 1:1 toggle
- Frameless window with edge resize on Windows
- Fade-in animation
- Drag to move
"""

import ctypes
import os
import sys
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import (
    QGuiApplication,
    QKeySequence,
    QMouseEvent,
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

from gui.styles.base_styles import BaseStyles

# ── Windows hit-test constants for frameless edge resize ──────────────────
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
EDGE_WIDTH = 6

# ── Zoom limits ───────────────────────────────────────────────────────────
MIN_ZOOM = 0.10
MAX_ZOOM = 5.00
ZOOM_STEP = 0.10


class ScreenshotViewer(QDialog):
    """Modal screenshot preview with zoom, multi-nav, and file tools."""

    def __init__(self, image_paths: list, current_index: int = 0, parent=None):
        super().__init__(parent)
        self._image_paths = list(image_paths) if image_paths else []
        self._current_idx = (
            max(0, min(current_index, len(self._image_paths) - 1)) if self._image_paths else 0
        )
        self._zoom_factor = 1.0
        self._fit_to_window = True
        self._original_pixmap = None
        self._drag_pos = QPoint()
        self._resize_edge = 0
        self._pinned = True
        self._closed = False

        self._init_window()
        self._init_shortcuts()
        self._init_ui()

        if self._image_paths:
            self._navigate_to(0)
        else:
            self._show_placeholder("No screenshot available")

        self._start_fade_in()

    # ═══════════════════════════════════════════════════════════════════════
    # Window setup
    # ═══════════════════════════════════════════════════════════════════════

    def _init_window(self) -> None:
        self.setWindowTitle("Screenshot Viewer")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(360, 260)
        self.setStyleSheet(self._window_qss())

    def _init_shortcuts(self) -> None:
        QShortcut(QKeySequence("Esc"), self, self.close)
        QShortcut(QKeySequence("Ctrl+C"), self, self.copy_to_clipboard)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_as)
        QShortcut(QKeySequence("Ctrl+="), self, self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, self._reset_zoom)
        QShortcut(QKeySequence("Left"), self, self.navigate_prev)
        QShortcut(QKeySequence("Right"), self, self.navigate_next)

    # ═══════════════════════════════════════════════════════════════════════
    # Styles
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _c(key: str) -> str:
        return BaseStyles.color(key)

    def _window_qss(self) -> str:
        C = self._c
        R = BaseStyles
        return f"""
        QDialog {{
            background-color: {C('PANEL_BG')};
            border-radius: {R.RADIUS_XL}px;
            border: 1px solid {C('BORDER_COLOR')};
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
        """

    def _tool_btn_qss(self) -> str:
        C = self._c
        return (
            f"QPushButton {{ background: transparent; border: none; "
            f"color: {C('TEXT_SECONDARY')}; font-size: 14px; border-radius: 4px; padding: 2px; }}"
            f"QPushButton:hover {{ background: {C('BUTTON_HOVER')}; color: {C('TEXT_PRIMARY')}; }}"
        )

    def _close_btn_qss(self) -> str:
        C = self._c
        return (
            f"QPushButton {{ background: transparent; border: none; "
            f"color: {C('TEXT_SECONDARY')}; font-size: 15px; border-radius: 4px; padding: 2px; }}"
            f"QPushButton:hover {{ background: {C('BUTTON_DANGER')}; color: white; }}"
        )

    def _accent_btn_qss(self) -> str:
        C = self._c
        return (
            f"QPushButton {{ background-color: {C('BUTTON_ACCENT')}; color: white; "
            f"border: none; border-radius: {BaseStyles.RADIUS_SM}px; "
            f"padding: 5px 14px; font-size: 12px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {C('BUTTON_ACCENT_HOVER')}; }}"
            f"QPushButton:pressed {{ background-color: {C('BUTTON_ACCENT_PRESSED')}; }}"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # UI construction
    # ═══════════════════════════════════════════════════════════════════════

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 12)
        root.setSpacing(6)

        root.addLayout(self._build_top_bar())
        self._build_image_area(root)
        root.addLayout(self._build_bottom_bar())

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        self._info_label = QLabel()
        self._info_label.setStyleSheet(
            f"color: {self._c('TEXT_SECONDARY')}; font-size: 11px; padding: 3px 0;"
        )
        bar.addWidget(self._info_label)
        bar.addStretch()

        self._pin_btn = self._make_tool_btn("📌", "Unpin (toggle always-on-top)", self._toggle_pin)
        bar.addWidget(self._pin_btn)

        self._delete_btn = self._make_tool_btn("🗑", "Delete file", self._delete_file)
        bar.addWidget(self._delete_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setToolTip("Close (Esc)")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(self._close_btn_qss())
        close_btn.clicked.connect(self.close)
        bar.addWidget(close_btn)

        return bar

    def _build_image_area(self, root: QVBoxLayout) -> None:
        C = self._c
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignCenter)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {C('INPUT_BG')}; "
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

    def _build_bottom_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        # ── Navigation ────────────────────────────────────────────────
        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedSize(30, 28)
        self._prev_btn.setToolTip("Previous (←)")
        self._prev_btn.clicked.connect(self.navigate_prev)
        bar.addWidget(self._prev_btn)

        self._nav_label = QLabel("1 / 1")
        self._nav_label.setAlignment(Qt.AlignCenter)
        self._nav_label.setFixedWidth(48)
        self._nav_label.setStyleSheet(
            f"color: {self._c('TEXT_SECONDARY')}; font-size: 11px; font-weight: bold;"
        )
        bar.addWidget(self._nav_label)

        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedSize(30, 28)
        self._next_btn.setToolTip("Next (→)")
        self._next_btn.clicked.connect(self.navigate_next)
        bar.addWidget(self._next_btn)

        bar.addSpacing(10)

        # ── Zoom ──────────────────────────────────────────────────────
        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFixedSize(30, 28)
        zoom_out_btn.setToolTip("Zoom Out (Ctrl+-)")
        zoom_out_btn.clicked.connect(self.zoom_out)
        bar.addWidget(zoom_out_btn)

        self._zoom_btn = QPushButton("Fit")
        self._zoom_btn.setFixedWidth(54)
        self._zoom_btn.setFixedHeight(28)
        self._zoom_btn.setToolTip("Reset / Fit (Ctrl+0)")
        self._zoom_btn.clicked.connect(self._reset_zoom)
        bar.addWidget(self._zoom_btn)

        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedSize(30, 28)
        zoom_in_btn.setToolTip("Zoom In (Ctrl+=)")
        zoom_in_btn.clicked.connect(self.zoom_in)
        bar.addWidget(zoom_in_btn)

        bar.addStretch()

        # ── Actions ───────────────────────────────────────────────────
        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setFixedHeight(28)
        self._copy_btn.setToolTip("Copy to Clipboard (Ctrl+C)")
        self._copy_btn.clicked.connect(self.copy_to_clipboard)
        bar.addWidget(self._copy_btn)

        self._save_btn = QPushButton("Save As")
        self._save_btn.setFixedHeight(28)
        self._save_btn.setToolTip("Save As... (Ctrl+S)")
        self._save_btn.clicked.connect(self.save_as)
        bar.addWidget(self._save_btn)

        self._folder_btn = QPushButton("Folder")
        self._folder_btn.setFixedHeight(28)
        self._folder_btn.setToolTip("Open file location")
        self._folder_btn.clicked.connect(self._open_file_location)
        bar.addWidget(self._folder_btn)

        self._fit_btn = QPushButton("1:1")
        self._fit_btn.setFixedHeight(28)
        self._fit_btn.setToolTip("Toggle Fit / 100%")
        self._fit_btn.clicked.connect(self._toggle_fit)
        bar.addWidget(self._fit_btn)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(28)
        close_btn.setToolTip("Close (Esc)")
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet(self._accent_btn_qss())
        bar.addWidget(close_btn)

        self._update_nav_visibility()
        return bar

    def _make_tool_btn(self, text: str, tooltip: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(28, 28)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(self._tool_btn_qss())
        btn.clicked.connect(slot)
        return btn

    # ═══════════════════════════════════════════════════════════════════════
    # Image loading & display
    # ═══════════════════════════════════════════════════════════════════════

    def _current_path(self) -> str:
        if 0 <= self._current_idx < len(self._image_paths):
            return self._image_paths[self._current_idx]
        return ""

    def _navigate_to(self, index: int) -> None:
        if not self._image_paths or index < 0 or index >= len(self._image_paths):
            return
        self._current_idx = index
        self._original_pixmap = QPixmap(self._current_path())
        if self._original_pixmap.isNull():
            self._show_placeholder("Failed to load image")
            return

        self._fit_to_window = True
        self._zoom_factor = 1.0
        self._apply_fit()
        self._update_info()
        self._update_nav_label()

    def _apply_fit(self) -> None:
        """Scale pixmap to fit the scroll area, then size the window."""
        if self._original_pixmap is None or self._original_pixmap.isNull():
            return

        screen = QGuiApplication.primaryScreen().availableGeometry()
        max_w = int(screen.width() * 0.70)
        max_h = int(screen.height() * 0.70)

        pw, ph = self._original_pixmap.width(), self._original_pixmap.height()
        scale = min(max_w / pw, max_h / ph, 1.0)
        self._zoom_factor = scale
        self._fit_to_window = True

        scaled = self._original_pixmap.scaled(
            int(pw * scale),
            int(ph * scale),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self._image_label.adjustSize()
        self._update_zoom_label()
        self._adjust_window_for_pixmap(scaled)

    def _apply_custom_zoom(self) -> None:
        """Scale pixmap by the current zoom factor."""
        if self._original_pixmap is None or self._original_pixmap.isNull():
            return

        pw, ph = self._original_pixmap.width(), self._original_pixmap.height()
        scaled = self._original_pixmap.scaled(
            int(pw * self._zoom_factor),
            int(ph * self._zoom_factor),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self._image_label.adjustSize()
        self._update_zoom_label()

    def _adjust_window_for_pixmap(self, pixmap: QPixmap) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        pad_w, pad_h = 60, 110
        win_w = min(pixmap.width() + pad_w, screen.width() - 40)
        win_h = min(pixmap.height() + pad_h, screen.height() - 40)
        self.resize(win_w, win_h)
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

    def _show_placeholder(self, text: str) -> None:
        self._image_label.setText(text)
        self._image_label.setStyleSheet(
            f"color: {self._c('TEXT_DISABLED')}; font-size: 14px; padding: 60px;"
        )
        self.resize(400, 300)
        self.move(
            (QGuiApplication.primaryScreen().availableGeometry().width() - 400) // 2,
            (QGuiApplication.primaryScreen().availableGeometry().height() - 300) // 2,
        )

    def navigate_prev(self) -> None:
        if len(self._image_paths) <= 1:
            return
        idx = self._current_idx - 1
        if idx < 0:
            idx = len(self._image_paths) - 1
        self._navigate_to(idx)

    def navigate_next(self) -> None:
        if len(self._image_paths) <= 1:
            return
        idx = self._current_idx + 1
        if idx >= len(self._image_paths):
            idx = 0
        self._navigate_to(idx)

    # ═══════════════════════════════════════════════════════════════════════
    # Zoom
    # ═══════════════════════════════════════════════════════════════════════

    def zoom_in(self) -> None:
        self._fit_to_window = False
        self._zoom_factor = min(MAX_ZOOM, self._zoom_factor + ZOOM_STEP)
        self._apply_custom_zoom()

    def zoom_out(self) -> None:
        self._fit_to_window = False
        self._zoom_factor = max(MIN_ZOOM, self._zoom_factor - ZOOM_STEP)
        self._apply_custom_zoom()

    def _reset_zoom(self) -> None:
        if self._fit_to_window and abs(self._zoom_factor - 1.0) < 0.001:
            return
        self._fit_to_window = True
        self._apply_fit()

    def _toggle_fit(self) -> None:
        if self._fit_to_window:
            self._fit_to_window = False
            self._zoom_factor = 1.0
            self._apply_custom_zoom()
            self._fit_btn.setText("Fit")
        else:
            self._fit_to_window = True
            self._apply_fit()
            self._fit_btn.setText("1:1")

    def _update_zoom_label(self) -> None:
        if self._fit_to_window:
            pct = int(self._zoom_factor * 100)
            self._zoom_btn.setText(f"Fit ({pct}%)" if pct != 100 else "Fit")
        else:
            pct = int(self._zoom_factor * 100)
            self._zoom_btn.setText(f"{pct}%")
        self._fit_btn.setText("Fit" if not self._fit_to_window else "1:1")

    # ═══════════════════════════════════════════════════════════════════════
    # Info bar
    # ═══════════════════════════════════════════════════════════════════════

    def _update_info(self) -> None:
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
            size_str = "—"

        try:
            mtime = os.path.getmtime(path)
            time_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except OSError:
            time_str = "—"

        self._info_label.setText(f"{pw}×{ph}  |  {size_str}  |  {time_str}")

    # ═══════════════════════════════════════════════════════════════════════
    # Navigation UI
    # ═══════════════════════════════════════════════════════════════════════

    def _update_nav_visibility(self) -> None:
        visible = len(self._image_paths) > 1
        self._prev_btn.setVisible(visible)
        self._next_btn.setVisible(visible)
        self._nav_label.setVisible(visible)

    def _update_nav_label(self) -> None:
        if self._image_paths:
            self._nav_label.setText(f"{self._current_idx + 1} / {len(self._image_paths)}")

    # ═══════════════════════════════════════════════════════════════════════
    # Actions
    # ═══════════════════════════════════════════════════════════════════════

    def copy_to_clipboard(self) -> None:
        path = self._current_path()
        if not path:
            return
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            QApplication.clipboard().setPixmap(pixmap)
            self._copy_btn.setText("Copied!")
            QTimer.singleShot(2000, lambda: self._copy_btn.setText("Copy"))

    def save_as(self) -> None:
        path = self._current_path()
        if not path:
            return
        default_name = os.path.basename(path)
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Save Screenshot As",
            default_name,
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

    def _open_file_location(self) -> None:
        path = self._current_path()
        if not path or not os.path.exists(path):
            return
        folder = os.path.dirname(os.path.abspath(path))
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            import subprocess

            subprocess.Popen(["xdg-open", folder])

    def _delete_file(self) -> None:
        path = self._current_path()
        if not path or not os.path.exists(path):
            return
        reply = QMessageBox.question(
            self,
            "Delete Screenshot",
            f"Delete this file permanently?\n\n{os.path.basename(path)}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
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
        if self._current_idx >= len(self._image_paths):
            self._current_idx = len(self._image_paths) - 1
        self._navigate_to(self._current_idx)
        self._update_nav_visibility()

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        if sys.platform == "win32":
            hwnd = int(self.winId())
            if self._pinned:
                ctypes.windll.user32.SetWindowPos(
                    hwnd,
                    -1,
                    0,
                    0,
                    0,
                    0,
                    0x0002 | 0x0001,
                )
                self._pin_btn.setText("📌")
                self._pin_btn.setToolTip("Unpin (toggle always-on-top)")
            else:
                ctypes.windll.user32.SetWindowPos(
                    hwnd,
                    -2,
                    0,
                    0,
                    0,
                    0,
                    0x0002 | 0x0001,
                )
                self._pin_btn.setText("📍")
                self._pin_btn.setToolTip("Pin (toggle always-on-top)")
        else:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, self._pinned)
            self._pin_btn.setText("📌" if self._pinned else "📍")

    # ═══════════════════════════════════════════════════════════════════════
    # Right-click context menu
    # ═══════════════════════════════════════════════════════════════════════

    def _on_context_menu(self, pos) -> None:
        path = self._current_path()
        menu = QMenu(self)
        menu.setStyleSheet(self._menu_qss())

        copy_action = menu.addAction("Copy to Clipboard\tCtrl+C")
        copy_action.triggered.connect(self.copy_to_clipboard)
        copy_action.setEnabled(bool(path))

        save_action = menu.addAction("Save As…\tCtrl+S")
        save_action.triggered.connect(self.save_as)
        save_action.setEnabled(bool(path))

        menu.addSeparator()

        folder_action = menu.addAction("Open File Location")
        folder_action.triggered.connect(self._open_file_location)
        folder_action.setEnabled(bool(path and os.path.exists(path)))

        delete_action = menu.addAction("Delete File")
        delete_action.triggered.connect(self._delete_file)
        delete_action.setEnabled(bool(path and os.path.exists(path)))

        menu.addSeparator()

        zoom_in_action = menu.addAction("Zoom In\tCtrl+=")
        zoom_in_action.triggered.connect(self.zoom_in)

        zoom_out_action = menu.addAction("Zoom Out\tCtrl+-")
        zoom_out_action.triggered.connect(self.zoom_out)

        fit_action = menu.addAction("Fit to Window\tCtrl+0")
        fit_action.triggered.connect(self._reset_zoom)

        menu.addSeparator()

        toggle_pin = menu.addAction("Unpin" if self._pinned else "Pin")
        toggle_pin.triggered.connect(self._toggle_pin)

        menu.exec(self._image_label.mapToGlobal(pos))

    def _menu_qss(self) -> str:
        C = self._c
        return (
            f"QMenu {{ background: {C('PANEL_BG')}; border: 1px solid {C('BORDER_COLOR')}; "
            f"border-radius: {BaseStyles.RADIUS_SM}px; padding: 4px; color: {C('TEXT_PRIMARY')}; }}"
            f"QMenu::item {{ padding: 6px 24px; border-radius: 3px; }}"
            f"QMenu::item:selected {{ background: {C('BUTTON_HOVER')}; }}"
            f"QMenu::separator {{ height: 1px; background: {C('BORDER_COLOR')}; margin: 4px 8px; }}"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Animation
    # ═══════════════════════════════════════════════════════════════════════

    def _start_fade_in(self) -> None:
        self.setWindowOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(180)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.start()

    # ═══════════════════════════════════════════════════════════════════════
    # Mouse: drag-to-move + edge resize
    # ═══════════════════════════════════════════════════════════════════════

    def _cursor_for_edge(self, edge: int):
        return {
            HTLEFT: Qt.SizeHorCursor,
            HTRIGHT: Qt.SizeHorCursor,
            HTTOP: Qt.SizeVerCursor,
            HTBOTTOM: Qt.SizeVerCursor,
            HTTOPLEFT: Qt.SizeFDiagCursor,
            HTBOTTOMRIGHT: Qt.SizeFDiagCursor,
            HTTOPRIGHT: Qt.SizeBDiagCursor,
            HTBOTTOMLEFT: Qt.SizeBDiagCursor,
        }.get(edge)

    def _hit_test(self, pos) -> int:
        """Return the HT* constant for a local position, or 0 for client area."""
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        e = EDGE_WIDTH
        left = x < e
        right = x > w - e
        top = y < e
        bottom = y > h - e
        if top and left:
            return HTTOPLEFT
        if top and right:
            return HTTOPRIGHT
        if bottom and left:
            return HTBOTTOMLEFT
        if bottom and right:
            return HTBOTTOMRIGHT
        if left:
            return HTLEFT
        if right:
            return HTRIGHT
        if top:
            return HTTOP
        if bottom:
            return HTBOTTOM
        return 0

    def _is_on_interactive(self, pos) -> bool:
        """Check whether the position is over a button or scrollbar (skip drag)."""
        widget = self.childAt(pos)
        if widget is None:
            return False
        from PySide6.QtWidgets import QPushButton, QScrollBar

        while widget is not None:
            if isinstance(widget, (QPushButton, QScrollBar)):
                return True
            widget = widget.parentWidget()
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)

        edge = self._hit_test(event.position().toPoint())
        if edge != 0:
            self._resize_edge = edge
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()
            return

        if self._is_on_interactive(event.position().toPoint()):
            return super().mousePressEvent(event)

        self._resize_edge = 0
        self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # If in resize mode
        if self._resize_edge != 0 and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            geo = self.frameGeometry()
            edge = self._resize_edge

            if edge in (HTLEFT, HTTOPLEFT, HTBOTTOMLEFT):
                geo.setLeft(geo.left() + delta.x())
            if edge in (HTRIGHT, HTTOPRIGHT, HTBOTTOMRIGHT):
                geo.setRight(geo.right() + delta.x())
            if edge in (HTTOP, HTTOPLEFT, HTTOPRIGHT):
                geo.setTop(geo.top() + delta.y())
            if edge in (HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT):
                geo.setBottom(geo.bottom() + delta.y())

            if geo.width() >= self.minimumWidth() and geo.height() >= self.minimumHeight():
                self.setGeometry(geo)
                if self._fit_to_window and self._original_pixmap:
                    self._apply_fit()

            self._drag_pos = event.globalPosition().toPoint()
            event.accept()
            return

        # If in drag-move mode
        if self._resize_edge == 0 and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return

        # Update cursor for edge hover
        if not (event.buttons() & Qt.LeftButton):
            edge = self._hit_test(event.position().toPoint())
            if edge != 0:
                self.setCursor(self._cursor_for_edge(edge))
            else:
                self.unsetCursor()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._resize_edge = 0
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    # ═══════════════════════════════════════════════════════════════════════
    # Windows native edge-resize (fallback via WM_NCHITTEST)
    # ═══════════════════════════════════════════════════════════════════════

    if sys.platform == "win32":

        def nativeEvent(self, eventType, message):
            if eventType != "windows_generic_MSG":
                return False, 0
            try:
                ptr = int(message)
                msg = ctypes.cast(ptr, ctypes.POINTER(ctypes.wintypes.MSG)).contents
            except Exception:
                return False, 0
            if msg.message != 0x0084:  # WM_NCHITTEST
                return False, 0

            # Convert screen coords
            x = msg.lParam & 0xFFFF
            y = (msg.lParam >> 16) & 0xFFFF
            # Sign-extend (values above 32767 are negative in signed 16-bit)
            if x > 32767:
                x -= 65536
            if y > 32767:
                y -= 65536

            geo = self.frameGeometry()
            edge = EDGE_WIDTH
            left = x < geo.left() + edge
            right = x > geo.right() - edge
            top = y < geo.top() + edge
            bottom = y > geo.bottom() - edge

            if top and left:
                return True, HTTOPLEFT
            if top and right:
                return True, HTTOPRIGHT
            if bottom and left:
                return True, HTBOTTOMLEFT
            if bottom and right:
                return True, HTBOTTOMRIGHT
            if left:
                return True, HTLEFT
            if right:
                return True, HTRIGHT
            if top:
                return True, HTTOP
            if bottom:
                return True, HTBOTTOM
            return False, 0
