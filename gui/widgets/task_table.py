"""任务中心的表格视觉；真实行控件管理展示与选择，不拥有执行资源。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    SmoothScrollArea,
    TransparentPushButton,
    TransparentToolButton,
    isDarkTheme,
)

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import (
    apply_focus_indicator,
    apply_font_role,
    apply_label_role,
    use_smooth_scroll,
)
from gui.widgets.collapsible_tools import ContentReveal
from gui.widgets.task_action_gesture import TaskActionGesture


@dataclass(frozen=True)
class TaskRowData:
    """已脱敏的单行投影；稳定 key 与取消身份分别由页面维护。"""

    key: str
    title: str
    kind: str
    target: str
    state: str
    tone: str
    time_text: str
    scope: str
    cancellable: bool = False
    cancelling: bool = False
    unread: bool = False
    progress: int | None = None
    stop_action: bool = False
    stop_revision: str = ""

    @property
    def status_text(self) -> str:
        """百分比仅来自 Operation 快照，不为普通命令估算进度。"""
        return self.state if self.progress is None else f"{self.state} {self.progress}%"


class _ElidingLabel(BodyLabel):
    def __init__(self, parent=None):
        self._full_text = ""
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self._elide()

    def _elide(self) -> None:
        super().setText(
            self.fontMetrics().elidedText(
                self._full_text,
                Qt.TextElideMode.ElideRight,
                max(0, self.contentsRect().width()),
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        # 列宽与行高不变时，字体字宽仍可能变化，不能等待下一次 resize 才省略。
        if event.type() == QEvent.Type.FontChange:
            self._elide()


class _TaskTitle(TransparentPushButton):
    def __init__(self, parent=None):
        self.full_text = ""
        super().__init__(parent)
        self.setObjectName("taskTitle")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        apply_focus_indicator(
            self,
            keyboard_only=True,
            content_qss="QPushButton#taskTitle { text-align: left; padding: 0px; }",
        )

    def setText(self, text: str) -> None:
        self.full_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self._elide()

    def _elide(self) -> None:
        super().setText(
            self.fontMetrics().elidedText(
                self.full_text,
                Qt.TextElideMode.ElideRight,
                max(0, self.width() - 16),
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._elide()


class TaskRow(QWidget):
    """保留同身份行、真实按钮和阅读器宿主；刷新不重建已聚焦的控件。"""

    activated = Signal(str)
    selected = Signal(str)
    navigate_requested = Signal(str, int)
    cancel_requested = Signal(str)
    stop_requested = Signal(str, str)

    def __init__(self, data: TaskRowData, parent=None):
        super().__init__(parent)
        self.data = data
        self._selected = False
        self._alternate = False
        self._hovered = False
        self._pointer_pressed = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QWidget(self)
        self.columns = QHBoxLayout(self.header)
        self.columns.setContentsMargins(0, 0, 0, 0)
        self.columns.setSpacing(0)
        self.task_cell = QWidget(self.header)
        name_layout = QVBoxLayout(self.task_cell)
        name_layout.setContentsMargins(8, 5, 8, 5)
        name_layout.setSpacing(0)
        title_line = QHBoxLayout()
        title_line.setContentsMargins(0, 0, 0, 0)
        title_line.setSpacing(4)
        self.title = _TaskTitle(self.task_cell)
        self.unread = BodyLabel("•", self.task_cell)
        self.unread.setAccessibleName(tr("有未查看的异常"))
        self.scope = BodyLabel(self.task_cell)
        self.scope.setTextFormat(Qt.TextFormat.PlainText)
        title_line.addWidget(self.title, 1)
        title_line.addWidget(self.unread)
        title_line.addWidget(self.scope)
        name_layout.addLayout(title_line)
        self.subtitle = _ElidingLabel(self.task_cell)
        self.subtitle.hide()
        name_layout.addWidget(self.subtitle)
        self.kind = _ElidingLabel(self.header)
        self.target = _ElidingLabel(self.header)
        self.status_cell = QWidget(self.header)
        status_layout = QHBoxLayout(self.status_cell)
        status_layout.setContentsMargins(8, 5, 8, 5)
        status_layout.setSpacing(4)
        self.status = _ElidingLabel(self.status_cell)
        self.cancel = TransparentToolButton(FluentIcon.CLOSE, self.status_cell)
        self.cancel.setAccessibleName(tr("取消任务"))
        apply_focus_indicator(self.cancel, keyboard_only=True)
        status_layout.addWidget(self.status, 1)
        status_layout.addWidget(self.cancel)
        self.time = _ElidingLabel(self.header)
        self.cells = (
            self.task_cell,
            self.kind,
            self.target,
            self.status_cell,
            self.time,
        )
        for cell in self.cells:
            cell.setMinimumWidth(0)
            self.columns.addWidget(cell)
        for label in (self.kind, self.target, self.time):
            label.setContentsMargins(8, 0, 8, 0)
        for label in (self.unread, self.scope, self.kind, self.target, self.status, self.time):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.header)
        self.detail_host = QWidget(self)
        self.detail_layout = QVBoxLayout(self.detail_host)
        self.detail_layout.setContentsMargins(8, 12, 12, 16)
        self.detail_layout.setSpacing(8)
        self.reveal = ContentReveal(self.detail_host, self.title, self)
        layout.addWidget(self.reveal)
        # 视口负责裁切移出窗口的行，安全区不能再次压缩这些内容布局。
        for surface in (
            self,
            self.header,
            self.task_cell,
            self.status_cell,
            self.detail_host,
            self.reveal,
        ):
            surface.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)
        self.title.clicked.connect(lambda: self.activated.emit(self.data.key))
        for button in (self.title, self.cancel):
            # Cocoa 默认键盘导航会跳过仅有 TabFocus 的按钮，行内动作需真实可达。
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.pressed.connect(lambda: self.selected.emit(self.data.key))
            button.installEventFilter(self)
        self._cancel_gesture = TaskActionGesture(
            self.cancel,
            lambda: (self.data.key, self.data.stop_action, self.data.stop_revision),
        )
        self._cancel_gesture.activated.connect(self._dispatch_cancel)
        self.update_data(data)

    def _dispatch_cancel(self, key: str, stop_action: bool, revision: str) -> None:
        """点击完成只使用按下时显示的身份，刷新后的运行版本不能承接旧手势。"""
        if stop_action:
            self.stop_requested.emit(key, revision)
        else:
            self.cancel_requested.emit(key)

    def update_data(self, data: TaskRowData) -> None:
        self.data = data
        self.title.setText(data.title)
        self.unread.setVisible(data.unread)
        self.scope.setText(data.scope)
        self.kind.setText(data.kind)
        self.target.setText(data.target)
        self.subtitle.setText(f"{data.scope} · {data.target}")
        self.status.setText(data.status_text)
        self.time.setText(data.time_text)
        self.cancel.setVisible(data.cancellable)
        self.cancel.setEnabled(data.cancellable and not data.cancelling)
        self.cancel.setAccessibleName(tr("停止会话") if data.stop_action else tr("取消任务"))
        self.cancel.setToolTip(
            (tr("正在停止") if data.cancelling else tr("停止 {task}").format(task=data.title))
            if data.stop_action
            else (tr("正在取消") if data.cancelling else tr("取消 {task}").format(task=data.title))
        )
        self.setAccessibleName(f"{data.title} · {data.scope} · {data.target} · {data.state}")
        self.sync_style()

    def sync_style(self) -> None:
        apply_font_role(self.title, FontRole.UI, ensure_height=True)
        apply_label_role(self.unread, FontRole.UI, color_key="LOG_ERROR")
        for label in (self.kind, self.target, self.time, self.subtitle, self.scope):
            apply_label_role(label, FontRole.UI_SMALL, color_key="TEXT_SECONDARY")
        key = {
            "success": "LOG_SUCCESS",
            "warning": "LOG_WARNING",
            "danger": "LOG_ERROR",
            "accent": "BORDER_FOCUS",
        }.get(self.data.tone, "TEXT_SECONDARY")
        apply_label_role(self.status, FontRole.UI_SMALL, color_key=key)
        side = max(28, self.title.fontMetrics().height() + 8)
        self.cancel.setFixedSize(side, side)
        # 行高统一由表格根据字体预算，长内容保留全文提示与辅助技术名称。
        first_line_height = self.title.minimumHeight()
        self.status_cell.setMinimumHeight(first_line_height)
        for label in (self.kind, self.target, self.time):
            label.setMinimumHeight(first_line_height)
        self.update()

    def set_presentation(self, *, selected: bool, alternate: bool) -> None:
        """选择与交替背景只影响本行绘制，不改变任务数据或按钮准入。"""
        if (selected, alternate) != (self._selected, self._alternate):
            self._selected, self._alternate = selected, alternate
            self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._pointer_pressed = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self.selected.emit(self.data.key)
        super().focusInEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.header.geometry().contains(
            event.position().toPoint()
        ):
            self._pointer_pressed = True
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.selected.emit(self.data.key)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        pressed, self._pointer_pressed = self._pointer_pressed, False
        if (
            pressed
            and event.button() == Qt.MouseButton.LeftButton
            and self.header.geometry().contains(event.position().toPoint())
        ):
            self.activated.emit(self.data.key)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if (
            isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End)
        ):
            self.navigate_requested.emit(self.data.key, event.key())
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.data.key)
            event.accept()
        elif event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
            self.navigate_requested.emit(self.data.key, event.key())
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha = 17 if self._selected else 5 if self._alternate else 0
        if self._hovered:
            alpha = 25 if self._selected else 12
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QColor(
                255 if isDarkTheme() else 0,
                255 if isDarkTheme() else 0,
                255 if isDarkTheme() else 0,
                alpha,
            )
        )
        painter.drawRoundedRect(QRectF(self.header.rect()).adjusted(4, 2, -4, -2), 5, 5)
        if self._selected:
            painter.setBrush(QColor(BaseStyles.color("BORDER_FOCUS")))
            height = self.header.height()
            painter.drawRoundedRect(QRectF(4, height * 0.257, 3, height * 0.486), 1.5, 1.5)


class _TaskHeader(QWidget):
    """真实标签组成表头，和记录使用相同列预算及项目字体。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.cells = tuple(_ElidingLabel(self) for _ in range(5))
        for cell, text in zip(self.cells, ("任务", "类型", "目标", "状态", "时间")):
            cell.setText(tr(text))
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setContentsMargins(5, 0, 5, 0)
            layout.addWidget(cell)
        self.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        line = QColor(
            255 if isDarkTheme() else 0,
            255 if isDarkTheme() else 0,
            255 if isDarkTheme() else 0,
            15,
        )
        painter.setPen(line)
        painter.drawLine(0, 0, self.width(), 0)
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        for cell in self.cells[:-1]:
            right = cell.geometry().right()
            painter.drawLine(right, 0, right, self.height() - 1)


