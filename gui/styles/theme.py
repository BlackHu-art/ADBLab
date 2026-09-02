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


def _sync_qfluentwidgets_theme() -> None:
    """把当前主题与强调色同步给 qfluentwidgets（UI 重做迁移桥接）。

    qfluentwidgets 组件在 Phase 2/3 才逐步接入，本函数先把 ADBLab 的明暗主题与
    ``BUTTON_ACCENT`` 强调色映射到其全局 ``setTheme``/``setThemeColor``，使后续接入的
    组件自动跟随主题切换。采用局部导入，避免所有仅读样式或跑测试的代码在 import 期
    加载整个 qfluentwidgets 包。
    """
    from qfluentwidgets import Theme, setTheme, setThemeColor

    qfw_theme = Theme.DARK if _current_theme == "Dark" else Theme.LIGHT
    setTheme(qfw_theme)
    setThemeColor(_tc("BUTTON_ACCENT"))


def _application_palette():
    """由当前主题 token 构建全局 QPalette，用于主题化纯 Qt 控件。

    qfluentwidgets 只主题化它自己的控件，原生 ``QWidget``/``QDialog``/``QHeaderView``
    等纯 Qt 控件的文字色/背景/选区仍需由全局调色板提供。此调色板按 token 语义映射，
    与 ``PANEL_BASE_STYLE`` 旧 QSS 的文字色/背景色同源，替换后保持视觉一致。
    """
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(_tc("WINDOW_BG")))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(_tc("TEXT_PRIMARY")))
    palette.setColor(QPalette.ColorRole.Base, QColor(_tc("INPUT_BG")))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(_tc("PANEL_BG")))
    palette.setColor(QPalette.ColorRole.Text, QColor(_tc("TEXT_PRIMARY")))
    palette.setColor(QPalette.ColorRole.Button, QColor(_tc("BUTTON_BG")))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(_tc("TEXT_PRIMARY")))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(_tc("SELECTION_BG")))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(_tc("SELECTION_TEXT")))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(_tc("TEXT_PLACEHOLDER")))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(_tc("PANEL_BG")))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(_tc("TEXT_PRIMARY")))
    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor(_tc("TEXT_DISABLED")))
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor(_tc("TEXT_DISABLED")))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor(_tc("TEXT_DISABLED")))
    return palette


def _sync_application_palette() -> None:
    """把全局 QPalette 同步到 QApplication（主题化纯 Qt 控件的文字色/背景/选区）。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.setPalette(_application_palette())


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
            _sync_application_palette()
            _theme_signal.changed.emit(name)
            _sync_qfluentwidgets_theme()

    @classmethod
    def toggle_theme(cls) -> str:
        next_theme = "Dark" if _current_theme == "Light" else "Light"
        cls.switch_theme(next_theme)
        return next_theme

    @classmethod
    def color(cls, key: str) -> str:
        return _tc(key)

    @classmethod
    def color_for(cls, theme: str, key: str) -> str:
        """按指定主题（``Light``/``Dark``）读取 token 颜色。

        供需要同时固化明暗两套颜色的控件（如 qfluentwidgets 标签的
        ``setTextColor(light, dark)``）使用，避免跨主题读取当前主题色。
        """

        from .tokens import color_token_for

        return color_token_for(theme, key)

    @classmethod
    def get_color(cls, color_name: str) -> QColor:
        from PySide6.QtGui import QColor

        theme_color = _tc(color_name.upper())
        return QColor(theme_color) if theme_color else QColor("#000000")
