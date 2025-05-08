from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, 
                              QPushButton, QWidget, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, QPropertyAnimation
from PySide6.QtGui import QColor

from labgui.widgets.style.menubar_styles import MENUBAR_STYLES

class AboutDialog(QDialog):
    """使用全局样式的关于对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setFixedSize(500, 400)
        self.setStyleSheet(MENUBAR_STYLES)  # 使用全局样式
        
        self._setup_content()
        self._setup_animations()
        self._setup_shadow_effect()
        
    def _setup_content(self):
        """设置对话框内容"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题
        title = QLabel("ADB Manager")
        title.setObjectName("title")
        
        # 版本
        version = QLabel("Version 2.4.0")
        version.setObjectName("version")
        
        # 内容
        content = QLabel()
        content.setObjectName("content")
        content.setTextFormat(Qt.RichText)
        content.setText(self._get_content_html())
        
        # 内容容器
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(30, 30, 30, 30)
        content_layout.addWidget(content)

        # 关闭按钮
        btn_close = QPushButton("Close")
        btn_close.setObjectName("close_btn")
        btn_close.clicked.connect(self._fade_out_and_close)

        # 组装布局
        layout.addWidget(title, 0, Qt.AlignCenter)
        layout.addWidget(version, 0, Qt.AlignCenter)
        layout.addWidget(content_container, 1)
        layout.addWidget(btn_close, 0, Qt.AlignCenter)
        
    def _get_content_html(self):
        """生成内容HTML"""
        return """
        <div style='color: #dddddd; line-height: 1.6;'>
            <p style='margin-bottom: 15px;'>Advanced Device Management Platform</p>
            <ul style='margin-left: 20px;'>
                <li>Multi-device control and monitoring</li>
                <li>Real-time performance analytics</li>
                <li>Automated testing framework</li>
                <li>Secure log collection system</li>
            </ul>
            <p style='margin-top: 20px; color: #888888; font-size: 11px;'>
                Copyright © 2025.4 Frankie Hu. All rights reserved.
            </p>
        </div>
        """
        
    def _setup_animations(self):
        """设置淡入淡出动画"""
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(200)
        
    def _setup_shadow_effect(self):
        """设置阴影效果"""
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setXOffset(3)
        shadow.setYOffset(3)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(shadow)
        
    def _fade_out_and_close(self):
        """执行淡出动画并关闭"""
        self.fade_animation.setStartValue(1.0)
        self.fade_animation.setEndValue(0.0)
        self.fade_animation.finished.connect(self.close)
        self.fade_animation.start()
        
    def showEvent(self, event):
        """显示时重置透明度"""
        self.setWindowOpacity(1.0)
        super().showEvent(event)
        
    def keyPressEvent(self, event):
        """ESC键关闭"""
        if event.key() == Qt.Key_Escape:
            self._fade_out_and_close()
        else:
            super().keyPressEvent(event)
            
    def mousePressEvent(self, event):
        """实现拖动功能"""
        if event.button() == Qt.LeftButton:
            self._drag_position = event.globalPosition().toPoint()
            event.accept()
            
    def mouseMoveEvent(self, event):
        """处理拖动"""
        if hasattr(self, '_drag_position') and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_position
            self.move(self.pos() + delta)
            self._drag_position = event.globalPosition().toPoint()
            event.accept()
            
    def mouseReleaseEvent(self, event):
        """结束拖动"""
        if hasattr(self, '_drag_position'):
            del self._drag_position
        super().mouseReleaseEvent(event)