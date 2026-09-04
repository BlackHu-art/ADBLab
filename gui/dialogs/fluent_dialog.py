"""统一的 Fluent 对话框外壳、提示框与文本输入框。"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FluentTitleBar,
    IconWidget,
    InfoBarIcon,
    LineEdit,
    MessageBoxBase,
    SmoothScrollArea,
    SubtitleLabel,
    setCustomStyleSheet,
)
from qframelesswindow import FramelessDialog

from gui.styles import BaseStyles
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole


class FluentDialog(FramelessDialog):
    """保留 ``QDialog`` 语义的 Fluent 无边框功能窗口。

    ``standalone`` 窗口保留最小化、最大化和独立任务栏交互；模态子窗口仅
    显示关闭按钮。业务内容仍由各功能模块拥有，本类只统一标题栏、背景和
    主题同步，不接管 worker 或关闭流程。
    """

    TITLE_BAR_HEIGHT = 48

    def __init__(self, parent: QWidget | None = None, *, standalone: bool = False):
        super().__init__(parent)
        self._standalone = bool(standalone)
        self._fluent_content_margin_applied = False
        self._routing_reject_to_close = False

        self._fluent_title_bar = FluentTitleBar(self)
        self.setTitleBar(self._fluent_title_bar)
        window_type = Qt.WindowType.Window if self._standalone else Qt.WindowType.Dialog
        window_flags = (
            window_type
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        if self._standalone:
            window_flags |= (
                Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowMaximizeButtonHint
            )
        self.setWindowFlags(window_flags)
        # FramelessDialog 初始化时已经注册了原生窗口效果；切换 Window/Dialog
        # 类型会重建窗口标志，因此必须重新应用阴影、动画和无边框约束。
        self.updateFrameless()
        self.titleBar.minBtn.setVisible(self._standalone)
        self.titleBar.maxBtn.setVisible(self._standalone)
        self.titleBar.closeBtn.show()
        self.titleBar.setDoubleClickEnabled(self._standalone)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAutoFillBackground(True)

        BaseStyles.theme_changed.connect(self._sync_fluent_chrome)
        BaseStyles.ui_font_changed.connect(self._sync_fluent_chrome)
        self._sync_fluent_chrome()

    def finalize_fluent_layout(self, layout: QLayout | None = None) -> None:
        """在现有业务布局上方为 Fluent 标题栏保留固定空间。"""

        if self._fluent_content_margin_applied:
            return
        target = layout or self.layout()
        if target is None:
            return
        margins = target.contentsMargins()
        target.setContentsMargins(
            margins.left(),
            margins.top() + self.TITLE_BAR_HEIGHT,
            margins.right(),
            margins.bottom(),
        )
        self._fluent_content_margin_applied = True

    def _sync_fluent_chrome(self, *_args) -> None:
        """同步窗口调色板、标题字体和 Windows 深浅标题栏属性。"""

        app = QApplication.instance()
        if isinstance(app, QApplication):
            self.setPalette(app.palette())
            self.titleBar.setPalette(app.palette())
        self._fluent_title_bar.setIcon(self.windowIcon())
        _apply_role_font(
            self._fluent_title_bar.titleLabel,
            FontRole.UI_SMALL,
        )
        apply_dark_title_bar(self)
        self.update()

    def reject(self) -> None:
        """让 Esc/拒绝动作经过派生窗口的 closeEvent 清理路径。"""

        if self._routing_reject_to_close or not self.isVisible():
            super().reject()
            return
        self._routing_reject_to_close = True
        try:
            self.close()
        finally:
            self._routing_reject_to_close = False

    def showEvent(self, event) -> None:
        self.finalize_fluent_layout()
        self._sync_fluent_chrome()
        super().showEvent(event)
        self.titleBar.raise_()

    def closeEvent(self, event) -> None:
        # ``QDialog.closeEvent()`` 会虚调用 ``reject()``。这里提前进入路由保护，
        # 避免普通 close 再次回到 ``close()`` 并递归触发派生类的资源清理。
        was_routing = self._routing_reject_to_close
        self._routing_reject_to_close = True
        try:
            super().closeEvent(event)
        finally:
            self._routing_reject_to_close = was_routing
        if not event.isAccepted():
            return
        for signal in (BaseStyles.theme_changed, BaseStyles.ui_font_changed):
            try:
                signal.disconnect(self._sync_fluent_chrome)
            except (TypeError, RuntimeError):
                pass


class MessageLevel(str, Enum):
    """提示框的可访问语义级别。"""

    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"


def _font_rule(font: QFont) -> str:
    """把项目 QFont 转为可覆盖第三方显式字体 QSS 的声明。"""

    family = font.family().replace("\\", "\\\\").replace("'", "\\'")
    if font.pointSizeF() > 0:
        size = f"{font.pointSizeF():g}pt"
    else:
        size = f"{max(1, font.pixelSize())}px"
    style = "italic" if font.italic() else "normal"
    return (
        f"font-family: '{family}'; font-size: {size}; "
        f"font-weight: {int(font.weight())}; font-style: {style};"
    )


def _apply_role_font(widget: QWidget, role: FontRole) -> None:
    """应用字体角色，并以自定义 QSS 覆盖 qfluentwidgets 的固定字号。"""

    font = BaseStyles.font_for_role(role)
    widget.setFont(font)
    if not bool(widget.property("_adblab_font_style_captured")):
        widget.setProperty(
            "_adblab_font_base_light_qss",
            str(widget.property("lightCustomQss") or ""),
        )
        widget.setProperty(
            "_adblab_font_base_dark_qss",
            str(widget.property("darkCustomQss") or ""),
        )
        widget.setProperty("_adblab_font_style_captured", True)
    object_name = widget.objectName()
    selector = f"#{object_name}" if object_name else type(widget).__name__
    rule = f"{selector} {{ {_font_rule(font)} }}"
    light = f"{widget.property('_adblab_font_base_light_qss')}\n{rule}"
    dark = f"{widget.property('_adblab_font_base_dark_qss')}\n{rule}"
    setCustomStyleSheet(widget, light, dark)
    # MessageBoxBase 的取消按钮是原生 QPushButton，不在 Fluent 样式管理器中；
    # 它不会响应 custom QSS 动态属性，只能在控件自身补上同一字体规则。
    if not widget.styleSheet().strip():
        widget.setStyleSheet(rule)


_LEVEL_ICON = {
    MessageLevel.INFORMATION: InfoBarIcon.INFORMATION,
    MessageLevel.WARNING: InfoBarIcon.WARNING,
    MessageLevel.ERROR: InfoBarIcon.ERROR,
}


class _FluentMessageDialog(MessageBoxBase):
    """带严重级别图标和有界正文滚动区的 Fluent 消息框。"""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        content: str,
        level: MessageLevel,
    ):
        super().__init__(parent)
        self.level = level
        self.titleLabel = SubtitleLabel(str(title), self.widget)
        self.titleLabel.setObjectName("messageTitleLabel")
        self.titleLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.iconWidget = IconWidget(_LEVEL_ICON[level], self.widget)
        self.iconWidget.setFixedSize(22, 22)
        self.iconWidget.setAccessibleName(level.value)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(self.iconWidget, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.titleLabel, 1)
        self.viewLayout.addLayout(header)

        self.contentLabel = BodyLabel(str(content), self.widget)
        self.contentLabel.setObjectName("messageContentLabel")
        self.contentLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.contentLabel.setWordWrap(True)
        self.contentLabel.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.contentLabel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self.contentScroll = SmoothScrollArea(self.widget)
        self.contentScroll.setObjectName("messageContentScroll")
        self.contentScroll.setWidgetResizable(True)
        self.contentScroll.setFrameShape(QFrame.Shape.NoFrame)
        self.contentScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.contentScroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.contentScroll.setStyleSheet("background: transparent; border: none;")
        content_host = QWidget()
        content_host.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content_host)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.contentLabel)
        self.contentScroll.setWidget(content_host)
        self.viewLayout.addWidget(self.contentScroll)

        owner = parent.window() or parent
        owner_width = max(parent.width(), owner.width())
        owner_height = max(parent.height(), owner.height())
        card_width = max(300, min(560, max(300, owner_width - 48)))
        body_width = max(220, card_width - 48 - 14)
        _apply_role_font(self.titleLabel, FontRole.TITLE)
        _apply_role_font(self.contentLabel, FontRole.UI)
        _apply_role_font(self.yesButton, FontRole.UI)
        _apply_role_font(self.cancelButton, FontRole.UI)
        text_rect = QFontMetrics(self.contentLabel.font()).boundingRect(
            QRect(0, 0, body_width, 100_000),
            Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextExpandTabs,
            str(content),
        )
        content_host.setMinimumWidth(body_width)
        content_host.setMinimumHeight(max(1, text_rect.height()))
        maximum_body_height = max(80, min(320, max(80, owner_height - 210)))
        self.contentScroll.setFixedHeight(
            min(
                max(QFontMetrics(self.contentLabel.font()).height() + 4, text_rect.height()),
                maximum_body_height,
            )
        )
        self.widget.setFixedWidth(card_width)
        self.widget.setAccessibleName(str(title))
        self.widget.setAccessibleDescription(str(content))
        self.widget.setProperty("messageLevel", level.value)
        self.yesButton.setText("确定")
        self.hideCancelButton()


class FluentMessageBox:
    """提供与旧静态提示调用等价的 Fluent 单按钮提示框。"""

    @staticmethod
    def _show(parent: QWidget, title: str, content: str, level: MessageLevel) -> int:
        dialog = _FluentMessageDialog(parent, str(title), str(content), level)
        try:
            return dialog.exec()
        finally:
            dialog.deleteLater()

    @classmethod
    def information(cls, parent: QWidget, title: str, content: str) -> int:
        return cls._show(parent, title, content, MessageLevel.INFORMATION)

    @classmethod
    def warning(cls, parent: QWidget, title: str, content: str) -> int:
        return cls._show(parent, title, content, MessageLevel.WARNING)

    @classmethod
    def critical(cls, parent: QWidget, title: str, content: str) -> int:
        return cls._show(parent, title, content, MessageLevel.ERROR)


class FluentInputDialog(MessageBoxBase):
    """带标题、说明和单行输入的 Fluent 模态对话框。"""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        label: str,
        *,
        text: str = "",
    ):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(str(title), self.widget)
        self.titleLabel.setObjectName("inputTitleLabel")
        self.titleLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.label = BodyLabel(str(label), self.widget)
        self.label.setObjectName("inputPromptLabel")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.lineEdit = LineEdit(self.widget)
        self.lineEdit.setObjectName("inputValueEdit")
        self.lineEdit.setText(str(text))
        self.lineEdit.selectAll()
        self.lineEdit.setClearButtonEnabled(True)
        self.lineEdit.setAccessibleName(str(label))
        self.lineEdit.returnPressed.connect(self.accept)
        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.label)
        self.viewLayout.addWidget(self.lineEdit)
        owner = parent.window() or parent
        owner_width = max(parent.width(), owner.width())
        self.widget.setFixedWidth(max(300, min(420, max(300, owner_width - 48))))
        for widget, role in (
            (self.titleLabel, FontRole.TITLE),
            (self.label, FontRole.UI),
            (self.lineEdit, FontRole.UI),
            (self.yesButton, FontRole.UI),
            (self.cancelButton, FontRole.UI),
        ):
            _apply_role_font(widget, role)
        self.lineEdit.setFocus()

    @classmethod
    def getText(
        cls,
        parent: QWidget,
        title: str,
        label: str,
        *,
        text: str = "",
    ) -> tuple[str, bool]:
        """显示输入框并保持 ``QInputDialog.getText`` 的返回顺序。"""

        dialog = cls(parent, title, label, text=text)
        try:
            accepted = bool(dialog.exec())
            return dialog.lineEdit.text(), accepted
        finally:
            dialog.deleteLater()
