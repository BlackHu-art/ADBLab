"""主窗口内容面上的共享任务抽屉；只呈现任务身份，不执行或保存业务状态。"""

from __future__ import annotations

import weakref
from math import ceil

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QKeySequence, QPalette, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    HorizontalSeparator,
    PushButton,
    SmoothScrollArea,
    StrongBodyLabel,
    TransparentToolButton,
    setCustomStyleSheet,
)
from shiboken6 import isValid

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import (
    apply_label_role,
    configure_button,
    configure_fluent_control,
    set_function_tooltip,
    use_smooth_scroll,
)
from gui.widgets.frame_animation import FrameAnimation
from gui.widgets.task_action_gesture import TaskActionGesture
from gui.widgets.task_table import TaskRowData


class TaskDetailDrawer(QWidget):
    """固定拥有一个阅读器的非模态覆盖层；开关与取消任务互不关联。

    opened 表示当前目标。关闭意图立即发 opened_changed(False)，完成位移并
    隐藏才发 closed；中途重新打开不会发旧 closed。宿主隐藏或最小化时提交
    当前目标的最终几何。shutdown 封闭全部更新、立即关闭且不归还焦点。
    """

    task_requested = Signal(str)
    cancel_requested = Signal(str)
    stop_requested = Signal(str, str)
    source_requested = Signal(str)
    locate_requested = Signal(str)
    opened_changed = Signal(bool)
    closed = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("taskDetailDrawer")
        self.setAccessibleName(tr("任务详情"))
        self.setMinimumWidth(0)
        # QWidget 子类须显式绘制 QSS 底板；自身 grab 不能证明宿主叠放时已遮住下层。
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAutoFillBackground(True)
        self._opened = False
        self._shutdown = False
        self._host_ref = weakref.ref(parent)
        self._selected_key = ""
        self._stop_action = False
        self._stop_revision = ""
        self._content: QWidget | None = None
        self._origin: weakref.ReferenceType[QWidget] | None = None
        self._needs_closed = False
        self._settling = False
        self._focus_policies: weakref.WeakKeyDictionary[QWidget, Qt.FocusPolicy] = (
            weakref.WeakKeyDictionary()
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 12, 8)
        header_layout.setSpacing(8)
        self.title_label = StrongBodyLabel(header)
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.close_button = TransparentToolButton(FluentIcon.CLOSE, header)
        self.close_button.setAccessibleName(tr("收起任务详情，任务继续执行"))
        set_function_tooltip(self.close_button, "收起任务详情，任务继续执行")
        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.close_button)
        layout.addWidget(header)
        layout.addWidget(HorizontalSeparator(self))

        self.scroll_area = use_smooth_scroll(SmoothScrollArea(self))
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll_area.viewport().setAutoFillBackground(False)
        self.body = QWidget()
        self.body.setMinimumWidth(0)
        self.body.setAutoFillBackground(False)
        self.body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._body_layout = QVBoxLayout(self.body)
        self._body_layout.setContentsMargins(16, 12, 16, 16)
        self._body_layout.setSpacing(12)
        self.meta_host = QWidget(self.body)
        self._meta_layout = QGridLayout(self.meta_host)
        self._meta_layout.setContentsMargins(0, 0, 0, 0)
        self._meta_layout.setHorizontalSpacing(8)
        self._meta_layout.setVerticalSpacing(4)
        self.status_label = BodyLabel(self.meta_host)
        self.status_label.setContentsMargins(7, 2, 7, 2)
        self.source_label = BodyLabel(self.meta_host)
        self.target_label = BodyLabel(self.meta_host)
        for label in (self.status_label, self.source_label, self.target_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setMinimumWidth(0)
            label.setWordWrap(True)
        self._body_layout.addWidget(self.meta_host)
        self.cancel_button = PushButton(FluentIcon.CANCEL, tr("取消任务"), self.body)
        self._body_layout.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.cancel_button.hide()
        self._body_layout.addStretch(1)
        self.scroll_area.setWidget(self.body)
        # setWidget 会重新启用正文填充；安装后再透出抽屉同一实色底板。
        self.body.setAutoFillBackground(False)
        self.scroll_area.viewport().setAutoFillBackground(False)
        layout.addWidget(self.scroll_area, 1)

        self.animation = FrameAnimation(self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._move_to)
        self.animation.finished.connect(self._finish)
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape.setContext(Qt.ShortcutContext.WindowShortcut)
        self._escape.activated.connect(self.close_drawer)
        self._close_gesture = TaskActionGesture(
            self.close_button, lambda: (self._selected_key, False, ""),
            admission=self.accepts_user_actions,
        )
        self._close_gesture.activated.connect(lambda *_args: self.close_drawer())
        self._cancel_gesture = TaskActionGesture(
            self.cancel_button,
            lambda: (self._selected_key, self._stop_action, self._stop_revision),
            admission=self.accepts_user_actions,
        )
        self._cancel_gesture.activated.connect(self._dispatch_cancel)
        BaseStyles.theme_changed.connect(self._sync_theme)
        BaseStyles.accent_color_changed.connect(self._sync_theme)
        BaseStyles.ui_font_changed.connect(self._sync_fonts)
        parent.installEventFilter(self)
        self.scroll_area.viewport().installEventFilter(self)
        parent.destroyed.connect(self._host_destroyed)
        self._sync_theme()
        self._sync_fonts()
        self._place(0.0)
        self.hide()
        self._set_interactive(False)

    @property
    def opened(self) -> bool:
        """立即返回开关目标，不把动画尚未完成误当成仍可交互。"""
        return self._opened

    @property
    def selected_key(self) -> str:
        """当前展示的稳定任务身份；不随收起清空。"""
        return self._selected_key

    def accepts_user_actions(self) -> bool:
        """只允许正在呈现的打开目标接收新动作；覆盖区的鼠标遮挡独立于该资格。"""
        window = self.window()
        return (self._opened and not self._shutdown and self.isVisible()
                and window is not None and not window.isMinimized())

    def set_content(self, content: QWidget) -> None:
        """一次安装页面的单例阅读器；重复安装同一对象无副作用，不允许替换。"""
        if self._shutdown or content is self._content:
            return
        if self._content is not None:
            raise ValueError("任务抽屉只能安装一个共享阅读器")
        self._content = content
        self._body_layout.insertWidget(self._body_layout.count() - 1, content)
        content.show()
        if not self._opened:
            self._set_interactive(False)

    def present(
        self, row: TaskRowData, *, source_label: str = "", archived: bool = False,
        source_available: bool = False, recent: tuple[TaskRowData, ...] = (),
        from_task_center: bool = False,
    ) -> None:
        """原位呈现当前任务；旧调用方传入的来源导航及最近列表参数保留兼容。"""
        if self._shutdown:
            return
        self._selected_key = row.key
        self._stop_action = row.stop_action
        self._stop_revision = row.stop_revision
        self.title_label.setToolTip(row.title)
        self.title_label.setAccessibleName(row.title)
        self.status_label.setText(row.status_text)
        color = {"success": "LOG_SUCCESS", "warning": "LOG_WARNING",
                 "danger": "LOG_ERROR", "accent": "BORDER_FOCUS"}.get(row.tone, "TEXT_SECONDARY")
        self.status_label.setProperty("taskStatusColor", color)
        self.source_label.setText(source_label or row.kind)
        self.target_label.setText(row.target)
        for label in (self.source_label, self.target_label):
            label.setToolTip(label.text())
        self.source_label.setVisible(bool(self.source_label.text()))
        self.target_label.setVisible(bool(row.target))
        self.cancel_button.setVisible(row.cancellable)
        self.cancel_button.setEnabled(row.cancellable and not row.cancelling)
        self.cancel_button.setText(
            (tr("正在停止") if row.cancelling else tr("停止会话")) if row.stop_action
            else (tr("正在取消") if row.cancelling else tr("取消任务"))
        )
        retention = (tr("已归档 · 关闭应用后仍可查看") if archived
                     else tr("本次会话 · 需要保留的正文请导出"))
        self.status_label.setToolTip(retention)
        self.status_label.setAccessibleDescription(retention)
        self._sync_fonts()
        if not self._opened:
            self._set_interactive(False)

    def _dispatch_cancel(self, key: str, stop_action: bool, revision: str) -> None:
        """阅读目标或版本在按下后改变时，仍提交原手势身份供页面复核。"""
        if not self.accepts_user_actions():
            return
        if stop_action:
            self.stop_requested.emit(key, revision)
        else:
            self.cancel_requested.emit(key)

    def _reflow_controls(self) -> None:
        """固定标题为关闭入口预留空间，原名可由提示或辅助技术读取。"""
        available = max(1, self.width() - 1 - 16 - 12 - 8 - self.close_button.width())
        title = self.title_label
        full_title = title.accessibleName()
        title.setText(full_title)
        metrics = title.fontMetrics()
        if (title.heightForWidth(available) > 2 * metrics.lineSpacing() + 4
                or title.minimumSizeHint().width() > available):
            title.setText(metrics.elidedText(full_title, Qt.TextElideMode.ElideRight, available))
        width = max(1, self.scroll_area.viewport().width() - 32)
        grid = self._meta_layout
        while grid.count():
            grid.takeAt(0)
        for label in (self.source_label, self.status_label, self.target_label):
            label.setMaximumWidth(width)
        status = self.status_label
        source = self.source_label
        margins = status.contentsMargins()
        text_width = QFontMetricsF(status.font(), status).horizontalAdvance(status.text())
        status_width = ceil(text_width) + margins.left() + margins.right()
        # 来源列可以伸展，但不能收窄徽标；较长译文独占一行并在正文宽度内换行。
        status.setMinimumWidth(min(status_width, width))
        source_width = ceil(QFontMetricsF(source.font(), source).horizontalAdvance(source.text()))
        if status_width + grid.horizontalSpacing() + source_width <= width:
            grid.addWidget(status, 0, 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(source, 0, 1)
            target_row = 1
        else:
            grid.addWidget(status, 0, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(source, 1, 0, 1, 2)
            target_row = 2
        grid.addWidget(self.target_label, target_row, 0, 1, 2)
        grid.setColumnStretch(1, 1)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_meta_layout"):
            self._reflow_controls()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 滑出后隐藏时，macOS 安全区可把布局宽度扣至零。重新显示后内容区已恢复，
        # 位置动画不会触发 resize，须在第一帧前把可见内容区交还原布局。
        layout = self.layout()
        if layout is not None:
            layout.setGeometry(self.contentsRect())

    def open_drawer(self, origin: QWidget | None = None, *, animated: bool = True) -> None:
        """打开当前任务；只有显式有效入口才转移焦点，自动反馈保留原焦点。"""
        if self._shutdown:
            return
        changed = not self._opened
        if changed:
            # 关闭期间也可能收到不合格的 AX 动画；进入新呈现前结束它，不能吞掉新按下。
            self._cancel_pending_inputs()
        self._opened = True
        self._needs_closed = True
        external_origin = (origin is not None and isValid(origin)
                           and origin is not self and not self.isAncestorOf(origin))
        previous_origin = self._origin() if self._origin is not None else None
        if (external_origin and origin is not None
                and (previous_origin is None or not isValid(previous_origin))):
            self._origin = weakref.ref(origin)
        self._set_interactive(True)
        self.show()
        self.raise_()
        if changed:
            self.opened_changed.emit(True)
        if not self._opened or self._shutdown:
            return
        if changed:
            self._animate(animated)
        if external_origin:
            self.close_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def close_drawer(self, *, animated: bool = True) -> None:
        """同步撤销业务动作与焦点，保留覆盖区鼠标遮挡；隐藏后才发 closed。"""
        if self._shutdown or not self._opened:
            return
        self._opened = False
        focus = QApplication.focusWidget()
        if focus is None or focus is self or self.isAncestorOf(focus):
            origin = self._origin() if self._origin is not None else None
            if origin is not None and isValid(origin) and origin.isVisible() and origin.isEnabled():
                origin.setFocus(Qt.FocusReason.OtherFocusReason)
            elif focus is not None:
                focus.clearFocus()
        self._origin = None
        self._set_interactive(False)
        self.opened_changed.emit(False)
        if not self._opened:
            self._animate(animated)

    def _set_interactive(self, interactive: bool) -> None:
        # 可见的滑出表面仍须参与命中；关闭态事件由本地过滤器吃掉，不能穿给底层按钮。
        widgets = (self, *self.findChildren(QWidget))
        if interactive:
            policies = [(widget, policy) for widget, policy in self._focus_policies.items()
                        if isValid(widget)]

            def proxy_depth(item) -> int:
                widget = item[0]
                seen = set()
                while widget is not None and isValid(widget) and widget not in seen:
                    seen.add(widget)
                    widget = widget.focusProxy()
                return len(seen)

            # setFocusPolicy 会传播到 focusProxy；先恢复代理来源、最后恢复实际焦点宿主。
            # 原值已经相同时不再写入，避免 viewport 的 NoFocus 再次污染阅读器。
            for widget, policy in sorted(policies, key=proxy_depth, reverse=True):
                if widget.focusPolicy() != policy:
                    widget.setFocusPolicy(policy)
            self._focus_policies.clear()
        else:
            self._cancel_pending_inputs()
            # 必须先取得全树快照，任一代理的策略写入都可能同步改变另一个控件。
            for widget in widgets:
                if widget not in self._focus_policies:
                    self._focus_policies[widget] = widget.focusPolicy()
            for widget in widgets:
                if widget.focusPolicy() != Qt.FocusPolicy.NoFocus:
                    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                widget.installEventFilter(self)
        self._escape.setEnabled(interactive)

    def _cancel_pending_inputs(self) -> None:
        """使当前呈现留下的输入及原生动画失效，不影响新呈现中的合法手势。"""
        for gesture in (self._cancel_gesture, self._close_gesture):
            if isValid(gesture):
                gesture.cancel_pending()

    def _place(self, fraction: float) -> None:
        host = self._host_ref()
        if host is not None and isValid(host):
            width = min(390, max(0, host.width()))
            self.setGeometry(host.width() - round(width * fraction), 0, width, host.height())

    def _move_to(self, value: object) -> None:
        if self._shutdown or not isinstance(value, (float, int)):
            return
        x = round(value)
        if x == self.x():
            return
        self.move(x, 0)
        if QApplication.platformName() == "cocoa":
            host = self.parentWidget()
            if host is not None:
                # Cocoa 轮换绘制缓冲。用同一片侧栏区域提交各帧，覆盖更早位置可能留下的边线。
                host.update(self.rect().translated(host.width() - self.width(), 0))

    def _animate(self, animated: bool) -> None:
        self.animation.stop()
        host = self._host_ref()
        if host is None or not isValid(host):
            return
        end = host.width() - self.width() if self._opened else host.width()
        distance = abs(self.x() - end)
        window = self.window()
        if (not animated or not distance or not self.isVisible()
                or window is not None and window.isMinimized()
                or not self.style().styleHint(QStyle.StyleHint.SH_Widget_Animate)):
            self._finish()
            return
        with QSignalBlocker(self.animation):
            self.animation.setDuration(max(1, round(280 * distance / max(1, self.width()))))
            self.animation.setStartValue(float(self.x()))
            self.animation.setEndValue(float(end))
        self.animation.start()

    def _finish(self) -> None:
        if self._settling:
            return
        self._settling = True
        try:
            self.animation.stop()
            self._place(1.0 if self._opened else 0.0)
            if not self._opened:
                self.hide()
                if self._needs_closed:
                    self._needs_closed = False
                    self.closed.emit()
        finally:
            self._settling = False

    def shutdown(self) -> None:
        """封闭晚到更新并停止本控件资源；立即隐藏且不取消任务或归还入口焦点。"""
        if self._shutdown:
            return
        self._shutdown = True
        was_open = self._opened
        self._opened = False
        self._origin = None
        self._set_interactive(False)
        if was_open:
            self.opened_changed.emit(False)
        self._finish()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if self._shutdown:
            return False
        host = self._host_ref()
        # 宿主析构会同步分发隐藏和子对象移除事件；此时不能再查询控件树或提交几何。
        if host is None or not isValid(host):
            return False
        if watched is self and event.type() == QEvent.Type.Show:
            self._cancel_pending_inputs()
        if (watched is self.scroll_area.viewport() and event.type() == QEvent.Type.Resize
                and hasattr(self, "_meta_layout")):
            self._reflow_controls()
        if (not self._opened and event.type() == QEvent.Type.ChildPolished
                and isinstance(watched, QWidget)
                and (watched is self or self.isAncestorOf(watched))):
            # 后台结果可能在滑出期间增加控件；完成构造后再移出焦点链，避免改到半构造对象。
            self._set_interactive(False)
        if watched is host:
            if event.type() == QEvent.Type.Resize and isinstance(event, QResizeEvent):
                fraction = max(0.0, min(1.0,
                    (event.oldSize().width() - self.x()) / max(1, self.width()),
                ))
                running = self.animation.state() == QAbstractAnimation.State.Running
                self.animation.stop()
                self._place(fraction if running else (1.0 if self._opened else 0.0))
                if running:
                    self._animate(True)
            elif event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
                self._finish()
            elif event.type() == QEvent.Type.WindowStateChange:
                self._cancel_pending_inputs()
                window = self.window()
                if window is not None and window.isMinimized():
                    self._finish()
        if not self._opened and event.type() in (
            QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseMove,
            QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
            QEvent.Type.Shortcut, QEvent.Type.Wheel, QEvent.Type.ContextMenu,
        ) and isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched)):
            return True
        return super().eventFilter(watched, event)

    def hideEvent(self, event) -> None:  # noqa: N802
        host = self._host_ref()
        if not self._shutdown and host is not None and isValid(host):
            self._finish()
        super().hideEvent(event)

    def _host_destroyed(self) -> None:
        """宿主开始拆解后只封闭与停钟，不读写销毁中的窗口或后代控件。"""
        self._shutdown = True
        self._opened = False
        self._origin = None
        self.animation.stop()

    def _sync_theme(self, *_args) -> None:
        if self._shutdown:
            return
        background = QColor(BaseStyles.color("CONTENT_BG"))
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, background)
        self.setPalette(palette)
        self.setStyleSheet(
            f"QWidget#taskDetailDrawer {{ background: {background.name()}; "
            f"border-left: 1px solid {BaseStyles.color('BORDER_COLOR')}; }}"
        )
        self._sync_fonts()

    def _sync_fonts(self, *_args) -> None:
        if self._shutdown:
            return
        apply_label_role(self.title_label, FontRole.TITLE, bold=True)
        for label in (self.source_label, self.target_label):
            apply_label_role(label, FontRole.UI_SMALL, color_key="TEXT_SECONDARY")
        apply_label_role(
            self.status_label, FontRole.UI_SMALL,
            color_key=self.status_label.property("taskStatusColor") or "TEXT_SECONDARY",
        )
        status_color = BaseStyles.color(
            self.status_label.property("taskStatusColor") or "TEXT_SECONDARY",
        )
        tint = QColor(status_color)
        tint.setAlpha(24)
        # 注册到 Fluent 的自定义合成入口，强调色重建样式时仍保留徽标底色。
        badge_style = (
            "FluentLabelBase { "
            f"background: rgba({tint.red()}, {tint.green()}, {tint.blue()}, {tint.alpha()}); "
            f"color: {status_color}; border-radius: 4px; }}"
        )
        setCustomStyleSheet(self.status_label, badge_style, badge_style)
        configure_fluent_control(self.close_button)
        self.close_button.setFixedSize(self.close_button.height(), self.close_button.height())
        configure_button(self.cancel_button, text=self.cancel_button.text(),
                         tooltip=self.cancel_button.text(), danger=True)
        self._reflow_controls()
