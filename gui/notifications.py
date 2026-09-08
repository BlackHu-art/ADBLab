"""窗口内的非阻塞提示：保留全文，限制占用，并随窗口释放所有计时器。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import QFrame, QLayout, QSizePolicy, QWidget
from qfluentwidgets import InfoBar, InfoBarIcon, InfoBarPosition, LineEdit, PushButton
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
_BACKGROUNDS = {
    "info": ("#e8f2ff", "#153650"),
    "success": ("#e5f5e7", "#1b3b29"),
    "warning": ("#fff4ce", "#4b3b15"),
    "error": ("#fde7e9", "#4c2429"),
}


def _top_margin(owner: QWidget) -> int:
    """提示避开窗口标题栏与设备入口，保持导航、设备选择和关闭操作可用。"""
    context_bar = getattr(owner, "_global_device_bar", None)
    if isinstance(context_bar, QWidget) and context_bar.isVisibleTo(owner):
        return context_bar.mapTo(owner, QPoint(0, context_bar.height())).y() + 12
    title_bar = getattr(owner, "titleBar", None)
    if isinstance(title_bar, QWidget) and title_bar.isVisible():
        return title_bar.height() + 12
    return 24


class ToastNotification(InfoBar):
    """复用 Fluent 外观，以单行展示消息；正文可横向阅读和完整选择复制。"""

    def __init__(
        self, owner: QWidget, title: str, content: str, *, level: ToastLevel,
        duration: int, action_text: str | None, on_action: Callable[[], object] | None,
    ):
        self._ready = False
        self._closed = False
        self.level = level
        self.feedback_key = ""
        self._on_action = on_action
        self._timeout_ms = duration
        self._remaining_ms = duration
        self._action_text = tr(action_text or "")
        # 上游 singleShot 无法暂停；位置和计时由所属窗口的有界栈统一管理。
        super().__init__(
            _ICONS[level], title, content, orient=Qt.Orientation.Horizontal,
            duration=-1, position=InfoBarPosition.TOP_RIGHT, parent=owner,
        )
        self.setCustomBackgroundColor(*_BACKGROUNDS[level])
        self.setObjectName("toastNotification")
        self.setAccessibleName(title)
        self.setAccessibleDescription(content)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.hBoxLayout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.textLayout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.titleLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.titleLabel.setWordWrap(False)
        self.titleLabel.setToolTip(title)
        self.titleLabel.setAccessibleName(title)
        self.titleLabel.setMinimumWidth(0)
        while self.textLayout.count():
            self.textLayout.takeAt(0)
        self.textLayout.setContentsMargins(0, 0, 0, 0)
        self.textLayout.setSpacing(8)
        self.textLayout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.contentLabel.hide()
        self.content_edit = LineEdit(self)
        self.content_edit.setObjectName("toastContent")
        self.content_edit.setReadOnly(True)
        self.content_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        displayed_content = " ".join(content.splitlines())
        # QLineEdit 默认只保留 32767 个字符；通知必须保留长诊断全文和代理字符对。
        self.content_edit.setMaxLength(max(32767, len(displayed_content) * 2))
        self.content_edit.setText(displayed_content)
        self.content_edit.setCursorPosition(0)
        self.content_edit.setToolTip(content)
        self.content_edit.setAccessibleName(title)
        self.content_edit.setAccessibleDescription(content)
        self.textLayout.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        self.textLayout.addWidget(self.content_edit, 1, Qt.AlignmentFlag.AlignVCenter)
        self.hBoxLayout.setStretch(1, 1)
        self.hBoxLayout.setAlignment(self.iconWidget, Qt.AlignmentFlag.AlignVCenter)
        self.hBoxLayout.setAlignment(self.closeButton, Qt.AlignmentFlag.AlignVCenter)
        self.action_button = None
        if action_text and on_action:
            self.action_button = configure_button(
                PushButton(self), text=action_text, tooltip=action_text,
            )
            self.action_button.clicked.connect(self._activate_action)
            self.widgetLayout.setContentsMargins(8, 0, 0, 0)
            self.widgetLayout.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignVCenter)
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
        if self.action_button is not None:
            self.action_button.setFont(font)
        self.content_edit.setStyleSheet(
            "LineEdit, LineEdit:hover, LineEdit:focus "
            "{ background: transparent; border: none; border-radius: 0; padding: 0; "
            + font_qss(font) + " }"
        )
        self._adjustText()
        stack = getattr(self.parentWidget(), "_adblab_toast_stack", None)
        if stack is not None:
            stack.arrange()

    def _adjustText(self) -> None:
        """单行按实际字体分配宽度，优先保留正文、操作和关闭入口。"""
        if not self._ready:
            return
        owner = self.parentWidget()
        if owner is None:
            return
        title = " ".join(self.title.splitlines())
        title_metrics = self.titleLabel.fontMetrics()
        title_natural = title_metrics.horizontalAdvance(title)
        body_natural = self.content_edit.fontMetrics().horizontalAdvance(self.content_edit.text())
        action_natural = 0
        if self.action_button is not None:
            action_natural = self.action_button.fontMetrics().horizontalAdvance(
                self._action_text
            ) + 32
        margins = self.hBoxLayout.contentsMargins()
        fixed_width = margins.left() + margins.right() + self.iconWidget.width()
        fixed_width += self.closeButton.width() + 12
        gap = (8 if title else 0) + (8 if self.action_button is not None else 0)
        natural = fixed_width + gap + title_natural + body_natural + action_natural + 8
        width = max(1, min(max(280, natural), 840, owner.width() - 48))
        available = max(1, width - fixed_width - gap)
        action_height = 0
        if self.action_button is not None:
            action_width = min(action_natural, available // 2)
            self.action_button.setFixedWidth(action_width)
            self.action_button.setText(self.action_button.fontMetrics().elidedText(
                self._action_text, Qt.TextElideMode.ElideRight, max(1, action_width - 32),
            ))
            action_height = self.action_button.sizeHint().height()
            available -= action_width
        title_width = min(title_natural, available // 3)
        self.titleLabel.setVisible(bool(title))
        self.titleLabel.setFixedWidth(title_width)
        self.titleLabel.setFixedHeight(title_metrics.height())
        self.titleLabel.setText(title_metrics.elidedText(
            title, Qt.TextElideMode.ElideRight, title_width,
        ))
        self.content_edit.setFixedWidth(max(1, available - title_width))
        body_height = self.content_edit.fontMetrics().height() + 8
        self.content_edit.setFixedHeight(body_height)
        height = max(
            body_height, action_height, self.closeButton.height(), self.iconWidget.height(),
        )
        self.setFixedSize(width, height + margins.top() + margins.bottom())

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
    key: str = "",
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
    for notice in tuple(stack.notices):
        if key and getattr(notice, "feedback_key", "") == key:
            notice.close()
            continue
        if (notice.title, notice.content, notice.level, notice._closed) == (
            title, content, level, False,
        ) and not key:
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
    notice.feedback_key = key
    stack.add(notice)
    return notice
