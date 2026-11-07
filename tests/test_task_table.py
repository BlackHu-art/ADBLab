"""任务表共享列宽、行内详情和响应式布局的可观察契约。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget

from core.settings_manager import DEFAULTS, AppSettings
from gui.styles import BaseStyles
from gui.widgets.task_table import TaskRowData, TaskTable


def _records():
    return (
        TaskRowData(
            "first", "批量安装", "应用", "测试手机", "部分成功", "warning", "11-07 10:10", "本次"
        ),
        TaskRowData(
            "second", "性能采集", "性能", "平板设备", "成功", "success", "11-06 18:20", "已归档"
        ),
    )


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("width", [300, 540, 1000])
def test_headers_and_record_columns_align_and_fit(qt_application, width, theme):
    BaseStyles.switch_theme(theme)
    table = TaskTable()
    table.set_rows(_records())
    table.resize(width, 500)
    table.show()
    qt_application.processEvents()
    try:
        for index, cell in enumerate(table.header_cells):
            if cell.isHidden():
                continue
            header_x = cell.mapTo(table, QPoint()).x()
            for row in table.rows.values():
                peer = row.cells[index]
                assert not peer.isHidden()
                assert peer.mapTo(table, QPoint()).x() == header_x
                assert peer.width() == cell.width()
        for row in table.rows.values():
            assert row.width() <= width
            title_y = row.title.mapTo(table, row.title.rect().center()).y()
            status_y = row.status.mapTo(table, row.status.rect().center()).y()
            assert abs(title_y - status_y) <= 2
            for cell in row.cells:
                if not cell.isHidden():
                    assert cell.geometry().right() < row.width()
    finally:
        table.close()


def test_refresh_reuses_rows_and_inline_detail_stays_below_its_task(qt_application):
    table = TaskTable()
    table.set_rows(_records())
    table.resize(900, 500)
    detail = QWidget()
    detail.setMinimumHeight(160)
    table.set_expanded("first", detail)
    table.show()
    qt_application.processEvents()
    first = table.rows["first"]
    try:
        table.set_rows(_records())
        qt_application.processEvents()
        assert table.rows["first"] is first
        assert detail.isVisibleTo(first)
        assert detail.mapTo(first, QPoint()).y() >= first.header.height()
        first.toggle.click()
        assert not detail.isVisibleTo(table)
        assert table.expanded_key == ""
        assert first.toggle.accessibleName() == "展开任务详情"
    finally:
        table.close()


def test_font_round_trip_reelides_capped_target_without_replacing_row(
    qt_application, monkeypatch,
):
    values = dict(DEFAULTS, ui_font_size=12, font_family="Arial")
    monkeypatch.setattr(
        AppSettings, "instance", classmethod(lambda _cls: SimpleNamespace(get=values.get)),
    )
    BaseStyles.reload_from_settings()
    record = replace(
        _records()[0],
        title="批量安装并验证设备上的应用程序" * 5,
        target="长名称的测试设备与工作平板" * 8,
    )
    table = TaskTable()
    table.set_rows((record,))
    table.resize(1500, 500)
    table.show()
    row = table.rows[record.key]
    try:
        for size in (12, 22, 12):
            values["ui_font_size"] = size
            BaseStyles.reload_from_settings()
            qt_application.processEvents()
            assert table.rows[record.key] is row
            assert row.target.width() == 180
            for widget, full_text, padding in (
                (row.title, record.title, 16),
                (row.target, record.target, 0),
            ):
                expected = widget.fontMetrics().elidedText(
                    full_text, Qt.TextElideMode.ElideRight, max(0, widget.width() - padding),
                )
                assert widget.text() == expected
                assert widget.toolTip() == widget.accessibleName() == full_text
    finally:
        table.close()


@pytest.mark.parametrize("column", ["title", "target"])
def test_font_width_change_reelides_text_without_a_resize(qt_application, column):
    record = replace(_records()[0], title="应用安装与验证" * 10, target="测试设备与平板" * 15)
    table = TaskTable()
    table.set_rows((record,))
    table.resize(1500, 500)
    table.show()
    qt_application.processEvents()
    control = getattr(table.rows[record.key], column)
    before = control.size()
    try:
        font = QFont(control.font())
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.0)
        control.setFont(font)
        qt_application.processEvents()
        assert control.size() == before
        expected = control.fontMetrics().elidedText(
            getattr(record, column), Qt.TextElideMode.ElideRight,
            max(0, control.width() - (16 if column == "title" else 0)),
        )
        assert control.text() == expected
    finally:
        table.close()
