"""任务列表向固定外部阅读器发布选择和未筛选状态，不接管执行资源。"""

from dataclasses import replace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from gui.pages.tasks_page import TaskCenterPage
from gui.run_library import RunLibraryController
from services.run_library import RunArtifact, RunLibrary, RunRecord
from services.tasks.action_results import ActionItem, ActionResult, ActionResults, ActionSpec
from services.tasks.operations import OperationManager, OperationState
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def _result(key="request", state="running", *, operation_ids=(), items=()):
    return ActionResult(
        key, ActionSpec("shell_command", "system.shell", "执行 Shell", "text"),
        ("synthetic-target",), 100, state=state, operation_ids=operation_ids,
        target_labels=("测试手机",), items=items,
        finished_at=200 if state != "running" else None,
    )


@pytest.fixture
def external_page(qt_application):
    page = TaskCenterPage(external_details=True)
    yield page
    page.shutdown()
    page.close()


def test_external_selection_opens_fixed_reader_even_when_filtered_and_repeated(external_page):
    page = external_page
    host = QWidget()
    page.detail.setParent(host)
    page.present_action_result(_result(state="failed"))
    page.search_edit.setText("不匹配")
    requested = QSignalSpy(page.detail_requested)
    assert page.select_entry("action:request")
    assert page.select_entry("action:request")
    assert requested.count() == 2
    assert page.selected_key == "action:request"
    assert page.action_results._selected == "request"
    assert page.detail.parentWidget() is host
    assert page.table.expanded_key == ""
    assert page.search_edit.text() == "不匹配"
    assert page.detail_source("action:request") == "system.shell"
    assert not page.select_entry("action:missing")
    page.detail.setParent(page)
    host.close()


def test_inline_selection_api_honors_mark_read_and_emits_once_per_success(qt_application):
    page = TaskCenterPage()
    try:
        page.present_action_result(_result(state="failed"))
        requested = QSignalSpy(page.detail_requested)
        assert page.select_entry("action:request", mark_read=False)
        assert page.navigation_snapshot().unread_count == 1
        assert requested.count() == 1
        assert page.select_entry("action:request", mark_read=False)
        assert page.navigation_snapshot().unread_count == 1
        assert requested.count() == 2
        assert page.select_entry("action:request", mark_read=True)
        assert page.navigation_snapshot().unread_count == 0
        assert requested.count() == 3
        page.table.rows["action:request"].title.click()
        page.present_action_result(replace(_result(state="failed"), items=(
            ActionItem("new-error", "synthetic-target", "手机", "failed", "新错误"),
        )))
        assert page.navigation_snapshot().unread_count == 1
        page.table.rows["action:request"].title.click()
        assert page.navigation_snapshot().unread_count == 0
        assert requested.count() == 4
    finally:
        page.shutdown()
        page.close()


@pytest.mark.parametrize("reader_has_target", [False, True])
def test_inline_hidden_row_selection_refuses_without_changing_reader_or_read_status(
    qt_application, reader_has_target,
):
    page = TaskCenterPage()
    try:
        page.present_action_result(_result("failed", "failed"))
        page.present_action_result(_result("other", "succeeded"))
        if reader_has_target:
            assert page.select_entry("action:failed", mark_read=False)
            page.close_detail()
        assert page.action_results._selected == ("failed" if reader_has_target else "other")
        unread_before = page.navigation_snapshot().unread_count
        assert unread_before == 1
        page.search_edit.setText("no match")
        assert not page.table.rows
        requested = QSignalSpy(page.detail_requested)
        assert not page.select_entry("action:failed", clear_filters=False, mark_read=False)
        assert page.search_edit.text() == "no match"
        assert page.selected_key == ""
        assert page.action_results._selected == ("failed" if reader_has_target else "other")
        assert page.navigation_snapshot().unread_count == unread_before
        assert requested.count() == 0
        assert page.select_entry("action:failed", clear_filters=True, mark_read=False)
        assert page.search_edit.text() == ""
        assert page.selected_key == "action:failed"
        assert page.navigation_snapshot().unread_count == unread_before
        assert requested.count() == 1
    finally:
        page.shutdown()
        page.close()


