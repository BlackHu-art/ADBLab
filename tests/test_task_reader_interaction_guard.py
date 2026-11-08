"""共享阅读器只屏蔽失去呈现资格的新动作，后台正文与独立模式保持可用。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets.components.widgets.menu import TextEditMenu
from shiboken6 import isValid

from gui.pages.tasks_page import TaskCenterPage
from gui.run_library import RunLibraryController
from gui.session_tasks import SessionTaskSnapshot
from gui.task_feedback import TaskFeedbackCoordinator
from gui.widgets.action_result_view import ActionResultView
from gui.widgets.run_results import RunResultsWidget
from services.run_library import RunArtifact, RunLibrary, RunRecord
from services.tasks.action_results import ActionItem, ActionResult, ActionSpec
from tests.test_task_drawer_input_isolation import (
    _activate,
    _closing_quarter,
    _start_accessible_press,
)
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def reader_host(qt_application, tmp_path, monkeypatch):
    # 离屏剪贴板首次无 MIME 对象；标准 Fluent 菜单要求有效的剪贴板初始状态。
    QApplication.clipboard().setText("reader-fixture-sentinel")
    path = str(tmp_path / "artifact.txt")
    record = RunRecord("archive", "monkey", "com.example.fixture", 1.0, 2.0,
                       "succeeded", {"seed": 41}, (RunArtifact("合成附件", path),))
    store = RunLibrary(tmp_path / "runs.json")
    store.record_run(record)
    library = RunLibraryController(store)
    opened = []
    monkeypatch.setattr(
        library, "open_artifact", lambda path, folder=False: opened.append((path, folder)),
    )
    host = QWidget()
    host.resize(700, 620)
    page = TaskCenterPage(run_library=library, external_details=True, parent=host)
    page.hide()
    coordinator = TaskFeedbackCoordinator(
        page, host, show_task_center=lambda: None, open_source=lambda _source: None,
        is_task_center=lambda: False, parent=host,
    )
    result = ActionResult("current", ActionSpec("fixture", "apps.packages", "合成查询", "text"),
                          ("fixture-target",), 1.0, state="succeeded", finished_at=2.0,
                          items=(ActionItem("job", "fixture-target", "测试手机", "succeeded",
                                            "完整合成正文", (path,)),))
    page.present_action_result(result)
    host.show()
    wait_until(qt_application, lambda: "run:archive" in page._entries)
    state = SimpleNamespace(host=host, page=page, coordinator=coordinator,
                            result=result, record=record, path=path, opened=opened,
                            library=library)
    yield state
    coordinator.shutdown()
    page.shutdown()
    host.close()
    assert library.shutdown()


def _reader_action(state, action):
    page = state.page
    if action.startswith("run-"):
        assert state.coordinator.open_entry("run:archive")
        reader = page.run_results
        assert reader is not None
        assert reader.artifact_section is not None
        assert reader.parameters_section.toggle_button.isHidden()
        assert reader.parameters_edit.isVisibleTo(state.coordinator.drawer)
        assert reader.artifact_section.toggle_button.isHidden()
        assert reader.artifact_combo.isVisibleTo(state.coordinator.drawer)
        button = {"run-open": reader.open_button, "run-folder": reader.folder_button,
                  "run-reuse": reader.reuse_button}[action]
    else:
        assert state.coordinator.open_request("current")
        reader = page.action_results
        assert reader.detail_toggle.isHidden()
        assert reader.output.isVisibleTo(state.coordinator.drawer)
        assert reader.artifact_section is not None
        assert reader.artifact_section.toggle_button.isHidden()
        assert reader.artifacts.isVisibleTo(state.coordinator.drawer)
        button = {"copy": reader.copy_button, "export": reader.export_button,
                  "open": reader.open_button, "folder": reader.folder_button}[action]
    panel = state.coordinator.drawer
    panel.animation.setCurrentTime(panel.animation.duration())
    assert button.isVisible() and button.isEnabled()
    return reader, button


@pytest.mark.parametrize("method", ["click", "accessible"])
@pytest.mark.parametrize("phase", ["closing", "hidden", "shutdown"])
@pytest.mark.parametrize("action", [
    "copy", "export", "open", "folder", "run-open", "run-folder", "run-reuse",
])
def test_hosted_reader_actions_stop_when_drawer_loses_presentation(
    reader_host, method, phase, action,
):
    state = reader_host
    reader, button = _reader_action(state, action)
    action_exports = QSignalSpy(state.page.action_results.export_requested)
    action_artifacts = QSignalSpy(state.page.action_results.artifact_requested)
    assert state.page.run_results is not None
    reused = QSignalSpy(state.page.run_results.reuse_requested)
    clipboard = QApplication.clipboard()
    clipboard.setText("保留剪贴板")
    panel = state.coordinator.drawer
    _closing_quarter(panel)
    if phase == "hidden":
        panel.animation.setCurrentTime(panel.animation.duration())
        assert panel.isHidden()
    elif phase == "shutdown":
        state.coordinator.shutdown()
    _activate(button, method)
    assert clipboard.text() == "保留剪贴板"
    assert action_exports.count() == 0
    assert action_artifacts.count() == 0
    assert reused.count() == 0
    assert state.opened == []
    assert reader.isEnabled() and button.isEnabled()


def test_closing_reader_continues_background_updates_and_reopen_preserves_identity(reader_host):
    state = reader_host
    reader, _button = _reader_action(state, "copy")
    _closing_quarter(state.coordinator.drawer)
    state.page.present_action_result(replace(state.result, items=(
        replace(state.result.items[0], detail="后台更新后的完整正文"),
    )))
    assert reader.records_snapshot()[0].items[0].detail == "后台更新后的完整正文"
    assert state.page.selected_key == "action:current"
    assert state.page.action_results is reader
    assert state.coordinator.open_request("current")
    reader.copy_button.click()
    assert QApplication.clipboard().text() == "后台更新后的完整正文"


def test_independent_readers_keep_default_actions_without_host_guard(reader_host):
    state = reader_host
    action = ActionResultView()
    run = RunResultsWidget(state.library, detail_only=True)
    try:
        action.present(state.result)
        action.detail_toggle.setChecked(True)
        action.copy_button.click()
        assert QApplication.clipboard().text() == "完整合成正文"
        exports = QSignalSpy(action.export_requested)
        action.export_button.click()
        assert exports.count() == 1
        assert exports.at(0) == ["current", "完整合成正文"]
        run.present_record(state.record)
        reused = QSignalSpy(run.reuse_requested)
        run.reuse_button.click()
        assert reused.count() == 1
        assert reused.at(0)[0] == state.record
    finally:
        action.close()
        run.close()


@pytest.mark.parametrize("action", ["export", "run-reuse"])
@pytest.mark.parametrize("start_open", [False, True, None],
                         ids=["press-closing", "close-after-press", "same-open"])
def test_delayed_reader_activation_cannot_follow_reopen_to_another_identity(
    reader_host, qt_application, action, start_open,
):
    state = reader_host
    reader, button = _reader_action(state, action)
    if action == "export":
        state.page.present_action_result(replace(
            state.result, request_id="second", started_at=3.0,
            items=(replace(state.result.items[0], detail="second-body"),),
        ))
        key = "action:second"
        spy = QSignalSpy(reader.export_requested)
    else:
        state.library.record_run(replace(state.record, run_id="second", finished_at=3.0))
        key = "run:second"
        wait_until(qt_application, lambda: key in state.page._entries)
        spy = QSignalSpy(reader.reuse_requested)
    panel = state.coordinator.drawer
    if start_open is not False:
        _start_accessible_press(button)
        if start_open is True:
            _closing_quarter(panel)
    else:
        _closing_quarter(panel)
        _start_accessible_press(button)
    assert state.coordinator.open_entry(key)
    QTest.qWait(160)
    assert spy.count() == 0
    button.click()
    assert spy.count() == 1
    if action == "export":
        assert spy.at(0) == ["second", "second-body"]
    else:
        assert spy.at(0)[0].run_id == "second"


def _request_context_menu(editor):
    viewport = editor.viewport()
    point = QPoint(5, 5)
    QApplication.sendEvent(viewport, QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, point, viewport.mapToGlobal(point),
    ))
    return [menu for menu in editor.findChildren(TextEditMenu)
            if isValid(menu) and menu.isVisible()]


@pytest.mark.parametrize("kind", ["action", "run-summary", "run-parameters"])
@pytest.mark.parametrize("already_open", [False, True])
def test_reader_context_menu_cannot_copy_across_close_and_reopen(reader_host, kind, already_open):
    state = reader_host
    reader, _button = _reader_action(state, "copy" if kind == "action" else "run-reuse")
    if kind == "action":
        editor = reader.output
    else:
        editor = reader.summary_edit if kind == "run-summary" else reader.parameters_edit
        if kind == "run-parameters":
            assert reader.parameters_section.toggle_button.isHidden()
            assert editor.isVisibleTo(state.coordinator.drawer)
    editor.selectAll()
    assert editor.textCursor().hasSelection()
    clipboard = QApplication.clipboard()
    clipboard.setText("keep-context-sentinel")
    menus = _request_context_menu(editor) if already_open else []
    if already_open:
        assert len(menus) == 1
        action = menus[0].copyAct
        assert isValid(action)
        action.trigger()
        assert clipboard.text() == editor.textCursor().selectedText().replace("\u2029", "\n")
        clipboard.setText("keep-context-sentinel")
    _closing_quarter(state.coordinator.drawer)
    if not already_open:
        assert _request_context_menu(editor) == []
    else:
        assert not menus[0].isVisible()
        if isValid(action):
            action.trigger()
        assert clipboard.text() == "keep-context-sentinel"
        assert state.coordinator.open_entry(state.page.selected_key)
        if isValid(action):
            action.trigger()
        assert clipboard.text() == "keep-context-sentinel"
    for menu in menus:
        if isValid(menu):
            menu.close()


@pytest.mark.parametrize("kind", ["action", "run-summary"])
@pytest.mark.parametrize("close_first", [False, True])
def test_old_reader_menu_remains_revoked_after_switching_to_another_task(
    reader_host, qt_application, kind, close_first,
):
    state = reader_host
    reader, _button = _reader_action(state, "copy" if kind == "action" else "run-reuse")
    editor = reader.output if kind == "action" else reader.summary_edit
    editor.selectAll()
    menus = _request_context_menu(editor)
    assert len(menus) == 1
    old_action = menus[0].copyAct
    assert isValid(old_action)
    if close_first:
        _closing_quarter(state.coordinator.drawer)
    if kind == "action":
        state.page.present_action_result(replace(
            state.result, request_id="second", started_at=3.0,
            items=(replace(state.result.items[0], detail="second-body"),),
        ))
        key = "action:second"
    else:
        state.library.record_run(replace(state.record, run_id="second", message="second-body"))
        key = "run:second"
        wait_until(qt_application, lambda: key in state.page._entries)
    assert state.coordinator.open_entry(key)
    clipboard = QApplication.clipboard()
    clipboard.setText("keep-old-menu-sentinel")
    if isValid(old_action):
        old_action.trigger()
    assert clipboard.text() == "keep-old-menu-sentinel"
    assert not menus[0].isVisible()
    editor.selectAll()
    fresh_menus = _request_context_menu(editor)
    assert len(fresh_menus) == 1
    assert isValid(fresh_menus[0].copyAct)
    fresh_menus[0].copyAct.trigger()
    assert "second-body" in clipboard.text()
    for menu in (*menus, *fresh_menus):
        if isValid(menu):
            menu.close()


@pytest.mark.parametrize("kind", ["action", "run-summary", "run-parameters"])
def test_independent_reader_standard_menu_keeps_normal_selection_copy(reader_host, kind):
    state = reader_host
    reader = ActionResultView() if kind == "action" else RunResultsWidget(
        state.library, detail_only=True,
    )
    try:
        if kind == "action":
            reader.present(state.result)
            reader.detail_toggle.setChecked(True)
            reader.detail_reveal.set_expanded(True, animated=False)
            editor = reader.output
        else:
            reader.present_record(state.record)
            editor = reader.summary_edit if kind == "run-summary" else reader.parameters_edit
            if kind == "run-parameters":
                reader.parameters_section.toggle_button.setChecked(True)
                reader.parameters_section.reveal.set_expanded(True, animated=False)
        reader.show()
        editor.selectAll()
        assert editor.textCursor().hasSelection()
        QApplication.clipboard().setText("independent-menu-sentinel")
        menus = _request_context_menu(editor)
        assert len(menus) == 1
        assert isValid(menus[0].copyAct)
        menus[0].copyAct.trigger()
        assert QApplication.clipboard().text() == editor.textCursor().selectedText().replace(
            "\u2029", "\n",
        )
        menus[0].close()
    finally:
        reader.close()


def test_continuous_session_body_menu_uses_the_same_close_boundary(reader_host):
    state = reader_host
    state.page.set_session_snapshots((SessionTaskSnapshot(
        "session-body", "r1", "logcat", "running", True, True, ("测试手机",), "session-body",
    ),))
    assert state.coordinator.open_entry("session:session-body")
    panel = state.coordinator.drawer
    panel.animation.setCurrentTime(panel.animation.duration())
    editor = state.page.operation_output
    editor.selectAll()
    menus = _request_context_menu(editor)
    assert len(menus) == 1
    action = menus[0].copyAct
    assert isValid(action)
    action.trigger()
    assert QApplication.clipboard().text() == "session-body"
    _closing_quarter(panel)
    QApplication.clipboard().setText("session-menu-sentinel")
    assert _request_context_menu(editor) == []
    if isValid(action):
        action.trigger()
    assert QApplication.clipboard().text() == "session-menu-sentinel"


@pytest.mark.parametrize("action", ["export", "run-reuse"])
def test_old_reader_timer_cannot_end_new_physical_activation_before_release(
    reader_host, qt_application, action,
):
    state = reader_host
    reader, button = _reader_action(state, action)
    if action == "export":
        state.page.present_action_result(replace(
            state.result, request_id="second", started_at=3.0,
            items=(replace(state.result.items[0], detail="second-body"),),
        ))
        key = "action:second"
        spy = QSignalSpy(reader.export_requested)
    else:
        state.library.record_run(replace(state.record, run_id="second", finished_at=3.0))
        key = "run:second"
        wait_until(qt_application, lambda: key in state.page._entries)
        spy = QSignalSpy(reader.reuse_requested)
    _start_accessible_press(button)
    _closing_quarter(state.coordinator.drawer)
    assert state.coordinator.open_entry(key)
    QTest.mousePress(button, Qt.MouseButton.LeftButton)
    QTest.qWait(160)
    assert spy.count() == 0
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    assert spy.count() == 1
    if action == "export":
        assert spy.at(0) == ["second", "second-body"]
    else:
        assert spy.at(0)[0].run_id == "second"


@pytest.mark.parametrize("action", ["export", "run-reuse"])
@pytest.mark.parametrize("start_open", [False, True])
@pytest.mark.parametrize("same_identity", [False, True])
def test_new_accessible_reader_action_after_reopen_has_its_own_identity(
    reader_host, qt_application, action, start_open, same_identity,
):
    state = reader_host
    reader, button = _reader_action(state, action)
    if action == "export":
        state.page.present_action_result(replace(
            state.result, request_id="second", started_at=3.0,
            items=(replace(state.result.items[0], detail="second-body"),),
        ))
        key = "action:second"
        spy = QSignalSpy(reader.export_requested)
    else:
        state.library.record_run(replace(state.record, run_id="second", finished_at=3.0))
        key = "run:second"
        wait_until(qt_application, lambda: key in state.page._entries)
        spy = QSignalSpy(reader.reuse_requested)
    if same_identity:
        key = "action:current" if action == "export" else "run:archive"
    if not start_open:
        _closing_quarter(state.coordinator.drawer)
    _start_accessible_press(button)
    if start_open:
        _closing_quarter(state.coordinator.drawer)
    assert state.coordinator.open_entry(key)
    _start_accessible_press(button)
    QTest.qWait(170)
    assert spy.count() == 1
    if action == "export":
        assert spy.at(0) == (["current", "完整合成正文"] if same_identity
                             else ["second", "second-body"])
    else:
        assert spy.at(0)[0].run_id == ("archive" if same_identity else "second")


@pytest.mark.parametrize("action", ["export", "run-reuse"])
def test_new_accessible_reader_action_after_direct_hide_show_is_fresh(reader_host, action):
    state = reader_host
    reader, button = _reader_action(state, action)
    spy = QSignalSpy(reader.export_requested if action == "export" else reader.reuse_requested)
    panel = state.coordinator.drawer
    panel.hide()
    assert panel.opened and not panel.accepts_user_actions()
    _start_accessible_press(button)
    panel.show()
    assert panel.opened and panel.accepts_user_actions()
    _start_accessible_press(button)
    QTest.qWait(170)
    assert spy.count() == 1
    if action == "export":
        assert spy.at(0) == ["current", "完整合成正文"]
    else:
        assert spy.at(0)[0].run_id == "archive"
