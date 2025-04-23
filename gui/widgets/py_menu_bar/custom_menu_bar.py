from PySide6.QtWidgets import (QMenuBar, QDialog, 
                              QVBoxLayout, QLabel, QPushButton, QWidget)
from PySide6.QtCore import Qt, QObject, QPropertyAnimation, QEvent
from PySide6.QtGui import QMouseEvent
from gui.widgets.style.base_styles import get_default_font


class CustomMenuBar(QMenuBar):
    """完全自包含的菜单栏，内部实现About对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._drag_pos = None

    def _setup_ui(self):
        """初始化UI组件"""
        self.setFont(get_default_font())
        self._setup_styles()
        self._create_menus()

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

    def _create_menus(self):
        """创建菜单结构（直接绑定槽函数）"""
        # File菜单
        file_menu = self.addMenu("File")
        file_menu.addAction("Restore Default Size", self.parent().restore_default_size)
        
        # Help菜单（直接绑定对话框显示）
        help_menu = self.addMenu("Help")
        help_menu.addAction("About", self._show_about_dialog)

        # 窗口控制按钮
        self.addAction("Minimize", self.parent().showMinimized)
        self.addAction("Clear Logs", self.parent().clear_log)
        self.addAction("Exit", self.parent().close)

    def _show_about_dialog(self):
        """优化后的无标题栏对话框实现"""
        dialog = QDialog(self.parent())
        
        # 窗口设置（直角无阴影）
        dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        dialog.setFixedSize(500, 400)  # 稍微增大尺寸
        
        # 使用styles中的背景色
        bg_color = "#f0f0f0"  # 从styles.WINDOW_BACKGROUND获取
        
        # 现代化样式表（直角设计）
        dialog.setStyleSheet(f"""
            QDialog {{
                background: {bg_color};
                border: 1px solid #d1d8e0;
            }}
            /* 标题样式 */
            QLabel#title {{
                font: bold 18px 'Segoe UI';
                color: #2c3e50;
                padding: 20px 0 0 0;
                qproperty-alignment: AlignCenter;
            }}
            /* 版本信息 */
            QLabel#version {{
                font: 12px 'Segoe UI';
                color: #7f8c8d;
                padding-bottom: 20px;
                qproperty-alignment: AlignCenter;
            }}
            /* 内容卡片（直角设计） */
            QLabel#content {{
                font: 13px 'Segoe UI';
                color: #34495e;
                background: white;
                padding: 25px;
                margin: 0 30px;
                border: 1px solid #e0e5ec;
            }}
            QLabel#content ul {{
                margin: 10px 0;
                padding-left: 5px;
            }}
            QLabel#content li {{
                margin-bottom: 8px;
            }}
            /* 关闭按钮 */
            QPushButton#close_btn {{
                background: #3498db;
                color: white;
                border: none;
                padding: 8px 24px;
                min-width: 100px;
                font: 13px 'Segoe UI';
                margin-top: 15px;
            }}
            QPushButton#close_btn:hover {{
                background: #2980b9;
            }}
        """)
        
        # 主布局（直角布局）
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)  # 移除默认边距
        layout.setSpacing(0)

        # 标题区
        title = QLabel("ADB Manager")
        title.setObjectName("title")

        version = QLabel("Version 2.4.0")
        version.setObjectName("version")

        # 内容区（优化排版）
        content = QLabel()
        content.setObjectName("content")
        content.setTextFormat(Qt.RichText)
        content.setText("""
            <div style='line-height: 1.6;'>
                <p style='margin-bottom: 15px;'>Advanced Device Management Platform</p>
                <ul>
                    <li>Multi-device control and monitoring</li>
                    <li>Real-time performance analytics</li>
                    <li>Automated testing framework</li>
                    <li>Secure log collection system</li>
                </ul>
                <p style='margin-top: 20px; color: #95a5a6; font-size: 11px;'>
                    Copyright © 2025.4 Frankie Hu. All rights reserved.
                </p>
            </div>
        """)

        # 内容区容器（实现边距）
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(30, 30, 30, 30)
        content_layout.addWidget(content)

        # 关闭按钮
        btn_close = QPushButton("Close")
        btn_close.setObjectName("close_btn")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(dialog.accept)

        # 组装布局
        layout.addWidget(title, 0, Qt.AlignCenter)
        layout.addWidget(version, 0, Qt.AlignCenter)
        layout.addWidget(content_container, 1)
        layout.addWidget(btn_close, 0, Qt.AlignCenter)
        
        # 添加顶部拖拽区域
        title.installEventFilter(DragHandler(dialog))
        
        dialog.exec()

    # 保留窗口拖拽功能
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
    
class DragHandler(QObject):
    """专用的拖拽事件处理器"""
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.drag_pos = None

    def eventFilter(self, source, event):
        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self.drag_pos = event.globalPosition().toPoint()
                return True
                
        elif event.type() == QEvent.MouseMove and self.drag_pos:
            delta = event.globalPosition().toPoint() - self.drag_pos
            self.window.move(self.window.pos() + delta)
            self.drag_pos = event.globalPosition().toPoint()
            return True
            
        elif event.type() == QEvent.MouseButtonRelease:
            self.drag_pos = None
            return True
            
        return super().eventFilter(source, event)