def test_automatic_reading_and_refresh_never_acknowledge_new_failure_versions(external_page):
    page = external_page
    failed = _result(state="failed")
    page.present_action_result(failed)
    assert page.select_entry("action:request", mark_read=False)
    page.refresh()
    assert page.navigation_snapshot().unread_count == 1
    assert page.select_entry("action:request")
    assert page.navigation_snapshot().unread_count == 0
    page.present_action_result(replace(failed, items=(
        ActionItem("later", "synthetic-target", "手机", "failed", "新增错误"),
    )))
    page.refresh()
    assert page.navigation_snapshot().unread_count == 1
    assert page.table.rows["action:request"].data.unread


@pytest.mark.parametrize("appended_state,unread", [
    ("recorded", 0), ("succeeded", 0), ("failed", 1), ("warning", 1),
])
def test_notes_only_new_exception_identity_restores_unread(
    external_page, appended_state, unread,
):
    page = external_page
    first = replace(
        _result(state="recorded"),
        spec=ActionSpec("notes", "system", "记录", "notes"),
        items=(ActionItem("error", "synthetic-target", "手机", "failed", "旧错误"),),
    )
    page.present_action_result(first)
    page.select_entry("action:request")
    assert page.navigation_snapshot().unread_count == 0
    page.present_action_result(replace(
        first, finished_at=300,
        items=first.items + (
            ActionItem("appended", "synthetic-target", "手机", appended_state, "新增事件"),
        ),
    ))
    assert page.navigation_snapshot().unread_count == unread
    assert set(page.table.rows) == {"action:request"}


def test_notes_capacity_rotation_keeps_acknowledged_exception_read_until_new_error(external_page):
    page = external_page
    results = ActionResults(page.present_action_result)
    spec = ActionSpec("notes:rotation", "system", "合成记录", "notes")
    last = None
    for index in range(200):
        last = results.record_note(
            spec, (), f"合成事件 {index}", "error" if index in (0, 99) else "info",
        )
    assert last is not None
    assert len(last.items) == 200
    oldest_error = last.items[0].job_id
    key = f"action:{last.request_id}"
    assert page.select_entry(key)
    assert page.navigation_snapshot().unread_count == 0
    rotated = results.record_note(spec, (), "容量轮转后的普通说明", "info")
    assert len(rotated.items) == 200
    assert oldest_error not in {item.job_id for item in rotated.items}
    assert any(item.state == "failed" for item in rotated.items)
    assert page.navigation_snapshot().unread_count == 0
    results.record_note(spec, (), "容量轮转后的成功说明", "success")
    assert page.navigation_snapshot().unread_count == 0
    results.record_note(spec, (), "真正新增的异常", "error")
    assert page.navigation_snapshot().unread_count == 1
    assert page.select_entry(key)
    assert page.navigation_snapshot().unread_count == 0


def test_filtering_does_not_close_selected_reader_or_change_navigation_counts(external_page):
    page = external_page
    page.present_action_result(_result("active"))
    page.present_action_result(
        replace(
            _result("failed", "failed"), spec=ActionSpec("file_pull", "files", "文件传输", "text")
        )
    )
    page.select_entry("action:active")
    closed = QSignalSpy(page.detail_closed)
    page.kind_combo.setCurrentIndex(page.kind_combo.findData("file"))
    assert set(page.table.rows) == {"action:failed"}
    assert page.selected_key == "action:active"
    assert closed.count() == 0
    assert page.navigation_snapshot().active_count == 1
    assert page.navigation_snapshot().unread_count == 1
    page.search_edit.setText("文件")
    assert set(page.table.rows) == {"action:failed"}
    page.select_entry("action:active", clear_filters=True)
    assert set(page.table.rows) == {"action:active", "action:failed"}
    page.kind_combo.setCurrentIndex(page.kind_combo.findData("shell"))
    assert set(page.table.rows) == {"action:active"}


