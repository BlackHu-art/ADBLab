"""验证结果列表的筛选、附件边界、参数复用和有界布局。"""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QDateTime, QEvent, Qt, QThread
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QScrollArea, QStyleOptionViewItem
from shiboken6 import isValid

from core.settings_manager import AppSettings
from gui.run_library import RunLibraryController
from gui.styles import BaseStyles
from gui.widgets.run_results import RunResultsWidget
from services.run_library import RunArtifact, RunLibrary, RunRecord
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_non_overlapping,
    assert_scroll_target_reachable,
    wait_for_stable_geometry,
    wait_until,
)


def _record(identifier="one", **changes):
    start = QDateTime.fromString("2026-09-06T12:00:00", Qt.DateFormat.ISODate).toSecsSinceEpoch()
    record = RunRecord(
        identifier,
        "monkey",
        "com.example.alpha",
        start,
        start + 60,
        "succeeded",
        {"seed": 41, "events": 100},
        message="测试结束",
    )
    return replace(record, **changes)


def _set_font_size(monkeypatch, size):
    settings = {"font_family": "Microsoft YaHei", "ui_font_size": size, "log_font_size": 12}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()


@pytest.fixture
def make_panel(qt_application, tmp_path):
    owned = []

    def create(records=()):
        source = RunLibrary(tmp_path / f"runs-{len(owned)}.json")
        for record in records:
            source.record_run(record)
        controller = RunLibraryController(source)
        panel = RunResultsWidget(controller)
        owned.append((panel, controller))
        wait_until(qt_application, lambda: len(controller.records) == len(records))
        return panel, controller

    yield create
    for panel, controller in owned:
        if isValid(panel):
            panel.close()
            panel.deleteLater()
            QCoreApplication.sendPostedEvents(panel, QEvent.Type.DeferredDelete)
        assert controller.shutdown()
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(controller, QEvent.Type.DeferredDelete)


def test_empty_results_then_live_update_has_one_selected_record(make_panel, qt_application):
    panel, controller = make_panel()
    assert panel.table.rowCount() == 0
    assert "尚无测试结果" in panel.empty_label.text()
    assert panel.details.isHidden()
    assert not panel.open_button.isEnabled()
    record = _record()
    controller.record_run(record)
    wait_until(qt_application, lambda: panel.table.rowCount() == 1)
    assert panel.selected_record == record
    assert not panel.table.isHidden()
    assert panel.empty_label.isHidden()
    assert panel.parameters_section.content.isHidden()
    assert not panel.open_button.isEnabled()
    assert not panel.folder_button.isEnabled()
    assert panel.reuse_button.isEnabled()


def test_search_kind_and_state_filters_compose_and_distinguish_no_matches(make_panel):
    records = (
        _record(),
        _record("two", package_name="com.example.beta", kind="performance", state="failed"),
        _record("three", package_name="com.example.beta", state="partial"),
        _record("four", state="cancelled"),
    )
    panel, _controller = make_panel(records)
    panel.search_edit.setText("COM.EXAMPLE.BETA")
    assert panel.table.rowCount() == 2
    panel.kind_combo.setCurrentIndex(2)
    assert panel.table.rowCount() == 1
    assert panel.selected_record == records[1]
    panel.state_combo.setCurrentIndex(1)
    assert panel.table.rowCount() == 0
    assert "没有匹配的结果" in panel.empty_label.text()
    assert panel.details.isHidden()
    panel.state_combo.setCurrentIndex(2)
    assert panel.table.rowCount() == 1
    panel.search_edit.setText("2026-09-06")
    assert panel.table.rowCount() == 1
    panel.kind_combo.setCurrentIndex(0)
    panel.state_combo.setCurrentIndex(0)
    assert panel.table.rowCount() == 4
    panel.search_edit.clear()
    assert panel.table.rowCount() == 4


