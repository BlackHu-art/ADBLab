from PySide6.QtGui import QFont

class Styles:
    DEFAULT_FONT_SIZE = 10
    LOG_FONT_SIZE = 10
    LOG_FONT = "Consolas"
    INFO_COLOR = "#00FF00"
    WARNING_COLOR = "#FFA500"
    ERROR_COLOR = "#FF0000"
    DEBUG_COLOR = "#888888"
    SUCCESS_COLOR = "#00FF00" 
    CRITICAL_COLOR = "#FF0000"
    LOG_BACKGROUND = "#000000"
    LOG_TEXT_COLOR = "#FFFFFF"
    WINDOW_BACKGROUND = "#f0f0f0"
    # styles.py
    MENU_BAR_BG = "#333333"      # 菜单栏背景色
    MENU_TEXT_COLOR = "#888888"  # 菜单文字颜色
    MENU_ITEM_HOVER = "#404040"  # 菜单项悬停背景
    BORDER_COLOR = "#555555"     # 分割线颜色

    # 在styles.py中添加：
    SCROLLBAR_STYLE = """
        QScrollBar:vertical {
            background: #888888;
            width: 2px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
        /* 手柄必须可见 */
        background: #666666;
        min-height: 20px;
        }
    """

def get_default_font():
    return QFont("Segoe UI", Styles.DEFAULT_FONT_SIZE)
