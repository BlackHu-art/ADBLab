"""在主导航中提供不参与页面选择的主题开关。"""

from PySide6.QtCore import QEvent, QMargins, QSignalBlocker, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen
from qfluentwidgets import FluentIcon, NavigationPushButton, SwitchButton

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole


class NavigationThemeToggle(NavigationPushButton):
    """紧凑模式直接切换主题，展开模式显示与实际明暗同步的原生开关。"""

    def __init__(self, parent=None) -> None:
        super().__init__(FluentIcon.QUIET_HOURS, tr("深色"), False, parent)
        self.setObjectName("navigationThemeToggle")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.switch = SwitchButton(self)
        self.switch.setOnText("")
        self.switch.setOffText("")
        self.switch.label.hide()
        self.switch.hBox.setContentsMargins(0, 0, 0, 0)
        self.switch.hBox.setSpacing(0)
        self.switch.setFixedSize(self.switch.indicator.size())
        self.switch.indicator.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.switch.indicator.installEventFilter(self)
        self.switch.checkedChanged.connect(self.click)
        self.switch.hide()
        BaseStyles.ui_font_changed.connect(self._refresh_font)
        self._refresh_font()
        self.sync_theme()

    def sync_theme(self) -> None:
        """刷新显示状态，不把系统或设置页的主题通知再次当作用户操作。"""

        dark = BaseStyles.resolved_theme() == "Dark"
        with QSignalBlocker(self.switch):
            self.switch.setChecked(dark)
        self.setIcon(FluentIcon.BRIGHTNESS if dark else FluentIcon.QUIET_HOURS)
        target = tr("浅色") if dark else tr("深色")
        action = tr("切换到{theme}主题").format(theme=target)
        self.setToolTip(action)
        self.setAccessibleName(action)
        self.switch.setToolTip(action)
        self.switch.setAccessibleName(tr("深色"))
        self.switch.indicator.setToolTip(action)
        self.switch.indicator.setAccessibleName(tr("深色"))

    def _refresh_font(self, *_args) -> None:
        self.setFont(BaseStyles.font_for_role(FontRole.UI))

    def _margins(self):
        reserved = self.switch.width() + 12 if not self.isCompacted else 0
        return QMargins(0, 0, reserved, 0)

    def setCompacted(self, isCompacted: bool):
        """切换导航形态时保留键盘焦点，并只保留一个可达的切换入口。"""

        focused = self.hasFocus() or self.switch.indicator.hasFocus()
        super().setCompacted(isCompacted)
        self.switch.setVisible(not isCompacted)
        self.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus if isCompacted else Qt.FocusPolicy.NoFocus,
        )
        self._position_switch()
        if focused:
            target = self if isCompacted else self.switch.indicator
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _position_switch(self) -> None:
        self.switch.move(
            self.width() - self.switch.width() - 12,
            (self.height() - self.switch.height()) // 2,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "switch"):
            self._position_switch()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        activate = self.isPressed and self.rect().contains(event.position().toPoint())
        self.isPressed = False
        self.update()
        if activate:
            self.click()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.switch.indicator:
            if (
                isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            ):
                if not event.isAutoRepeat():
                    self.switch.indicator.click()
                return True
            if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
                self.update()
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.hasFocus() or self.switch.indicator.hasFocus():
            # 导航和开关均自行绘制，直接绘制焦点框以免 QSS 边框被原生画笔覆盖。
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(BaseStyles.color("BORDER_FOCUS")), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()
