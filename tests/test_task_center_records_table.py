"""任务记录保留表格视觉，并使用真实行控件与搜索、类型筛选。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QAccessible, QColor, QFontMetrics, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication
from shiboken6 import isValid

from core.settings_manager import DEFAULTS, AppSettings
from gui.pages.tasks_page import TaskCenterPage
from gui.styles import BaseStyles, FontRole
from gui.widgets.task_table import TaskRowData, TaskTable
from services.tasks.action_results import ActionResult, ActionSpec
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until

pytestmark = pytest.mark.ui


def test_records_expose_real_accessible_controls_without_item_view_interfaces(qt_application):
    table = TaskTable(external_details=True)
    record = TaskRowData(
        "one", "执行 Shell", "Shell", "测试手机", "运行中", "accent", "10:10", "本次",
        cancellable=True,
    )
    table.set_rows((record,))
    table.resize(900, 320)
    table.show()
    qt_application.processEvents()
    try:
        assert not table.findChildren(QAbstractItemView)
        row = table.rows[record.key]
        assert table.record_keys == (record.key,)
        for control in (row.title, row.cancel):
            interface = QAccessible.queryAccessibleInterface(control)
            assert interface is not None and interface.isValid()
            assert interface.role() == QAccessible.Role.Button
            assert interface.text(QAccessible.Text.Name) == control.accessibleName()
        assert row.cells == (row.task_cell, row.kind, row.target, row.status_cell, row.time)
        assert row.title.accessibleName() == record.title
        assert row.status.accessibleName() == record.status_text
        requested = QSignalSpy(table.detail_requested)
        row.setFocus()
        QTest.keyClick(row, Qt.Key.Key_Return)
        assert table.selected_key == record.key
        assert requested.count() == 1 and requested.at(0) == [record.key]
    finally:
        table.close()


def test_removed_row_releases_controls_but_returns_shared_reader(qt_application):
    from PySide6.QtWidgets import QWidget

    table = TaskTable()
    record = TaskRowData("one", "任务", "Shell", "本机", "成功", "success", "", "本次")
    table.set_rows((record, replace(record, key="other")))
    reader = QWidget()
    reader.setMinimumHeight(120)
    table.set_expanded(record.key, reader)
    row = table.rows[record.key]
    controls = (row, row.title, row.cancel)
    destroyed = [QSignalSpy(control.destroyed) for control in controls]
    reader_destroyed = QSignalSpy(reader.destroyed)
    try:
        table.set_rows((replace(record, key="other"),))
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_application.processEvents()
        assert table.record_keys == ("other",)
        assert all(spy.count() == 1 for spy in destroyed)
        assert all(not isValid(control) for control in controls)
        assert reader_destroyed.count() == 0
        assert reader.parentWidget() is table
        assert isValid(reader) and reader.isHidden()
        assert table.expanded_key == ""
    finally:
        table.close()


def test_alternation_selection_and_hover_have_visible_row_feedback(qt_application):
    table = TaskTable(external_details=True)
    record = TaskRowData("one", "任务", "Shell", "本机", "成功", "success", "", "本次")
    table.set_rows((record, replace(record, key="other"), replace(record, key="third")))
    table.resize(1100, 320)
    table.show()
    table.activateWindow()
    try:
        assert QTest.qWaitForWindowExposed(table)
        window = table.windowHandle()
        for theme in ("Light", "Dark"):
            BaseStyles.switch_theme(theme)
            assert BaseStyles.resolved_theme() == theme
            # 表格透出宿主底色；独立测试窗口显式提供主题材质的背景。
            palette = table.palette()
            for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base):
                palette.setColor(role, QColor(BaseStyles.color("WINDOW_BG")))
            for surface in (table, table.view, table.view.viewport(), table.content):
                surface.setPalette(palette)
            table.setAutoFillBackground(True)
            table.select_row("third")
            viewport = table.view.viewport()
            # 由窗口按坐标命中子控件；移动系统指针后，Cocoa 可能尚未投递进入事件。
            QTest.mouseMove(window, viewport.mapTo(table, QPoint(20, viewport.height() - 12)))
            header_point = table.header_clip.mapTo(table, QPoint(24, 12))
            QTest.mouseMove(window, header_point)
            wait_until(qt_application, table.header_clip.underMouse)
            first, second = table.rows["one"], table.rows["other"]
            assert not second.underMouse()

            def background(row):
                image = table.grab().toImage()
                scale = image.devicePixelRatio()
                point = row.mapTo(table, QPoint(row.width() - 6, 20))
                return image.pixelColor(round(point.x() * scale), round(point.y() * scale))

            plain = background(second)
            assert background(first) != plain
            table.select_row("other")
            qt_application.processEvents()
            selected = background(second)
            assert selected != plain
            QTest.mouseMove(window, second.header.mapTo(table, QPoint(12, 20)))
            wait_until(qt_application, second.underMouse)
            assert background(second) != selected
            QTest.mouseMove(window, header_point)
            wait_until(qt_application, table.header_clip.underMouse)
            assert not second.underMouse()
            assert background(second) == selected
    finally:
        table.close()


def _rendered_header_text_extent(qt_application, item):
    original = item.text()
    alignment = item.alignment()
    try:
        item.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        item.setText("Header Mg")
        qt_application.processEvents()
        labelled = item.grab().toImage()
        item.setText("")
        qt_application.processEvents()
        blank = item.grab().toImage()
        assert labelled.size() == blank.size()
        changed = [
            (x, y)
            for y in range(labelled.height())
            for x in range(labelled.width())
            if labelled.pixelColor(x, y) != blank.pixelColor(x, y)
        ]
        assert changed
        scale = labelled.devicePixelRatio()
        return (
            round((max(x for x, _y in changed) - min(x for x, _y in changed) + 1) / scale),
            round((max(y for _x, y in changed) - min(y for _x, y in changed) + 1) / scale),
        )
    finally:
        item.setText(original)
        item.setAlignment(alignment)
        qt_application.processEvents()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("family", ["Arial", "Courier New"])
def test_rendered_header_font_and_height_follow_live_font_round_trip(
    qt_application, monkeypatch, theme, family,
):
    values = dict(DEFAULTS, ui_font_size=12, font_family=family)
    monkeypatch.setattr(
        AppSettings, "instance", classmethod(lambda _cls: SimpleNamespace(get=values.get)),
    )
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    table = TaskTable(external_details=True)
    table.set_rows((TaskRowData(
        "one", "任务", "Shell", "测试手机", "运行中", "accent", "10:10", "本次",
    ),))
    table.resize(1100, 320)
    table.show()
    header = table.header
    item = table.header_cells[0]
    row = table.rows["one"]
    observed = []
    try:
        for size in (12, 22, 12):
            values["ui_font_size"] = size
            BaseStyles.reload_from_settings()
            wait_for_stable_geometry(qt_application, (table, table.view, header))
            # 文字临时左对齐测量，隔离列宽变化导致的居中抗锯齿相位差。
            extent = _rendered_header_text_extent(qt_application, item)
            metrics = QFontMetrics(BaseStyles.font_for_role(FontRole.UI_SMALL))
            expected = metrics.tightBoundingRect("Header Mg")
            assert abs(extent[0] - expected.width()) <= 2
            assert abs(extent[1] - expected.height()) <= 2
            assert header.height() >= metrics.height() + 12
            assert table.rows["one"] is row
            observed.append((extent, header.height()))
        assert observed[1][0][1] > observed[0][0][1]
        assert observed[1][1] > observed[0][1]
        assert observed[2] == observed[0]
    finally:
        table.close()


def test_records_keep_headers_selection_and_both_axis_scrolling(qt_application):
    table = TaskTable(external_details=True)
    record = TaskRowData(
        "one", "执行 Shell", "Shell", "测试手机", "失败", "danger", "10:10", "本次"
    )
    table.set_rows((record,))
    table.resize(400, 320)
    table.show()
    try:
        view = table.view
        assert [cell.text() for cell in table.header_cells] == [
            "任务", "类型", "目标", "状态", "时间",
        ]
        assert table.record_keys == (record.key,)
        qt_application.processEvents()
        assert view.horizontalScrollBar().maximum() > 0
        view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
        qt_application.processEvents()
        for header, cell in zip(table.header_cells, table.rows[record.key].cells):
            assert cell.isVisibleTo(table)
            assert cell.mapTo(table, QPoint()).x() == header.mapTo(table, QPoint()).x()
            assert cell.width() == header.width()
        requested = QSignalSpy(table.detail_requested)
        view.setFocus()
        QTest.keyClick(view, Qt.Key.Key_Down)
        QTest.keyClick(table.rows[record.key], Qt.Key.Key_Return)
        assert table.selected_key == record.key
        assert requested.count() == 1 and requested.at(0) == [record.key]
        header_top = table.header_clip.mapTo(table, QPoint())
        table.set_rows(tuple(replace(record, key=f"record:{i}") for i in range(12)))
        qt_application.processEvents()
        assert view.verticalScrollBar().maximum() > 0
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        qt_application.processEvents()
        assert table.header_clip.mapTo(table, QPoint()) == header_top
        QTest.keyClick(view, Qt.Key.Key_End)
        assert table.selected_key == "record:11"
        QTest.keyClick(table.rows["record:11"], Qt.Key.Key_Up)
        assert table.selected_key == "record:10"
        QTest.keyClick(table.rows["record:10"], Qt.Key.Key_Home)
        assert table.selected_key == "record:0"
    finally:
        table.close()


def test_status_is_row_information_and_navigation_survives_type_search(qt_application):
    page = TaskCenterPage(external_details=True)
    try:
        for key, state in (("active", "running"), ("failure", "failed"), ("done", "succeeded")):
            page.present_action_result(
                ActionResult(
                    key,
                    ActionSpec("shell_command", "system.shell", key, "text"),
                    (),
                    100,
                    state=state,
                )
            )
        assert {
            widget.accessibleName() for widget in page.filters.findChildren(type(page.kind_combo))
        } == {"任务类型"}
        assert not page.findChildren(type(page.clear_filters_button), "taskStateFilter")
        assert not hasattr(page, "state_combo")
        assert not hasattr(page, "quick_filter_buttons")
        assert {row.data.state for row in page.table.rows.values()} == {"运行中", "失败", "成功"}
        page.search_edit.setText("done")
        assert set(page.table.rows) == {"action:done"}
        assert page.navigation_snapshot().active_count == 1
        assert page.navigation_snapshot().unread_count == 1
        page._clear_filters()
        assert len(page.table.rows) == 3
    finally:
        page.shutdown()
        page.close()


@pytest.mark.parametrize("font_size", [12, 22])
def test_session_title_stays_identifiable_without_unbounded_column_growth(
    qt_application, monkeypatch, font_size,
):
    values = dict(DEFAULTS, ui_font_size=font_size, font_family="Arial")
    monkeypatch.setattr(
        AppSettings, "instance", classmethod(lambda _cls: SimpleNamespace(get=values.get)),
    )
    BaseStyles.reload_from_settings()
    table = TaskTable(external_details=True)
    record = TaskRowData(
        "session", "远程控制", "系统", "设备 1 · 测试手机",
        "运行中", "accent", "进行中", "持续会话",
        cancellable=True, unread=True,
    )
    table.set_rows((record,))
    table.resize(336, 320)
    table.show()
    try:
        wait_for_stable_geometry(qt_application, (table, table.view))
        row = table.rows[record.key]
        assert row.title.text().startswith("远程")
        assert row.title.toolTip() == row.title.accessibleName() == record.title
        width = row.task_cell.width()
        assert width >= 200
        table.set_rows((replace(record, title=record.title * 1000),))
        wait_for_stable_geometry(qt_application, (table, table.view))
        assert table.rows[record.key] is row
        assert row.task_cell.width() == width
        assert row.title.text().startswith("远程")
        assert table.view.horizontalScrollBar().maximum() > 0
    finally:
        table.close()


def test_reorder_keeps_cell_widgets_and_pressed_stop_revision(qt_application):
    table = TaskTable(external_details=True)
    record = TaskRowData(
        "owner",
        "持续会话",
        "性能",
        "测试手机",
        "运行中",
        "accent",
        "",
        "本次",
        cancellable=True,
        stop_action=True,
        stop_revision="old",
    )
    other = replace(record, key="other", title="另一任务")
    table.set_rows((record, other))
    table.resize(1100, 320)
    table.show()
    qt_application.processEvents()
    row = table.rows["owner"]
    button = row.cancel
    stopped = QSignalSpy(table.stop_requested)
    try:
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        table.set_rows((other, replace(record, stop_revision="new")))
        qt_application.processEvents()
        assert table.rows["owner"] is row
        assert row.cancel is button
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        assert stopped.count() <= 1
        if stopped.count():
            assert stopped.at(0) == ["owner", "old"]
        button.click()
        assert stopped.at(stopped.count() - 1) == ["owner", "new"]
    finally:
        table.close()


def test_real_tab_reaches_detail_title_and_stop_after_reorder(qt_application):
    table = TaskTable(external_details=True)
    record = TaskRowData(
        "session", "远程控制", "系统", "测试手机", "运行中", "accent", "", "持续会话",
        cancellable=True, stop_action=True, stop_revision="original",
    )
    other = replace(record, key="other", title="另一任务")
    table.set_rows((record, other))
    table.resize(1100, 320)
    table.show()
    table.activateWindow()
    row = table.rows[record.key]
    controls = (row.title, row.cancel)
    details = QSignalSpy(table.detail_requested)
    stopped = QSignalSpy(table.stop_requested)
    try:
        wait_until(qt_application, table.isActiveWindow)
        row.setFocus(Qt.FocusReason.TabFocusReason)
        wait_until(qt_application, lambda: QApplication.focusWidget() is row)
        QTest.keyClick(row, Qt.Key.Key_Tab)
        wait_until(qt_application, lambda: QApplication.focusWidget() is row.title)
        QTest.keyClick(row.title, Qt.Key.Key_Return)
        assert details.count() == 1 and details.at(0) == [record.key]
        QTest.keyClick(row.title, Qt.Key.Key_Space)
        assert details.count() == 2 and details.at(1) == [record.key]
        QTest.keyClick(row.title, Qt.Key.Key_Tab)
        wait_until(qt_application, lambda: QApplication.focusWidget() is row.cancel)
        QTest.keyPress(row.cancel, Qt.Key.Key_Space)
        table.set_rows((other, replace(record, stop_revision="refreshed")))
        qt_application.processEvents()
        assert table.rows[record.key] is row
        assert (row.title, row.cancel) == controls
        assert QApplication.focusWidget() is row.cancel
        QTest.keyRelease(row.cancel, Qt.Key.Key_Space)
        assert stopped.count() == 1 and stopped.at(0) == [record.key, "original"]
        QTest.keyClick(row.cancel, Qt.Key.Key_Space)
        assert stopped.count() == 2 and stopped.at(1) == [record.key, "refreshed"]
        assert details.count() == 2
    finally:
        table.close()


@pytest.mark.parametrize("cancellable,cancelling", [(False, False), (True, True)])
def test_real_tab_skips_hidden_or_disabled_stop(qt_application, cancellable, cancelling):
    table = TaskTable(external_details=True)
    record = TaskRowData(
        "session", "远程控制", "系统", "测试手机", "运行中", "accent", "", "持续会话",
        cancellable=cancellable, cancelling=cancelling,
    )
    other = replace(record, key="other", title="另一任务", cancellable=True, cancelling=False)
    table.set_rows((record, other))
    table.resize(1100, 320)
    table.show()
    table.activateWindow()
    row = table.rows[record.key]
    try:
        wait_until(qt_application, table.isActiveWindow)
        row.setFocus(Qt.FocusReason.TabFocusReason)
        wait_until(qt_application, lambda: QApplication.focusWidget() is row)
        for previous, expected in ((row, row.title), (row.title, table.rows[other.key].title)):
            QTest.keyClick(previous, Qt.Key.Key_Tab)
            wait_until(
                qt_application, lambda expected=expected: QApplication.focusWidget() is expected,
            )
        assert not row.cancel.isVisibleTo(table) or not row.cancel.isEnabled()
    finally:
        table.close()


def test_clicking_non_action_cell_requests_only_its_task(qt_application):
    table = TaskTable(external_details=True)
    record = TaskRowData("one", "执行 Shell", "Shell", "测试手机", "运行中",
                         "accent", "", "本次", cancellable=True)
    table.set_rows((record, replace(record, key="other")))
    table.resize(1050, 300)
    table.show()
    qt_application.processEvents()
    try:
        requests = QSignalSpy(table.detail_requested)
        cancels = QSignalSpy(table.cancel_requested)
        row = table.rows["other"]
        point = row.target.mapTo(table, row.target.rect().center())
        QTest.mouseClick(table.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
        assert requests.count() == 1 and requests.at(0) == ["other"]
        assert table.selected_key == "other" and cancels.count() == 0
        point = row.cancel.mapTo(table, row.cancel.rect().center())
        QTest.mouseClick(table.windowHandle(), Qt.MouseButton.LeftButton, pos=point)
        assert requests.count() == 1
        assert cancels.count() == 1 and cancels.at(0) == ["other"]
    finally:
        table.close()
