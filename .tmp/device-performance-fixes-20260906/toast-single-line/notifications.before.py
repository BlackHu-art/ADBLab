"""窗口内的非阻塞提示：保留全文，限制占用，并随窗口释放所有计时器。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QTextDocument, QTextOption
from PySide6.QtWidgets import QFrame, QLayout, QSizePolicy, QWidget
from qfluentwidgets import InfoBar, InfoBarIcon, InfoBarPosition, PlainTextEdit, PushButton
from shiboken6 import isValid

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import configure_button, font_qss

ToastLevel = Literal["info", "success", "warning", "error"]
_ICONS = {
    "info": InfoBarIcon.INFORMATION,
    "success": InfoBarIcon.SUCCESS,
    "warning": InfoBarIcon.WARNING,
    "error": InfoBarIcon.ERROR,
}


def _top_margin(owner: QWidget) -> int:
    """提示放在窗口标题栏下方，避免遮挡最小化与关闭入口。"""
    title_bar = getattr(owner, "titleBar", None)
    if isinstance(title_bar, QWidget) and title_bar.isVisible():
        return title_bar.height() + 12
    return 24


class ToastNotification(InfoBar):
    """复用 Fluent 外观，正文按实际字体换行，超出可用高度时在提示内滚动。"""

    def __init__(
        self, owner: QWidget, title: str, content: str, *, level: ToastLevel,
        duration: int, action_text: str | None, on_action: Callable[[], object] | None,
    ):
        self._ready = False
        self._closed = False
        self.level = level
        self._on_action = on_action
        self._timeout_ms = duration
        self._remaining_ms = duration
        # 上游 singleShot 无法暂停；位置和计时由所属窗口的有界栈统一管理。
        super().__init__(
            _ICONS[level], title, content, orient=Qt.Orientation.Vertical,
            duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=owner,
        )
        self.setObjectName("toastNotification")
        self.setAccessibleName(title)
        self.setAccessibleDescription(content)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.hBoxLayout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.textLayout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.titleLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.titleLabel.setWordWrap(True)
        self.titleLabel.setMinimumWidth(0)
        self.textLayout.removeWidget(self.contentLabel)
        self.contentLabel.hide()
        self.content_edit = PlainTextEdit(self)
        self.content_edit.setObjectName("toastContent")
        self.content_edit.setReadOnly(True)
        self.content_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.content_edit.setPlainText(content)
        self.content_edit.setAccessibleName(title)
        self.content_edit.setAccessibleDescription(content)
        self.content_edit.setLineWrapMode(PlainTextEdit.LineWrapMode.WidgetWidth)
        self.content_edit.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.content_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_edit.document().setDocumentMargin(4)
        self.textLayout.insertWidget(1, self.content_edit)
        self.action_button = None
        if action_text and on_action:
            self.action_button = configure_button(
                PushButton(self), text=action_text, tooltip=action_text,
            )
            self.action_button.clicked.connect(self._activate_action)
            self.widgetLayout.addWidget(self.action_button)
        self.closeButton.setAccessibleName(tr("Close"))
        self.closeButton.setToolTip(tr("Close"))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)
        BaseStyles.fonts_changed.connect(self._refresh_style)
        self._ready = True
        self._refresh_style()

    def _refresh_style(self, *_args) -> None:
        if not self._ready or self._closed:
            return
        font = BaseStyles.font_for_role(FontRole.UI)
        title_font = BaseStyles.font_for_role(FontRole.UI)
        title_font.setBold(True)
        self.titleLabel.setFont(title_font)
        self.titleLabel.setStyleSheet(f"QLabel {{ {font_qss(title_font)} }}")
        self.content_edit.setFont(font)
        self.content_edit.document().setDefaultFont(font)
        if self.action_button is not None:
            self.action_button.setFont(font)
        self.content_edit.setStyleSheet(
            "PlainTextEdit, PlainTextEdit:hover, PlainTextEdit:focus "
            "{ background: transparent; border: none; border-radius: 0; padding: 0; "
            + font_qss(font) + " }"
        )
        self._adjustText()
        stack = getattr(self.parentWidget(), "_adblab_toast_stack", None)
        if stack is not None:
            stack.arrange()

    def _adjustText(self) -> None:
        """在真实窗口宽度下测量全文，不使用按字符数估算的上游换行。"""
        if not self._ready:
            return
        owner = self.parentWidget()
        if owner is None:
            return
        natural = max(
            self.titleLabel.fontMetrics().horizontalAdvance(self.title),
            *(self.content_edit.fontMetrics().horizontalAdvance(line)
              for line in self.content.splitlines() or [""]),
            self.action_button.sizeHint().width() if self.action_button is not None else 0,
        ) + 98
        width = max(160, min(max(280, natural), 520, owner.width() - 48))
        text_width = max(1, width - 98)
        maximum = max(100, min(320, owner.height() - _top_margin(owner) - 24))
        self.titleLabel.setFixedWidth(text_width)
        self.titleLabel.setText(self.title)
        title_height = max(0, self.titleLabel.heightForWidth(text_width)) if self.title else 0
        # 超长文件名标题和正文共同进入可滚动区域，不能挤出关闭按钮或省略信息。
        title_in_body = title_height > maximum // 3
        displayed_content = f"{self.title}\n\n{self.content}" if title_in_body else self.content
        self.titleLabel.setVisible(bool(self.title) and not title_in_body)
        if title_in_body:
            title_height = 0
        self.titleLabel.setFixedHeight(title_height)
        if self.content_edit.toPlainText() != displayed_content:
            self.content_edit.setPlainText(displayed_content)
        self.content_edit.setFixedWidth(text_width)
        document = QTextDocument()
        document.setDefaultFont(self.content_edit.font())
        document.setDocumentMargin(4)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(option)
        document.setPlainText(displayed_content)
        # 预留滚动条宽度，长路径出现滚动条时不会再次挤出横向内容。
        document.setTextWidth(max(1, text_width - 18))
        action_height = 0
        if self.action_button is not None:
            self.action_button.setMaximumWidth(text_width)
            action_height = self.action_button.sizeHint().height() + 5
        body_height = min(
            int(document.size().height()) + 8,
            max(28, maximum - title_height - action_height - 38),
        )
        self.content_edit.setFixedHeight(body_height)
        self.setFixedSize(width, title_height + body_height + action_height + 38)

    def restart_timeout(self) -> None:
        """重复通知延长阅读时间，不再添加一个相同提示。"""
        self._remaining_ms = self._timeout_ms
        if self._timeout_ms >= 0 and not self.underMouse():
            self._timer.start(self._timeout_ms)

    def enterEvent(self, event) -> None:
        if self._timer.isActive():
            self._remaining_ms = self._timer.remainingTime()
            self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if not self._closed and self._remaining_ms >= 0:
            self._timer.start(max(1, self._remaining_ms))

    def showEvent(self, event) -> None:
        # 不接入上游的全局动画栈，窗口关闭即可按父子树完成清理。
        QFrame.showEvent(self, event)
        self._adjustText()
        self.restart_timeout()

    def closeEvent(self, event) -> None:
        if not self._closed:
            self._closed = True
            self._timer.stop()
            self._on_action = None
            self.hide()
            self.closedSignal.emit()
            self.deleteLater()
        event.accept()

    def _activate_action(self) -> None:
        if self._closed:
            return
        callback = self._on_action
        self.close()
        if callback is not None:
            callback()


class _ToastStack(QObject):
    """每个窗口至多三条提示，按可用高度淘汰最早提示，不持有全局窗口引用。"""

    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self.owner = owner
        self.notices: list[ToastNotification] = []
        owner.installEventFilter(self)

    def add(self, notice: ToastNotification) -> None:
        self.notices.append(notice)
        notice.closedSignal.connect(self._remove_closed)
        notice.show()
        self.arrange()

    def _remove_closed(self) -> None:
        self.notices = [n for n in self.notices if isValid(n) and not n._closed]
        self.arrange()

    def arrange(self) -> None:
        if not isValid(self.owner):
            return
        self.notices = [n for n in self.notices if isValid(n) and not n._closed]
        while len(self.notices) > 1 and (
            len(self.notices) > 3
            or sum(n.height() for n in self.notices) + 12 * (len(self.notices) - 1)
            > self.owner.height() - _top_margin(self.owner) - 24
        ):
            self.notices.pop(0).close()
        top = _top_margin(self.owner)
        for notice in self.notices:
            notice.move(max(0, self.owner.width() - notice.width() - 24), top)
            notice.raise_()
            top += notice.height() + 12

    def eventFilter(self, obj, event) -> bool:
        if obj is self.owner:
            if event.type() == QEvent.Type.Resize:
                for notice in tuple(self.notices):
                    notice._adjustText()
                self.arrange()
            elif event.type() == QEvent.Type.Close:
                for notice in tuple(self.notices):
                    notice.close()
        return super().eventFilter(obj, event)


def show_toast(
    parent: QWidget, title: str, content: str, *, level: ToastLevel = "info",
    duration: int | None = None, action_text: str | None = None,
    on_action: Callable[[], object] | None = None,
) -> ToastNotification | None:
    """在调用页面所属窗口右上角提示并立即返回；仅供 GUI 线程的活页面使用。"""
    if not isValid(parent) or getattr(parent, "_closing", False):
        return None
    owner = parent.window() or parent
    if getattr(owner, "_closing", False):
        return None
    title, content = tr(str(title)), tr(str(content))
    stack = getattr(owner, "_adblab_toast_stack", None)
    if stack is None:
        stack = _ToastStack(owner)
        setattr(owner, "_adblab_toast_stack", stack)
    for notice in stack.notices:
        if (notice.title, notice.content, notice.level, notice._closed) == (
            title, content, level, False,
        ):
            notice.restart_timeout()
            return notice
    if duration is None:
        duration = max(
            8000 if level == "error" or action_text else 5000,
            min(15000, 2000 + 60 * len(title + content)),
        )
    notice = ToastNotification(
        owner, title, content, level=level, duration=duration,
        action_text=action_text, on_action=on_action,
    )
    stack.add(notice)
    return notice
