"""统一导出 ADBLab 主题、QSS 模板和字体能力。

用法：
    from gui.styles import BaseStyles, get_default_font
"""

from .theme import ThemeMixin
from .qss import QSSMixin
from .fonts import FontMixin, get_default_font


class BaseStyles(ThemeMixin, QSSMixin, FontMixin):
    """组合主题颜色、QSS 模板和字体管理能力。"""
    pass


__all__ = ["BaseStyles", "get_default_font"]
