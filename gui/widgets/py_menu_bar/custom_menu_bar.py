from PySide6.QtWidgets import QMenuBar, QWidget
from PySide6.QtGui import QMouseEvent, QAction
from PySide6.QtCore import Qt, QPoint
from typing import Optional
from gui.styles import Styles  # 新增导入

class CustomMenuBar(QMenuBar):
    """自定义菜单栏，支持窗口拖拽和常用操作"""
    
    # ... 其他代码保持不变 ...

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.parent_window = parent
        self._drag_pos: Optional[QPoint] = None
        self._setup_ui()
        self._setup_styles()  # 新增样式初始化

    def _setup_styles(self) -> None:
        """设置菜单栏视觉样式"""
        self.setStyleSheet(f"""
            QMenuBar {{
                border-bottom: 1px solid {Styles.BORDER_COLOR};
                background: {Styles.MENU_BAR_BG};
                spacing: 5px;
            }}
            QMenuBar::item {{
                color: {Styles.MENU_TEXT_COLOR};
                padding: 5px 12px;
                border-radius: 3px;
            }}
            QMenuBar::item:selected {{
                background: {Styles.MENU_ITEM_HOVER};
            }}
        """)
    
    # 菜单项常量
    MENU_TITLES = {
        "file": "File",
        "help": "Help",
        "minimize": "Minimize",
        "clear_log": "Clear logs",
        "exit": "Exit"
    }
    
    ACTION_TEXTS = {
        "restore": "Restore Default Size",
        "about": "About"
    }

    def _setup_ui(self) -> None:
        """初始化菜单栏界面"""
        self._create_file_menu()
        self._create_help_menu()
        self._create_window_controls()

    def _create_file_menu(self) -> None:
        """创建File菜单及其子项"""
        file_menu = self.addMenu(self.MENU_TITLES["file"])
        restore_action = QAction(self.ACTION_TEXTS["restore"], self.parent_window)
        restore_action.triggered.connect(self.parent_window.restore_default_size)
        file_menu.addAction(restore_action)

    def _create_help_menu(self) -> None:
        """创建Help菜单及其子项"""
        help_menu = self.addMenu(self.MENU_TITLES["help"])
        about_action = QAction(self.ACTION_TEXTS["about"], self.parent_window)
        about_action.triggered.connect(self.parent_window.show_about_dialog)
        help_menu.addAction(about_action)

    def _create_window_controls(self) -> None:
        """创建窗口控制按钮（一级按钮）"""

        # 最小化按钮
        minimize_action = QAction(self.MENU_TITLES["minimize"], self.parent_window)
        minimize_action.triggered.connect(self.parent_window.showMinimized)
        self.addAction(minimize_action)

        # ✅ Clear Logs 作为一级按钮
        clear_logs_action = QAction(self.MENU_TITLES["clear_log"], self.parent_window)
        clear_logs_action.triggered.connect(self.parent_window.clear_log)
        self.addAction(clear_logs_action)

        # 退出按钮
        exit_action = QAction(self.MENU_TITLES["exit"], self.parent_window)
        exit_action.triggered.connect(self.parent_window.close)
        self.addAction(exit_action)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """处理鼠标按下事件"""
        if event.button() == Qt.LeftButton and self._is_blank_area(event.pos()):
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """处理鼠标移动事件"""
        if self._is_dragging(event):
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """处理鼠标释放事件"""
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _is_blank_area(self, pos: QPoint) -> bool:
        """判断点击位置是否为空白区域"""
        return self.actionAt(pos) is None

    def _is_dragging(self, event: QMouseEvent) -> bool:
        """判断是否处于拖拽状态"""
        return bool(
            event.buttons() & Qt.LeftButton 
            and self._drag_pos is not None
        )


class MenuBarCreator:
    """菜单栏创建工厂类"""
    
    def __init__(self, parent: QWidget):
        self.parent = parent
        self.menu_bar = CustomMenuBar(parent)

    def get_menu_bar(self) -> QMenuBar:
        """获取创建好的菜单栏实例"""
        return self.menu_bar