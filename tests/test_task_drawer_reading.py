"""抽屉完整阅读、Fluent 滚条与设置热更新的普通 QWidget 回归。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtGui import QColor, QFontDatabase, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import SmoothScrollArea

from core.settings_manager import AppSettings
from gui.i18n import install_translators, tr
from gui.pages.tasks_page import TaskCenterPage
from gui.run_library import RunLibraryController
from gui.styles import BaseStyles, FontRole
from gui.task_feedback import TaskFeedbackCoordinator
from gui.widgets.action_result_view import ActionResultView
from gui.widgets.run_results import RunResultsWidget
from gui.widgets.task_detail_drawer import TaskDetailDrawer
from gui.widgets.task_table import TaskRowData
from services.run_library import RunArtifact, RunLibrary, RunRecord
from services.tasks.action_results import ActionItem, ActionResult, ActionSpec
from tests.ui_geometry_helpers import (
    assert_scroll_target_reachable,
    wait_for_stable_geometry,
    wait_until,
)

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("stop", [False, True])
def test_english_active_action_keeps_full_caption_and_original_identity(
    qt_application, monkeypatch, stop,
):
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: {
        "font_family": "", "ui_font_size": 22, "log_font_size": 11,
    }))
    BaseStyles.reload_from_settings()
    translators = install_translators(qt_application, "en_US")
    host = QWidget()
    panel = None
    try:
        host.resize(280, 640)
        panel = TaskDetailDrawer(host)
        row = TaskRowData("action:original", "合成任务", "合成类型", "合成目标", "运行中",
                          "accent", "刚刚", "本次", cancellable=True)
        row = replace(row, stop_action=stop, stop_revision="old")
        panel.present(row)
        host.show()
        panel.open_drawer(animated=False)
        action = panel.cancel_button
        caption = "Stop session" if stop else "Cancel task"
        for width in (280, 390, 280):
            host.resize(width, 640)
            wait_for_stable_geometry(qt_application, (panel, action))
            assert action.sizeHint().width() <= action.width()
            assert action.text() == action.accessibleName() == caption
            assert not action.icon().isNull()
            assert action.isVisibleTo(panel)
            assert action.toolTip() == action.accessibleDescription() == caption
        requested = QSignalSpy(panel.stop_requested if stop else panel.cancel_requested)
        QTest.mousePress(action, Qt.MouseButton.LeftButton)
        panel.present(replace(row, key="action:newer", stop_revision="new"))
        QTest.mouseRelease(action, Qt.MouseButton.LeftButton)
        assert requested.count() == 1
        assert requested.at(0) == (["action:original", "old"] if stop else ["action:original"])
    finally:
        if panel is not None:
            panel.shutdown()
        host.close()
        for translator in translators:
            qt_application.removeTranslator(translator)


@pytest.fixture
def reading(qt_application, tmp_path):
    record = RunRecord("archive", "monkey", "com.example.fixture", 1.0, 2.0,
                       "succeeded", {"seed": 41}, (
                           RunArtifact("第一个附件", str(tmp_path / "one.txt")),
                           RunArtifact("缺失的附件", str(tmp_path / "missing.txt")),
                       ))
    store = RunLibrary(tmp_path / "runs.json")
    store.record_run(record)
    library = RunLibraryController(store)
    host = QWidget()
    host.resize(760, 700)
    page = TaskCenterPage(run_library=library, external_details=True, parent=host)
    coordinator = TaskFeedbackCoordinator(
        page, host, show_task_center=lambda: None, open_source=lambda _source: None,
        is_task_center=lambda: False, parent=host,
    )
    sample = ActionResult(
        "current", ActionSpec("fixture", "system", "合成查询", "text"),
        ("synthetic",), 1.0, state="succeeded", finished_at=2.0,
        message="Shell [echo]：命令提示",
        items=(ActionItem("job", "synthetic", "测试手机", "succeeded", "完整正文",
                          tuple(item.path for item in record.artifacts)),),
        target_labels=("合成设备",),
    )
    host.show()
    page.hide()
    page.present_action_result(sample)
    assert coordinator.open_request("current")
    coordinator.drawer.open_drawer(animated=False)
    wait_until(qt_application, lambda: "run:archive" in page._entries)
    yield SimpleNamespace(host=host, page=page, coordinator=coordinator,
                          panel=coordinator.drawer, sample=sample, record=record, library=library)
    coordinator.shutdown()
    page.shutdown()
    host.close()
    assert library.shutdown()


@pytest.mark.parametrize("state", ["running", "succeeded", "failed", "partial", "cancelled"])
def test_hosted_output_and_files_are_immediately_readable(reading, qt_application, state):
    sample = replace(reading.sample, state=state,
                     items=(replace(reading.sample.items[0], state=state),))
    reading.page.present_action_result(sample)
    qt_application.processEvents()
    reader = reading.page.action_results
    assert reader.detail_toggle.isHidden()
    assert reader.output.isVisibleTo(reading.panel)
    assert reader.output.toPlainText() == "完整正文"
    assert reader.message_label.text() == "Shell [echo]：命令提示"
    assert reader.detail_reveal.animation.state() == QAbstractAnimation.State.Stopped
    assert reader.artifact_section is not None
    assert reader.artifact_section.toggle_button.isHidden()
    assert reader.artifacts.isVisibleTo(reading.panel)
    assert reader.open_button.isVisibleTo(reading.panel)
    assert reader.targets.isHidden()
    assert_scroll_target_reachable(reading.panel.scroll_area, reader.folder_button)


def test_hosted_archive_parameters_files_and_reuse_do_not_need_expansion(reading, qt_application):
    assert reading.coordinator.open_entry("run:archive")
    reading.panel.open_drawer(animated=False)
    qt_application.processEvents()
    reader = reading.page.run_results
    assert reader is not None and reader.artifact_section is not None
    assert reader.parameters_section.toggle_button.isHidden()
    assert reader.artifact_section.toggle_button.isHidden()
    assert reader.parameters_edit.isVisibleTo(reading.panel)
    assert '"seed": 41' in reader.parameters_edit.toPlainText()
    assert reader.parameters_section.reveal.animation.state() == QAbstractAnimation.State.Stopped
    assert reader.artifact_combo.isVisibleTo(reading.panel)
    reader.artifact_combo.setCurrentIndex(1)
    reader.parameters_edit.selectAll()
    reader.present_record(reading.record)
    assert reader.artifact_combo.currentData() == reading.record.artifacts[1].path
    assert reader.parameters_edit.textCursor().hasSelection()
    reused = QSignalSpy(reader.reuse_requested)
    reader.reuse_button.click()
    assert reused.count() == 1
    snapshot = reused.at(0)[0]
    assert snapshot == reading.record and snapshot is not reading.record
    snapshot.parameters["seed"] = 99
    assert reader.selected_record.parameters == {"seed": 41}
    reader.present_record(replace(reading.record, artifacts=()))
    assert reader.artifact_section.isHidden()
    assert reader.parameters_edit.isVisibleTo(reading.panel)
    assert reader.reuse_button.isVisibleTo(reading.panel) and reader.reuse_button.isEnabled()


def test_fluent_overlay_scrollbar_scrolls_body_without_moving_heading(reading, qt_application):
    reader = reading.page.action_results
    assert isinstance(reading.panel.scroll_area, SmoothScrollArea)
    reading.host.resize(280, 250)
    reading.panel.open_drawer(animated=False)
    qt_application.processEvents()
    scroll = reading.panel.scroll_area
    bar = scroll.delegate.vScrollBar
    assert bar.maximum() > 0 and bar.isVisibleTo(reading.panel)
    assert not scroll.verticalScrollBar().isVisibleTo(reading.panel)
    assert scroll.horizontalScrollBar().maximum() == 0
    header_position = reading.panel.close_button.mapToGlobal(
        reading.panel.close_button.rect().topLeft(),
    )
    start = bar.handle.geometry().center()
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(bar, QPoint(start.x(), bar.height() - 16))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(start.x(), bar.height() - 16))
    qt_application.processEvents()
    assert scroll.verticalScrollBar().value() == bar.value() > 0
    assert reading.panel.close_button.mapToGlobal(
        reading.panel.close_button.rect().topLeft(),
    ) == header_position
    assert_scroll_target_reachable(scroll, reader.folder_button)
    assert bar.x() + bar.width() <= scroll.width()


@pytest.mark.parametrize("kind", ["action", "run"])
def test_late_toggle_cannot_collapse_hosted_full_results(reading, qt_application, kind):
    if kind == "action":
        reader = reading.page.action_results
        sections = (reader.artifact_section,)
        reader.detail_toggle.setChecked(False)
        assert reader.detail_toggle.isChecked()
        assert reader.output.isVisibleTo(reading.panel)
    else:
        assert reading.coordinator.open_entry("run:archive")
        reader = reading.page.run_results
        assert reader is not None
        sections = (reader.parameters_section, reader.artifact_section)
    for section in sections:
        assert section is not None
        section.toggle_button.setChecked(False)
        qt_application.processEvents()
        assert section.toggle_button.isChecked()
        assert section.content.isVisibleTo(reading.panel)
        assert section.reveal.expanded
        assert section.reveal.animation.state() == QAbstractAnimation.State.Stopped


@pytest.mark.parametrize("tone,color_key", [("accent", "BORDER_FOCUS"),
                                             ("success", "LOG_SUCCESS"),
                                             ("danger", "LOG_ERROR")])
def test_accent_refresh_keeps_badge_tint_palette_and_reading_state(
    reading, qt_application, tone, color_key,
):
    panel = reading.panel
    row = reading.page.detail_row("action:current")
    assert row is not None
    panel.present(replace(row, tone=tone), source_label="系统工具")
    reader = reading.page.action_results
    reader.output.selectAll()
    reader.search.setText("正文")
    reader.artifacts.setCurrentIndex(1)
    old_accent = BaseStyles.color("BORDER_FOCUS")
    try:
        for theme in ("Light", "Dark", "Light"):
            BaseStyles.switch_theme(theme)
            for accent in ("#AE2277", "#2277AE"):
                BaseStyles.set_accent_color(accent)
                qt_application.processEvents()
                panel.status_label.ensurePolished()
                expected = QColor(BaseStyles.color(color_key))
                assert panel.status_label.palette().color(QPalette.ColorRole.WindowText) == expected
                style = panel.status_label.styleSheet()
                assert f"rgba({expected.red()}, {expected.green()}, {expected.blue()}, 24)" in style
                assert accent.lower() in reader.copy_button.styleSheet().lower()
                assert reader.output.textCursor().selectedText() == "完整正文"
                assert reader.search.text() == "正文"
                assert reader.artifacts.currentIndex() == 1
                assert reading.page.selected_key == "action:current"
                assert panel.grab().toImage().pixelColor(panel.width() - 3, panel.height() - 3) == (
                    QColor(BaseStyles.color("CONTENT_BG"))
                )
        panel.close_drawer(animated=False)
        BaseStyles.set_accent_color("#7744AA")
        panel.open_drawer(animated=False)
        assert "#7744aa" in reader.copy_button.styleSheet().lower()
    finally:
        BaseStyles.set_accent_color(old_accent)


def test_default_consumers_keep_collapsed_inline_contract(reading):
    action = ActionResultView(inline=True)
    diagnostic = ActionResultView(diagnostic=True)
    run = RunResultsWidget(reading.library, detail_only=True)
    try:
        action.present(reading.sample)
        assert not action.detail_toggle.isHidden()
        assert action.detail_host.isHidden()
        assert action.artifact_section is not None
        assert not action.artifact_section.toggle_button.isHidden()
        diagnostic.present(reading.sample)
        assert diagnostic.detail_toggle.isHidden()
        assert not diagnostic.detail_host.isHidden()
        run.present_record(reading.record)
        assert not run.parameters_section.toggle_button.isHidden()
        assert run.parameters_edit.isHidden()
    finally:
        for widget in (action, diagnostic, run):
            widget.close()
            widget.deleteLater()


def test_full_output_budget_search_copy_export_and_font_roles_remain_independent(
    reading, qt_application, monkeypatch,
):
    reader = reading.page.action_results
    full = "开头\n" + "正文😀\n" * 16000 + "尾部命中   空格"
    sample = replace(reading.sample, items=(replace(reading.sample.items[0], detail=full),))
    reading.page.present_action_result(sample)
    assert reader.output.isVisibleTo(reading.panel)
    assert reader.detail_toggle.isHidden()
    assert len(reader.output.toPlainText()) == 64000
    assert reader.preview_notice.isVisibleTo(reading.panel)
    reader.search.setText("尾部命中   ")
    QTest.keyClick(reader.search, Qt.Key.Key_Return)
    assert reader.output.textCursor().selectedText() == "尾部命中   "
    selection = (reader.output.textCursor().selectionStart(),
                 reader.output.textCursor().selectionEnd())
    reader.artifacts.setCurrentIndex(1)
    reader.copy_button.click()
    assert QApplication.clipboard().text() == full
    exported = QSignalSpy(reader.export_requested)
    reader.export_button.click()
    assert exported.count() == 1
    assert exported.at(0) == ["current", full]
    settings = {"font_family": "", "ui_font_size": 12, "log_font_size": 9}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    families = QFontDatabase.families()
    custom_family = next(family for family in ("Arial", "DejaVu Sans", "Helvetica", *families)
                         if family in families and family != reader.search.font().family())
    for size, output_size in ((12, 9), (22, 15), (12, 11)):
        settings.update(font_family=custom_family, ui_font_size=size, log_font_size=output_size)
        BaseStyles.reload_from_settings()
        qt_application.processEvents()
        assert reader.output.font().pointSizeF() == output_size
        assert reader.search.font().pointSizeF() == size
        assert reader.search.font().family() == custom_family
        assert reader.output.font() == BaseStyles.font_for_role(FontRole.LOG)
        assert reader.output.font().family() != custom_family
        assert reading.panel.title_label.font().pointSizeF() == size + 4
        assert (reader.output.textCursor().selectionStart(),
                reader.output.textCursor().selectionEnd()) == selection
        assert reader.output.textCursor().selectedText() == "尾部命中   "
        assert reader.output.verticalScrollBar().value() > 0
        assert reader.artifacts.currentIndex() == 1
        assert reading.page.action_results is reader
    assert reading.coordinator.open_entry("run:archive")
    archive = reading.page.run_results
    assert archive is not None
    assert archive.parameters_edit.font() == BaseStyles.font_for_role(FontRole.MONO)
    assert archive.parameters_edit.font().pointSizeF() == 12


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("size", [12, 22])
@pytest.mark.parametrize("width", [280, 390])
@pytest.mark.parametrize("archived", [False, True])
def test_active_action_and_status_retention_fit_narrow_large_fonts(
    reading, qt_application, monkeypatch, theme, size, width, archived,
):
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: {
        "font_family": "", "ui_font_size": size, "log_font_size": 11,
    }))
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    panel = reading.panel
    row = reading.page.detail_row("action:current")
    assert row is not None
    panel.present(replace(row, cancellable=True), archived=archived,
                  from_task_center=archived, source_available=True)
    reading.host.resize(width, 640)
    panel.open_drawer(animated=False)
    qt_application.processEvents()
    assert not panel.cancel_button.icon().isNull()
    assert panel.cancel_button.property("buttonVariant") == "danger"
    for button in (panel.close_button, panel.cancel_button):
        assert button.isVisibleTo(panel)
        assert panel.rect().contains(button.mapTo(panel, button.rect().topLeft()))
        assert panel.rect().contains(button.mapTo(panel, button.rect().bottomRight()))
        assert button.height() >= button.fontMetrics().height() + 8
    assert panel.cancel_button.width() >= panel.cancel_button.sizeHint().width()
    assert panel.status_label.toolTip() == panel.status_label.accessibleDescription()
    assert panel.status_label.toolTip() == (tr("已归档 · 关闭应用后仍可查看") if archived
                                            else tr("本次会话 · 需要保留的正文请导出"))
    status = panel.status_label.mapToGlobal(panel.status_label.rect().bottomRight())
    cancel = panel.cancel_button.mapToGlobal(panel.cancel_button.rect().topLeft())
    assert cancel.y() > status.y()
    assert panel.scroll_area.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize("variant", ["empty-running", "empty-failed", "local", "multiple", "notes"])
def test_complete_mode_keeps_fallbacks_request_errors_and_target_navigation(reading, variant):
    sample = reading.sample
    if variant == "empty-running":
        sample = replace(sample, state="running", items=(), message="")
        expected = "正在执行，请等待结果。"
    elif variant == "empty-failed":
        sample = replace(sample, state="failed", items=(), message="请求收尾失败")
        expected = "请求收尾失败"
    elif variant == "local":
        sample = replace(sample, targets=(), target_labels=(),
                         items=(replace(sample.items[0], target=None),))
        expected = "完整正文"
    elif variant == "multiple":
        sample = replace(sample, targets=("synthetic", "second"), state="partial", items=(
            sample.items[0], ActionItem("job2", "second", "第二设备", "failed", "第二设备错误"),
        ))
        expected = "第二设备错误"
    else:
        sample = replace(sample, spec=replace(sample.spec, presentation="notes"), state="warning",
                         items=(replace(sample.items[0], state="warning", detail="需要检查条件"),))
        expected = "[注意] 需要检查条件"
    reading.page.present_action_result(sample)
    reader = reading.page.action_results
    if variant == "multiple":
        assert reader.targets.isVisibleTo(reading.panel)
        reader.targets.setCurrentIndex(1)
    assert reader.output.isVisibleTo(reading.panel)
    assert reader.output.toPlainText() == expected
    assert reader.detail_toggle.isHidden()
    if variant == "empty-failed":
        assert reader.message_label.isHidden()
        assert reader.output.toPlainText() == "请求收尾失败"
    elif variant == "notes":
        assert reader.targets.isHidden()
    elif variant == "local":
        assert reader.targets.isHidden()


def test_same_snapshot_other_task_and_reopen_preserve_reader_selection_search_and_file(reading):
    reader = reading.page.action_results
    reader.output.selectAll()
    reader.search.setText("正文")
    reader.artifacts.setCurrentIndex(1)
    reading.page.present_action_result(reading.sample)
    reading.page.present_action_result(replace(reading.sample, request_id="other", started_at=3.0))
    assert reading.page.selected_key == "action:current"
    reading.panel.close_drawer(animated=False)
    assert reading.coordinator.open_request("current")
    reading.panel.open_drawer(animated=False)
    assert reading.page.action_results is reader
    assert reader.output.textCursor().selectedText() == "完整正文"
    assert reader.search.text() == "正文"
    assert reader.artifacts.currentIndex() == 1
    assert reader.output.isVisibleTo(reading.panel)


def test_closing_fluent_bar_is_inert_and_reopening_uses_same_bar(reading, qt_application):
    reading.host.resize(280, 250)
    reading.panel.open_drawer(animated=False)
    qt_application.processEvents()
    scroll = reading.panel.scroll_area
    bar = scroll.delegate.vScrollBar
    bar.setValue(0)
    point = bar.handle.geometry().center()
    reading.panel.close_drawer()
    reading.panel.animation.setCurrentTime(80)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(bar, QPoint(point.x(), bar.height() - 16))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(point.x(), bar.height() - 16))
    assert scroll.verticalScrollBar().value() == 0
    reading.panel.open_drawer(animated=False)
    assert scroll.delegate.vScrollBar is bar
    assert bar.isVisibleTo(reading.panel)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(bar, QPoint(point.x(), bar.height() - 16))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(point.x(), bar.height() - 16))
    assert scroll.verticalScrollBar().value() > 0


def test_short_hosted_output_uses_compact_viewport_and_long_output_stays_bounded(reading):
    reader = reading.page.action_results
    assert reader.output.height() < 2 * reader.output.fontMetrics().lineSpacing() + 16
    reading.page.present_action_result(replace(reading.sample, items=(
        replace(reading.sample.items[0], detail="长行\n" * 2000),
    )))
    assert reader.output.height() <= 320
    assert reader.output.verticalScrollBar().maximum() > 0


def test_toolbar_focus_follows_custom_accent_without_reordering_results(reading, qt_application):
    reading.page.present_action_result(replace(reading.sample, request_id="other", started_at=3.0))
    assert reading.coordinator.open_request("current")
    panel = reading.panel
    keys = [row.key for row in reading.page.recent_rows()]
    assert keys == ["action:other", "action:current", "run:archive"]
    tool = reading.page.action_results.copy_button
    accent_before = BaseStyles.accent_color()
    try:
        for theme in ("Light", "Dark"):
            BaseStyles.switch_theme(theme)
            for accent in ("#AE2277", "#2277AE"):
                BaseStyles.set_accent_color(accent)
                qt_application.processEvents()
                assert accent.lower() in tool.styleSheet().lower()
                assert tool.isVisibleTo(panel)
                assert [row.key for row in reading.page.recent_rows()] == keys
                assert panel.selected_key == "action:current"
    finally:
        BaseStyles.set_accent_color(accent_before)


def test_long_wrapped_paragraph_gets_reading_height_after_width_and_font_changes(
    reading, qt_application, monkeypatch,
):
    reader = reading.page.action_results
    settings = {"font_family": "", "ui_font_size": 12, "log_font_size": 11}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()
    reading.host.resize(280, 700)
    paragraph = "这是没有换行符的完整设备诊断结果，应该按真实换行分配阅读空间。" * 18
    reading.page.present_action_result(replace(reading.sample, items=(
        replace(reading.sample.items[0], detail=paragraph),
    )))
    qt_application.processEvents()
    assert reader.output.height() >= 280
    assert reader.output.height() <= 320
    assert reader.output.toPlainText() == paragraph
    short_paragraph = "这一段文字在宽视口中可连续阅读，在窄视口或较大输出字号下需要更多行。" * 2
    reading.page.present_action_result(replace(reading.sample, items=(
        replace(reading.sample.items[0], detail=short_paragraph),
    )))
    reading.host.resize(390, 700)
    wait_for_stable_geometry(qt_application, (reading.panel, reader, reader.output))
    wide_height = reader.output.height()
    wide_width = reader.output.viewport().width()
    reading.host.resize(280, 700)
    wait_for_stable_geometry(qt_application, (reading.panel, reader, reader.output))
    narrow_height = reader.output.height()
    assert narrow_height > wide_height, (wide_width, reader.output.viewport().width())
    settings["log_font_size"] = 18
    BaseStyles.reload_from_settings()
    qt_application.processEvents()
    assert reader.output.height() > narrow_height
    assert reader.output.height() <= 320


def test_same_device_jobs_switch_full_search_export_and_files_without_mixing(reading):
    reader = reading.page.action_results
    first = reading.sample.items[0]
    full = "second\n" * 11000 + "unique-tail"
    second = replace(first, job_id="second", detail=full, artifacts=("second.txt",))
    reading.page.present_action_result(replace(reading.sample, items=(first, second)))
    assert reader.targets.isVisibleTo(reading.panel)
    assert reader.targets.itemText(0) != reader.targets.itemText(1)
    reader.targets.setCurrentIndex(reader.targets.findData("second"))
    assert reader.targets.currentData() == "second"
    assert reader.output.toPlainText() == full[:64000]
    reader.search.setText("unique-tail")
    QTest.keyClick(reader.search, Qt.Key.Key_Return)
    assert reader.output.textCursor().selectedText() == "unique-tail"
    reader.copy_button.click()
    assert QApplication.clipboard().text() == full
    exported = QSignalSpy(reader.export_requested)
    reader.export_button.click()
    assert exported.count() == 1 and exported.at(0) == ["current", full]
    assert reader.artifacts.count() == 1 and reader.artifacts.currentData() == "second.txt"
    reader.targets.setCurrentIndex(reader.targets.findData(first.job_id))
    assert reader.output.toPlainText() == first.detail
    assert reader.artifacts.currentData() in first.artifacts
