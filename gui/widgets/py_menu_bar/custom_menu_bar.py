from PySide6.QtWidgets import (QMenuBar, QDialog, 
                              QVBoxLayout, QLabel, QPushButton, QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, QEasingCurve, QPropertyAnimation, QTimer
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
        """无标题栏对话框的稳定拖拽实现"""
        dialog = QDialog(self.parent())
        dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        dialog.setFixedSize(480, 380)  # 必须固定尺寸
        
        # 关键设置：移除窗口标题栏和边框
        dialog.setWindowFlags(
            Qt.Dialog | 
            Qt.FramelessWindowHint |  # 无边框
            Qt.NoDropShadowWindowHint  # 无阴影（可选）
        )
        
        # 现代化样式表（适配无标题栏）
        dialog.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f5f7fa, stop:1 #e4e8f0);
                border: 2px solid #c4d0dc;
                border-radius: 12px;
            }
            /* 标题样式 */
            QLabel#title {
                font: bold 20px 'Segoe UI';
                color: #2c3e50;
                padding: 20px 0 5px 0;
                background: transparent;
            }
            /* 版本信息 */
            QLabel#version {
                font: 13px 'Segoe UI';
                color: #7f8c8d;
                padding-bottom: 15px;
                background: transparent;
            }
            /* 内容卡片 */
            QLabel#content {
                font: 14px 'Segoe UI';
                color: #34495e;
                background: rgba(255,255,255,0.75);
                border-radius: 8px;
                padding: 20px;
                margin: 0 25px;
                border: 1px solid #d1d8e0;
            }
            /* 关闭按钮 */
            QPushButton#close_btn {
                background: #3498db;
                color: white;
                border: none;
                padding: 8px 24px;
                border-radius: 4px;
                min-width: 100px;
                font: 13px 'Segoe UI';
            }
            QPushButton#close_btn:hover {
                background: #2980b9;
            }
            QPushButton#close_btn:pressed {
                background: #1a6da8;
            }
        """)
        
        # 主布局（增加顶部间距补偿缺失的标题栏）
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        # 标题区
        title = QLabel("ADB Manager")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)

        version = QLabel("Version 2.4.0")
        version.setObjectName("version")
        version.setAlignment(Qt.AlignCenter)

        # 内容区（富文本）
        content = QLabel()
        content.setObjectName("content")
        content.setTextFormat(Qt.RichText)
        content.setText("""
            <div style='text-align: center; line-height: 1.7;'>
                <ul style='margin: 15px 0; text-align: left; 
                        display: inline-block; list-style-type: none;'>
                    <li>• Multi-device control</li>
                    <li>• Real-time performance metrics</li>
                    <li>• Automated testing framework</li>
                    <li>• Secure log collection</li>
                </ul>
                <p style='color: #95a5a6; font-size: 12px;'>
                    Copyright © 2025.4 Frankie Hu. All rights reserved.
                </p>
            </div>
        """)
        content.setWordWrap(True)

        # 自定义关闭按钮（替代标题栏关闭功能）
        btn_close = QPushButton("Close")
        btn_close.setObjectName("close_btn")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(dialog.accept)
        

        # 组装布局
        layout.addWidget(title)
        layout.addWidget(version)
        layout.addWidget(content, 1)
        layout.addWidget(btn_close, 0, Qt.AlignCenter)

        # 显示对话框（无动画避免闪烁）
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