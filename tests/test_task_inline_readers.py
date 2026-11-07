"""任务表的内嵌阅读器保留阅读目标，归档刷新不替用户展开其他记录。"""

from dataclasses import replace

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QSignalSpy

from gui.run_library import RunLibraryController
from gui.widgets.action_result_view import ActionResultView
from gui.widgets.run_results import RunResultsWidget
from services.run_library import RunArtifact, RunLibrary, RunRecord
from services.tasks.action_results import ActionItem, ActionResult, ActionSpec
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def _action(identifier, *, state="succeeded", detail="reading-marker"):
    return ActionResult(
        identifier, ActionSpec("query", "system.shell", "查询", "text"), (), 1, state,
        items=(ActionItem(f"{identifier}-job", "", "本机", state, detail),), finished_at=2,
    )


def _run(identifier="chosen", **changes):
    return replace(RunRecord(
        identifier, "monkey", "com.example.app", 1, 61, "succeeded",
        {"seed": 41, "nested": {"events": 100}},
        artifacts=(RunArtifact("附件一", "/tmp/one.txt"), RunArtifact("附件二", "/tmp/two.txt")),
        message="完整测试说明",
    ), **changes)


def test_inline_actions_keep_reader_selection_and_do_not_reveal_new_results(qt_application):
    view = ActionResultView(inline=True)
    revealed = QSignalSpy(view.reveal_requested)
    first = _action("first")
    view.present(first)
    view.detail_toggle.setChecked(True)
    view.search.setText("reading-marker")
    view._find()
    view.present(_action("later", state="failed", detail="later failure"))

    assert view._selected == "first"
    assert view.output.textCursor().selectedText() == "reading-marker"
    assert [result.request_id for result in view.records_snapshot()] == ["first", "later"]
    assert view.history.isHidden()
    assert view.summary.isHidden()
    assert not view.targets.isHidden()
    assert revealed.count() == 0


def test_inline_action_output_only_expands_when_requested(qt_application):
    view = ActionResultView(inline=True)
    view.present(_action("text"))
    assert not view.detail_toggle.isChecked()
    view.present(replace(_action("text"), state="failed"))
    assert not view.detail_toggle.isChecked()
    view.detail_toggle.click()
    assert view.detail_toggle.isChecked()


def test_inline_action_attachments_expand_separately_from_output(qt_application):
    view = ActionResultView(inline=True)
    result = _action("files")
    result = replace(result, items=(replace(result.items[0], artifacts=("/tmp/demo.txt",)),))
    view.present(result)
    assert not view.artifact_section.isHidden()
    assert not view.artifact_section.toggle_button.isChecked()
    assert not view.detail_toggle.isChecked()
    view.artifact_section.toggle_button.click()
    assert view.artifact_section.toggle_button.isChecked()
    assert not view.detail_toggle.isChecked()


def test_inline_request_selection_emits_only_for_valid_changed_request(qt_application):
    view = ActionResultView(inline=True)
    view.present(_action("first"))
    view.present(_action("second", detail="second result"))
    selected = QSignalSpy(view.selection_changed)

    assert not view.select_request("missing")
    assert view.select_request("first")
    assert selected.count() == 0
    assert view.select_request("second")
    assert selected.count() == 1
    assert selected.at(0) == ["second"]
    assert view.output.toPlainText() == "second result"
    assert view.select_request("second")
    assert selected.count() == 1


@pytest.fixture
def make_inline_run_reader(qt_application, tmp_path):
    owned = []

    def create(records=(), *, capacity=200):
        source = RunLibrary(tmp_path / f"runs-{len(owned)}.json", capacity=capacity)
        for record in records:
            source.record_run(record)
        controller = RunLibraryController(source)
        view = RunResultsWidget(controller, detail_only=True)
        owned.append((view, controller))
        wait_until(qt_application, lambda: len(controller.records) == len(records))
        return view, controller

    yield create
    for view, controller in owned:
        view.close()
        assert controller.shutdown()


def test_inline_runs_wait_for_explicit_record_and_reuse_isolated_snapshot(make_inline_run_reader):
    record = _run()
    view, controller = make_inline_run_reader((record,))
    assert view.selected_record is None
    assert view.details.isHidden()
    for widget in (view.filters, view.count_label, view.empty_label, view.table):
        assert widget.isHidden()

    view.present_record(record)
    assert not view.artifact_section.toggle_button.isChecked()
    assert not view.details.isHidden()
    assert "完整测试说明" in view.summary_edit.toPlainText()
    assert '"seed": 41' in view.parameters_edit.toPlainText()
    reused = QSignalSpy(view.reuse_requested)
    view.reuse_button.click()
    assert reused.at(0)[0] == record
    reused.at(0)[0].parameters["nested"]["events"] = 1
    assert view.selected_record.parameters["nested"]["events"] == 100
    assert controller.records[0].parameters["nested"]["events"] == 100

    view.present_record(None)
    assert view.selected_record is None
    assert view.details.isHidden()
    assert not view.reuse_button.isEnabled()
    assert not view.open_button.isEnabled()
    assert not view.folder_button.isEnabled()


def test_inline_run_library_refresh_preserves_reading_and_selected_artifact(
    make_inline_run_reader, qt_application,
):
    record = _run()
    view, controller = make_inline_run_reader((record,))
    view.present_record(record)
    view.artifact_combo.setCurrentIndex(1)
    cursor = view.summary_edit.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(7, QTextCursor.MoveMode.KeepAnchor)
    view.summary_edit.setTextCursor(cursor)
    selected = cursor.selectedText()
    controller.record_run(_run("later", finished_at=100))
    wait_until(qt_application, lambda: len(controller.records) == 2)

    assert view.selected_record.run_id == "chosen"
    assert view.summary_edit.textCursor().selectedText() == selected
    assert view.artifact_combo.currentData() == "/tmp/two.txt"
    controller.record_run(replace(record, message="更新后的测试说明"))
    wait_until(qt_application, lambda: "更新后的测试说明" in view.summary_edit.toPlainText())
    assert view.selected_record.run_id == "chosen"
    assert view.artifact_combo.currentData() == "/tmp/two.txt"


def test_inline_run_eviction_clears_reader_without_selecting_another_record(
    make_inline_run_reader, qt_application,
):
    record = _run()
    view, controller = make_inline_run_reader((record,), capacity=1)
    view.present_record(record)
    controller.record_run(_run("newer", finished_at=100))
    wait_until(qt_application, lambda: controller.records[0].run_id == "newer")
    assert view.selected_record is None
    assert view.details.isHidden()
    assert not view.reuse_button.isEnabled()
