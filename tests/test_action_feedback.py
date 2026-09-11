"""验证全部入口的任务记录、分级通知与专用业务结果阅读。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QThread
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from adblab.application.action_results import ActionResults, ActionSpec, capture_action_job
from controllers.action_catalog import ACTION_SIGNALS
from controllers.signals import ADBControllerSignals
from gui.widgets.action_result_view import ActionResultView
from tests.test_logging_contract import create_log_service  # noqa: F401  复用隔离单例的 fixture。
from tests.test_main_window_layout import build_main_frame


@pytest.fixture
def result_frame(qt_application):
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


def test_all_declared_actions_record_tasks_and_notify_without_changing_page(
    result_frame, monkeypatch,
):
    frame = result_frame
    store = frame.adb_controller.action_results
    original_page = frame.stackedWidget.currentWidget()
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    for spec in ACTION_SIGNALS.values():
        jobs = []
        frame._action_feedback.dispatch(
            spec,
            lambda devices: jobs.extend(
                capture_action_job("query_async", device) for device in devices
            ),
            (["synthetic-a", "synthetic-b"],),
        )
        assert len(jobs) == 2, spec
        view = frame._task_page.action_results
        assert view._records[jobs[0].request_id].state == "running", spec
        store.complete(jobs[0], {"success": False, "error": "设备暂不可用，请重试"})
        assert "执行中" in view.summary.text(), spec
        store.complete(jobs[1], {"success": True, "output": "second target answer"})
        snapshot = store.recent()[0]
        assert snapshot.state == "partial", spec
        assert view._records[snapshot.request_id] is snapshot
        assert frame._task_page.action_results._records[snapshot.request_id] is snapshot
        assert "部分成功" in view.summary.text(), spec
        assert notices[-1]["level"] == "warning", spec
        assert notices[-1]["key"] == snapshot.request_id, spec
        assert frame.stackedWidget.currentWidget() is original_page
    assert not hasattr(frame.left_panel._apps_tab, "action_result_views")
    assert not hasattr(frame.left_panel._advanced_tab, "action_result_views")
    assert not hasattr(frame._settings_page, "action_results")


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
        assert export.at(0)[1] == raw
        opened = QSignalSpy(view.artifact_requested)
        view.open_button.click()
        view.folder_button.click()
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


def test_settings_adb_restart_notifies_and_opens_exact_task(result_frame, monkeypatch):
    frame = result_frame
    frame._on_nav_requested("settings")
    jobs = []
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append((a, kw)))
    frame._action_feedback.dispatch(
        ACTION_SIGNALS["restart_adb_requested"],
        lambda: jobs.append(capture_action_job("restart_adb_async")),
        (),
    )
    store = frame.adb_controller.action_results
    store.complete(jobs[0], {"success": False, "error": "请重新检测 ADB 环境"})
    assert store.recent()[0].spec.section == "settings.maintenance"
    assert notices[-1][1]["level"] == "error"
    assert "请重新检测" in notices[-1][0][2]
    assert frame.stackedWidget.currentWidget() is frame._settings_page
    notices[-1][1]["on_action"]()
    assert frame._task_page.isVisibleTo(frame)
    assert frame._task_page.action_results._selected == jobs[0].request_id


def test_task_center_exposes_running_plain_commands_without_native_operation(result_frame):
    frame = result_frame
    page = frame._task_page
    page._operation_manager = None
    page.refresh()
    jobs = []
    frame._action_feedback.dispatch(
        ACTION_SIGNALS["capture_bugreport_requested"],
        lambda devices: jobs.append(capture_action_job("bugreport_async", devices[0])),
        (["synthetic-a"],),
    )
    assert not page.running_actions_button.isHidden()
    assert "1" in page.running_actions_button.text()
    assert page._idle_label.isHidden()
    page.running_actions_button.click()
    assert page.history_views.current_key == "operations"
    assert page.action_results._selected == jobs[0].request_id
    frame.adb_controller.action_results.complete(jobs[0], {"success": False, "error": "生成失败"})
    assert page.running_actions_button.isHidden()
    assert not page._idle_label.isHidden()
    assert "失败" in page.action_results.summary.text()


def test_remote_feedback_records_in_task_center_and_notifies(result_frame, monkeypatch):
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    remote = result_frame.left_panel._scrcpy_tab
    remote._active_device = "synthetic-a"
    remote._log("ERROR", "synthetic-a: 远程启动失败，请检查连接")
    assert not hasattr(remote._form_controller, "feedback")
    result = result_frame.adb_controller.action_results.recent()[0]
    assert result.spec.section == "remote"
    assert "远程启动失败" in result.items[-1].detail
    assert "synthetic-a" not in result.items[-1].detail
    assert notices[-1]["level"] == "error"


def test_toast_counts_devices_and_task_labels_survive_new_selection(result_frame, monkeypatch):
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
    assert notices[-1][1]["level"] == "warning"
    assert "成功 1 台 · 失败 1 台" in notices[-1][0][2]
    assert "设备 3 · Phone" in frame.left_panel._apps_tab.diagnostic_results.targets.itemText(0)


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


def test_request_level_failure_does_not_claim_all_devices_succeeded(result_frame, monkeypatch):
    from adblab.application.action_results import report_action_message

    store = result_frame.adb_controller.action_results
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **_kw: notices.append(a))

    def submit():
        job = capture_action_job("query_async", "demo-a")
        store.complete(job, {"success": True})
        report_action_message(False, "收尾未完成")

    store.run(ActionSpec("probe", "system.shell", "查询"), ("demo-a",), submit)
    assert store.recent()[0].state == "partial"
    assert "成功 1 台" not in notices[-1][2]
    assert "部分操作失败" in notices[-1][2]


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
        page._on_operation_feedback("error", "设备连接已断开，请重试")
        assert not hasattr(page, "log_output")
        result = result_frame.adb_controller.action_results.recent()[0]
        assert result.spec.section == "apps.manager"
        assert "设备连接已断开" in result.items[-1].detail
        assert notices[-1]["level"] == "error"
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
    view = result_frame._task_page.action_results
    assert "[记录] 第一条" in view.output.toPlainText()
    assert "[失败] 第二条" in view.output.toPlainText()
    assert view.targets.isHidden()
    assert not view.running_results()


@pytest.mark.parametrize("failed", [False, True])
def test_file_result_records_task_notifies_and_refreshes_only_on_success(
    result_frame, monkeypatch, failed,
):
    from gui.dialogs.file_explorer import FileExplorerPage

    page = FileExplorerPage(device_ip="synthetic-file-device", parent=result_frame)
    page._refresh = Mock()
    notices = []
    monkeypatch.setattr("gui.action_feedback.show_toast", lambda *a, **kw: notices.append(kw))
    try:
        page._ops_controller._on_transfer_done("Permission denied", failed, "文件已传输")
        result = result_frame.adb_controller.action_results.recent()[0]
        assert result.spec.section == "devices.files"
        assert result.items[-1].state == ("failed" if failed else "succeeded")
        assert notices[-1]["level"] == ("error" if failed else "success")
        assert page._refresh.call_count == (0 if failed else 1)
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
        "synthetic-app-device", "modify_app", action="enable", package_name="com.example.app",
    )
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


def test_later_success_does_not_replace_an_independent_failure_notice(result_frame):
    from gui.notifications import ToastNotification

    presenter = result_frame._action_feedback
    presenter.record_notice("probe", "操作", "first item failed", "error", notify=True)
    presenter.record_notice("probe", "操作", "second item succeeded", "success", notify=True)
    notices = [n for n in result_frame.findChildren(ToastNotification) if n.isVisible()]
    assert {notice.level for notice in notices} == {"error", "success"}