def test_recent_tasks_use_natural_order_while_visible_list_stays_frozen(external_page):
    page = external_page
    for key, finished in (("old", 100), ("middle", 200), ("chosen", 300)):
        page.present_action_result(replace(_result(key, "succeeded"), finished_at=finished))
    page.select_entry("action:chosen")
    page.present_action_result(replace(_result("newest", "succeeded"), finished_at=400))
    visible_order = page.table.record_keys
    assert visible_order == (
        "action:chosen", "action:middle", "action:old", "action:newest",
    )
    assert tuple(row.key for row in page.recent_rows()) == (
        "action:newest", "action:chosen", "action:middle", "action:old",
    )


def test_navigation_signal_slots_read_one_committed_projection_generation(qt_application):
    manager = OperationManager()
    page = TaskCenterPage(manager, external_details=True)
    generations = []

    def capture(snapshot):
        generations.append((
            snapshot.active_count,
            tuple(row.key for row in page.recent_rows()),
            tuple(page.table.rows), page.selected_key,
        ))

    page.navigation_snapshot_changed.connect(capture)
    try:
        operation = manager.begin("install")
        key = f"operation:{operation.operation_id}"
        page.refresh()
        page.select_entry(key)
        manager.finish(operation.operation_id, OperationState.CANCELLED)
        page.refresh()
        assert generations == [(1, (key,), (key,), ""), (0, (), (), "")]
        assert page.detail_row(key) is None
    finally:
        page.shutdown()
        page.close()


def test_close_is_idempotent_and_late_results_do_not_open_reader(external_page):
    page = external_page
    page.present_action_result(_result())
    page.select_entry("action:request")
    closed, requested = QSignalSpy(page.detail_closed), QSignalSpy(page.detail_requested)
    page.close_detail()
    page.close_detail()
    assert closed.count() == 1
    assert page.selected_key == ""
    page.present_action_result(_result(state="failed"))
    assert page.selected_key == ""
    assert requested.count() == 0
    assert page.navigation_snapshot().unread_count == 1


def test_closed_external_reader_releases_budget_protection_on_next_result(external_page):
    page = external_page
    page.action_results.TEXT_BUDGET = 200
    page.present_action_result(_result("chosen", "succeeded"))
    page.select_entry("action:chosen")
    large = _result("latest", "succeeded", items=(
        ActionItem("large", "synthetic-target", "手机", "succeeded", "正文" * 1000),
    ))
    page.present_action_result(large)
    assert page.detail_row("action:chosen") is not None
    page.close_detail()
    page.present_action_result(_result("next", "succeeded"))
    assert page.detail_row("action:chosen") is None
    assert page.selected_key == ""


def test_hidden_refresh_merges_operations_and_cancel_gap_without_success(qt_application):
    manager = OperationManager()
    op = manager.begin("screenshot")
    manager.mark_running(op.operation_id)
    page = TaskCenterPage(
        manager, external_details=True,
        stop_hook=lambda oid: manager.finish(oid, OperationState.CANCELLED),
    )
    try:
        result = _result(operation_ids=(op.operation_id,))
        page.present_action_result(result)
        assert not page.isVisible()
        assert page.navigation_snapshot().active_count == 1
        page.cancel_entry("action:request")
        page.refresh()
        assert page.navigation_snapshot().active_count == 1
        assert page.detail_row("action:request").cancelling
        assert page.navigation_snapshot().success_event_id is None
        page.present_action_result(replace(result, state="cancelled", finished_at=200))
        assert page.navigation_snapshot().active_count == 0
        assert page.navigation_snapshot().success_event_id is None
        unlinked = manager.begin("install")
        page.refresh()
        assert page.navigation_snapshot().active_count == 1
        manager.finish(unlinked.operation_id, OperationState.CANCELLED)
        page.refresh()
        assert page.navigation_snapshot().active_count == 0
        assert page.navigation_snapshot().success_event_id is None
    finally:
        page.shutdown()
        page.close()


