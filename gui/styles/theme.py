"""ADBLab theme colors, signal, and theme switching."""

from __future__ import annotations

import ctypes
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget


def apply_dark_title_bar(window: QWidget) -> None:
    """Set Windows title bar to match the current theme (dark / light).

    Safe to call on any platform — no-op on non-Windows.
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        dark = 1 if _current_theme == "Dark" else 0
        DWMA_USE_IMMERSIVE_DARK_MODE = 20
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.wintypes.HWND(hwnd),
            ctypes.wintypes.DWORD(DWMA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(ctypes.c_int(dark)),
            ctypes.sizeof(ctypes.c_int(dark)),
        )
    except Exception:
        pass  # DWM unavailable (e.g. remote desktop, older Windows)

# -- Theme color palettes ------------------------------------------------

THEMES = {
    "Light": {
        "WINDOW_BG": "#f0f0f0", "PANEL_BG": "#ffffff", "INPUT_BG": "#f5f5f5",
        "INPUT_BG_HOVER": "#ebebeb", "BUTTON_BG": "#e8e8e8", "BUTTON_HOVER": "#d4d4d4",
        "BUTTON_PRESSED": "#cccccc", "BUTTON_ACCENT": "#0078d4", "BUTTON_ACCENT_HOVER": "#106ebe",
        "BUTTON_ACCENT_PRESSED": "#005a9e", "BUTTON_DANGER": "#d32f2f", "BUTTON_DANGER_HOVER": "#e53935",
        "TEXT_PRIMARY": "#1a1a1a", "TEXT_SECONDARY": "#666666", "TEXT_DISABLED": "#999999",
        "TEXT_PLACEHOLDER": "#888888", "BORDER_COLOR": "#d1d1d1", "BORDER_FOCUS": "#0078d4",
        "SELECTION_BG": "#cce5ff", "SELECTION_TEXT": "#1a1a1a", "SCROLLBAR_BG": "#f0f0f0",
        "SCROLLBAR_HANDLE": "#c1c1c1", "SCROLLBAR_HANDLE_HOVER": "#a1a1a1",
        "TOOLBAR_BG": "#e8e8e8", "LOG_BACKGROUND": "#ffffff", "LOG_TEXT_COLOR": "#1a1a1a",
        "GROUP_TITLE_COLOR": "#0078d4", "TITLE_COLOR": "#1a1a1a",
    },
    "Dark": {
        "WINDOW_BG": "#1a1a24", "PANEL_BG": "#212130", "INPUT_BG": "#2a2a3a",
        "INPUT_BG_HOVER": "#333350", "BUTTON_BG": "#2e2e42", "BUTTON_HOVER": "#3d3d58",
        "BUTTON_PRESSED": "#222238", "BUTTON_ACCENT": "#4da6e8", "BUTTON_ACCENT_HOVER": "#6dbcf0",
        "BUTTON_ACCENT_PRESSED": "#3d8cc8", "BUTTON_DANGER": "#d95555", "BUTTON_DANGER_HOVER": "#e87070",
        "TEXT_PRIMARY": "#e0e0e8", "TEXT_SECONDARY": "#a8a8b8", "TEXT_DISABLED": "#606070",
        "TEXT_PLACEHOLDER": "#707080", "BORDER_COLOR": "#3d3d50", "BORDER_FOCUS": "#4da6e8",
        "SELECTION_BG": "#304060", "SELECTION_TEXT": "#ffffff", "SCROLLBAR_BG": "#1a1a24",
        "SCROLLBAR_HANDLE": "#454560", "SCROLLBAR_HANDLE_HOVER": "#5a5a78",
        "TOOLBAR_BG": "#252538", "LOG_BACKGROUND": "#1a1a24", "LOG_TEXT_COLOR": "#d8d8e0",
        "GROUP_TITLE_COLOR": "#4da6e8", "TITLE_COLOR": "#e0e0e8",
    },
}

_current_theme: str = "Light"


class ThemeSignal(QObject):
    """Theme change signal emitter."""
    changed = Signal(str)


_theme_signal = ThemeSignal()


def _tc(key: str) -> str:
    """Get color from current theme; fallback to Light then #000."""
    return THEMES[_current_theme].get(key, THEMES["Light"].get(key, "#000000"))


# -- Theme management mixin ----------------------------------------------

class ThemeMixin:
    """Add to BaseStyles via inheritance for theme switching + color access."""

    # static exports
    DEBUG_COLOR: str = "#6C757D"
    INFO_COLOR: str = "#17A2B8"
    SUCCESS_COLOR: str = "#28A745"
    WARNING_COLOR: str = "#FFC107"
    ERROR_COLOR: str = "#DC3545"
    CRITICAL_COLOR: str = "#FF4081"
    TIMESTAMP_COLOR: str = "#6C757D"
    RADIUS_SM: int = 4
    RADIUS_MD: int = 6
    RADIUS_LG: int = 8
    RADIUS_XL: int = 12
    ICON_SIZE: int = 18
    TOOLBAR_ICON_SIZE: int = 16
    WINDOW_BACKGROUND: str = "#f0f0f0"

    theme_changed = _theme_signal.changed
    settings_changed = _theme_signal.changed

    @classmethod
    def theme_names(cls):
        return list(THEMES.keys())

    @classmethod
    def current_theme(cls) -> str:
        return _current_theme

    @classmethod
    def switch_theme(cls, name: str):
        global _current_theme
        if name in THEMES:
            _current_theme = name
            _theme_signal.changed.emit(name)

    @classmethod
    def toggle_theme(cls) -> str:
        next_theme = "Dark" if _current_theme == "Light" else "Light"
        cls.switch_theme(next_theme)
        return next_theme

    @classmethod
    def color(cls, key: str) -> str:
        return _tc(key)

    @classmethod
    def get_color(cls, color_name: str) -> QColor:
        from PySide6.QtGui import QColor
        color_hex = getattr(cls, color_name.upper(), None)
        if color_hex:
            return QColor(color_hex)
        theme_color = _tc(color_name.upper())
        return QColor(theme_color) if theme_color else QColor("#000000")
