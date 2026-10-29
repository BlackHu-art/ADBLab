"""将同页的次要操作折叠收纳，控件及其业务状态始终保留。"""

import weakref

from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QEasingCurve,
    QEvent,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import QApplication, QScrollArea, QSizePolicy, QStyle, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon, PushButton

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.widgets.frame_animation import FrameAnimation


class ContentReveal(QWidget):
    """按完整内容布局裁剪展开；只拥有视觉状态，不修改输入值或业务开关。

    收起先移出焦点和交互链，结束后隐藏原控件。反向点击从当前高度续接；
    宿主隐藏或关闭时直接落实最后目标，避免离页后留下半截内容或活动时钟。
    """

    geometry_changed = Signal()

    def __init__(self, content: QWidget, toggle: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.content = content
        self._toggle_ref: weakref.ReferenceType[QWidget] | None = weakref.ref(toggle)
        toggle.destroyed.connect(self._toggle_destroyed)
        self.expanded = False
        self._target_height = 0
        self._measuring = False
        self._preparing = False
        self._finishing = False
        self._alive = True
        # 保留原控件的横向约束，避免换行标签的首选宽度挤压同卡片其他响应式行。
        self.setSizePolicy(content.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Fixed)
        self.setFixedHeight(0)
        content.setParent(self)
        content.move(0, 0)
        content.installEventFilter(self)
        content.destroyed.connect(self._content_destroyed)
        self._measure_timer = QTimer(self)
        self._measure_timer.setSingleShot(True)
        self._measure_timer.timeout.connect(self._sync_content_size)
        self.animation = FrameAnimation(self)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation.valueChanged.connect(self._apply_height)
        self.animation.finished.connect(self.finish)
        self.animation.stateChanged.connect(self._animation_state_changed)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self._focus_changed)
        content.hide()
        self.hide()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.content.sizeHint().width(), self.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.content.minimumSizeHint().width(), self.height())

    def set_expanded(self, expanded: bool, *, animated: bool = True) -> None:
        """同步提交目标；动画只改变可见范围，重复目标不重新播放。"""
        if not self._alive:
            return
        changed = self.expanded != expanded
        self.expanded = expanded
        if not expanded:
            focus = QApplication.focusWidget()
            toggle = self._toggle_ref() if self._toggle_ref is not None else None
            if (focus is not None and toggle is not None and self.isVisible()
                    and (focus is self.content or self.content.isAncestorOf(focus))):
                toggle.setFocus(Qt.FocusReason.OtherFocusReason)
        self.setEnabled(expanded)
        if expanded:
            self._preparing = True
            try:
                self.show()
                self.content.show()
                parent = self.parentWidget()
                if parent is not None and parent.layout() is not None:
                    parent.layout().activate()
                self._sync_content_size(retarget=False)
            finally:
                self._preparing = False
        if changed:
            self._animate(animated=animated)
        elif self.animation.state() == QAbstractAnimation.State.Stopped:
            self.finish()

    def _animate(self, *, animated: bool = True) -> None:
        self.animation.stop()
        end = self._target_height if self.expanded else 0
        distance = abs(end - self.height())
        window = self.window()
        if (not animated or not self.isVisible() or not distance
                or window is not None and window.isMinimized()
                or not self.style().styleHint(QStyle.StyleHint.SH_Widget_Animate)):
            self.finish()
            return
        with QSignalBlocker(self.animation):
            self.animation.setDuration(max(1, round(
                240 * min(1.0, distance / max(1, self._target_height)),
            )))
            self.animation.setStartValue(float(self.height()))
            self.animation.setEndValue(float(end))
        self.animation.start()

    def _apply_height(self, value: object) -> None:
        if self._alive and isinstance(value, (float, int)):
            self.setFixedHeight(round(value))
            # 同步祖先与滚动范围，避免旧卡片高度在中间帧压缩上方已有输入行。
            ancestor = self
            while ancestor is not None:
                ancestor.updateGeometry()
                layout = ancestor.layout()
                if layout is not None:
                    layout.activate()
                if isinstance(ancestor, QScrollArea):
                    QCoreApplication.sendEvent(ancestor, QEvent(QEvent.Type.LayoutRequest))
                    break
                ancestor = ancestor.parentWidget()
            self.geometry_changed.emit()

    def _sync_content_size(self, *, retarget: bool = True) -> None:
        if not self._alive or self._measuring:
            return
        self._measuring = True
        try:
            # 宽度变化后让换行布局得到完整自然高；动画帧不缩小内容本身。
            for _ in range(2):
                width = max(self.content.minimumWidth(), self.width())
                # QLabel 的尺寸策略可能被调用方重设；直接询问换行高，-1 才代表不支持。
                height = self.content.heightForWidth(width)
                if height < 0:
                    height = self.content.sizeHint().height()
                height = max(0, height, self.content.minimumSizeHint().height())
                self.content.resize(width, height)
                layout = self.content.layout()
                if layout is not None:
                    layout.activate()
            height = self.content.height()
            changed = self._target_height != height
            self._target_height = height
            if changed and retarget and self.expanded and not self._preparing:
                if self.animation.state() == QAbstractAnimation.State.Running:
                    self._animate()
                else:
                    self._apply_height(height)
        finally:
            self._measuring = False

    def finish(self) -> None:
        """取消等待与采样，提交当前业务目标的最终可见范围。"""
        if not self._alive or self._finishing:
            return
        self._finishing = True
        try:
            self._measure_timer.stop()
            self.animation.stop()
            if self.expanded:
                self._sync_content_size(retarget=False)
            if not self.expanded:
                self.content.hide()
                self.hide()
            # 隐藏后再通知外层测高，才能同时收回布局为可见槽位预留的间距。
            self._apply_height(self._target_height if self.expanded else 0)
        finally:
            self._finishing = False

    def _animation_state_changed(self, state: object, _previous: object) -> None:
        window = self.window()
        if (state == QAbstractAnimation.State.Stopped
                and window is not None and window.isMinimized()):
            self.finish()

    def _focus_changed(self, _previous: QWidget | None, current: QWidget | None) -> None:
        if (self._alive and self.expanded and current is not None
                and (current is self.content or self.content.isAncestorOf(current))):
            self.finish()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._sync_content_size()

    def hideEvent(self, event) -> None:  # noqa: N802
        self.finish()
        super().hideEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (self._alive and self.expanded and not self._measuring and event.type() in (
                QEvent.Type.LayoutRequest, QEvent.Type.FontChange, QEvent.Type.Resize,
        )):
            self._measure_timer.start(0)
        return False

    def event(self, event) -> bool:
        result = super().event(event)
        if (event.type() == QEvent.Type.LayoutRequest and getattr(self, "_alive", False)
                and self.expanded and not self._measuring):
            self._measure_timer.start(0)
        return result

    def _content_destroyed(self) -> None:
        self._alive = False
        self._measure_timer.stop()
        self.animation.stop()

    def _toggle_destroyed(self) -> None:
        self._toggle_ref = None


