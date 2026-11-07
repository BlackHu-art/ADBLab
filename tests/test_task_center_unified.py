"""单页任务中心的统一身份、筛选和行内阅读契约。"""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest

from gui.pages.tasks_page import TaskCenterPage
from gui.run_library import RunLibraryController
from services.run_library import RunLibrary, RunRecord
from services.task_history import TaskHistoryEntry, TaskHistoryStore
from services.tasks.action_results import ActionItem, ActionResult, ActionSpec
from services.tasks.operations import OperationManager, OperationState
from tests.ui_geometry_helpers import wait_until


def _result(request_id="query", **kwargs):
    return ActionResult(
        request_id,
        ActionSpec("shell_command", "system.shell", "执行 Shell", "text"),
        ("synthetic-target",),
        100,
        target_labels=("测试手机",),
        **kwargs,
    )


def test_sources_share_one_table_and_filters_apply_to_both(qt_application, tmp_path):
    store = RunLibrary(tmp_path / "runs.json")
    store.record_run(RunRecord("run", "performance", "com.example.app", 1, 200, "succeeded", {}))
    library = RunLibraryController(store)
    page = TaskCenterPage(run_library=library)
    try:
        wait_until(qt_application, lambda: bool(library.records_view))
        page.present_action_result(_result(state="failed"))
        page.refresh()
        assert set(page.table.rows) == {"action:query", "run:run"}
        assert page._ordered_keys == ("run:run", "action:query")
        page.search_edit.setText("com.example")
        assert set(page.table.rows) == {"run:run"}
        page.search_edit.clear()
        page.state_combo.setCurrentIndex(page.state_combo.findData("failed"))
        assert set(page.table.rows) == {"action:query"}
        assert not hasattr(page, "history_views")
    finally:
        page.close()
        assert library.shutdown()


def test_incomplete_archive_keeps_incomplete_result_label(qt_application, tmp_path):
    store = RunLibrary(tmp_path / "incomplete.json")
    store.record_run(RunRecord("run", "monkey", "com.example.app", 1, 2, "partial", {}))
    library = RunLibraryController(store)
    page = TaskCenterPage(run_library=library)
    try:
        wait_until(qt_application, lambda: bool(library.records_view))
        assert page.table.rows["run:run"].data.state == "结果不完整"
        page.state_combo.setCurrentIndex(page.state_combo.findData("partial"))
        assert "run:run" in page.table.rows
    finally:
        page.close()
        assert library.shutdown()


def test_explicit_operation_identity_merges_progress_with_action(qt_application):
    manager = OperationManager()
    op = manager.begin("screenshot", unit_ids=("unit",))
    manager.mark_running(op.operation_id)
    stop = Mock()
    page = TaskCenterPage(manager, stop_hook=stop)
    page.present_action_result(_result(operation_ids=(op.operation_id,)))
    page.refresh()
    assert set(page.table.rows) == {"action:query"}
    row = page.table.rows["action:query"]
    manager.update_progress(op.operation_id, 35)
    page.refresh()
    assert "35%" in row.status.accessibleName()
    row.cancel.click()
    assert manager.get(op.operation_id).cancel_requested
    stop.assert_called_once_with(op.operation_id)
    assert not row.cancel.isEnabled()
    assert row.data.state == "正在取消"
    page.shutdown()


def test_background_updates_do_not_expand_or_replace_current_reader(qt_application):
    page = TaskCenterPage()
    page.resize(720, 600)
    first = _result(
        state="succeeded",
        items=(ActionItem("one", "synthetic-target", "手机", "succeeded", "marker"),),
    )
    page.present_action_result(first)
    assert page.table.expanded_key == ""
    page.show()
    page.select_request("query")
    page.action_results.detail_toggle.setChecked(True)
    page.action_results.detail_reveal.finish()
    page.action_results.output.selectAll()
    page.present_action_result(_result("newer", state="running"))
    page.present_action_result(replace(first, message="已完成"))
    qt_application.processEvents()
    assert page.table.expanded_key == "action:query"
    assert page.action_results._selected == "query"
    assert page.action_results.output.textCursor().selectedText() == "marker"
    page.activateWindow()
    page.action_results.output.setFocus()
    qt_application.processEvents()
    QTest.keyClick(page.action_results.output, Qt.Key.Key_Escape)
    assert page.table.expanded_key == ""
    page.close()


def test_notification_selection_clears_filters_and_reveals_exact_request(qt_application):
    page = TaskCenterPage()
    page.present_action_result(_result(state="failed"))
    page.search_edit.setText("no match")
    assert not page.table.rows
    assert page.select_request("query")
    assert page.search_edit.text() == ""
    assert page.table.expanded_key == "action:query"
    assert page.action_results._selected == "query"
    assert not page.select_request("missing")
    page.shutdown()