def test_keyboard_selection_and_library_update_preserve_selected_run(make_panel, qt_application):
    panel, controller = make_panel(
        (_record(), _record("two", finished_at=_record().finished_at + 1))
    )
    panel.resize(800, 650)
    panel.show()
    panel.table.setFocus()
    QTest.keyClick(panel.table, Qt.Key.Key_Down)
    assert panel.selected_record.run_id == "one"
    controller.record_run(_record("new", finished_at=_record().finished_at + 2))
    wait_until(qt_application, lambda: panel.table.rowCount() == 3)
    assert panel.selected_record.run_id == "one"
    assert '"seed": 41' in panel.parameters_edit.toPlainText()


def test_summary_and_application_tooltip_describe_saved_device_version_and_duration(make_panel):
    record = _record(
        device_label="Pixel 测试机",
        app_version="2.4.1 (83)",
        finished_at=_record().started_at + 3661,
    )
    panel, _controller = make_panel((record,))
    for text in (panel.summary_edit.toPlainText(), panel.table.item(0, 2).toolTip()):
        assert "设备：Pixel 测试机" in text
        assert "应用版本：2.4.1 (83)" in text
        assert "耗时 01:01:01" in text
    panel, _controller = make_panel((_record(),))
    assert "设备：" not in panel.summary_edit.toPlainText()
    assert "应用版本：" not in panel.summary_edit.toPlainText()
    assert "耗时 00:01:00" in panel.summary_edit.toPlainText()


def test_load_only_emits_selected_snapshot_and_does_not_change_library(make_panel):
    record = _record(parameters={"seed": 78, "nested": {"events": 100}})
    panel, controller = make_panel((record,))
    requested = QSignalSpy(panel.reuse_requested)
    changed = QSignalSpy(controller.changed)
    panel.reuse_button.click()
    assert requested.count() == 1
    emitted = requested.at(0)[0]
    assert emitted == record
    assert changed.count() == 0
    emitted.parameters["nested"]["events"] = 1
    assert controller.records[0].parameters["nested"]["events"] == 100
    assert panel.selected_record.parameters["nested"]["events"] == 100


def test_artifact_open_uses_explicit_local_paths_and_gui_thread(
    make_panel,
    tmp_path,
    monkeypatch,
    qt_application,
):
    path = tmp_path / "report with spaces.html"
    path.write_text("report", encoding="utf-8")
    opened = []
    threads = []

    def capture(url):
        opened.append(url)
        threads.append(QThread.currentThread())
        return True

    monkeypatch.setattr("gui.run_library.QDesktopServices.openUrl", capture)
    record = _record(
        artifacts=(RunArtifact("性能报告", str(path)),),
        message="https://example.invalid/not-an-artifact",
    )
    panel, _controller = make_panel((record,))
    assert panel.artifact_combo.count() == 1
    panel.open_button.click()
    wait_until(qt_application, lambda: len(opened) == 1)
    assert opened[0].isLocalFile()
    assert Path(opened[0].toLocalFile()) == path
    panel.folder_button.click()
    wait_until(qt_application, lambda: len(opened) == 2)
    assert opened[1].isLocalFile()
    assert Path(opened[1].toLocalFile()) == tmp_path
    assert threads == [qt_application.thread(), qt_application.thread()]


def test_deleted_artifact_reports_error_and_keeps_parameter_reuse(
    make_panel,
    tmp_path,
    monkeypatch,
    qt_application,
):
    path = tmp_path / "removed.txt"
    path.write_text("original", encoding="utf-8")
    panel, controller = make_panel((_record(artifacts=(RunArtifact("日志", str(path)),)),))
    opened = []
    monkeypatch.setattr("gui.run_library.QDesktopServices.openUrl", lambda url: opened.append(url))
    errors = QSignalSpy(controller.error)
    path.unlink()
    panel.open_button.click()
    wait_until(qt_application, lambda: errors.count() == 1)
    assert "移动或删除" in errors.at(0)[0]
    assert opened == []
    assert panel.reuse_button.isEnabled()
    assert panel.selected_record.run_id == "one"


