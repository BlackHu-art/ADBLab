"""提供 ADBLab 主题颜色、变化信号和主题切换能力。"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal

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
        "WINDOW_BG": "#F3F3F3",
        "PANEL_BG": "#FBFBFB",
        "INPUT_BG": "#FFFFFF",
        "INPUT_BG_HOVER": "#F7F7F7",
        "BUTTON_BG": "#FFFFFF",
        "BUTTON_HOVER": "#F6F6F6",
        "BUTTON_PRESSED": "#EDEDED",
        "BUTTON_ACCENT": "#0F6CBD",
        "BUTTON_ACCENT_HOVER": "#115EA3",
        "BUTTON_ACCENT_PRESSED": "#0C3B5E",
        "BUTTON_DANGER": "#d32f2f",
        "BUTTON_DANGER_HOVER": "#c62828",
        "TEXT_PRIMARY": "#1B1A19",
        "TEXT_SECONDARY": "#605E5C",
        "TEXT_DISABLED": "#A19F9D",
        "TEXT_PLACEHOLDER": "#757575",
        "BORDER_COLOR": "#E1DFDD",
        "BORDER_FOCUS": "#0F6CBD",
        "SELECTION_BG": "#D7EAF8",
        "SELECTION_TEXT": "#1B1A19",
        "SCROLLBAR_BG": "#F3F3F3",
        "SCROLLBAR_HANDLE": "#C8C6C4",
        "SCROLLBAR_HANDLE_HOVER": "#A19F9D",
        "TOOLBAR_BG": "#F7F7F7",
        "LOG_BACKGROUND": "#FBFBFB",
        "LOG_TEXT_COLOR": "#1B1A19",
        "LOG_DEBUG": "#6C757D",
        "LOG_INFO": "#006D77",
        "LOG_SUCCESS": "#167D2D",
        "LOG_WARNING": "#8A5A00",
        "LOG_ERROR": "#DC3545",
        "LOG_CRITICAL": "#C51162",
        "LOG_TIMESTAMP": "#6C757D",
        "GROUP_TITLE_COLOR": "#0F6CBD",
        "TITLE_COLOR": "#1B1A19",
    },
    "Dark": {
        "WINDOW_BG": "#202020",
        "PANEL_BG": "#2B2B2B",
        "INPUT_BG": "#323232",
        "INPUT_BG_HOVER": "#383838",
        "BUTTON_BG": "#333333",
        "BUTTON_HOVER": "#3D3D3D",
        "BUTTON_PRESSED": "#292929",
        "BUTTON_ACCENT": "#0F6CBD",
        "BUTTON_ACCENT_HOVER": "#115EA3",
        "BUTTON_ACCENT_PRESSED": "#0C3B5E",
        "BUTTON_DANGER": "#A62F2F",
        "BUTTON_DANGER_HOVER": "#B83939",
        "TEXT_PRIMARY": "#F3F2F1",
        "TEXT_SECONDARY": "#C8C6C4",
        "TEXT_DISABLED": "#777777",
        "TEXT_PLACEHOLDER": "#A19F9D",
        "BORDER_COLOR": "#484848",
        "BORDER_FOCUS": "#60CDFF",
        "SELECTION_BG": "#123B55",
        "SELECTION_TEXT": "#FFFFFF",
        "SCROLLBAR_BG": "#202020",
        "SCROLLBAR_HANDLE": "#5A5A5A",
        "SCROLLBAR_HANDLE_HOVER": "#777777",
        "TOOLBAR_BG": "#292929",
        "LOG_BACKGROUND": "#202020",
        "LOG_TEXT_COLOR": "#F3F2F1",
        "LOG_DEBUG": "#8B949E",
        "LOG_INFO": "#58A6FF",
        "LOG_SUCCESS": "#3FB950",
        "LOG_WARNING": "#E3B341",
        "LOG_ERROR": "#F85149",
        "LOG_CRITICAL": "#FF6B9D",
        "LOG_TIMESTAMP": "#8B949E",
        "GROUP_TITLE_COLOR": "#60CDFF",
        "TITLE_COLOR": "#F3F2F1",
    },
}

_current_theme: str = "Light"
_theme_mode: str = "System"
_accent_color: str = "#0F6CBD"


class ThemeSignal(QObject):
    """发布主题变化信号。"""

    changed = Signal(str)
    accent_changed = Signal(str)


_theme_signal = ThemeSignal()
theme_changed = _theme_signal.changed
accent_color_changed = _theme_signal.accent_changed


def _tc(key: str) -> str:
    """读取当前主题颜色，缺失时依次回退到浅色主题和黑色。"""
    if key == "BUTTON_ACCENT":
        return _accent_color.lower()
    if key == "BORDER_FOCUS":
        return _accent_color.lower()
    return THEMES[_current_theme].get(key, THEMES["Light"].get(key, "#000000"))


def _sync_qfluentwidgets_theme() -> None:
    """把当前主题与强调色同步给 qfluentwidgets（UI 重做迁移桥接）。

    qfluentwidgets 组件在 Phase 2/3 才逐步接入，本函数先把 ADBLab 的明暗主题与
    ``BUTTON_ACCENT`` 强调色映射到其全局 ``setTheme``/``setThemeColor``，使后续接入的
    组件自动跟随主题切换。采用局部导入，避免所有仅读样式或跑测试的代码在 import 期
    加载整个 qfluentwidgets 包。
    """
    from PySide6.QtGui import QGuiApplication
    from qfluentwidgets import Theme, setTheme, setThemeColor

    if _theme_mode == "System":
        style_hints = (
            QGuiApplication.styleHints()
            if QGuiApplication.instance() is not None
            else None
        )
        scheme = style_hints.colorScheme() if style_hints is not None else None
        qfw_theme = (
            Theme.DARK if scheme == Qt.ColorScheme.Dark else Theme.LIGHT
        )
    else:
        qfw_theme = {"Dark": Theme.DARK, "Light": Theme.LIGHT}[_theme_mode]
    setTheme(qfw_theme)
    setThemeColor(_accent_color)


def _resolve_qfluentwidgets_theme() -> str:
    """读取 qfluentwidgets 已解析的实际明暗主题。"""

    from qfluentwidgets import isDarkTheme

    return "Dark" if isDarkTheme() else "Light"


def _application_palette():
    """由当前主题 token 构建全局 QPalette，用于主题化纯 Qt 控件。

    qfluentwidgets 只主题化它自己的控件，原生 ``QWidget``/``QDialog``/``QHeaderView``
    等纯 Qt 容器的文字色、背景和选区仍需由全局调色板提供。调色板统一由当前语义 token 映射，
    避免页面宿主和 Fluent 控件分别维护两套颜色来源。
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
    if isinstance(app, QApplication):
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
    accent_color_changed = accent_color_changed

    @classmethod
    def theme_names(cls):
        return ["System", "Light", "Dark"]

    @classmethod
    def current_theme(cls) -> str:
        return _theme_mode

    @classmethod
    def resolved_theme(cls) -> str:
        return _current_theme

    @classmethod
    def switch_theme(cls, name: str):
        global _current_theme, _theme_mode
        aliases = {"Auto": "System", "System": "System", "Light": "Light", "Dark": "Dark"}
        mode = aliases.get(str(name), "System")
        _theme_mode = mode
        _sync_qfluentwidgets_theme()
        _current_theme = _resolve_qfluentwidgets_theme()
        _sync_application_palette()
        _theme_signal.changed.emit(mode)

    @classmethod
    def toggle_theme(cls) -> str:
        next_theme = "Dark" if _current_theme == "Light" else "Light"
        cls.switch_theme(next_theme)
        return next_theme

    @classmethod
    def accent_color(cls) -> str:
        return _accent_color

    @classmethod
    def set_accent_color(cls, color: str) -> str:
        """校验并应用 Fluent 强调色，返回最终使用的十六进制颜色。"""

        global _accent_color
        previous = _accent_color
        value = str(color).strip().upper()
        if len(value) != 7 or not value.startswith("#"):
            value = "#0F6CBD"
        try:
            int(value[1:], 16)
        except ValueError:
            value = "#0F6CBD"
        _accent_color = value
        from qfluentwidgets import setThemeColor

        setThemeColor(value)
        _sync_application_palette()
        if value != previous:
            _theme_signal.accent_changed.emit(value)
        return value

    @classmethod
    def color(cls, key: str) -> str:
        return _tc(key)

    @classmethod
    def color_for(cls, theme: str, key: str) -> str:
        """按指定主题（``Light``/``Dark``）读取 token 颜色。

        供需要同时固化明暗两套颜色的控件（如 qfluentwidgets 标签的
        ``setTextColor(light, dark)``）使用，避免跨主题读取当前主题色。
        """

        if key in {"BUTTON_ACCENT", "BORDER_FOCUS"}:
            return _accent_color.lower()

        from .tokens import color_token_for

        return color_token_for(theme, key)

    @classmethod
    def get_color(cls, color_name: str) -> QColor:
        from PySide6.QtGui import QColor

        theme_color = _tc(color_name.upper())
        return QColor(theme_color) if theme_color else QColor("#000000")
