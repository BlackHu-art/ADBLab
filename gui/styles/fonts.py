"""ADBLab font configuration and factory methods."""

from PySide6.QtGui import QFont

# -- Mutable font config ------------------------------------------------

_font = {
    "FAMILY": "Segoe UI",
    "UI": 12,
    "LOG": 9,
}

# -- Immutable ----------------------------------------------------------
DEFAULT_FONT_FAMILY = "Segoe UI"
LOG_FONT = "Consolas"
LOG_FONT_SIZE = 9


class FontMixin:
    """Add to BaseStyles via inheritance for font access and reload."""

    DEFAULT_FONT_FAMILY: str = _font["FAMILY"]
    LOG_FONT: str = LOG_FONT
    LOG_FONT_SIZE: int = LOG_FONT_SIZE
    DEFAULT_FONT_SIZE: int = _font["UI"]
    LOG_FONT_SIZE_VAR: int = _font["LOG"]

    @classmethod
    def reload_from_settings(cls):
        from core.settings_manager import AppSettings
        s = AppSettings.instance()
        _font["FAMILY"] = s.get("font_family", "Segoe UI")
        _font["UI"] = s.get("ui_font_size", 12)
        _font["LOG"] = s.get("log_font_size", 9)
        cls.DEFAULT_FONT_FAMILY = _font["FAMILY"]
        cls.DEFAULT_FONT_SIZE = _font["UI"]
        cls.LOG_FONT_SIZE_VAR = _font["LOG"]
        from .theme import _theme_signal, _current_theme
        _theme_signal.changed.emit(_current_theme)

    @classmethod
    def get_default_font(cls, size: int | None = None) -> QFont:
        font = QFont(cls.DEFAULT_FONT_FAMILY, size if size is not None else cls.DEFAULT_FONT_SIZE)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        return font

    @classmethod
    def get_log_font(cls) -> QFont:
        font = QFont(cls.LOG_FONT, cls.LOG_FONT_SIZE)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        return font


def get_default_font() -> QFont:
    return FontMixin.get_default_font()
