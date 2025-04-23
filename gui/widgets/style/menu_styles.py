from PySide6.QtGui import QColor
from gui.widgets.style.base_styles import Styles

class MenuStyles:
    """菜单专用样式扩展（不修改原有样式）"""
    
    # 从原有样式继承颜色
    MENU_BAR_BG = Styles.MENU_BAR_BG
    MENU_TEXT = Styles.MENU_TEXT_COLOR
    MENU_HOVER = Styles.MENU_ITEM_HOVER
    BORDER = Styles.BORDER_COLOR
    
    # 扩展的菜单样式
    STYLE_SHEET = f"""
        QMenuBar {{
            background-color: {MENU_BAR_BG};
            border-bottom: 1px solid {BORDER};
            font-family: inherit;
        }}
        QMenuBar::item {{
            color: {MENU_TEXT};
            padding: 5px 12px;
            margin: 0 2px;
        }}
        QMenuBar::item:selected {{
            background-color: {MENU_HOVER};
            border-radius: 4px;
        }}
        /* 二级菜单样式 */
        QMenu {{
            background-color: {MENU_BAR_BG};
            border: 1px solid {BORDER};
        }}
        QMenu::item {{
            color: {MENU_TEXT};
            padding: 5px 25px 5px 20px;
        }}
        QMenu::item:selected {{
            background-color: {MENU_HOVER};
        }}
    """
    
    # About对话框样式
    ABOUT_STYLE = f"""
        QDialog {{
            background-color: {MENU_BAR_BG};
            color: {MENU_TEXT};
        }}
        QLabel#title {{
            font-size: 16px;
            font-weight: bold;
            color: {MENU_TEXT};
        }}
    """