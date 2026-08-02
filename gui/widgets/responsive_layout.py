"""提供按容器宽度重排现有控件的轻量布局辅助函数。"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import QGridLayout, QWidget


def responsive_column_count(
    width: int,
    *,
    compact_width: int = 420,
    wide_width: int = 560,
    compact_columns: int = 1,
    medium_columns: int = 2,
    wide_columns: int = 4,
) -> int:
    """根据逻辑像素宽度返回当前布局列数。"""

    width = max(0, int(width))
    if width < compact_width:
        return max(1, int(compact_columns))
    if width < wide_width:
        return max(1, int(medium_columns))
    return max(1, int(wide_columns))


def reflow_widgets(
    layout: QGridLayout,
    widgets: Iterable[QWidget],
    columns: int,
    *,
    column_stretch: int = 1,
    widget_stretches: Iterable[int] | None = None,
) -> None:
    """在不重建控件和信号连接的前提下重新排列网格控件。"""

    items = tuple(widgets)
    stretches = (
        tuple(max(0, int(value)) for value in widget_stretches)
        if widget_stretches is not None
        else tuple(max(0, int(column_stretch)) for _item in items)
    )
    if len(stretches) != len(items):
        raise ValueError("widget_stretches must match widgets")
    columns = max(1, int(columns))
    previous_columns = int(layout.property("responsiveColumnCount") or 0)
    if previous_columns == columns and layout.count() == len(items):
        return

    while layout.count():
        layout.takeAt(0)
    for index, widget in enumerate(items):
        row, column = divmod(index, columns)
        layout.addWidget(widget, row, column)
    for column in range(max(previous_columns, columns)):
        if column >= columns:
            stretch = 0
        else:
            stretch = max(
                (stretches[index] for index in range(column, len(items), columns)),
                default=0,
            )
        layout.setColumnStretch(column, stretch)
    layout.setProperty("responsiveColumnCount", columns)
