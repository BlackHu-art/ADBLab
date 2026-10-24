"""日志阅读开关的局部绘制，动作与溢出菜单仍由 Fluent 命令栏管理。"""

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import QStyle, QStyleOptionToolButton, QStylePainter
from qfluentwidgets import CommandBar
from qfluentwidgets.components.widgets.command_bar import CommandButton

from gui.styles import BaseStyles


class _ReadingButtonStyleOption(QStyleOptionToolButton):
    """补全当前 PySide6 类型存根遗漏的样式选项公开字段。"""

    state: QStyle.StateFlag
    text: str
    icon: QIcon


class LogcatReadingButton(CommandButton):
    """阅读状态由动作图标颜色表示，文字和交互底色沿用普通工具按钮。"""

    def paintEvent(self, event) -> None:
        option = _ReadingButtonStyleOption()
        self.initStyleOption(option)
        # 选中状态只体现在图标上，避免原生 Toggle 同时反转文字和整块背景。
        option.state &= ~QStyle.StateFlag.State_On
        option.text = ""
        option.icon = QIcon()
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self.font())
        foreground = BaseStyles.get_color("TEXT_PRIMARY")
        painter.setPen(Qt.PenStyle.NoPen)
        if not self.isEnabled():
            painter.setOpacity(.43)
        elif self.isPressed:
            painter.setOpacity(.63)
        # 动作提前缓存好普通或强调色图标，重绘不解析 SVG，也与溢出菜单共享状态。
        icon_size = self.iconSize()
        action = self.action()
        if action is not None:
            action.icon().paint(
                painter, QRect(11, (self.height() - icon_size.height()) // 2,
                               icon_size.width(), icon_size.height()),
                Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Normal, QIcon.State.Off,
            )
        painter.setPen(foreground)
        painter.drawText(QRectF(26, 0, self.width() - 26, self.height()),
                         Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()


class LogcatCommandBar(CommandBar):
    """仅替换阅读开关，沿用 QAction 同步、原生溢出和非开关命令。"""

    def _createButton(self, action):
        if not action.isCheckable():
            return super()._createButton(action)
        button = LogcatReadingButton(self)
        button.setAction(action)
        button.setToolButtonStyle(self.toolButtonStyle())
        button.setTight(self.isButtonTight())
        button.setIconSize(self.iconSize())
        button.setFont(self.font())
        return button
