"""主题化表格组件。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)
from qfluentwidgets import SmoothScrollDelegate

from gui.styles import BaseStyles, FontRole
from gui.widgets.fluent._base import apply_font_role_to, repolish

__all__ = ["FluentTable", "TableRow"]


@dataclass(frozen=True)
class TableRow:
    """FluentTable 的一行数据：单元格文本与可选业务数据。"""

    cells: tuple[str, ...]
    data: object | None = None


class FluentTable(QTableWidget):
    """主题化只读表格，提供行插入与选中信号。

    契约：
    * ``add_row`` / ``insert_row`` 返回新行下标，并把文本固化为不可变
      :class:`TableRow`；
    * 选择变化（含 ``setCurrentCell``）触发 ``rowSelected(int)``；
    * ``selected_data()`` 返回当前行业务数据，无选中返回 ``None``。
    """

    rowSelected = Signal(int)

    def __init__(self, *, columns: Sequence[str] = (), parent: QWidget | None = None) -> None:
        super().__init__(0, 0, parent)
        self._rows: list[TableRow] = []
        self._font_role = FontRole.UI
        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.setProperty("fontRole", FontRole.UI.value)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        vertical_header = self.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)
        horizontal_header = self.horizontalHeader()
        if horizontal_header is not None:
            horizontal_header.setStretchLastSection(True)
        if columns:
            self.set_columns(columns)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        # 原生滚动条已随 SCROLLBAR_STYLE 移除，改为 Fluent 平滑滚动条。
        SmoothScrollDelegate(self)
        self._sync_theme_state()

    # ── 列与行 ──────────────────────────────────────────────────────────

    def set_columns(self, columns: Sequence[str]) -> None:
        """重置列标题并清空全部数据行。"""

        self.setRowCount(0)
        self._rows.clear()
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels([str(column) for column in columns])

    def add_row(self, cells: Sequence[str], *, data: object | None = None) -> int:
        """在末尾追加一行并返回行下标。"""

        return self.insert_row(self.rowCount(), cells, data=data)

    def insert_row(
        self,
        index: int,
        cells: Sequence[str],
        *,
        data: object | None = None,
    ) -> int:
        """在指定位置插入一行并返回行下标。"""

        row = TableRow(tuple(str(cell) for cell in cells), data)
        self.insertRow(index)
        for column, cell in enumerate(row.cells):
            self.setItem(index, column, QTableWidgetItem(cell))
        self._rows.insert(index, row)
        return index

    def row_at(self, index: int) -> TableRow:
        """返回指定下标对应的不可变行数据。"""

        return self._rows[index]

    # ── 选中 ────────────────────────────────────────────────────────────

    def selected_index(self) -> int:
        """返回当前选中行下标，无选中返回 -1。"""

        return self.currentRow()

    def selected_data(self) -> object | None:
        """返回当前行业务数据，无选中返回 ``None``。"""

        index = self.currentRow()
        if 0 <= index < len(self._rows):
            return self._rows[index].data
        return None

    def selected_row(self) -> TableRow | None:
        """返回当前行数据，无选中返回 ``None``。"""

        index = self.currentRow()
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    # ── 字体与主题 ──────────────────────────────────────────────────────

    def apply_font_role(self, role: FontRole | str) -> None:
        """切换表格字体角色并同步 ``fontRole`` property。"""

        self._font_role = apply_font_role_to(self, role)

    def _on_selection_changed(self) -> None:
        self.rowSelected.emit(self.currentRow())

    def _sync_theme_state(self) -> None:
        """按当前主题重建表格样式。"""

        self.setStyleSheet(self._table_style())
        repolish(self)

    def _table_style(self) -> str:
        radius = BaseStyles.RADIUS_MD
        return (
            f"QTableWidget {{"
            f" background-color: {BaseStyles.color('INPUT_BG')};"
            f" color: {BaseStyles.color('TEXT_PRIMARY')};"
            f" border: 1px solid {BaseStyles.color('BORDER_COLOR')};"
            f" border-radius: {radius}px; outline: none; }}"
            f"QTableWidget::item {{ padding: 3px 6px; }}"
            f"QTableWidget::item:selected {{"
            f" background-color: {BaseStyles.color('SELECTION_BG')};"
            f" color: {BaseStyles.color('SELECTION_TEXT')}; }}"
            f"QHeaderView::section {{"
            f" background-color: {BaseStyles.color('BUTTON_BG')};"
            f" color: {BaseStyles.color('TEXT_PRIMARY')};"
            f" border: none;"
            f" border-right: 1px solid {BaseStyles.color('BORDER_COLOR')};"
            f" padding: 4px 6px; }}"
        )
