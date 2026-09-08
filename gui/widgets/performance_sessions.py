"""用有界列表汇总各设备采集状态，切换查看不改变操作目标或启动任务。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon, TableWidget

from gui.features.base import FeatureSessionKey, FeatureSessionRegistry
from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import configure_fluent_control, font_qss
from gui.widgets.collapsible_tools import CollapsibleTools


@dataclass(frozen=True, slots=True)
class PerformanceSnapshot:
    """页面在 GUI 线程发布的显示快照，不读取设备、文件或进程。"""

    state: str = "idle"
    status: str = ""
    percent: int = 0
    elapsed: int = 0
    duration: int = 0
    detail: str = ""


class PerformanceSessions(QWidget):
    """展示已选设备及保留会话；最多三行可见，其余在列表内滚动。"""

    device_requested = Signal(str)

    def __init__(self, registry: FeatureSessionRegistry, parent: QWidget | None = None):
        super().__init__(parent)
        self.registry = registry
        self._selected: tuple[str, ...] = ()
        self._connected: tuple[str, ...] = ()
        self._current = ""
        self._enabled = False
        self._devices: tuple[str, ...] = ()
        self._labels: dict[str, str] = {}
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.table = TableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels([tr("设备"), tr("状态"), tr("采集进度")])
        self.table.setAccessibleName(tr("各设备采集状态"))
        self.table.setToolTip(tr("各设备独立采集，点击一行查看并操作该设备。"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setMinimumWidth(0)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(40)
        self.table.itemClicked.connect(self._choose_item)
        self.table.itemActivated.connect(self._choose_item)
        self.section = CollapsibleTools(
            "各设备采集状态", self.table, self, icon=FluentIcon.SPEED_HIGH,
            tooltip="各设备独立采集，点击一行查看并操作该设备。",
        )
        self.section.toggle_button.setChecked(True)
        layout.addWidget(self.section)
        registry.session_added.connect(self._session_added)
        registry.session_removed.connect(self.refresh)
        BaseStyles.fonts_changed.connect(self._apply_fonts)
        self._apply_fonts()
        self.hide()

    def set_device_labels(self, labels: dict[str, str]) -> None:
        """复用全局会话编号，列表排序和离线不改变已运行采集的显示归属。"""
        self._labels.update(labels)
        self.refresh()

    def set_context(
        self, selected: tuple[str, ...], connected: tuple[str, ...], current: str,
        *, enabled: bool,
    ) -> None:
        """只更新显示上下文，未打开的设备不会提前创建采集页面。"""
        self._selected, self._connected = selected, connected
        self._current, self._enabled = current, enabled
        self.refresh()

    def _session_added(self, key: FeatureSessionKey, page: QWidget) -> None:
        if key.feature != "performance":
            return
        signal = getattr(page, "session_state_changed", None)
        if signal is not None:
            signal.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _clock(seconds: int) -> str:
        hours, rest = divmod(max(0, seconds), 3600)
        minutes, seconds = divmod(rest, 60)
        return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"

    def refresh(self, *_args) -> None:
        """保留离线或取消勾选后的运行会话，避免后台任务从列表中消失。"""
        pages = {
            key.device_id: page for key in self.registry.keys()
            if key.feature == "performance" and (page := self.registry.get(key)) is not None
        }
        self._devices = tuple(dict.fromkeys((*self._selected, *pages)))
        self.setVisible(self._enabled and len(self._devices) > 1)
        blocker = QSignalBlocker(self.table)
        scroll = self.table.verticalScrollBar().value()
        self.table.setRowCount(len(self._devices))
        current_row = -1
        for row, device in enumerate(self._devices):
            page = pages.get(device)
            provider = getattr(page, "performance_snapshot", None)
            snapshot = provider() if callable(provider) else PerformanceSnapshot()
            if not isinstance(snapshot, PerformanceSnapshot):
                raise TypeError("performance_snapshot must return PerformanceSnapshot")
            status = snapshot.status or tr("Idle")
            if device not in self._connected:
                status = f"{status} · {tr('离线')}"
            elif device not in self._selected:
                status = f"{status} · {tr('未选为操作目标')}"
            timing = f"{self._clock(snapshot.elapsed)} / {self._clock(snapshot.duration)}"
            progress = (
                f"{snapshot.percent}% · {self._clock(snapshot.elapsed)}"
                if snapshot.duration else "—"
            )
            label = self._labels.setdefault(
                device, tr("设备 {number}").format(number=len(self._labels) + 1),
            )
            full = f"{label}\n{status}\n{snapshot.percent}% · {timing}\n{snapshot.detail}".strip()
            for column, text in enumerate((label, status, progress)):
                item = self.table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, column, item)
                item.setText(text)
                # Fluent 委托默认固定字号；显式模型字体才能跟随项目缩放。
                item.setFont(self.table.font())
                item.setData(Qt.ItemDataRole.UserRole, device)
                item.setToolTip(full)
                item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, full)
            if device == self._current:
                current_row = row
        if current_row >= 0:
            self.table.selectRow(current_row)
        else:
            self.table.clearSelection()
        self.table.verticalScrollBar().setValue(scroll)
        del blocker
        self._size_table()

    def _choose_item(self, item: QTableWidgetItem) -> None:
        device = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if device and device != self._current:
            self.device_requested.emit(device)

    def _apply_fonts(self, *_args) -> None:
        configure_fluent_control(self.table)
        self.table.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        self.table.horizontalHeader().setStyleSheet(
            "QHeaderView::section { " + font_qss(self.table.font()) + " }"
        )
        for column in range(self.table.columnCount()):
            item = self.table.horizontalHeaderItem(column)
            if item is not None:
                item.setFont(self.table.font())
        for row in range(self.table.rowCount()):
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item is not None:
                    item.setFont(self.table.font())
        self._size_table()

    def _size_table(self) -> None:
        row_height = max(32, self.table.fontMetrics().height() + 12)
        self.table.verticalHeader().setDefaultSectionSize(row_height)
        self.table.setFixedHeight(
            self.table.horizontalHeader().sizeHint().height()
            + row_height * min(3, max(1, self.table.rowCount())) + 4
        )
