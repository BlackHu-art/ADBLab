from PySide6.QtGui import QColor
from labgui.widgets.style.base_styles import BaseStyles

class MenuBarStyles:
    
    WINDOW_BG = BaseStyles.MENU_BAR_BG  # 与主窗口一致
    BORDER_COLOR = "#d1d8e0"
    CONTENT_BG = "#ffffff"
    TITLE_COLOR = "#2c3e50"
    TEXT_COLOR = "#34495e"
    
    # 从原有样式继承颜色
    MENU_BAR_BG = BaseStyles.MENU_BAR_BG
    MENU_TEXT = BaseStyles.MENU_TEXT_COLOR
    MENU_HOVER = BaseStyles.MENU_ITEM_HOVER
    BORDER = BaseStyles.BORDER_COLOR
    
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

# 在base_styles.py或专门的样式文件中
MENUBAR_STYLES = """
/* 菜单栏基础样式 */
QMenuBar {
    background-color: #f0f0f0;
    border-bottom: 1px solid #555555;
    spacing: 5px;
}

QMenuBar::item {
    padding: 5px 10px;
    border-radius: 3px;
}

QMenuBar::item:selected {
    background-color: #eeeee4;
}

/* About对话框样式 */
AboutDialog {
    background-color: #2e2e2e;
    border: 1px solid #444;
}

AboutDialog QLabel#title {
    font: bold 18px 'Segoe UI';
    color: #ffffff;
    padding: 20px 0 0 0;
    qproperty-alignment: AlignCenter;
}

AboutDialog QLabel#version {
    font: 12px 'Segoe UI';
    color: #aaaaaa;
    padding-bottom: 20px;
    qproperty-alignment: AlignCenter;
}

AboutDialog QLabel#content {
    font: 13px 'Segoe UI';
    color: #dddddd;
    background-color: #3a3a3a;
    padding: 25px;
    margin: 0 30px;
    border: 1px solid #444;
    border-radius: 4px;
}

AboutDialog QPushButton#close_btn {
    background-color: #3498db;
    color: white;
    border: none;
    padding: 8px 24px;
    min-width: 100px;
    font: 13px 'Segoe UI';
    margin-top: 15px;
    border-radius: 4px;
}

AboutDialog QPushButton#close_btn:hover {
    background-color: #2980b9;
}

AboutDialog QPushButton#close_btn:pressed {
    background-color: #1c6da8;
}
"""