from PySide6.QtGui import QFont, QColor
from typing import Dict, Any, Final
from dataclasses import dataclass


class Styles:
    
    # 字体常量（保持原有名称）
    DEFAULT_FONT_SIZE: Final[int] = 10
    LOG_FONT_SIZE: Final[int] = 10
    LOG_FONT: Final[str] = "Consolas"
    
    # 颜色常量（保持原有名称）
    INFO_COLOR: Final[str] = "#00FF00"
    WARNING_COLOR: Final[str] = "#FFA500"
    ERROR_COLOR: Final[str] = "#FF0000"
    DEBUG_COLOR: Final[str] = "#888888"
    SUCCESS_COLOR: Final[str] = "#00FF00"
    CRITICAL_COLOR: Final[str] = "#FF0000"
    LOG_BACKGROUND: Final[str] = "#000000"
    LOG_TEXT_COLOR: Final[str] = "#FFFFFF"
    WINDOW_BACKGROUND: Final[str] = "#f0f0f0"
    
    # CustomMenuBar专用颜色（保持原有名称）
    MENU_BAR_BG: Final[str] = "#f0f0f0"
    MENU_TEXT_COLOR: Final[str] = "#000000"
    MENU_ITEM_HOVER: Final[str] = "#eeeee4"
    BORDER_COLOR: Final[str] = "#555555"
    MENU_ITEM_PRESSED: Final[str] = "#dddddd"
    
    # 滚动条样式（保持原有实现）
    SCROLLBAR_STYLE: Final[str] = """
        QScrollBar:vertical {
            background: #888888;
            width: 2px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #666666;
            min-height: 20px;
        }
    """
    
    # 新增的样式组（不影响兼容性）
    class Palette:
        """颜色调色板（扩展用）"""
        PRIMARY = "#3498db"
        SECONDARY = "#2ecc71"
        DANGER = "#e74c3c"
    
    @classmethod
    def get_default_font(cls) -> QFont:
        """
        获取默认字体（保持与原有实现完全兼容）
        返回:
            QFont: 配置好的字体对象
        """
        font = QFont("Segoe UI", cls.DEFAULT_FONT_SIZE)
        font.setStyleHint(QFont.SansSerif)
        return font
    
    @classmethod
    def get_log_font(cls) -> QFont:
        """
        获取日志专用字体（新增方法）
        返回:
            QFont: 配置好的等宽字体对象
        """
        font = QFont(cls.LOG_FONT, cls.LOG_FONT_SIZE)
        font.setStyleHint(QFont.Monospace)
        return font
    
    @classmethod
    def get_color(cls, color_name: str) -> QColor:
        """
        安全获取颜色对象（新增方法）
        参数:
            color_name: 颜色常量名称（如"INFO_COLOR"）
        返回:
            QColor: 对应的颜色对象，找不到时返回黑色
        """
        color_hex = getattr(cls, color_name.upper(), None)
        return QColor(color_hex) if color_hex else QColor("#000000")


# 保持原有导入兼容性
def get_default_font() -> QFont:
    """兼容旧版导入的全局函数"""
    return Styles.get_default_font()