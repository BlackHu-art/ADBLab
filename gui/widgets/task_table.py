"""任务中心的共享列宽列表；只管理展示和展开，不拥有任务执行资源。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon, TransparentPushButton, TransparentToolButton

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_focus_indicator, apply_font_role, apply_label_role
from gui.widgets.collapsible_tools import ContentReveal


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
                max(0, self.width()),
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
    """保留同身份行及其展开宿主，后台刷新不能替换聚焦控件。"""

    activated = Signal(str)
    cancel_requested = Signal(str)

    def __init__(self, data: TaskRowData, parent=None):
        super().__init__(parent)
        self.data = data
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 1)
        layout.setSpacing(0)
        self.header = QWidget(self)
        self.header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.columns = QHBoxLayout(self.header)
        self.columns.setContentsMargins(8, 5, 8, 5)
        self.columns.setSpacing(12)
        self.toggle = TransparentToolButton(FluentIcon.CHEVRON_RIGHT, self.header)
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName(tr("展开任务详情"))
        apply_focus_indicator(self.toggle, keyboard_only=True)
        self.task_cell = QWidget(self.header)
        name_layout = QVBoxLayout(self.task_cell)
        name_layout.setContentsMargins(0, 0, 0, 0)
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
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(4)
        self.status = _ElidingLabel(self.status_cell)
        self.cancel = TransparentToolButton(FluentIcon.CLOSE, self.status_cell)
        self.cancel.setAccessibleName(tr("取消任务"))
        apply_focus_indicator(self.cancel, keyboard_only=True)
        status_layout.addWidget(self.status, 1)
        status_layout.addWidget(self.cancel)
        self.time = _ElidingLabel(self.header)
        self.cells = (
            self.toggle,
            self.task_cell,
            self.kind,
            self.target,
            self.status_cell,
            self.time,
        )
        for cell in self.cells:
            cell.setMinimumWidth(0)
            self.columns.addWidget(cell, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.header)
        self.detail_host = QWidget(self)
        self.detail_layout = QVBoxLayout(self.detail_host)
        self.detail_layout.setContentsMargins(40, 12, 12, 16)
        self.detail_layout.setSpacing(8)
        self.reveal = ContentReveal(self.detail_host, self.toggle, self)
        layout.addWidget(self.reveal)
        self.toggle.clicked.connect(lambda: self.activated.emit(self.data.key))
        self.title.clicked.connect(lambda: self.activated.emit(self.data.key))
        self.cancel.clicked.connect(lambda: self.cancel_requested.emit(self.data.key))
        self.update_data(data)

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
        self.cancel.setToolTip(
            tr("正在取消") if data.cancelling else tr("取消 {task}").format(task=data.title)
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
        self.toggle.setFixedSize(side, side)
        self.cancel.setFixedSize(side, side)
        # 窄窗任务名下方多一行目标说明，其余列仍与首行文字共用垂直中心。
        first_line_height = self.title.minimumHeight()
        self.status_cell.setMinimumHeight(first_line_height)
        for label in (self.kind, self.target, self.time):
            label.setMinimumHeight(first_line_height)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QColor(BaseStyles.color("BORDER_COLOR")))
        painter.drawLine(8, self.height() - 1, self.width() - 8, self.height() - 1)


class TaskTable(QWidget):
    """表头与记录共享尺寸预算；详情跨整行，页面只保留一处纵向滚动。"""

    expanded_changed = Signal(str)
    cancel_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: dict[str, TaskRow] = {}
        self.expanded_key = ""
        self._detail: QWidget | None = None
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.header = QWidget(self)
        self.header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._header_layout = QHBoxLayout(self.header)
        self._header_layout.setContentsMargins(8, 4, 8, 4)
        self._header_layout.setSpacing(12)
        self.header_cells = tuple(_ElidingLabel(self.header) for _ in range(6))
        for cell, text in zip(self.header_cells, ("", "任务", "类型", "目标", "状态", "时间")):
            cell.setText(tr(text))
            self._header_layout.addWidget(cell)
        self._layout.addWidget(self.header)
        self._layout.addStretch(1)
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._escape.activated.connect(lambda: self.set_expanded("", None))
        BaseStyles.ui_font_changed.connect(self._sync_theme_state)
        BaseStyles.theme_changed.connect(self._sync_theme_state)
        self._sync_theme_state()

    def set_rows(self, records: tuple[TaskRowData, ...]) -> None:
        """按显式身份更新与排布；展开项消失时先归还详情，避免误删共享阅读器。"""
        keys = {record.key for record in records}
        if self.expanded_key and self.expanded_key not in keys:
            self.set_expanded("", None)
        for key in self.rows.keys() - keys:
            row = self.rows.pop(key)
            self._layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        for index, record in enumerate(records):
            row = self.rows.get(record.key)
            if row is None:
                row = TaskRow(record, self)
                row.activated.connect(self._toggle)
                row.cancel_requested.connect(self.cancel_requested)
                self.rows[record.key] = row
            elif row.data != record:
                row.update_data(record)
            if self._layout.indexOf(row) != index + 1:
                self._layout.insertWidget(index + 1, row)
            row.show()
        self._reflow()

    def _toggle(self, key: str) -> None:
        self.set_expanded("" if self.expanded_key == key else key, None)

    def set_expanded(self, key: str, detail: QWidget | None = None) -> None:
        """在同一行挂载既有阅读器；收起把焦点还给入口，控件内容继续保留。"""
        if key and key not in self.rows:
            return
        changed = key != self.expanded_key
        if changed and self.expanded_key in self.rows:
            old = self.rows[self.expanded_key]
            old.reveal.set_expanded(False, animated=False)
            old.toggle.setChecked(False)
            old.toggle.setIcon(FluentIcon.CHEVRON_RIGHT)
            old.toggle.setAccessibleName(tr("展开任务详情"))
            if self._detail is not None:
                old.detail_layout.removeWidget(self._detail)
                self._detail.hide()
                self._detail.setParent(self)
                self._detail = None
        self.expanded_key = key
        if key:
            row = self.rows[key]
            row.toggle.setChecked(True)
            row.toggle.setIcon(FluentIcon.DOWN)
            row.toggle.setAccessibleName(tr("收起任务详情"))
            if detail is not None:
                self._detail = detail
                row.detail_layout.addWidget(detail)
                detail.show()
            row.reveal.set_expanded(self._detail is not None, animated=False)
        if changed:
            self.expanded_changed.emit(key)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _sync_theme_state(self, *_args) -> None:
        for label in self.header_cells:
            apply_label_role(label, FontRole.UI_SMALL, color_key="TEXT_SECONDARY")
        for row in self.rows.values():
            row.sync_style()
        self._reflow()

    def _reflow(self) -> None:
        if not hasattr(self, "header_cells"):
            return
        fm = self.header_cells[1].fontMetrics()
        width = max(0, self.width() - 16)
        side = max(28, BaseStyles.font_for_role(FontRole.UI).pointSize() * 2)
        kind = max(
            64,
            min(
                120,
                max(
                    (fm.horizontalAdvance(r.data.kind) + 8 for r in self.rows.values()), default=64
                ),
            ),
        )
        target = max(
            96,
            min(
                180,
                max(
                    (fm.horizontalAdvance(r.data.target) + 8 for r in self.rows.values()),
                    default=96,
                ),
            ),
        )
        state = max(
            80,
            max(
                (
                    fm.horizontalAdvance(r.data.status_text)
                    + 12
                    + (side + 4 if r.data.cancellable else 0)
                    for r in self.rows.values()
                ),
                default=80,
            ),
        )
        time = fm.horizontalAdvance("11-07 10:10") + 8
        widths = [side, 0, kind, target, state, time]
        visible = [True] * 6
        title_min = max(100, fm.horizontalAdvance(tr("任务名称")) + 36)
        for column in (5, 2, 3):
            if sum(widths) + title_min + 12 * (sum(visible) - 1) <= width:
                break
            visible[column] = False
            widths[column] = 0
        widths[4] = min(state, max(60, width - side - 80 - 24))
        widths[1] = max(0, width - sum(widths) - 12 * (sum(visible) - 1))
        for cells in (self.header_cells, *(row.cells for row in self.rows.values())):
            for column, cell in enumerate(cells):
                cell.setVisible(visible[column])
                cell.setFixedWidth(widths[column])
        for row in self.rows.values():
            row.subtitle.setVisible(not visible[3])
            row.scope.setVisible(visible[3])
            row.detail_layout.setContentsMargins(12 if not visible[3] else 40, 12, 12, 16)
