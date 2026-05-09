"""ADBLab styles package -- theme, QSS templates, fonts.

Usage:
    from gui.styles.base_styles import BaseStyles, get_default_font
"""

from .theme import ThemeMixin
from .qss import QSSMixin
from .fonts import FontMixin, get_default_font


class BaseStyles(ThemeMixin, QSSMixin, FontMixin):
    """Unified styles: theme colors + QSS templates + font management."""
    pass


__all__ = ["BaseStyles", "get_default_font"]
