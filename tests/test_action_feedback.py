"""验证全部入口的共享任务抽屉、导航反馈与专用业务结果阅读。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt, QThread
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import SearchLineEdit

from controllers.action_catalog import ACTION_SIGNALS
from controllers.signals import ADBControllerSignals
from gui.widgets.action_result_view import ActionResultView
from services.tasks.action_results import (
    ActionEnvelope,
    ActionResults,
    ActionSpec,
    capture_action_job,
)
from tests.test_logging_contract import create_log_service  # noqa: F401  复用隔离单例的 fixture。
from tests.test_main_window_layout import build_main_frame

pytestmark = pytest.mark.ui


@pytest.fixture
def result_frame(qt_application, monkeypatch):
    # 启动零延迟回调在构造后才解析此方法，替身须覆盖整个窗口存活期。
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", Mock(),
    )
    controller = Mock()
    controller.signals = ADBControllerSignals()
    controller.action_results = ActionResults(controller.signals.action_result_changed.emit)
    frame = build_main_frame(controller=controller)
    frame.show()
    qt_application.processEvents()
    yield frame
    controller.action_results.close()
    frame._unbind_window_screen()
    frame._close_ready = True
    frame.close()


def _assert_drawer_request(frame, result):
    """共享阅读器必须呈现原请求，不能只让核心存储通过断言。"""
    page = frame._task_page
    drawer = frame._task_feedback.drawer
    key = f"action:{result.request_id}"
    assert drawer.opened
    assert drawer.selected_key == key
    assert page.selected_key == key
    assert page.action_results._selected == result.request_id
    assert drawer.isAncestorOf(page.detail)
    assert page.action_results.isVisibleTo(frame)
    assert page.detail_source(key) == result.spec.section
    assert drawer.target_label.text() == page.detail_row(key).target
    return page.action_results


def _drawer_output(frame, result):
    view = _assert_drawer_request(frame, result)
    view.detail_toggle.setChecked(True)
    assert view.output.isVisibleTo(frame)
    return view.output.toPlainText()


@pytest.fixture
def apk_actions(result_frame, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from controllers._app import ADBAppMixin
    from controllers._base import _ADBControllerBase
    from services.apps.apk_selection import ApkFilePicker

    frame = result_frame
    controller = frame.adb_controller
    controller.apk_picker = Mock(spec=ApkFilePicker)
    controller.apk_picker.select_one.return_value = None
    controller.apk_picker.select_many.return_value = ()
    controller._shutting_down = False
    controller._accepts_apk_selection = (
        _ADBControllerBase._accepts_apk_selection.__get__(controller)
    )
    controller._require_devices = _ADBControllerBase._require_devices.__get__(controller)
    controller._emit_operation = _ADBControllerBase._emit_operation.__get__(controller)
    controller._attempt_actions_preserving_first = (
        _ADBControllerBase._attempt_actions_preserving_first
    )
    operations = QSignalSpy(controller.signals.operation_completed)
    controller.batch_install_apk.side_effect = lambda devices: ADBAppMixin.batch_install_apk(
        controller, devices,
    )
    controller.parse_apk_info.side_effect = lambda: ADBAppMixin.parse_apk_info(controller)
    jobs = []
    submissions = []

    def install(kind, requests):
        submissions.append((kind, requests))
        jobs.extend(capture_action_job("install_apk_async", r.device_id) for r in requests)
        return "fixture-operation"

    controller._start_install_batch.side_effect = install
    controller.app_model.parse_apk_info_async.side_effect = lambda path: jobs.append(
        capture_action_job("parse_apk_info_async", path),
    )
    for method in ("getOpenFileName", "getOpenFileNames"):
        monkeypatch.setattr(
            QFileDialog, method, Mock(side_effect=AssertionError("unexpected dialog")),
        )
    log = Mock()
    monkeypatch.setattr(frame.log_service, "log", log)

    def emit(operation, targets=None):
        if operation == "batch_install":
            frame.left_panel.signals.batch_install_requested.emit(
                targets if targets is not None else ["device-a"],
            )
        else:
            frame.left_panel.signals.parse_apk_info_requested.emit()

    return SimpleNamespace(
        frame=frame, controller=controller, picker=controller.apk_picker,
        store=controller.action_results, jobs=jobs, submissions=submissions, emit=emit, log=log,
        operations=operations,
    )


def test_apk_picker_reentry_keeps_one_request_and_original_targets(apk_actions):
    ctx = apk_actions
    ctx.frame.left_panel.update_device_list(["device-a", "device-b"])
    ctx.frame.left_panel.set_selected_devices(["device-a"])
    original = ["device-a"]
    requests_seen = []

    def select():
        request = ctx.store.recent()[0]
        assert request.state == "running"
        requests_seen.append(request.request_id)
        assert ctx.jobs == []
        assert ctx.submissions == []
        ctx.emit("batch_install", ["device-b"])
        original[:] = ["device-b"]
        ctx.frame.left_panel.set_selected_devices(["device-b"])
        return ("a.apk",)

    ctx.picker.select_many.side_effect = select
    ctx.emit("batch_install", original)
    ctx.picker.select_many.assert_called_once_with()
    assert len(ctx.store.recent()) == 1
    assert ctx.store.recent()[0].targets == ("device-a",)
    assert ctx.frame.left_panel.selected_devices == ["device-b"]
    assert len(ctx.submissions) == 1
    assert [r.device_id for r in ctx.submissions[0][1]] == ["device-a"]
    assert len(ctx.jobs) == 1
    assert ctx.jobs[0].request_id == requests_seen[0]
    assert ctx.jobs[0].target == "device-a"
    assert capture_action_job("probe") is None


def test_apk_parse_picker_reentry_uses_original_signal_scope(apk_actions, tmp_path):
    ctx = apk_actions
    path = tmp_path / "demo.APK"
    path.write_bytes(b"fixture")
    requests_seen = []

    def select():
        request = ctx.store.recent()[0]
        assert request.state == "running"
        requests_seen.append(request.request_id)
        assert ctx.jobs == []
        ctx.emit("parse_apk_info")
        return str(path)

    ctx.picker.select_one.side_effect = select
    ctx.emit("parse_apk_info")
    ctx.picker.select_one.assert_called_once_with()
    ctx.controller.app_model.parse_apk_info_async.assert_called_once_with(str(path))
    assert len(ctx.store.recent()) == 1
    assert len(ctx.jobs) == 1
    assert ctx.jobs[0].request_id == requests_seen[0]
    assert capture_action_job("probe") is None


@pytest.mark.parametrize("operation", ["batch_install", "parse_apk_info"])
@pytest.mark.parametrize("raises", [False, True])
def test_apk_signals_preserve_cancel_and_exception_results(apk_actions, operation, raises):
    ctx = apk_actions
    picker = ctx.picker.select_many if operation == "batch_install" else ctx.picker.select_one
    if raises:
        picker.side_effect = RuntimeError("picker failed")
    ctx.emit(operation)
    results = ctx.store.recent()
    assert len(results) == 1
    assert results[0].state == (
        "failed" if raises or operation == "batch_install" else "cancelled"
    )
    if raises:
        assert "picker failed" in results[0].message
        ctx.log.assert_any_call("ERROR", "Action submission failed: RuntimeError")
    elif operation == "batch_install":
        assert "APK selection canceled" in results[0].message
    else:
        assert ctx.operations.count() == 0
    assert ctx.jobs == []
    assert ctx.submissions == []
    ctx.controller.app_model.parse_apk_info_async.assert_not_called()
    assert capture_action_job("probe") is None


@pytest.mark.parametrize("operation", ["batch_install", "parse_apk_info"])
def test_apk_signal_is_rejected_when_frame_is_closing(apk_actions, operation):
    ctx = apk_actions
    before = ctx.store.recent()
    ctx.frame._closing = True
    ctx.emit(operation)
    ctx.picker.select_one.assert_not_called()
    ctx.picker.select_many.assert_not_called()
    assert ctx.store.recent() == before
    assert ctx.jobs == []
    assert ctx.submissions == []
    ctx.controller.app_model.parse_apk_info_async.assert_not_called()


@pytest.mark.parametrize("operation", ["batch_install", "parse_apk_info"])
def test_apk_picker_empty_return_after_results_close_does_not_revive_request(
    apk_actions, operation,
):
    ctx = apk_actions

    def select():
        ctx.store.close()
        return () if operation == "batch_install" else None

    picker = ctx.picker.select_many if operation == "batch_install" else ctx.picker.select_one
    picker.side_effect = select
    ctx.emit(operation)
    picker.assert_called_once_with()
    assert ctx.store.recent() == ()
    assert ctx.jobs == []
    assert ctx.submissions == []
    ctx.controller.app_model.parse_apk_info_async.assert_not_called()
    assert capture_action_job("probe") is None
    assert not any(call.args[:1] == ("ERROR",) for call in ctx.log.call_args_list)


@pytest.fixture
def diagnostic_frame(request):
    service = request.getfixturevalue("create_log_service")()
    frame = request.getfixturevalue("result_frame")
    assert frame.log_service is service
    return frame


def test_runtime_diagnostic_is_saved_without_exception_summary_or_toast(
    diagnostic_frame, monkeypatch,
):
    frame = diagnostic_frame
    saved, notices = [], []
    monkeypatch.setattr(frame.run_library, "save_diagnostics", saved.append)
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))

    frame.log_service.record_runtime_diagnostic("ADB environment status=ready")

    assert len(saved) == 1
    assert "[INFO] ADB environment status=ready" in saved[0]
    assert frame._settings_page.diagnostics_card.button.isEnabled()
    assert frame._settings_page.diagnostics_card.contentLabel.text() == "本次运行尚无应用异常记录"
    assert notices == []


@pytest.mark.parametrize("level", ["WARNING", "ERROR", "CRITICAL"])
def test_runtime_info_preserves_warning_summary_without_repeating_warning_toast(
    diagnostic_frame, monkeypatch, level,
):
    frame = diagnostic_frame
    saved, notices = [], []
    monkeypatch.setattr(frame.run_library, "save_diagnostics", saved.append)
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    service = frame.log_service

    service.record_runtime_diagnostic("ADB benchmark complete")
    service.log(level, "配置保存失败", flush_immediately=True)
    assert len(notices) == 1
    assert notices[-1]["level"] == "warning"
    summary = frame._settings_page.diagnostics_card.contentLabel.text()
    assert "1 条异常摘要" in summary
    assert "配置保存失败" in summary

    service.record_runtime_diagnostic("ADB recovery devices fast=True")
    assert frame._settings_page.diagnostics_card.contentLabel.text() == summary
    assert len(notices) == 1
    assert "[INFO] ADB recovery devices fast=True" in saved[-1]
    assert f"[{level}] 配置保存失败" in saved[-1]

    service.log("ERROR", "新的保存失败", flush_immediately=True)
    assert len(notices) == 2
    assert "2 条异常摘要" in frame._settings_page.diagnostics_card.contentLabel.text()
    assert "新的保存失败" in frame._settings_page.diagnostics_card.contentLabel.text()


def test_all_declared_actions_record_tasks_in_drawer_without_changing_page(
    result_frame, monkeypatch,
):
    frame = result_frame
    store = frame.adb_controller.action_results
    original_page = frame.stackedWidget.currentWidget()
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    for spec in ACTION_SIGNALS.values():
        frame._task_feedback.drawer.close_drawer(animated=False)
        jobs = []
        frame._action_feedback.dispatch(
            spec,
            lambda devices: jobs.extend(
                capture_action_job("query_async", device) for device in devices
            ),
            (["synthetic-a", "synthetic-b"],),
        )
        assert len(jobs) == 2, spec
        page = frame._task_page
        view = page.action_results
        key = f"action:{jobs[0].request_id}"
        row = page.table.rows[key]
        assert view._records[jobs[0].request_id].state == "running", spec
        assert row.data.state == "运行中", spec
        store.complete(jobs[0], {"success": False, "error": "设备暂不可用，请重试"})
        assert row.data.state == "运行中", spec
        store.complete(jobs[1], {"success": True, "output": "second target answer"})
        snapshot = store.recent()[0]
        assert snapshot.state == "partial", spec
        assert view._records[snapshot.request_id] is snapshot
        assert row.data.state == "部分成功", spec
        assert row.data.unread, spec
        assert _assert_drawer_request(frame, snapshot) is view
        assert frame._task_feedback.drawer.status_label.text() == "部分成功", spec
        assert "设备暂不可用，请重试" in _drawer_output(frame, snapshot), spec
        view.targets.setCurrentIndex(1)
        assert view.output.toPlainText() == "second target answer", spec
        assert snapshot.targets == ("synthetic-a", "synthetic-b"), spec
        assert frame.stackedWidget.currentWidget() is original_page
    assert notices == []
    assert not hasattr(frame.left_panel._apps_tab, "action_result_views")
    assert not hasattr(frame.left_panel._advanced_tab, "action_result_views")
    assert not hasattr(frame._settings_page, "action_results")

@pytest.mark.parametrize("payload,state", [
    ({"success": True}, "succeeded"),
    ({"success": False, "error": "failed"}, "failed"),
    ({"cancelled": True}, "cancelled"),
])
def test_feedback_compaction_keeps_running_request_quiet_and_terminal_notice_idempotent(
    result_frame, monkeypatch, payload, state,
):
    frame = result_frame
    store = frame.adb_controller.action_results
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    present = frame._task_page.present_action_result
    # 小请求只用于触发去重集合压缩；长请求仍经过真实页面和抽屉阅读器。
    monkeypatch.setattr(frame._task_page, "present_action_result", lambda result: (
        present(result) if result.spec.key == "long" else None
    ))
    open_request = Mock(wraps=frame._task_feedback.open_request)
    monkeypatch.setattr(frame._task_feedback, "open_request", open_request)
    original_page = frame.stackedWidget.currentWidget()

    def start(name):
        return store.run(ActionSpec(name, "system.shell", name), (),
                         lambda: capture_action_job("query_async"))

    long_job = start("long")
    assert not frame._task_feedback.drawer.opened
    for _ in range(161):
        store.complete(start("short"), {"success": True})
    store.progress(long_job, "still running")
    assert not frame._task_feedback.drawer.opened
    snapshot = next(result for result in store.recent()
                    if result.request_id == long_job.request_id)
    assert snapshot.state == "running"
    assert frame._task_page.detail_row(f"action:{long_job.request_id}") is not None
    frame._action_feedback.open_task(long_job.request_id)
    _assert_drawer_request(frame, snapshot)
    assert frame._task_page.selected_key == f"action:{long_job.request_id}"
    frame._task_feedback.drawer.close_drawer(animated=False)
    store.complete(long_job, payload)
    snapshot = next(result for result in store.recent()
                    if result.request_id == long_job.request_id)
    calls_after_terminal = open_request.call_count
    frame._action_feedback.present(snapshot)
    assert open_request.call_count == calls_after_terminal
    assert not frame._task_feedback.drawer.opened
    assert snapshot.state == state
    row = frame._task_page.detail_row(f"action:{snapshot.request_id}")
    assert row.unread == (state == "failed")
    frame._action_feedback.open_task(snapshot.request_id)
    _assert_drawer_request(frame, snapshot)
    assert frame._task_page.navigation_snapshot().unread_count == 0
    assert frame.stackedWidget.currentWidget() is original_page
    assert notices == []


@pytest.mark.parametrize("succeeded", [True, False])
def test_slow_screenshot_stays_quiet_until_failure_and_success_updates_media(
    result_frame, qt_application, tmp_path, succeeded,
):
    from PySide6.QtGui import QImage

    frame = result_frame
    original_page = frame.stackedWidget.currentWidget()
    path = tmp_path / "synthetic-screenshot.png"
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(path))
    jobs = []
    frame._action_feedback.dispatch(
        ACTION_SIGNALS["screenshot_requested"],
        lambda devices: jobs.append(capture_action_job("screenshot_async", devices[0])),
        (["synthetic-device"],),
    )
    page = frame._task_page
    key = f"action:{jobs[0].request_id}"
    assert page.navigation_snapshot().active_count == 1
    success_before = page.navigation_snapshot().success_event_id
    QTest.qWait(650)
    assert not frame._task_feedback.drawer.opened
    assert page.selected_key == ""
    assert frame.stackedWidget.currentWidget() is original_page
    if succeeded:
        frame.adb_controller.signals.screenshot_batch_ready.emit([str(path)])
    frame.adb_controller.action_results.complete(jobs[0], {
        "success": succeeded,
        "screenshot_path": str(path) if succeeded else "",
        "error": "" if succeeded else "截图失败",
    })
    result = frame.adb_controller.action_results.recent()[0]
    assert result.request_id == jobs[0].request_id
    assert page.detail_row(key).state == ("成功" if succeeded else "失败")
    assert frame._task_feedback.drawer.opened is (not succeeded)
    assert page.navigation_snapshot().active_count == 0
    assert page.navigation_snapshot().unread_count == int(not succeeded)
    assert (page.navigation_snapshot().success_event_id != success_before) is succeeded
    assert frame.stackedWidget.currentWidget() is original_page
    if succeeded:
        host = frame._workspace_feature_hosts["apps"]
        media = next(p for k, p in zip(host.registry.keys(), host.registry.pages(), strict=True)
                     if k.feature == "media")
        assert media.image_paths == (str(path),)
        assert result.items[0].artifacts == (str(path),)
    frame._action_feedback.open_task(result.request_id)
    _assert_drawer_request(frame, result)
    assert page.navigation_snapshot().unread_count == 0


@pytest.mark.parametrize("history,level,notify,opens,unread", [
    (None, "success", True, False, 0),
    (None, "info", True, False, 0),
    (None, "warning", True, False, 1),
    (None, "error", False, False, 1),
    (None, "error", True, True, 1),
    ("error", "success", True, False, 1),
    ("error", "info", True, False, 1),
    ("error", "warning", True, False, 1),
    ("success", "error", True, True, 1),
])
def test_notice_only_new_notifying_failure_opens_and_preserves_unread(
    result_frame, history, level, notify, opens, unread,
):
    presenter = result_frame._action_feedback
    if history:
        presenter.record_notice("probe", "记录", "旧事件", history)
    presenter.record_notice("probe", "记录", "当前事件", level, notify=notify)
    result = result_frame.adb_controller.action_results.recent()[0]
    assert len(result.items) == (2 if history else 1)
    assert result.items[-1].detail == "当前事件"
    assert result_frame._task_feedback.drawer.opened is opens
    assert result_frame._task_page.navigation_snapshot().unread_count == unread
    presenter.open_task(result.request_id)
    _assert_drawer_request(result_frame, result)
    assert result_frame._task_page.navigation_snapshot().unread_count == 0


def test_result_view_retains_recent_completions_when_wall_clock_ties(qt_application, monkeypatch):
    monkeypatch.setattr("services.tasks.action_results.time.time", lambda: 1.0)
    view = ActionResultView()
    view.TEXT_BUDGET = 4500
    store = ActionResults(view.present)

    def start(name):
        return store.run(ActionSpec(name, "system.shell", name), (),
                         lambda: capture_action_job("query_async"))

    def finish(job):
        store.complete(job, {"success": True, "output": "x" * 2000})

    try:
        long_job = start("long")
        finish(start("first"))
        finish(start("second"))
        finish(long_job)
        finish(start("last"))
        assert view.select_request(long_job.request_id)
        assert view._detail == "x" * 2000
    finally:
        view.close()


def test_late_older_result_does_not_steal_new_request_or_device_selection(qt_application):
    view = ActionResultView()
    jobs = []
    store = ActionResults(view.present)
    try:
        for key in ("old", "new"):
            store.run(
                ActionSpec(key, "apps.diagnostics", key, "text"),
                ("demo",),
                lambda: jobs.append(capture_action_job("query_async", "demo")),
            )
        selected = view._selected
        store.complete(jobs[1], {"success": True, "output": "new answer"})
        store.complete(jobs[0], {"success": True, "output": "late old answer"})
        assert view._selected == selected
        assert view.output.toPlainText() == "new answer"
        view.history.setCurrentIndex(view.history.findData(jobs[0].request_id))
        assert view.output.toPlainText() == "late old answer"
    finally:
        view.close()


def test_long_text_copy_export_search_and_artifacts_keep_complete_payload(qt_application, tmp_path):
    view = ActionResultView()
    store = ActionResults(view.present)
    jobs = []
    raw = "first line\n" + "正文" * 50000 + "\nlast line"
    path = str(tmp_path / "report.zip")
    try:
        store.run(
            ActionSpec("report", "apps.reports", "报告", "text"),
            ("demo",),
            lambda: jobs.append(capture_action_job("report_async", "demo")),
        )
        store.complete(jobs[0], {"success": True, "output": raw, "bugreport_path": path})
        assert len(view.output.toPlainText()) == 64000
        view.copy_button.click()
        assert QApplication.clipboard().text() == raw
        export = QSignalSpy(view.export_requested)
        view.export_button.click()
        assert export.count() == 1
        assert export.at(0)[1] == raw
        opened = QSignalSpy(view.artifact_requested)
        view.open_button.click()
        view.folder_button.click()
        assert opened.count() == 2
        assert opened.at(0) == [path, False]
        assert opened.at(1) == [path, True]
        view.search.setText("first line")
        view._find()
        assert view.output.textCursor().selectedText() == "first line"
        view.search.setText("last line")
        view._find()
        assert view.output.textCursor().selectedText() == "last line"
        assert len(view.output.toPlainText()) < 64000
        assert view._detail == raw
    finally:
        view.close()


@pytest.mark.parametrize("query", ["result", " "])
def test_result_search_button_and_enter_find_once_and_clear_preserves_output(qt_application, query):
    """正文搜索每次点击或回车只前进一处，清空搜索不清除操作结果。"""
    view = ActionResultView()
    store = ActionResults(view.present)
    jobs = []
    raw = "alpha result\nbeta result\ngamma result"
    try:
        store.run(
            ActionSpec("report", "apps.reports", "报告", "text"),
            ("demo",),
            lambda: jobs.append(capture_action_job("report_async", "demo")),
        )
        store.complete(jobs[0], {"success": True, "output": raw})
        view.resize(640, 600)
        qt_application.processEvents()
        assert isinstance(view.search, SearchLineEdit)
        assert view.search.isVisible()
        view.search.setFocus()
        QTest.keyClicks(view.search, query)
        assert not view.output.textCursor().hasSelection()
        QTest.mouseClick(view.search.searchButton, Qt.MouseButton.LeftButton)
        assert view.output.textCursor().selectionStart() == raw.index(query)
        QTest.keyClick(view.search, Qt.Key.Key_Return)
        assert view.output.textCursor().selectionStart() == raw.index(query, 12)
        QTest.keyClick(view.search, Qt.Key.Key_Return)
        assert view.output.textCursor().selectionStart() == raw.rindex(query)
        QTest.mouseClick(view.search.searchButton, Qt.MouseButton.LeftButton)
        assert view.output.textCursor().selectionStart() == raw.index(query)
        assert view.search.clearButton.isVisible()
        QTest.mouseClick(view.search.clearButton, Qt.MouseButton.LeftButton)
        assert view.search.text() == ""
        assert view.output.toPlainText() == raw
        assert view._detail == raw
    finally:
        store.close()
        view.close()


def test_failure_before_submission_is_visible_and_repeated_jobs_are_ignored(qt_application):
    view = ActionResultView()
    store = ActionResults(view.present)
    try:

        def fail():
            raise ValueError("请检查输入参数")

        with pytest.raises(ValueError):
            store.run(ActionSpec("bad", "system.shell", "Shell"), (), fail)
        assert "失败" in view.summary.text()
        assert view.detail_toggle.isChecked()
        assert "请检查输入参数" in view.output.toPlainText()
    finally:
        view.close()


def test_background_progress_is_received_on_gui_thread(qt_application):
    from models.adb_model import ADBModelCore, async_command
    from tests.ui_geometry_helpers import wait_until

    class Model(ADBModelCore):
        @async_command
        def query_async(self, target, callback=None):
            callback("正在生成报告")
            return {"success": True}

    model = Model()
    threads, progress, original = [], [], []
    model.action_progress.connect(
        lambda job, text: (threads.append(QThread.currentThread()), progress.append((job, text)))
    )
    store = ActionResults(lambda value: None)
    store.run(
        ActionSpec("query", "apps.reports", "报告"),
        ("demo",),
        lambda: model.query_async("demo", callback=original.append),
    )
    wait_until(qt_application, lambda: len(progress) == 1)
    assert threads == [qt_application.thread()]
    assert progress[0][0].target == "demo"
    assert progress[0][1] == "正在生成报告"
    assert original == ["正在生成报告"]
    model.thread_pool.waitForDone(1000)


def test_bounded_history_preserves_all_inflight_results(qt_application):
    view = ActionResultView()
    store = ActionResults(view.present, capacity=2)
    jobs = []
    try:
        store.run(
            ActionSpec("active", "system.shell", "仍在执行"),
            (),
            lambda: jobs.append(capture_action_job("query_async")),
        )
        for index in range(25):
            store.run(ActionSpec(str(index), "system.shell", "查询"), (), lambda: None)
        assert jobs[0].request_id in view._records
        assert len(store.recent()) == 3
        assert sum(item.state != "running" for item in view._records.values()) <= 20
        store.complete(jobs[0], {"success": True, "output": "late answer"})
        assert view._records[jobs[0].request_id].state == "succeeded"
    finally:
        view.close()


def test_result_view_byte_budget_preserves_selected_text_and_inflight(qt_application):
    view = ActionResultView()
    view.TEXT_BUDGET = 2048
    store = ActionResults(view.present)
    jobs = []
    raw = "完整正文" * 2000 + "end-marker"
    try:
        for key in ("background", "pending", "selected"):
            store.run(
                ActionSpec(key, "system.shell", "查询", "text"), (),
                lambda: jobs.append(capture_action_job("query_async")),
            )
        store.complete(jobs[2], {"success": True, "output": raw})
        assert view.select_request(jobs[2].request_id)
        store.complete(jobs[0], {"success": True, "output": "其他结果" * 2000})
        assert jobs[0].request_id not in view._records
        assert jobs[1].request_id in view._records
        assert view._selected == jobs[2].request_id
        view.copy_button.click()
        assert QApplication.clipboard().text() == raw
        exported = QSignalSpy(view.export_requested)
        view.export_button.click()
        assert exported.count() == 1
        assert exported.at(0)[1] == raw
        view.search.setText("end-marker")
        view._find()
        assert view.output.textCursor().selectedText() == "end-marker"
    finally:
        store.close()
        view.close()


def test_diagnostic_history_receives_old_terminal_without_reviving_running_records(
    qt_application, monkeypatch,
):
    from itertools import count

    ticks = count(1.0)
    monkeypatch.setattr("services.tasks.action_results.time.time", lambda: next(ticks))
    view = ActionResultView(diagnostic=True)
    store = ActionResults(view.present)
    try:
        for index in range(25):
            jobs = []
            store.run(
                ActionSpec(f"old-{index}", "apps.diagnostics", "较早查询", "text"), (),
                lambda: jobs.extend(capture_action_job("query_async") for _ in range(2)),
            )
            store.complete(jobs[0], {"success": True, "output": "较早的部分结果"})
            store.run(
                ActionSpec(f"new-{index}", "apps.diagnostics", "较新查询", "text"), (),
                lambda: jobs.append(capture_action_job("query_async")),
            )
            store.complete(jobs[2], {"success": True, "output": "最新可见结果"})
            store.complete(jobs[1], {"success": True, "output": "旧请求的晚到结果"})
            assert view._detail == "最新可见结果"
        assert not view.running_results()
        assert len(view._records) <= 20
    finally:
        store.close()
        view.close()


def test_settings_adb_restart_opens_exact_drawer_without_navigation(result_frame, monkeypatch):
    frame = result_frame
    frame._on_nav_requested("settings")
    jobs, notices = [], []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append((a, kw)))
    frame._action_feedback.dispatch(
        ACTION_SIGNALS["restart_adb_requested"],
        lambda: jobs.append(capture_action_job("restart_adb_async")),
        (),
    )
    store = frame.adb_controller.action_results
    store.complete(jobs[0], {"success": False, "error": "请重新检测 ADB 环境"})
    result = store.recent()[0]
    assert result.spec.section == "settings.maintenance"
    assert notices == []
    assert frame._task_feedback.drawer.source_label.text() == "设置"
    assert frame._task_feedback.drawer.status_label.text() == "失败"
    assert frame._task_page.navigation_snapshot().unread_count == 1
    assert "请重新检测 ADB 环境" in _drawer_output(frame, result)
    assert frame.stackedWidget.currentWidget() is frame._settings_page
    frame._action_feedback.open_task(result.request_id)
    _assert_drawer_request(frame, result)
    assert frame._task_page.navigation_snapshot().unread_count == 0
    assert frame.stackedWidget.currentWidget() is frame._settings_page


@pytest.fixture
def restart_actions(result_frame, monkeypatch):
    from controllers._base import _ADBControllerBase
    from controllers._device import ADBDeviceMixin

    frame = result_frame
    frame._on_nav_requested("settings")
    controller = frame.adb_controller
    controller._shutting_down = False
    for name in ("_emit_operation", "_handle_async_response", "_complete_action_envelope"):
        setattr(controller, name, getattr(_ADBControllerBase, name).__get__(controller))
    controller._attempt_actions_preserving_first = (
        _ADBControllerBase._attempt_actions_preserving_first
    )
    controller._process_restart_adb_result = (
        ADBDeviceMixin._process_restart_adb_result.__get__(controller)
    )
    controller._handler_map = {"restart_adb": controller._process_restart_adb_result}
    controller.restart_adb.side_effect = lambda: ADBDeviceMixin.restart_adb(controller)
    jobs = []
    controller.device_model = SimpleNamespace(restart_adb_async=Mock(
        side_effect=lambda: jobs.append(capture_action_job("restart_adb_async")),
    ))
    timer = Mock()
    notify = Mock()
    log = Mock()
    monkeypatch.setattr("controllers._device.QTimer", SimpleNamespace(singleShot=timer))
    monkeypatch.setattr(frame, "note_adb_server_restarted", notify)
    monkeypatch.setattr(frame.log_service, "log", log)
    monkeypatch.setattr("gui.action_feedback.show_toast", Mock())
    return SimpleNamespace(
        frame=frame, controller=controller, store=controller.action_results, jobs=jobs,
        emit=frame.left_panel.signals.restart_adb_requested.emit,
        timer=timer, notify=notify, log=log,
    )


@pytest.mark.parametrize("success", [False, True])
def test_restart_signal_keeps_action_scope_and_reentry_guard(restart_actions, monkeypatch, success):
    ctx = restart_actions
    requests_seen = []

    def invalidate(reason):
        assert reason == "server_restart"
        pending = ctx.store.recent()[0]
        assert pending.state == "running"
        assert pending.spec.section == "settings.maintenance"
        requests_seen.append(pending.request_id)
        assert ctx.jobs == []
        ctx.emit()

    hook = Mock(side_effect=invalidate)
    monkeypatch.setattr(ctx.frame, "invalidate_wireless_pairing", hook)
    ctx.emit()
    hook.assert_called_once_with("server_restart")
    ctx.controller.device_model.restart_adb_async.assert_called_once_with()
    assert len(ctx.jobs) == 1 and ctx.jobs[0] is not None
    assert ctx.jobs[0].request_id == requests_seen[0]
    assert len(ctx.store.recent()) == 1
    assert ctx.store.recent()[0].state == "running"
    assert capture_action_job("probe") is None
    ctx.controller._handle_async_response("restart_adb_async", ActionEnvelope(
        {"success": success, "raw_output": "synthetic result", "error": "synthetic failure"},
        ctx.jobs[0],
    ))
    result = ctx.store.recent()[0]
    assert result.request_id == requests_seen[0]
    assert result.state == ("succeeded" if success else "failed")
    assert len(result.items) == 1
    assert result.items[0].job_id == ctx.jobs[0].job_id
    if success:
        ctx.notify.assert_called_once_with()
        ctx.timer.assert_called_once_with(
            3000, ctx.controller.signals, ctx.controller._refresh_devices_background,
        )
    else:
        ctx.notify.assert_not_called()
        ctx.timer.assert_not_called()
    assert capture_action_job("probe") is None


@pytest.mark.parametrize("failure", ["closing", "hook"])
def test_restart_signal_rejects_closing_and_reports_hook_exceptions(
    restart_actions, monkeypatch, failure,
):
    ctx = restart_actions
    hook = Mock(side_effect=RuntimeError("synthetic invalidation failed"))
    monkeypatch.setattr(ctx.frame, "invalidate_wireless_pairing", hook)
    ctx.frame._closing = failure == "closing"
    try:
        ctx.emit()
    finally:
        ctx.frame._closing = False
    if failure == "closing":
        hook.assert_not_called()
        assert ctx.store.recent() == ()
    else:
        hook.assert_called_once_with("server_restart")
        assert len(ctx.store.recent()) == 1
        assert ctx.store.recent()[0].state == "failed"
        ctx.log.assert_any_call("ERROR", "Action submission failed: RuntimeError")
    ctx.controller.device_model.restart_adb_async.assert_not_called()
    assert ctx.jobs == []
    ctx.notify.assert_not_called()
    ctx.timer.assert_not_called()
    assert capture_action_job("probe") is None


def test_task_center_exposes_running_plain_commands_without_native_operation(
    result_frame, qt_application,
):
    from tests.ui_geometry_helpers import wait_for_stable_geometry

    frame = result_frame
    page = frame._task_page
    frame._on_nav_requested("tasks")
    original_page = frame.stackedWidget.currentWidget()
    wait_for_stable_geometry(qt_application, [page, page.table])
    assert page.isVisibleTo(frame)
    page._operation_manager = None
    page.refresh()
    jobs = []
    frame._action_feedback.dispatch(
        ACTION_SIGNALS["capture_bugreport_requested"],
        lambda devices: jobs.append(capture_action_job("bugreport_async", devices[0])),
        (["synthetic-a"],),
    )
    key = f"action:{jobs[0].request_id}"
    row = page.table.rows[key]
    wait_for_stable_geometry(qt_application, [page.table, row])
    assert row.isVisibleTo(page)
    assert row.data.state == "运行中"
    assert "1 项进行中" in page.count_label.text()
    assert row.cancel.isHidden()
    assert not frame._task_feedback.drawer.opened
    row.title.click()
    result = frame.adb_controller.action_results.recent()[0]
    _assert_drawer_request(frame, result)
    assert page.selected_key == key
    assert frame.stackedWidget.currentWidget() is original_page
    frame.adb_controller.action_results.complete(jobs[0], {"success": False, "error": "生成失败"})
    assert page.table.rows[key] is row
    assert row.data.state == "失败"
    assert "0 项进行中" in page.count_label.text()
    assert "失败" in page.action_results.summary.text()


def test_remote_feedback_records_in_drawer_without_exposing_device_id(result_frame, monkeypatch):
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    original_page = result_frame.stackedWidget.currentWidget()
    remote = result_frame.left_panel._scrcpy_tab
    remote._active_device = "synthetic-a"
    remote._log("ERROR", "synthetic-a: 远程启动失败，请检查连接")
    assert not hasattr(remote._form_controller, "feedback")
    result = result_frame.adb_controller.action_results.recent()[0]
    assert result.spec.section == "remote"
    assert "远程启动失败，请检查连接" in _drawer_output(result_frame, result)
    assert "synthetic-a" not in result.items[-1].detail
    assert result_frame._task_feedback.drawer.status_label.text() == "失败"
    assert result_frame._task_page.navigation_snapshot().unread_count == 1
    assert result_frame.stackedWidget.currentWidget() is original_page
    assert notices == []


def test_drawer_counts_devices_and_task_labels_survive_new_selection(result_frame, monkeypatch):
    frame = result_frame
    frame._on_devices_updated(["demo-a", "demo-b", "demo-c"])
    frame._global_device_bar.set_device_labels({"demo-c": "Phone"})
    notices, jobs = [], []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append((a, kw)))
    frame._action_feedback.dispatch(
        ActionSpec("memory", "apps.diagnostics", "内存", "text"),
        lambda devices: jobs.extend(capture_action_job("query_async", device)
                                    for device in (devices[0], devices[0], devices[1])),
        (["demo-c", "demo-a"],),
    )
    frame._global_device_bar.selection_requested.emit(["demo-b"])
    for job, success in zip(jobs, (True, True, False)):
        frame.adb_controller.action_results.complete(job, {"success": success, "output": "body"})
    result = frame.adb_controller.action_results.recent()[0]
    assert result.items[0].label == "设备 3 · Phone"
    assert result.targets == ("demo-c", "demo-a")
    _assert_drawer_request(frame, result)
    assert frame._task_page.device_summary.isVisibleTo(frame)
    assert "成功 1 台 · 失败 1 台" in frame._task_page.device_summary.text()
    assert "0 台" not in frame._task_page.device_summary.text()
    assert frame._task_feedback.drawer.status_label.text() == "部分成功"
    assert "设备 3 · Phone" in frame._task_feedback.drawer.target_label.text()
    assert frame.left_panel.selected_devices == ["demo-b"]
    assert notices == []
    assert "设备 3 · Phone" in frame.left_panel._apps_tab.diagnostic_results.targets.itemText(0)


@pytest.mark.parametrize("payload,state,summary", [
    ({"success": True}, "succeeded", "成功 2 台"),
    ({"success": False, "error": "adb: transport error"}, "failed", "失败 2 台"),
    ({"success": False, "cancelled": True}, "cancelled", "未完成 2 台"),
])
def test_terminal_drawer_reports_only_relevant_device_counts(
    result_frame, monkeypatch, payload, state, summary,
):
    frame = result_frame
    notices, jobs = [], []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append((a, kw)))
    original_page = frame.stackedWidget.currentWidget()
    success_before = frame._task_page.navigation_snapshot().success_event_id
    frame._action_feedback.dispatch(
        ActionSpec("probe", "system.shell", "查询"),
        lambda devices: jobs.extend(
            capture_action_job("query_async", device) for device in devices
        ),
        (["demo-a", "demo-b"],),
    )
    for job in jobs:
        frame.adb_controller.action_results.complete(job, payload)
    result = frame.adb_controller.action_results.recent()[0]
    assert result.state == state
    assert frame._task_feedback.drawer.opened == (state == "failed")
    snapshot = frame._task_page.navigation_snapshot()
    assert snapshot.active_count == 0
    assert snapshot.unread_count == int(state == "failed")
    assert (snapshot.success_event_id != success_before) == (state == "succeeded")
    frame._action_feedback.open_task(result.request_id)
    _assert_drawer_request(frame, result)
    message = frame._task_page.device_summary.text()
    assert frame._task_page.device_summary.isVisibleTo(frame)
    assert summary in message
    assert "0 台" not in message
    assert "adb: transport error" not in message
    if state == "failed":
        assert "adb: transport error" in _drawer_output(frame, result)
    assert frame.stackedWidget.currentWidget() is original_page
    assert notices == []


def test_dispatch_copies_and_deduplicates_targets_before_handler(result_frame):
    original = ["demo-a", "demo-a", "demo-b", ""]
    seen = []

    def submit(devices):
        original.clear()
        seen.extend(devices)

    result_frame._action_feedback.dispatch(ActionSpec("probe", "system.shell", "查询"),
                                          submit, (original,))
    assert seen == ["demo-a", "demo-b"]
    assert result_frame.adb_controller.action_results.recent()[0].targets == tuple(seen)


@pytest.mark.parametrize("payload,state", [
    ({"success": True, "output": "Status: ok"}, "succeeded"),
    ({"success": False, "error": "Android rejected Intent"}, "failed"),
    ({"success": False, "cancelled": True}, "cancelled"),
])
def test_intent_signal_uses_result_routing_duplicate_guard_and_close_boundary(
    result_frame, monkeypatch, payload, state,
):
    from services.intent_request import IntentRequest

    frame = result_frame
    original_page = frame.stackedWidget.currentWidget()
    jobs = []
    received = []
    notices = []

    def submit(devices, request):
        received.append((devices, request))
        jobs.extend(capture_action_job("start_activity_async", target) for target in devices)

    frame.adb_controller.execute_intent.side_effect = submit
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    signal = frame.left_panel.signals.execute_intent_requested
    request = IntentRequest(action="android.settings.SETTINGS", wait=True)
    targets = ["demo-a", "demo-a", "demo-b"]
    signal.emit(targets, request)
    targets.clear()
    signal.emit(["demo-a"], request)
    assert received == [(["demo-a", "demo-b"], request)]
    assert len(jobs) == 2
    store = frame.adb_controller.action_results
    assert store.recent()[0].spec.section == "system.intent"
    assert store.recent()[0].state == "running"
    pending = store.recent()[0]
    assert pending.targets == ("demo-a", "demo-b")
    assert len(store.recent()) == 1
    assert not frame._task_feedback.drawer.opened
    assert frame._task_page.selected_key == ""
    frame._action_feedback.open_task(pending.request_id)
    _assert_drawer_request(frame, pending)
    assert frame.stackedWidget.currentWidget() is original_page
    for job in jobs:
        store.complete(job, payload)
    assert store.recent()[0].state == state
    assert frame._task_page.action_results._records[jobs[0].request_id].state == state
    _assert_drawer_request(frame, store.recent()[0])
    assert frame._task_page.navigation_snapshot().unread_count == int(state == "failed")
    assert notices == []

    frame._closing = True
    signal.emit(["demo-a"], request)
    assert len(received) == 1


def test_request_level_failure_does_not_claim_all_devices_succeeded(result_frame, monkeypatch):
    from services.tasks.action_results import report_action_message

    store = result_frame.adb_controller.action_results
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **_kw: notices.append(a))

    def submit():
        job = capture_action_job("query_async", "demo-a")
        store.complete(job, {"success": True})
        report_action_message(False, "收尾未完成")

    store.run(ActionSpec("probe", "system.shell", "查询"), ("demo-a",), submit)
    assert store.recent()[0].state == "partial"
    result = store.recent()[0]
    _assert_drawer_request(result_frame, result)
    assert result_frame._task_page.device_summary.isVisibleTo(result_frame)
    assert "成功 1 台" not in result_frame._task_page.device_summary.text()
    assert "部分操作失败" in result_frame._task_page.device_summary.text()
    assert "收尾未完成" in result_frame._task_page.action_results.message_label.text()
    assert result_frame._task_page.navigation_snapshot().unread_count == 1
    assert notices == []


def test_app_manager_records_process_silently_and_notifies_explicit_result(
    result_frame, monkeypatch,
):
    from tests.test_app_manager_selection import _app_manager_page

    _app, page = _app_manager_page()
    page.setParent(result_frame)
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    try:
        page.log("正在读取应用列表")
        assert not notices
        assert not result_frame._task_feedback.drawer.opened
        process = result_frame.adb_controller.action_results.recent()[0]
        assert process.spec.section == "apps.manager"
        assert "正在读取应用列表" in process.items[-1].detail
        page._on_operation_feedback("error", "设备连接已断开，请重试")
        assert not hasattr(page, "log_output")
        result = result_frame.adb_controller.action_results.recent()[0]
        assert result.spec.section == "apps.manager"
        assert result.request_id == process.request_id
        assert "设备连接已断开，请重试" in _drawer_output(result_frame, result)
        assert result_frame._task_feedback.drawer.status_label.text() == "失败"
        assert result_frame._task_page.navigation_snapshot().unread_count == 1
        assert notices == []
    finally:
        page.close()


def test_diagnostic_reader_keeps_latest_query_body_and_task_center_keeps_history(result_frame):
    frame = result_frame
    store = frame.adb_controller.action_results
    jobs = []
    for key in ("old-query", "new-query"):
        store.run(
            ActionSpec(key, "apps.diagnostics", key, "text"), ("demo",),
            lambda: jobs.append(capture_action_job("query_async", "demo")),
        )
    view = frame._action_feedback._diagnostics
    assert view.isHidden()
    store.complete(jobs[1], {"success": True, "output": "latest CPU answer"})
    store.complete(jobs[0], {"success": True, "output": "late memory answer"})
    assert view.output.toPlainText() == "latest CPU answer"
    assert view.history.isHidden() and view.detail_toggle.isHidden()
    assert not view.detail_host.isHidden()
    assert jobs[0].request_id in frame._task_page.action_results._records


def test_reports_show_only_generated_files_without_steps_or_empty_cleanup_result(result_frame):
    frame = result_frame
    store = frame.adb_controller.action_results
    view = frame._action_feedback._reports
    jobs = []
    for key in ("clean", "report"):
        store.run(
            ActionSpec(key, "apps.reports", key), ("demo",),
            lambda: jobs.append(capture_action_job("query_async", "demo")),
        )
    store.complete(jobs[0], {"success": True})
    assert view.isHidden()
    store.complete(jobs[1], {"success": True, "bugreport_path": "C:/sample/report.zip"})
    assert not view.isHidden()
    assert view.files.count() == 1
    view.present(store.recent()[0])
    assert view.files.count() == 1
    opened = QSignalSpy(view.artifact_requested)
    view.open_button.click()
    view.folder_button.click()
    assert opened.count() == 2
    assert opened.at(0) == ["C:/sample/report.zip", False]
    assert opened.at(1) == ["C:/sample/report.zip", True]

    store.run(
        ActionSpec("new-report", "apps.reports", "新报告"), ("demo",),
        lambda: jobs.append(capture_action_job("query_async", "demo")),
    )
    store.complete(jobs[-1], {"success": True, "bugreport_path": "C:/sample/new-report.zip"})
    assert view.files.currentData() == "C:/sample/new-report.zip"


def test_task_notes_keep_order_and_severity_without_pretending_to_complete(result_frame):
    presenter = result_frame._action_feedback
    presenter.record_notice("probe", "记录", "第一条", "info")
    presenter.record_notice("probe", "记录", "第二条", "error")
    result = result_frame.adb_controller.action_results.recent()[0]
    assert result_frame._task_page.select_request(result.request_id)
    view = result_frame._task_page.action_results
    view.detail_toggle.click()
    assert "[记录] 第一条" in view.output.toPlainText()
    assert "[失败] 第二条" in view.output.toPlainText()
    assert view.targets.isHidden()
    assert not view.running_results()


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("handler", ["_on_transfer_done", "_on_file_op_done"])
def test_file_result_records_task_notifies_and_refreshes_only_remote_changes(
    result_frame, monkeypatch, failed, handler,
):
    from gui.dialogs.file_explorer import FileExplorerPage

    page = FileExplorerPage(device_ip="synthetic-file-device", parent=result_frame)
    page._refresh = Mock()
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    try:
        getattr(page._ops_controller, handler)("Permission denied", failed, "文件已传输")
        result = result_frame.adb_controller.action_results.recent()[0]
        assert result.spec.section == "devices.files"
        assert result.items[-1].state == ("failed" if failed else "succeeded")
        assert result_frame._task_feedback.drawer.opened is failed
        if not failed:
            result_frame._action_feedback.open_task(result.request_id)
        assert ("Permission denied" if failed else "文件已传输") in _drawer_output(
            result_frame, result,
        )
        assert result_frame._task_feedback.drawer.status_label.text() == (
            "失败" if failed else "记录"
        )
        assert result_frame._task_page.navigation_snapshot().unread_count == int(failed)
        assert notices == []
        assert page._refresh.call_count == int(handler == "_on_file_op_done" and not failed)
    finally:
        page.close()


@pytest.mark.parametrize("succeeded", [True, False])
def test_app_manager_worker_feedback_reaches_page_before_worker_cleanup(
    result_frame, qt_application, monkeypatch, succeeded,
):
    from gui.dialogs.app_manager import AppManagerPage
    from models.app_manager_worker import AppManagerWorker
    from tests.ui_geometry_helpers import wait_until

    page = AppManagerPage(device_ip="synthetic-app-device", parent=result_frame)
    worker = AppManagerWorker(
        "synthetic-app-device", "modify_app", user_id=0,
        action="enable", package_name="com.example.app",
    )
    monkeypatch.setattr(worker, "_read_current_user", lambda: 0)
    monkeypatch.setattr(worker, "_adb", Mock(return_value=Mock(
        success=succeeded, error="Permission denied" if not succeeded else "", stdout="",
    )))
    page._track_worker(worker)
    worker.start()
    try:
        wait_until(
            qt_application, lambda: bool(result_frame.adb_controller.action_results.recent()),
        )
        result = result_frame.adb_controller.action_results.recent()[0]
        assert result.items[-1].state == ("succeeded" if succeeded else "failed")
        wait_until(qt_application, lambda: not page._workers)
    finally:
        page.close()


def test_later_success_does_not_replace_an_independent_failure_reader(result_frame, monkeypatch):
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    presenter = result_frame._action_feedback
    original_page = result_frame.stackedWidget.currentWidget()
    presenter.record_notice("probe.failure", "操作", "first item failed", "error", notify=True)
    store = result_frame.adb_controller.action_results
    failure = store.recent()[0]
    assert "first item failed" in _drawer_output(result_frame, failure)
    presenter.record_notice(
        "probe.success", "操作", "second item succeeded", "success", notify=True,
    )
    success = store.recent()[0]
    assert success.request_id != failure.request_id
    assert len(store.recent()) == 2
    assert "first item failed" in _drawer_output(result_frame, failure)
    assert result_frame._task_page.navigation_snapshot().unread_count == 1
    presenter.open_task(success.request_id)
    assert "second item succeeded" in _drawer_output(result_frame, success)
    assert result_frame._task_page.navigation_snapshot().unread_count == 1
    presenter.open_task(failure.request_id)
    assert "first item failed" in _drawer_output(result_frame, failure)
    assert result_frame._task_page.navigation_snapshot().unread_count == 0
    assert result_frame.stackedWidget.currentWidget() is original_page
    assert notices == []


@pytest.mark.parametrize("content", [
    "请先填写应用包名，再启动测试。",
    "设备连接已断开，请重新连接后重试。",
    "  请先选择应用。\n",
    "x" * 160,
    "x" * 161,
    "ADB 执行失败\nPermission denied",
])
def test_page_notice_keeps_complete_guidance_in_exact_drawer(
    result_frame, monkeypatch, content,
):
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append((a, kw)))
    original_page = result_frame.stackedWidget.currentWidget()
    result_frame._action_feedback.record_notice(
        "probe", "应用操作", content, "warning", notify=True,
    )

    result = result_frame.adb_controller.action_results.recent()[0]
    assert content.strip() == result.items[-1].detail.strip()
    assert not result_frame._task_feedback.drawer.opened
    assert result_frame._task_page.navigation_snapshot().unread_count == 1
    result_frame._action_feedback.open_task(result.request_id)
    assert "[注意] " + content in _drawer_output(result_frame, result)
    assert result_frame._task_feedback.drawer.title_label.text() == "应用操作"
    assert result_frame._task_feedback.drawer.status_label.text() == "注意"
    assert result_frame._task_page.navigation_snapshot().unread_count == 0
    assert result_frame.stackedWidget.currentWidget() is original_page
    assert notices == []

    result_frame._action_feedback.open_task(result.request_id)
    _assert_drawer_request(result_frame, result)
    assert result_frame._task_page.navigation_snapshot().unread_count == 0
    assert result_frame.stackedWidget.currentWidget() is original_page
