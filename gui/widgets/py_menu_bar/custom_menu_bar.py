from PySide6.QtWidgets import QMenuBar
from PySide6.QtCore import Qt, Signal 
from PySide6.QtGui import QMouseEvent, QAction

from gui.widgets.py_menu_bar.about_dialog import AboutDialog

class CustomMenuBar(QMenuBar):
    """优化后的自定义菜单栏"""
    
    # 定义菜单栏信号
    restore_size_requested = Signal()
    minimize_requested = Signal()
    clear_log_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos = None
        self._about_dialog = AboutDialog(self)  # 预创建对话框
        self._setup_ui()
        
    def _setup_ui(self):
        """初始化UI"""
        self._create_actions()
        self._setup_styles()
        self._setup_menus()
        self._connect_signals()

    def _setup_styles(self):
        """设置菜单栏样式（与主样式一致）"""
        self.setStyleSheet("""
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
            QDialog {
                background-color: #f0f0f0;
                font-family: 'Segoe UI';
            }
            QLabel#title {
                font-size: 16px;
                font-weight: bold;
                color: #2c3e50;
                padding: 10px;
            }
        """)

        
    def _create_actions(self):
        """创建所有菜单动作"""
        self.restore_action = QAction("Restore Default Size", self)
        self.minimize_action = QAction("Minimize", self)
        self.clear_action = QAction("Clear Logs", self)
        self.exit_action = QAction("Exit", self)
        self.about_action = QAction("About", self)
        
    def _setup_menus(self):
        """设置菜单结构"""
        # File菜单
        file_menu = self.addMenu("File")
        file_menu.addAction(self.restore_action)
        
        # Help菜单
        help_menu = self.addMenu("Help")
        help_menu.addAction(self.about_action)
        
        # 窗口控制按钮
        self.addAction(self.minimize_action)
        self.addAction(self.clear_action)
        self.addAction(self.exit_action)
        
    def _connect_signals(self):
        """连接信号与槽"""
        self.restore_action.triggered.connect(self.restore_size_requested.emit)
        self.minimize_action.triggered.connect(self.minimize_requested.emit)
        self.clear_action.triggered.connect(self.clear_log_requested.emit)
        self.exit_action.triggered.connect(self.exit_requested.emit)
        self.about_action.triggered.connect(self._show_about_dialog)
        
    def _show_about_dialog(self):
        """显示关于对话框"""
        # 重置对话框位置到中心
        if self.parent():
            dialog_size = self._about_dialog.size()
            parent_rect = self.parent().geometry()
            x = parent_rect.center().x() - dialog_size.width()/2
            y = parent_rect.center().y() - dialog_size.height()/2
            self._about_dialog.move(int(x), int(y))
            
        self._about_dialog.show()
        self._about_dialog.raise_()
        
    # 保留原有的窗口拖动方法...
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and not self.actionAt(event.pos()):
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging(event):
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _is_dragging(self, event):
        return bool(event.buttons() & Qt.LeftButton and self._drag_pos)