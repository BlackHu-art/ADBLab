"""验证 Logcat 正文空态随真实页面事件变化，不启动设备命令。"""

import pytest

from adblab.application.supervision import StopDisposition, TaskStopResult
from gui.dialogs.live_logcat import LiveLogcatPage, LogcatWorker
from gui.dialogs.live_logcat_worker import LogcatTermination, LogcatTerminationKind
from tests.test_phase2_live_logcat_gate import FakeQtTaskSupervisor

pytestmark = pytest.mark.ui


@pytest.fixture
def logcat_page(qt_application, monkeypatch):
    """只替换线程启动，页面、文档和生命周期协调仍使用真实实现。"""
    monkeypatch.setattr(LogcatWorker, "start", lambda _worker: None)
    page = LiveLogcatPage(device_ip="demo", task_supervisor=FakeQtTaskSupervisor())
    try:
        yield page
    finally:
        _release_worker(page)
        page.close()


def _release_worker(page):
    """未启动的测试线程以完成事件模拟资源已退出，再走页面的释放回调。"""
    worker = page.worker
    if worker is not None:
        worker._finished_event.set()
        page._on_worker_finished(worker)


def _hint(page):
    lines = page.output.placeholderText().splitlines()
    assert len(lines) == 2, page.output.placeholderText()
    title, body = lines
    assert title.strip() and body.strip()
    return title, body


def _assert_title(page, expected):
    title, body = _hint(page)
    assert title == expected
    return body


def _start_running(page):
    page._start()
    worker = page.worker
    assert worker is not None
    page._on_worker_status(worker, "正在采集")
    return worker


def _report_stop(page, disposition):
    page._on_task_stopped(TaskStopResult(
        page._supervisor_task_id, page._supervisor_owner_id, disposition,
    ))


def test_initial_hint_explains_ready_state_and_keeps_separate_capture_actions(logcat_page):
    page = logcat_page
    assert page.start_btn is not page.stop_btn
    assert page.start_btn.text() == page.start_action.text() == "开始"
    assert page.stop_btn.text() == page.stop_action.text() == "停止"
    assert page.start_action.isEnabled()
    assert not page.stop_action.isEnabled()
    assert page.output.document().isEmpty()
    body = _assert_title(page, "准备采集设备日志")
    assert "开始" in body


def test_starting_hint_keeps_stop_available_before_first_worker_message(logcat_page):
    page = logcat_page
    page._start()
    assert not page.start_action.isEnabled()
    assert page.stop_action.isEnabled()
    assert page.output.document().isEmpty()
    _assert_title(page, "正在启动日志采集")


def test_running_without_records_shows_waiting_hint(logcat_page):
    page = logcat_page
    _start_running(page)
    assert not page.start_action.isEnabled()
    assert page.stop_action.isEnabled()
    _assert_title(page, "正在等待新日志")


def test_clear_running_log_shows_cleared_context_without_stopping_capture(logcat_page):
    page = logcat_page
    worker = _start_running(page)
    page._on_line("record before clear", "I")
    page._flush_pending_lines()
    page._clear()
    assert page.output.document().isEmpty()
    assert worker.is_active()
    assert page.stop_action.isEnabled()
    body = _assert_title(page, "正在等待新日志")
    assert "已清空显示，采集仍在继续。" in body


@pytest.mark.parametrize("operation", ["wrap", "package_lookup"])
def test_unrelated_toolbar_feedback_does_not_replace_capture_hint(logcat_page, operation):
    page = logcat_page
    _start_running(page)
    before = page.output.placeholderText()
    if operation == "wrap":
        page.wrap_btn.click()
    else:
        page._on_status("未找到前台应用，请在设备上打开应用后重试")
    assert page.output.placeholderText() == before
    _assert_title(page, "正在等待新日志")


def test_stopping_hint_disables_both_capture_actions(logcat_page):
    page = logcat_page
    worker = _start_running(page)
    page._stop()
    assert not page.start_action.isEnabled()
    assert not page.stop_action.isEnabled()
    page._on_worker_status(worker, "正在采集")
    _assert_title(page, "正在停止采集")


@pytest.mark.parametrize("disposition", [StopDisposition.TIMED_OUT, StopDisposition.FAILED])
def test_unfinished_stop_keeps_cleanup_hint_until_worker_release(logcat_page, disposition):
    page = logcat_page
    worker = _start_running(page)
    page._stop()
    _report_stop(page, disposition)
    _assert_title(page, "仍在等待采集结束")
    before = page.output.placeholderText()
    page._on_worker_status(worker, "正在采集")
    page._on_worker_terminated(worker, LogcatTermination(LogcatTerminationKind.CANCELLED))
    page._clear()
    assert page.output.placeholderText() == before
    assert not page.start_action.isEnabled()
    assert not page.stop_action.isEnabled()
    _release_worker(page)
    assert page.start_action.isEnabled()
    assert not page.stop_action.isEnabled()
    _assert_title(page, "采集已停止")


@pytest.mark.parametrize("kind", [
    LogcatTerminationKind.START_FAILED,
    LogcatTerminationKind.UNEXPECTED_EXIT,
])
def test_capture_failure_survives_worker_release_and_clear(logcat_page, kind):
    page = logcat_page
    if kind is LogcatTerminationKind.START_FAILED:
        page._start()
        worker = page.worker
        assert worker is not None
    else:
        worker = _start_running(page)
    page._on_worker_terminated(worker, LogcatTermination(kind))
    title, _body = _hint(page)
    if kind is LogcatTerminationKind.START_FAILED:
        assert "启动失败" in title
    else:
        assert "意外" in title or "异常" in title
    failure_hint = page.output.placeholderText()
    assert "清理" in failure_hint
    page._clear()
    assert page.output.placeholderText() == failure_hint
    _release_worker(page)
    assert page.start_action.isEnabled()
    assert _hint(page)[0] == title
    assert "重试" in _hint(page)[1]
    failure_hint = page.output.placeholderText()
    page._clear()
    assert page.output.placeholderText() == failure_hint