class CollapsibleTools(QWidget):
    """只管理裁剪展开，不接管设备目标、任务或内容控件的信号连接。"""

    expanded_changed = Signal(bool)

    def __init__(
        self, title: str, content: QWidget, parent=None, *,
        icon: FluentIcon = FluentIcon.APPLICATION,
        tooltip: str = "批量操作使用顶部勾选的操作设备；本地 APK 工具无需设备。收起时保留输入",
    ):
        super().__init__(parent)
        self.title = tr(title)
        self.content = content
        self.toggle_button = PushButton(icon, tr("展开 · {title}").format(title=self.title), self)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setAccessibleName(self.title)
        self.toggle_button.setToolTip(tr(tooltip))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.toggle_button)
        self.reveal = ContentReveal(content, self.toggle_button, self)
        layout.addWidget(self.reveal)
        self.toggle_button.toggled.connect(self._set_expanded)
        BaseStyles.ui_font_changed.connect(self._apply_font)
        self._apply_font()

    def _apply_font(self, *_args):
        self.toggle_button.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.toggle_button.setMinimumHeight(max(32, self.toggle_button.fontMetrics().height() + 14))

    def _set_expanded(self, expanded: bool):
        self.reveal.set_expanded(expanded)
        template = tr("收起 · {title}") if expanded else tr("展开 · {title}")
        self.toggle_button.setText(template.format(title=self.title))
        self.updateGeometry()
        self.expanded_changed.emit(expanded)
