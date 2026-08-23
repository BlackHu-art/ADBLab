"""提供 ADBLab 主题颜色、变化信号和主题切换能力。"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget


def apply_dark_title_bar(window: QWidget) -> None:
    """使 Windows 标题栏与当前深色或浅色主题一致。

    允许在任意平台调用；非 Windows 平台不执行操作。
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        dark = 1 if _current_theme == "Dark" else 0
        DWMA_USE_IMMERSIVE_DARK_MODE = 20
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(ctypes.c_int(dark)),
            ctypes.sizeof(ctypes.c_int(dark)),
        )
    except Exception:
        pass  # 远程桌面或旧版 Windows 可能不提供 DWM，此时保留默认标题栏行为。


# ── 主题调色板 ──────────────────────────────────────────────────────────

THEMES = {
    "Light": {
        "WINDOW_BG": "#f0f0f0",
        "PANEL_BG": "#ffffff",
        "INPUT_BG": "#f5f5f5",
        "INPUT_BG_HOVER": "#ebebeb",
        "BUTTON_BG": "#e8e8e8",
        "BUTTON_HOVER": "#d4d4d4",
        "BUTTON_PRESSED": "#cccccc",
        "BUTTON_ACCENT": "#0078d4",
        "BUTTON_ACCENT_HOVER": "#106ebe",
        "BUTTON_ACCENT_PRESSED": "#005a9e",
        "BUTTON_DANGER": "#d32f2f",
        "BUTTON_DANGER_HOVER": "#c62828",
        "TEXT_PRIMARY": "#1a1a1a",
        "TEXT_SECONDARY": "#666666",
        "TEXT_DISABLED": "#999999",
        "TEXT_PLACEHOLDER": "#6b6b6b",
        "BORDER_COLOR": "#d1d1d1",
        "BORDER_FOCUS": "#0078d4",
        "SELECTION_BG": "#cce5ff",
        "SELECTION_TEXT": "#1a1a1a",
        "SCROLLBAR_BG": "#f0f0f0",
        "SCROLLBAR_HANDLE": "#c1c1c1",
        "SCROLLBAR_HANDLE_HOVER": "#a1a1a1",
        "TOOLBAR_BG": "#e8e8e8",
        "LOG_BACKGROUND": "#ffffff",
        "LOG_TEXT_COLOR": "#1a1a1a",
        "LOG_DEBUG": "#6C757D",
        "LOG_INFO": "#006D77",
        "LOG_SUCCESS": "#167D2D",
        "LOG_WARNING": "#8A5A00",
        "LOG_ERROR": "#DC3545",
        "LOG_CRITICAL": "#C51162",
        "LOG_TIMESTAMP": "#6C757D",
        "GROUP_TITLE_COLOR": "#0078d4",
        "TITLE_COLOR": "#1a1a1a",
    },
    "Dark": {
        "WINDOW_BG": "#1a1a24",
        "PANEL_BG": "#212130",
        "INPUT_BG": "#2a2a3a",
        "INPUT_BG_HOVER": "#333350",
        "BUTTON_BG": "#2e2e42",
        "BUTTON_HOVER": "#3d3d58",
        "BUTTON_PRESSED": "#222238",
        "BUTTON_ACCENT": "#286F9F",
        "BUTTON_ACCENT_HOVER": "#347DAA",
        "BUTTON_ACCENT_PRESSED": "#24658F",
        "BUTTON_DANGER": "#A62F2F",
        "BUTTON_DANGER_HOVER": "#B83939",
        "TEXT_PRIMARY": "#e0e0e8",
        "TEXT_SECONDARY": "#a8a8b8",
        "TEXT_DISABLED": "#606070",
        "TEXT_PLACEHOLDER": "#9A9AAA",
        "BORDER_COLOR": "#3d3d50",
        "BORDER_FOCUS": "#4da6e8",
        "SELECTION_BG": "#304060",
        "SELECTION_TEXT": "#ffffff",
        "SCROLLBAR_BG": "#1a1a24",
        "SCROLLBAR_HANDLE": "#454560",
        "SCROLLBAR_HANDLE_HOVER": "#5a5a78",
        "TOOLBAR_BG": "#252538",
        "LOG_BACKGROUND": "#1a1a24",
        "LOG_TEXT_COLOR": "#d8d8e0",
        "LOG_DEBUG": "#8B949E",
        "LOG_INFO": "#58A6FF",
        "LOG_SUCCESS": "#3FB950",
        "LOG_WARNING": "#E3B341",
        "LOG_ERROR": "#F85149",
        "LOG_CRITICAL": "#FF6B9D",
        "LOG_TIMESTAMP": "#8B949E",
        "GROUP_TITLE_COLOR": "#4da6e8",
        "TITLE_COLOR": "#e0e0e8",
    },
}

_current_theme: str = "Light"


class ThemeSignal(QObject):
    """发布主题变化信号。"""

    changed = Signal(str)


_theme_signal = ThemeSignal()
theme_changed = _theme_signal.changed


def _tc(key: str) -> str:
    """读取当前主题颜色，缺失时依次回退到浅色主题和黑色。"""
    return THEMES[_current_theme].get(key, THEMES["Light"].get(key, "#000000"))


# ── 主题管理混入类 ──────────────────────────────────────────────────────


class ThemeMixin:
    """通过 BaseStyles 提供主题切换和颜色访问能力。"""

    RADIUS_SM: int = 4
    RADIUS_MD: int = 6
    RADIUS_LG: int = 8
    RADIUS_XL: int = 12
    ICON_SIZE: int = 18
    TOOLBAR_ICON_SIZE: int = 16

    theme_changed = theme_changed

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

        theme_color = _tc(color_name.upper())
        return QColor(theme_color) if theme_color else QColor("#000000")