@pytest.mark.parametrize("font_size", [12, 22])
def test_narrow_layout_keeps_controls_and_expanded_parameters_reachable(
    make_panel,
    tmp_path,
    monkeypatch,
    qt_application,
    font_size,
):
    _set_font_size(monkeypatch, font_size)
    artifact = RunArtifact("长附件名称" * 20, str(tmp_path / "result.txt"))
    record = _record(
        package_name="com.example." + "long" * 70,
        parameters={"seed": 41, "notes": "long value " * 200},
        message="测试说明" * 500,
        artifacts=(artifact,),
    )
    panel, _controller = make_panel((record,))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(panel)
    scroll.resize(540, 500)
    scroll.show()
    panel.parameters_section.toggle_button.click()
    controls = (
        panel.search_edit,
        panel.kind_combo,
        panel.state_combo,
        panel.artifact_combo,
        panel.open_button,
        panel.folder_button,
        panel.reuse_button,
    )
    wait_for_stable_geometry(qt_application, (scroll, panel, *controls))
    assert scroll.width() == 540
    assert scroll.horizontalScrollBar().maximum() == 0
    assert panel.table.horizontalScrollBar().maximum() == 0
    assert_non_overlapping(controls, panel)
    for control in controls:
        assert_contained(control, panel)
        assert control.height() >= control.fontMetrics().height()
    assert panel.parameters_edit.isVisibleTo(panel)
    assert panel.parameters_edit.maximumHeight() < 250
    assert_scroll_target_reachable(scroll, panel.reuse_button)
    scroll.close()


def test_runtime_font_change_updates_visible_table_cells_and_controls(make_panel, monkeypatch):
    _set_font_size(monkeypatch, 12)
    panel, _controller = make_panel((_record(),))
    selected = panel.selected_record
    _set_font_size(monkeypatch, 22)
    option = QStyleOptionViewItem()
    index = panel.table.model().index(0, 2)
    panel.table.itemDelegate().initStyleOption(option, index)
    assert option.font.pointSize() == 22
    assert panel.table.horizontalHeaderItem(2).font().pointSize() == 22
    assert panel.table.horizontalHeader().font().pointSize() == 22
    for control in (
        panel.search_edit,
        panel.kind_combo,
        panel.state_combo,
        panel.open_button,
        panel.reuse_button,
        panel.summary_edit,
        panel.parameters_edit,
    ):
        assert control.font().pointSize() == 22
    assert panel.selected_record == selected
    assert panel.parameters_section.content.isHidden()


def test_many_records_do_not_increase_table_height_or_rebuild_controls(make_panel, qt_application):
    record = _record()
    panel, controller = make_panel((record,))
    panel.resize(900, 650)
    panel.show()
    height = panel.table.height()
    original_controls = (
        panel.search_edit,
        panel.kind_combo,
        panel.artifact_combo,
        panel.reuse_button,
    )
    for index in range(1, 200):
        controller.record_run(_record(str(index), finished_at=record.finished_at + index))
    wait_until(qt_application, lambda: panel.table.rowCount() == 200)
    assert panel.table.height() == height
    assert panel.table.verticalScrollBar().maximum() > 0
    panel.search_edit.setFocus()
    panel.search_edit.setText("alpha")
    for width in (540, 1100):
        panel.resize(width, 650)
        wait_for_stable_geometry(qt_application, (panel, panel.filters, panel.action_row))
        assert panel.search_edit.hasFocus()
        assert panel.search_edit.text() == "alpha"
    assert original_controls == (
        panel.search_edit,
        panel.kind_combo,
        panel.artifact_combo,
        panel.reuse_button,
    )


def test_destroyed_panel_does_not_own_library_or_receive_late_refresh(make_panel, qt_application):
    panel, controller = make_panel((_record(),))
    destroyed = QSignalSpy(panel.destroyed)
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(panel, QEvent.Type.DeferredDelete)
    assert destroyed.count() == 1
    assert not isValid(panel)
    controller.record_run(_record("later"))
    wait_until(qt_application, lambda: len(controller.records) == 2)
    assert isValid(controller)