def test_multiple_linked_operations_count_as_one_logical_request(qt_application):
    manager = OperationManager()
    operations = [manager.begin("install") for _ in range(3)]
    page = TaskCenterPage(manager, external_details=True)
    try:
        page.present_action_result(_result(
            operation_ids=tuple(operation.operation_id for operation in operations[:2]),
        ))
        assert page.navigation_snapshot().active_count == 2
        assert set(page.table.rows) == {
            "action:request", f"operation:{operations[2].operation_id}",
        }
    finally:
        page.shutdown()
        page.close()


def test_records_keep_all_states_after_explicit_acknowledgement(external_page):
    page = external_page
    for state in ("failed", "partial", "warning", "succeeded", "running"):
        page.present_action_result(_result(state, state))
    page.select_entry("action:failed")
    assert set(page.table.rows) == {
        f"action:{state}" for state in ("failed", "partial", "warning", "succeeded", "running")
    }
    assert not page.table.rows["action:failed"].data.unread
    assert page.navigation_snapshot().unread_count == 2
    assert page.navigation_snapshot().active_count == 1
    assert {row.data.state for row in page.table.rows.values()} == {
        "失败",
        "部分成功",
        "注意",
        "成功",
        "运行中",
    }
    assert "5 / 5" in page.count_label.text()


@pytest.mark.parametrize("state,item_states,expected", [
    ("partial", (("one", "succeeded"), ("one", "succeeded"), ("two", "failed")),
     "成功 1 台 · 失败 1 台 · 未完成 1 台"),
    ("succeeded", (("one", "succeeded"), ("two", "succeeded"), ("three", "succeeded")),
     "成功 3 台"),
    ("failed", (), "失败 3 台"),
    ("cancelled", (), "未完成 3 台"),
    ("partial", (("one", "succeeded"), ("two", "succeeded"), ("three", "succeeded")),
     "部分操作失败 · 3 台目标设备"),
])
def test_device_summary_starts_with_aggregate_outcomes_without_losing_per_device_details(
    external_page, state, item_states, expected,
):
    page = external_page
    items = tuple(
        ActionItem(f"job-{index}", target, "合成命令", item_state, "结果正文")
        for index, (target, item_state) in enumerate(item_states)
    )
    result = replace(
        _result(state=state, items=items), targets=("one", "two", "three"),
        target_labels=("测试手机甲", "测试手机乙", "测试手机丙"),
    )
    page.present_action_result(result)
    page.select_entry("action:request")
    lines = page.device_summary.text().splitlines()
    assert lines[0] == expected
    assert len(lines) == 4
    assert all(label in line for label, line in zip(result.target_labels, lines[1:]))
    assert not page.device_summary.isHidden()
    assert " 0 台" not in lines[0]


def test_only_observed_active_to_success_emits_one_stable_completion(external_page):
    page = external_page
    page.present_action_result(_result("old", "succeeded"))
    assert page.navigation_snapshot().success_event_id is None
    page.present_action_result(_result("live"))
    page.search_edit.setText("不匹配")
    page.present_action_result(_result("live", "succeeded"))
    event = page.navigation_snapshot().success_event_id
    assert event is not None
    page.refresh()
    page.present_action_result(_result("live", "succeeded"))
    assert page.navigation_snapshot().success_event_id == event
    page.present_action_result(replace(
        _result("notes"), spec=ActionSpec("notes", "system", "记录", "notes"),
    ))
    page.present_action_result(replace(
        _result("notes", "succeeded"), spec=ActionSpec("notes", "system", "记录", "notes"),
    ))
    assert page.navigation_snapshot().success_event_id == event
    page.present_action_result(_result("next"))
    page.present_action_result(_result("next", "succeeded"))
    assert page.navigation_snapshot().success_event_id != event


