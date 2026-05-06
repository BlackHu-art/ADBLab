"""
Central theme and style system for ADBLab.

Defines Light/Dark color palettes, QSS (Qt Style Sheet) templates,
font constants, and a runtime theme-switching mechanism driven by
ThemeSignal (a QObject Signal that notifies all connected widgets).
"""

from PySide6.QtGui import QFont, QColor
from PySide6.QtCore import Signal, QObject
from typing import Final


class ThemeSignal(QObject):
    """Signal emitter for theme change notifications."""
    changed = Signal(str)


_theme_signal = ThemeSignal()

# ── Theme color definitions ────────────────────────────────────────────────

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
        "BUTTON_DANGER_HOVER": "#e53935",
        "TEXT_PRIMARY": "#1a1a1a",
        "TEXT_SECONDARY": "#666666",
        "TEXT_DISABLED": "#999999",
        "TEXT_PLACEHOLDER": "#888888",
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
        "BUTTON_ACCENT": "#4da6e8",
        "BUTTON_ACCENT_HOVER": "#6dbcf0",
        "BUTTON_ACCENT_PRESSED": "#3d8cc8",
        "BUTTON_DANGER": "#d95555",
        "BUTTON_DANGER_HOVER": "#e87070",
        "TEXT_PRIMARY": "#e0e0e8",
        "TEXT_SECONDARY": "#a8a8b8",
        "TEXT_DISABLED": "#606070",
        "TEXT_PLACEHOLDER": "#707080",
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
        "GROUP_TITLE_COLOR": "#4da6e8",
        "TITLE_COLOR": "#e0e0e8",
    },
}

_current_theme: str = "Light"

# ── Fonts ───────────────────────────────────────────────────────────────────
DEFAULT_FONT_FAMILY: Final[str] = "Segoe UI"
DEFAULT_FONT_SIZE: Final[int] = 11
LOG_FONT: Final[str] = "Consolas"
LOG_FONT_SIZE: Final[int] = 9

# ── Icon sizes ──────────────────────────────────────────────────────────────
ICON_SIZE: Final[int] = 18
TOOLBAR_ICON_SIZE: Final[int] = 16

# ── Log level colors (theme-independent) ────────────────────────────────────
DEBUG_COLOR: Final[str] = "#6C757D"
INFO_COLOR: Final[str] = "#17A2B8"
SUCCESS_COLOR: Final[str] = "#28A745"
WARNING_COLOR: Final[str] = "#FFC107"
ERROR_COLOR: Final[str] = "#DC3545"
CRITICAL_COLOR: Final[str] = "#FF4081"
TIMESTAMP_COLOR: Final[str] = "#6C757D"

# ── Border radius ──────────────────────────────────────────────────────────
RADIUS_SM: Final[int] = 4
RADIUS_MD: Final[int] = 6
RADIUS_LG: Final[int] = 8
RADIUS_XL: Final[int] = 12

# ── Legacy compatibility ────────────────────────────────────────────────────
WINDOW_BACKGROUND: Final[str] = "#f0f0f0"


def _tc(key: str) -> str:
    """Look up a color key in the current theme, falling back to Light default."""
    return THEMES[_current_theme].get(key, THEMES["Light"].get(key, "#000000"))


