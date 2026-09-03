"""统一导出 ADBLab 主题与字体能力。

用法：
    from gui.styles import BaseStyles, get_default_font
"""

from .fonts import FontConfig, FontMixin, FontRole, get_default_font
from .theme import ThemeMixin


class BaseStyles(ThemeMixin, FontMixin):
    """组合主题颜色与字体管理能力。"""

    pass


__all__ = ["BaseStyles", "FontConfig", "FontRole", "get_default_font"]