def test_external_row_activation_emits_request_and_background_updates_only_change(external_page):
    page = external_page
    page.present_action_result(_result())
    opened, changed = QSignalSpy(page.detail_requested), QSignalSpy(page.detail_changed)
    row = page.table.rows["action:request"]
    row.title.click()
    assert opened.count() == 1
    assert page.selected_key == "action:request"
    page.present_action_result(_result(state="succeeded"))
    assert opened.count() == 1
    assert changed.count() >= 1
    assert page.table.rows["action:request"] is row
    assert page.action_results._selected == "request"


def test_external_full_output_export_and_selection_survive_other_results(external_page):
    page = external_page
    body = "完整正文" * 20000
    result = _result("chosen", "succeeded", items=(
        ActionItem("one", "synthetic-target", "手机", "succeeded", body),
    ))
    page.present_action_result(result)
    page.select_entry("action:chosen")
    page.action_results.detail_toggle.setChecked(True)
    page.action_results.detail_reveal.finish()
    page.action_results.output.selectAll()
    selected = page.action_results.output.textCursor().selectedText()
    page.present_action_result(_result("later"))
    page.present_action_result(replace(result, message="更新摘要"))
    assert page.selected_key == "action:chosen"
    assert page.action_results.output.textCursor().selectedText() == selected
    exports = QSignalSpy(page.action_results.export_requested)
    assert page.action_results.export_button.isEnabled()
    page.action_results.export_button.click()
    assert exports.count() == 1
    assert exports.at(0) == ["chosen", body]


def test_archived_external_reader_keeps_artifact_and_reuse_snapshot(qt_application, tmp_path):
    store = RunLibrary(tmp_path / "external-runs.json", capacity=2)
    record = RunRecord(
        "chosen", "performance", "com.example", 1, 2, "succeeded", {"frequency": 5},
        artifacts=(RunArtifact("first", "/tmp/one.html"), RunArtifact("second", "/tmp/two.html")),
    )
    store.record_run(record)
    library = RunLibraryController(store)
    page = TaskCenterPage(run_library=library, external_details=True)
    try:
        wait_until(qt_application, lambda: "run:chosen" in page._entries)
        assert page.select_entry("run:chosen")
        assert page.detail_source("run:chosen") == "system.performance"
        reader = page.run_results
        reader.artifact_combo.setCurrentIndex(1)
        page.search_edit.setText("不存在")
        library.record_run(replace(record, run_id="later", finished_at=3))
        wait_until(qt_application, lambda: len(library.records_view) == 2)
        assert page.selected_key == "run:chosen"
        assert reader.artifact_combo.currentData() == "/tmp/two.html"
        reused = QSignalSpy(reader.reuse_requested)
        reader.reuse_button.click()
        assert reused.count() == 1
        assert reused.at(0)[0] == record
        reused.at(0)[0].parameters["frequency"] = 999
        assert reader.selected_record.parameters == {"frequency": 5}
        assert page.navigation_snapshot().success_event_id is None
        closed = QSignalSpy(page.detail_closed)
        library.record_run(replace(record, run_id="third", finished_at=4))
        wait_until(qt_application, lambda: page.selected_key == "")
        assert closed.count() == 1
        assert not reader.open_button.isEnabled()
    finally:
        page.shutdown()
        page.close()
        assert library.shutdown()


def test_owner_deletion_releases_page_fixed_reader_and_table_controls(qt_application):
    owner = QWidget()
    page = TaskCenterPage(external_details=True, parent=owner)
    reader_host = QWidget(owner)
    page.detail.setParent(reader_host)
    page.present_action_result(_result())
    page.select_entry("action:request")
    owner.show()
    qt_application.processEvents()
    assert page._poll_timer.isActive()
    page.shutdown()
    assert not page._poll_timer.isActive()
    page_destroyed = QSignalSpy(page.destroyed)
    reader_destroyed = QSignalSpy(page.detail.destroyed)
    buttons = (
        page.search_edit,
        page.kind_combo,
        page.table.view,
        page.table.rows["action:request"].cancel,
    )
    owner.close()
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    wait_until(qt_application, lambda: page_destroyed.count() == 1)
    assert reader_destroyed.count() == 1
    assert all(not isValid(button) for button in buttons)