class TaskTable(QWidget):
    """真实行控件复用表格视觉；不创建 item view 的临时辅助行列对象。"""

    expanded_changed = Signal(str)
    detail_requested = Signal(str)
    cancel_requested = Signal(str)
    stop_requested = Signal(str, str)

    def __init__(self, parent=None, *, external_details: bool = False):
        super().__init__(parent)
        self.rows: dict[str, TaskRow] = {}
        self.expanded_key = ""
        self._external_details = external_details
        self._detail: QWidget | None = None
        self._order: tuple[str, ...] = ()
        self._selected_key = ""
        self._reflowing = False
        self.setMinimumWidth(0)
        self.setAccessibleName(tr("任务中心"))
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.header_clip = QWidget(self)
        self.header_clip.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)
        self.header = _TaskHeader(self.header_clip)
        self.header_cells = self.header.cells
        self._layout.addWidget(self.header_clip)
        self.view = use_smooth_scroll(SmoothScrollArea(self))
        self.view.setObjectName("taskRecordsTable")
        self.view.setAccessibleName(tr("任务中心"))
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setWidgetResizable(True)
        self.view.setMinimumWidth(0)
        self.view.setMinimumHeight(180)
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.view.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.content = QWidget()
        self.content.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._rows_layout = QVBoxLayout(self.content)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch(1)
        self.view.setWidget(self.content)
        # setWidget 会自动开启正文填底，须恢复透明以透出宿主的主题材质。
        self.content.setAutoFillBackground(False)
        self.view.viewport().setAutoFillBackground(False)
        self.view.installEventFilter(self)
        self.view.viewport().installEventFilter(self)
        self.view.horizontalScrollBar().valueChanged.connect(self._sync_header_offset)
        self._layout.addWidget(self.view, 1)
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._escape.setEnabled(not external_details)
        self._escape.activated.connect(lambda: self.set_expanded("", None))
        BaseStyles.ui_font_changed.connect(self._sync_theme_state)
        BaseStyles.theme_changed.connect(self._sync_theme_state)
        self._sync_theme_state()

    @property
    def record_keys(self) -> tuple[str, ...]:
        """返回当前显示顺序；读取不改变任务、选择或详情状态。"""
        return self._order

    @property
    def selected_key(self) -> str:
        """返回本表当前选择，和外部阅读器独立保留的任务身份无关。"""
        return self._selected_key

    def set_rows(self, records: tuple[TaskRowData, ...]) -> None:
        """按身份原位更新与移动；移除行前先归还共享阅读器，再延迟销毁行。"""
        keys = {record.key for record in records}
        if self.expanded_key and self.expanded_key not in keys:
            self.set_expanded("", None)
        for key in self.rows.keys() - keys:
            row = self.rows.pop(key)
            self._rows_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        if self._selected_key not in keys:
            self._selected_key = ""
        for index, record in enumerate(records):
            row = self.rows.get(record.key)
            if row is None:
                row = TaskRow(record, self.content)
                row.title.setCheckable(not self._external_details)
                row.title.setAccessibleDescription(
                    tr("查看任务详情") if self._external_details else tr("展开任务详情")
                )
                row.activated.connect(self._toggle)
                row.selected.connect(self.select_row)
                row.navigate_requested.connect(self._navigate)
                row.cancel_requested.connect(self.cancel_requested)
                row.stop_requested.connect(self.stop_requested)
                row.reveal.geometry_changed.connect(self._reflow)
                self.rows[record.key] = row
            elif row.data != record:
                row.update_data(record)
            if self._rows_layout.indexOf(row) != index:
                self._rows_layout.insertWidget(index, row)
            row.set_presentation(
                selected=record.key == self._selected_key, alternate=index % 2 == 0
            )
            row.show()
        self._order = tuple(record.key for record in records)
        self._reflow()
        # 原生 Tab 顺序跟随当前行顺序，真实按钮仍由 Qt 提供可访问操作。
        controls = [
            button
            for key in self._order
            for button in (
                self.rows[key].title,
                self.rows[key].cancel,
            )
        ]
        for first, second in zip(controls, controls[1:]):
            QWidget.setTabOrder(first, second)

    def select_row(self, key: str, *, focus: bool = False) -> None:
        """只更新表内选择；聚焦导航时确保入口可见，不执行任务或停止动作。"""
        if key not in self.rows:
            return
        self._selected_key = key
        for index, name in enumerate(self._order):
            self.rows[name].set_presentation(selected=name == key, alternate=index % 2 == 0)
        if focus:
            row = self.rows[key]
            row.setFocus(Qt.FocusReason.OtherFocusReason)
            self.view.ensureWidgetVisible(row.title, 0, 4)

    def _navigate(self, key: str, direction: int) -> None:
        if not self._order:
            return
        index = self._order.index(key) if key in self._order else -1
        if direction == Qt.Key.Key_Home:
            index = 0
        elif direction == Qt.Key.Key_End:
            index = len(self._order) - 1
        else:
            index = max(
                0, min(len(self._order) - 1, index + (1 if direction == Qt.Key.Key_Down else -1))
            )
        self.select_row(self._order[index], focus=True)

    def _toggle(self, key: str) -> None:
        self.select_row(key)
        if self._external_details:
            self.detail_requested.emit(key)
            return
        self.set_expanded("" if self.expanded_key == key else key, None)

    def set_expanded(self, key: str, detail: QWidget | None = None) -> None:
        """在原行挂载既有阅读器；收起或筛掉记录只归还控件，不取消任务。"""
        if key and key not in self.rows:
            return
        changed = key != self.expanded_key
        if changed and self.expanded_key in self.rows:
            old = self.rows[self.expanded_key]
            old.reveal.set_expanded(False, animated=False)
            old.title.setChecked(False)
            old.title.setAccessibleDescription(tr("展开任务详情"))
            if self._detail is not None:
                old.detail_layout.removeWidget(self._detail)
                self._detail.hide()
                self._detail.setParent(self)
                self._detail = None
        self.expanded_key = key
        if key:
            row = self.rows[key]
            row.title.setChecked(True)
            row.title.setAccessibleDescription(tr("收起任务详情"))
            if detail is not None:
                self._detail = detail
                row.detail_layout.addWidget(detail)
                detail.show()
            row.reveal.set_expanded(self._detail is not None, animated=False)
        self._reflow()
        if changed:
            self.expanded_changed.emit(key)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.view.viewport() and event.type() == QEvent.Type.Resize:
            self._reflow()
        if (
            watched is self.view
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
        ):
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
                self._navigate(self._selected_key, event.key())
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                if self._selected_key:
                    self._toggle(self._selected_key)
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _sync_theme_state(self, *_args) -> None:
        self.header.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        for cell in self.header_cells:
            apply_label_role(cell, FontRole.UI_SMALL, color_key="TEXT_SECONDARY")
        height = max(35, self.header.fontMetrics().height() + 14)
        self.header_clip.setFixedHeight(height)
        self.header.setFixedHeight(height)
        for row in self.rows.values():
            row.sync_style()
        self.header.update()
        self._reflow()

    def _sync_header_offset(self, *_args) -> None:
        self.header.move(self.view.viewport().x() - self.view.horizontalScrollBar().value(), 0)

    def _reflow(self) -> None:
        if not hasattr(self, "view") or self._reflowing:
            return
        self._reflowing = True
        try:
            fm = self.header.fontMetrics()
            side = max((row.cancel.width() for row in self.rows.values()), default=28)
            kind = max(
                80,
                min(
                    144,
                    max(
                        (fm.horizontalAdvance(r.data.kind) + 24 for r in self.rows.values()),
                        default=80,
                    ),
                ),
            )
            state = max(
                100,
                max(
                    (
                        fm.horizontalAdvance(r.data.status_text)
                        + 28
                        + (side + 4 if r.data.cancellable else 0)
                        for r in self.rows.values()
                    ),
                    default=100,
                ),
            )
            widths = [0, kind, 180, state, fm.horizontalAdvance("11-07 10:10") + 24]
            # 按固定短语保留任务名可辨预算，不随任意长名称无限拉宽；名称区另有
            # 左右 16px 留白、4px 标签间距，未读标记出现时再计入它的实际宽度。
            task_minimum = max(200, max((
                row.title.fontMetrics().horizontalAdvance(tr("任务名称")) + 36
                + row.scope.sizeHint().width() + 20
                + (row.unread.sizeHint().width() + 4 if row.data.unread else 0)
                for row in self.rows.values()
            ), default=200))
            widths[0] = max(task_minimum, self.view.viewport().width() - sum(widths))
            total = sum(widths)
            self.content.setMinimumWidth(total)
            self.header.setFixedWidth(total)
            for cell, width in zip(self.header_cells, widths):
                cell.setFixedWidth(width)
            height = 0
            for row in self.rows.values():
                for cell, width in zip(row.cells, widths):
                    cell.setFixedWidth(width)
                row_height = max(40, row.title.minimumHeight() + 10, side + 10)
                row.header.setFixedHeight(row_height)
                row.setFixedHeight(row_height + row.reveal.height())
                height += row.height()
            self.content.setMinimumHeight(height)
            self._rows_layout.activate()
            self._sync_header_offset()
        finally:
            self._reflowing = False