class BaseStyles:

    # Re-exported module constants
    DEBUG_COLOR = DEBUG_COLOR
    INFO_COLOR = INFO_COLOR
    SUCCESS_COLOR = SUCCESS_COLOR
    WARNING_COLOR = WARNING_COLOR
    ERROR_COLOR = ERROR_COLOR
    CRITICAL_COLOR = CRITICAL_COLOR
    TIMESTAMP_COLOR = TIMESTAMP_COLOR
    RADIUS_SM = RADIUS_SM
    RADIUS_MD = RADIUS_MD
    RADIUS_LG = RADIUS_LG
    RADIUS_XL = RADIUS_XL
    LOG_FONT = LOG_FONT
    LOG_FONT_SIZE = LOG_FONT_SIZE
    DEFAULT_FONT_FAMILY = DEFAULT_FONT_FAMILY
    DEFAULT_FONT_SIZE = DEFAULT_FONT_SIZE
    ICON_SIZE = ICON_SIZE
    TOOLBAR_ICON_SIZE = TOOLBAR_ICON_SIZE
    WINDOW_BACKGROUND = WINDOW_BACKGROUND

    theme_changed = _theme_signal.changed

    # ── Theme management ────────────────────────────────────────────────

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
        """Toggle between Light and Dark themes, returns the new theme name."""
        next_theme = "Dark" if _current_theme == "Light" else "Light"
        cls.switch_theme(next_theme)
        return next_theme

    @classmethod
    def color(cls, key: str) -> str:
        return _tc(key)

    # ── QSS Templates ──────────────────────────────────────────────────

    @classmethod
    def SCROLLBAR_STYLE(cls) -> str:
        return f"""
        QScrollBar:vertical {{
            background: {_tc('SCROLLBAR_BG')};
            width: 8px;
            margin: 2px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {_tc('SCROLLBAR_HANDLE')};
            min-height: 28px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {_tc('SCROLLBAR_HANDLE_HOVER')};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QScrollBar:horizontal {{
            background: {_tc('SCROLLBAR_BG')};
            height: 8px;
            margin: 2px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {_tc('SCROLLBAR_HANDLE')};
            min-width: 28px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {_tc('SCROLLBAR_HANDLE_HOVER')};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: none;
        }}
        """

    @classmethod
    def BUTTON_STYLE(cls) -> str:
        return f"""
        QPushButton {{
            background-color: {_tc('BUTTON_BG')};
            color: {_tc('TEXT_PRIMARY')};
            border: 1px solid {_tc('BORDER_COLOR')};
            border-radius: {RADIUS_MD}px;
            padding: 3px 6px;
            font-family: '{DEFAULT_FONT_FAMILY}';
            font-size: {DEFAULT_FONT_SIZE}px;
        }}
        QPushButton:hover {{
            background-color: {_tc('BUTTON_HOVER')};
            border-color: {_tc('BORDER_FOCUS')};
        }}
        QPushButton:pressed {{
            background-color: {_tc('BUTTON_PRESSED')};
        }}
        QPushButton:disabled {{
            background-color: {_tc('INPUT_BG')};
            color: {_tc('TEXT_DISABLED')};
            border-color: {_tc('BORDER_COLOR')};
        }}
        """

    @classmethod
    def INPUT_STYLE(cls) -> str:
        return f"""
        QLineEdit, QComboBox {{
            background-color: {_tc('INPUT_BG')};
            color: {_tc('TEXT_PRIMARY')};
            border: 1px solid {_tc('BORDER_COLOR')};
            border-radius: {RADIUS_MD}px;
            padding: 3px 6px;
            font-family: '{DEFAULT_FONT_FAMILY}';
            font-size: {DEFAULT_FONT_SIZE}px;
            selection-background-color: {_tc('SELECTION_BG')};
        }}
        QLineEdit:focus, QComboBox:focus {{
            border-color: {_tc('BORDER_FOCUS')};
        }}
        QLineEdit:disabled, QComboBox:disabled {{
            background-color: {_tc('PANEL_BG')};
            color: {_tc('TEXT_DISABLED')};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 20px;
            border-left: 1px solid {_tc('BORDER_COLOR')};
            border-top-right-radius: {RADIUS_MD}px;
            border-bottom-right-radius: {RADIUS_MD}px;
            background-color: {_tc('BUTTON_BG')};
        }}
        QComboBox::drop-down:hover {{
            background-color: {_tc('BUTTON_HOVER')};
        }}
        QComboBox::down-arrow {{
            image: url(resources/icons/dropdown_arrow.svg);
            width: 10px;
            height: 6px;
            margin-right: 4px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {_tc('INPUT_BG')};
            color: {_tc('TEXT_PRIMARY')};
            border: 1px solid {_tc('BORDER_COLOR')};
            border-radius: {RADIUS_SM}px;
            selection-background-color: {_tc('SELECTION_BG')};
            outline: none;
            font-family: 'Courier New', monospace;
        }}
        QComboBox QAbstractItemView::item:hover {{
            background-color: {_tc('BUTTON_HOVER')};
        }}
        """

    @classmethod
    def GROUP_BOX_STYLE(cls) -> str:
        return f"""
        QGroupBox {{
            background-color: {_tc('PANEL_BG')};
            border: 1px solid {_tc('BORDER_COLOR')};
            border-radius: {RADIUS_LG}px;
            margin-top: 8px;
            padding: 6px 6px 4px 6px;
            font-family: '{DEFAULT_FONT_FAMILY}';
            font-size: {DEFAULT_FONT_SIZE}px;
            font-weight: bold;
            color: {_tc('TEXT_PRIMARY')};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 8px;
            left: 10px;
            color: {_tc('GROUP_TITLE_COLOR')};
        }}
        """

    @classmethod
    def LIST_WIDGET_STYLE(cls) -> str:
        return f"""
        QListWidget {{
            background-color: {_tc('INPUT_BG')};
            color: {_tc('TEXT_PRIMARY')};
            border: 1px solid {_tc('BORDER_COLOR')};
            border-radius: {RADIUS_MD}px;
            padding: 2px;
            font-family: 'Courier New';
            font-size: {DEFAULT_FONT_SIZE}px;
            outline: none;
        }}
        QListWidget::item {{
            padding: 3px 6px;
            border-radius: {RADIUS_SM}px;
            color: {_tc('TEXT_PRIMARY')};
        }}
        QListWidget::item:selected {{
            background-color: {_tc('SELECTION_BG')};
            color: {_tc('SELECTION_TEXT')};
        }}
        QListWidget::item:hover {{
            background-color: {_tc('BUTTON_HOVER')};
        }}
        """

    @classmethod
    def TOOLBAR_STYLE(cls) -> str:
        return f"""
        QFrame#toolbar {{
            background-color: {_tc('TOOLBAR_BG')};
            border-radius: {RADIUS_MD}px;
            border: 1px solid {_tc('BORDER_COLOR')};
        }}
        QFrame#toolbar QPushButton {{
            background-color: transparent;
            color: {_tc('TEXT_PRIMARY')};
            border: none;
            border-radius: {RADIUS_SM}px;
            padding: 2px 6px;
            font-family: '{DEFAULT_FONT_FAMILY}';
            font-size: {DEFAULT_FONT_SIZE}px;
        }}
        QFrame#toolbar QPushButton:hover {{
            background-color: {_tc('BUTTON_HOVER')};
        }}
        QFrame#toolbar QPushButton#exit_btn:hover {{
            background-color: {_tc('BUTTON_DANGER')};
            color: #ffffff;
        }}
        QFrame#toolbar QLabel {{
            color: {_tc('TEXT_PRIMARY')};
            font-family: '{DEFAULT_FONT_FAMILY}';
            font-size: {DEFAULT_FONT_SIZE}px;
            font-weight: bold;
        }}
        """

    @classmethod
    def ABOUT_DIALOG_STYLE(cls) -> str:
        return f"""
        QDialog {{
            background-color: {_tc('PANEL_BG')};
            border: 1px solid {_tc('BORDER_COLOR')};
            border-radius: {RADIUS_LG}px;
            font-family: '{DEFAULT_FONT_FAMILY}';
        }}
        QLabel#title {{
            font-size: 18px;
            font-weight: bold;
            color: {_tc('TITLE_COLOR')};
            padding: 20px 0 0 0;
            qproperty-alignment: AlignCenter;
        }}
        QLabel#version {{
            font-size: 12px;
            color: {_tc('TEXT_SECONDARY')};
            padding-bottom: 20px;
            qproperty-alignment: AlignCenter;
        }}
        QLabel#content {{
            font-size: 13px;
            color: {_tc('TEXT_PRIMARY')};
            background-color: {_tc('INPUT_BG')};
            padding: 25px;
            margin: 0 30px;
            border: 1px solid {_tc('BORDER_COLOR')};
            border-radius: {RADIUS_MD}px;
        }}
        QPushButton#close_btn {{
            background-color: {_tc('BUTTON_ACCENT')};
            color: white;
            border: none;
            padding: 8px 24px;
            min-width: 100px;
            font-size: 13px;
            border-radius: {RADIUS_MD}px;
            margin-top: 15px;
        }}
        QPushButton#close_btn:hover {{
            background-color: {_tc('BUTTON_ACCENT_HOVER')};
        }}
        QPushButton#close_btn:pressed {{
            background-color: {_tc('BUTTON_ACCENT_PRESSED')};
        }}
        """

    # ── Composite styles ────────────────────────────────────────────────

    @classmethod
    def PANEL_BASE_STYLE(cls) -> str:
        return (
            cls.BUTTON_STYLE() + cls.INPUT_STYLE() + cls.LIST_WIDGET_STYLE()
            + f"QWidget {{ background-color: {_tc('WINDOW_BG')}; }} "
            + "QFrame { background-color: transparent; border: none; }"
        )

    # ── Font factory methods ────────────────────────────────────────────

    @classmethod
    def get_default_font(cls, size: int = None) -> QFont:
        font = QFont(cls.DEFAULT_FONT_FAMILY, size or cls.DEFAULT_FONT_SIZE)
        font.setStyleHint(QFont.SansSerif)
        font.setHintingPreference(QFont.PreferFullHinting)
        return font

    @classmethod
    def get_log_font(cls) -> QFont:
        font = QFont(cls.LOG_FONT, cls.LOG_FONT_SIZE)
        font.setStyleHint(QFont.Monospace)
        font.setHintingPreference(QFont.PreferFullHinting)
        return font

    @classmethod
    def get_color(cls, color_name: str) -> QColor:
        color_hex = getattr(cls, color_name.upper(), None)
        if color_hex:
            return QColor(color_hex)
        theme_color = _tc(color_name.upper())
        return QColor(theme_color) if theme_color else QColor("#000000")


def get_default_font() -> QFont:
    return BaseStyles.get_default_font()