def test_notes_exception_is_unread_until_opened_and_new_note_becomes_unread(qt_application):
    page = TaskCenterPage()
    result = replace(
        _result(state="recorded"),
        spec=ActionSpec("notes", "apps.files", "文件操作", "notes"),
        items=(ActionItem("note-one", "synthetic-target", "手机", "failed", "操作失败"),),
    )
    page.present_action_result(result)
    assert page.table.rows["action:query"].data.unread
    assert page.table.rows["action:query"].data.state == "失败"
    page.select_request("query")
    assert not page.table.rows["action:query"].data.unread
    page.table.set_expanded("")
    page.present_action_result(
        replace(
            result,
            items=result.items
            + (ActionItem("note-two", "synthetic-target", "手机", "failed", "新的失败"),),
        )
    )
    assert page.table.rows["action:query"].data.unread
    page.shutdown()


def test_collapsed_reader_preserves_latest_large_result_under_budget(qt_application):
    page = TaskCenterPage()
    page.action_results.TEXT_BUDGET = 200
    page.present_action_result(_result("old", state="succeeded"))
    latest = _result(
        "latest",
        state="succeeded",
        items=(ActionItem("large", "synthetic-target", "手机", "succeeded", "输出" * 1000),),
    )
    page.present_action_result(latest)
    assert "action:latest" in page.table.rows
    assert page.select_request("latest")
    assert page.action_results._detail == "输出" * 1000
    page.shutdown()


@pytest.mark.parametrize("state,label", [("cancelled", "已取消"), ("warning", "注意")])
def test_device_summary_preserves_actual_item_state(qt_application, state, label):
    page = TaskCenterPage()
    page.present_action_result(
        _result(
            state=state, items=(ActionItem("state", "synthetic-target", "手机", state, "明细"),)
        )
    )
    page.select_request("query")
    assert label in page.device_summary.text()
    assert "成功" not in page.device_summary.text()
    page.shutdown()


@pytest.mark.parametrize("language", ["zh_CN", "zh_HK", "en_US"])
def test_long_state_filter_fits_narrow_page_at_large_font(qt_application, monkeypatch, language):
    from core.settings_manager import AppSettings
    from gui.i18n import install_translators
    from gui.styles import BaseStyles
    from tests.ui_geometry_helpers import wait_for_stable_geometry

    settings = {"ui_font_size": 22, "font_family": "Arial", "log_font_size": 11}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()
    translators = install_translators(qt_application, language)
    page = TaskCenterPage()
    page.resize(360, 600)
    page.show()
    try:
        page.state_combo.setCurrentIndex(page.state_combo.findData("partial"))
        wait_for_stable_geometry(qt_application, (page, page.filters, page.state_combo))
        assert page.filters.rect().contains(page.state_combo.geometry())
        assert page._scroll.horizontalScrollBar().maximum() == 0
        count_rect = page.count_label.contentsRect()
        needed = page.count_label.fontMetrics().boundingRect(
            QRect(0, 0, count_rect.width(), 10000),
            Qt.TextFlag.TextWordWrap,
            page.count_label.text(),
        )
        assert needed.height() <= count_rect.height() + 2
    finally:
        page.close()
        for translator in translators:
            qt_application.removeTranslator(translator)


@pytest.mark.parametrize("same_kind", [False, True])
def test_legacy_history_append_keeps_expanded_record_identity(qt_application, same_kind):
    history = TaskHistoryStore()
    history.record(TaskHistoryEntry("install", "install", "install", True, "旧正文"))
    page = TaskCenterPage(history_store=history)
    key = next(iter(page.table.rows))
    page.table.set_expanded(key)
    page.record_history(
        TaskHistoryEntry(
            "install" if same_kind else "screenshot",
            "install",
            "install",
            True,
            "新正文",
        )
    )
    assert page.table.expanded_key == key
    assert page.operation_output.toPlainText() == "旧正文"
    page.shutdown()


def test_cancel_intent_survives_operation_removal_until_action_settles(qt_application):
    manager = OperationManager()
    op = manager.begin("screenshot")
    manager.mark_running(op.operation_id)
    page = TaskCenterPage(
        manager, stop_hook=lambda oid: manager.finish(oid, OperationState.CANCELLED)
    )
    result = _result(operation_ids=(op.operation_id,))
    page.present_action_result(result)
    row = page.table.rows["action:query"]
    row.cancel.click()
    page.refresh()
    assert manager.get(op.operation_id) is None
    assert row.data.state == "正在取消"
    assert not row.cancel.isEnabled()
    assert page._entries["action:query"].active
    page.present_action_result(replace(result, state="cancelled"))
    assert page.table.rows["action:query"].data.state == "已取消"
    assert not page._entries["action:query"].active
    page.shutdown()