@pytest.mark.parametrize("message, expected_words", [
    ("正在等待目标应用启动；过滤期间不会显示其他应用日志", ("等待", "应用")),
    ("应用进程查询失败，正在重试；过滤期间不会显示其他应用日志", ("查询", "重试")),
], ids=["waiting_for_app", "pid_retry"])
def test_package_waiting_hint_survives_clear_without_repeated_worker_status(
    logcat_page, message, expected_words,
):
    page = logcat_page
    page.pkg_input.setText("com.example.demo")
    page._start()
    worker = page.worker
    assert worker is not None
    page._on_worker_status(worker, message)
    title, body = _hint(page)
    for word in expected_words:
        assert word in title + body
    before = page.output.placeholderText()
    page._clear()
    assert page.output.placeholderText() == before
    assert page.stop_action.isEnabled()


def test_filtered_empty_hint_offers_level_adjustment(logcat_page):
    page = logcat_page
    _start_running(page)
    page._on_line("record below error filter", "I")
    page._flush_pending_lines()
    page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
    assert page.output.document().isEmpty()
    assert page.clear_action.isEnabled()
    assert not page.export_action.isEnabled()
    body = _assert_title(page, "当前条件下暂无日志")
    assert "等级" in body and "调整" in body


def test_stopped_filtered_empty_hint_does_not_wait_for_new_logs(logcat_page):
    page = logcat_page
    _start_running(page)
    page._on_line("retained filtered record", "I")
    page._flush_pending_lines()
    page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
    page._stop()
    _report_stop(page, StopDisposition.GRACEFUL)
    _release_worker(page)
    body = _assert_title(page, "当前条件下暂无日志")
    assert "等级" in body
    assert "等待新日志" not in page.output.placeholderText()
    page.level_combo.setCurrentIndex(page.level_combo.findData(None))
    assert page.output.toPlainText() == "retained filtered record"


@pytest.mark.parametrize("unavailable, expected_word", [
    ("disconnected", "连接"),
    ("unselected", "勾选"),
], ids=["disconnected", "unselected"])
def test_idle_unavailable_device_hint_explains_required_action(
    logcat_page, unavailable, expected_word,
):
    page = logcat_page
    if unavailable == "disconnected":
        page.set_device_connected(False)
    else:
        page.set_device_selected(False)
    assert not page.start_action.isEnabled()
    assert not page.stop_action.isEnabled()
    title, body = _hint(page)
    assert expected_word in title + body
    assert title != "准备采集设备日志"


def test_deselecting_device_does_not_turn_running_capture_hint_into_stopped(logcat_page):
    page = logcat_page
    worker = _start_running(page)
    before = page.output.placeholderText()
    page.set_device_selected(False)
    assert worker.is_active()
    assert page.stop_action.isEnabled()
    assert page.output.placeholderText() == before
    _assert_title(page, "正在等待新日志")


def test_finished_stop_without_records_shows_stopped_hint(logcat_page):
    page = logcat_page
    _start_running(page)
    page._stop()
    _report_stop(page, StopDisposition.GRACEFUL)
    _release_worker(page)
    assert page.start_action.isEnabled()
    assert not page.stop_action.isEnabled()
    _assert_title(page, "采集已停止")


def test_stopping_preserves_existing_log_document(logcat_page):
    page = logcat_page
    _start_running(page)
    page._on_line("retained after stopping", "I")
    page._flush_pending_lines()
    page._stop()
    _report_stop(page, StopDisposition.GRACEFUL)
    _release_worker(page)
    assert page.output.toPlainText() == "retained after stopping"
    assert page.export_action.isEnabled()
    assert page.clear_action.isEnabled()


def test_new_record_replaces_cleared_hint_without_entering_export_content(logcat_page):
    page = logcat_page
    _start_running(page)
    page._clear()
    assert "采集仍在继续" in page.output.placeholderText()
    page._on_line("new device record", "I")
    page._flush_pending_lines()
    assert page.output.toPlainText() == "new device record"
    assert page.output.placeholderText() == page.output.accessibleDescription() == ""
    assert page.export_action.isEnabled()


def test_restart_resets_previous_failure_and_ignores_old_worker_status(logcat_page):
    page = logcat_page
    old_worker = _start_running(page)
    page._on_worker_terminated(
        old_worker, LogcatTermination(LogcatTerminationKind.UNEXPECTED_EXIT),
    )
    _release_worker(page)
    page._start()
    page._on_worker_status(old_worker, "正在采集")
    _assert_title(page, "正在启动日志采集")
    page._clear()
    _assert_title(page, "正在启动日志采集")
    page._on_worker_status(page.worker, "正在采集")
    _assert_title(page, "正在等待新日志")


def test_registration_failure_shows_retry_without_claiming_capture_started(
    logcat_page, monkeypatch,
):
    page = logcat_page

    def reject_registration(*args, **kwargs):
        raise RuntimeError("registration rejected")

    monkeypatch.setattr(page._task_supervisor.supervisor, "register", reject_registration)
    page._start()
    assert page.worker is None
    assert page.start_action.isEnabled()
    assert not page.stop_action.isEnabled()
    assert "重试" in _assert_title(page, "日志采集启动失败")
