"""性能启动准备的事件循环、取消和资源归属回归。"""

import threading
from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QTimer

from gui.dialogs.performance_launcher import PerformancePage
from services.mobileperf_runner import MobilePerfRunner
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


class ControlledRunner:
    """仅通过测试事件控制准备与停止，不启动设备命令或进程。"""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.running = False
        self.fail = False
        self.ignore_cancel_during_spawn = False
        self.calls = []
        self.stop_calls = []
        self.callbacks = []
        self.last_config = None
        self.last_exit_code = 0

    def start(self, config, *, on_log, on_finished, cancelled=lambda: False):
        self.calls.append((config, threading.get_ident()))
        self.callbacks.append((on_log, on_finished))
        self.last_config = config
        self.entered.set()
        assert self.release.wait(1), "test did not release startup"
        if cancelled() and not self.ignore_cancel_during_spawn:
            raise CancelledError
        if self.fail:
            raise OSError("synthetic startup failure")
        self.running = True

    def is_running(self):
        return self.running

    def stop(self):
        self.stop_calls.append(threading.get_ident())
        self.running = False

    def force_stop(self, timeout=0):
        self.stop()
        return True

    def latest_result_dir(self):
        return ""

    def latest_report_file(self, **_kwargs):
        return ""


@pytest.fixture
def start_page(qt_application, tmp_path):
    page = PerformancePage("synthetic-device", "com.example.synthetic")
    page.save_path_edit.setText(str(tmp_path))
    runner = ControlledRunner()
    page._runner = runner
    yield page, runner
    runner.release.set()
    runner.running = False
    page.request_dispose()
    wait_until(qt_application, lambda: page._dispose_ready_state)
    page.close()


def test_slow_result_baseline_does_not_block_qt_heartbeat(monkeypatch, qt_application, tmp_path):
    page = PerformancePage("synthetic-device", "com.example.synthetic")
    runner = MobilePerfRunner(process_runner=Mock(), project_root=tmp_path)
    page._runner = runner
    entered, finished, release = threading.Event(), threading.Event(), threading.Event()
    heartbeat = []

    def baseline(_config):
        entered.set()
        release.wait(0.35)
        finished.set()
        raise OSError("synthetic directory failure")

    monkeypatch.setattr(runner, "_capture_result_baseline", baseline)
    timer = QTimer(page)
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeat.append(entered.is_set() and not finished.is_set()))
    timer.start()
    try:
        page.start_mobileperf()
        wait_until(qt_application, lambda: bool(heartbeat))
        assert any(heartbeat), "启动目录扫描阻塞了 Qt 心跳"
        assert page._configuration_locked
        assert page._status_state == "starting"
    finally:
        release.set()
        timer.stop()
        page.request_dispose()
        wait_until(qt_application, lambda: page._dispose_ready_state)
        page.close()


def test_start_success_freezes_config_and_rejects_repeated_clicks(start_page, qt_application):
    page, runner = start_page
    main_thread = threading.get_ident()
    page.start_mobileperf()
    page.start_mobileperf()
    wait_until(qt_application, runner.entered.is_set)
    assert len(runner.calls) == 1
    assert runner.calls[0][1] != main_thread
    assert page._configuration_locked and page.stop_btn.isEnabled()
    assert page._status_state == "starting"
    assert page._run_started_at is None
    page.package_edit.setText("com.example.changed")
    runner.release.set()
    wait_until(qt_application, lambda: page._status_state == "running")
    assert runner.calls[0][0].package == "com.example.synthetic"
    assert page._run_started_at is not None


def test_start_failure_unlocks_and_finishes_once(start_page, qt_application, monkeypatch):
    page, runner = start_page
    runner.fail = True
    finish = Mock(wraps=page._library_controller.finish)
    monkeypatch.setattr(page._library_controller, "finish", finish)
    page.start_mobileperf()
    runner.release.set()
    wait_until(qt_application, lambda: page._status_state == "failed")
    assert not page._configuration_locked
    assert page.start_btn.isEnabled() and not page.stop_btn.isEnabled()
    assert finish.call_count == 1
    assert not runner.running


@pytest.mark.parametrize("reason", ["stop", "close", "deselect", "offline"])
def test_cancel_start_never_launches_after_context_is_revoked(start_page, qt_application, reason):
    page, runner = start_page
    page.start_mobileperf()
    wait_until(qt_application, runner.entered.is_set)
    if reason == "stop":
        page.stop_mobileperf()
    elif reason == "close":
        assert not page.request_dispose()
    elif reason == "deselect":
        page.set_device_selected(False)
    else:
        page.set_device_connected(False)
    assert page._configuration_locked
    assert not page.start_btn.isEnabled()
    runner.release.set()
    wait_until(qt_application, lambda: page._runner_finished_handled)
    assert not runner.running
    assert not runner.stop_calls
    if reason != "close":
        assert page._status_state == "cancelled"


def test_cancel_during_process_creation_stops_spawned_process_off_gui(start_page, qt_application):
    page, runner = start_page
    runner.ignore_cancel_during_spawn = True
    page.start_mobileperf()
    wait_until(qt_application, runner.entered.is_set)
    assert not page.request_dispose()
    runner.release.set()
    wait_until(qt_application, lambda: page._dispose_ready_state)
    assert runner.stop_calls == [runner.calls[0][1]]
    assert not runner.running


def test_old_run_callbacks_do_not_change_new_start(start_page, qt_application):
    page, runner = start_page
    runner.release.set()
    page.start_mobileperf()
    wait_until(qt_application, lambda: page._status_state == "running")
    old_log, old_finished = runner.callbacks[0]
    runner.running = False
    old_finished()
    wait_until(qt_application, lambda: not page._configuration_locked)
    runner.release.clear()
    page.start_mobileperf()
    wait_until(qt_application, lambda: len(runner.calls) == 2)
    old_log("obsolete output")
    old_finished()
    qt_application.processEvents()
    assert page._status_state == "starting"
    assert page._configuration_locked
    assert "obsolete output" not in "\n".join(page._pending_log_rows)


def test_real_runner_cancellation_after_baseline_never_spawns(
    monkeypatch, qt_application, tmp_path,
):
    page = PerformancePage("synthetic-device", "com.example.synthetic")
    processes = Mock()
    processes.start.side_effect = AssertionError("cancelled startup launched a process")
    runner = MobilePerfRunner(process_runner=processes, project_root=tmp_path)
    page._runner = runner
    entered, release = threading.Event(), threading.Event()

    def baseline(_config):
        entered.set()
        assert release.wait(1)

    monkeypatch.setattr(runner, "_capture_result_baseline", baseline)
    try:
        page.start_mobileperf()
        wait_until(qt_application, entered.is_set)
        page.stop_mobileperf()
        heartbeat = threading.Event()
        QTimer.singleShot(0, heartbeat.set)
        wait_until(qt_application, heartbeat.is_set)
        assert not release.is_set()
        release.set()
        wait_until(qt_application, lambda: page._runner_finished_handled)
        processes.start.assert_not_called()
        assert page._status_state == "cancelled"
    finally:
        release.set()
        page.request_dispose()
        wait_until(qt_application, lambda: page._dispose_ready_state)
        page.close()


def test_shutdown_registration_keeps_startup_until_cancelled_and_joined(start_page, qt_application):
    page, runner = start_page
    registrations = []
    supervisor = SimpleNamespace(register=lambda task_id, **fields: registrations.append(fields))
    page.start_mobileperf()
    wait_until(qt_application, runner.entered.is_set)
    page.register_shutdown_tasks(supervisor, owner_id="synthetic-owner", task_prefix="performance")
    task = next(item for item in registrations if item["kind"] == "performance_start_worker")
    task["request_stop"]()
    assert task["is_running"]()
    assert not task["wait"](0)
    assert not page.request_dispose()
    runner.release.set()
    wait_until(qt_application, lambda: page._dispose_ready_state)
    assert task["wait"](0.1)
    assert not task["is_running"]()
    assert not runner.running


def test_cancel_after_start_thread_returns_before_gui_completion(start_page, qt_application):
    page, runner = start_page
    page.start_mobileperf()
    worker = page._run_controller._start_worker
    runner.release.set()
    assert worker.wait(1000)
    assert runner.running
    page.stop_mobileperf()
    wait_until(qt_application, lambda: not page._configuration_locked)
    assert not runner.running
    assert len(runner.stop_calls) == 1
    assert page._status_state == "cancelled"


def test_shutdown_snapshot_stops_process_even_after_startup_handoff(start_page, qt_application):
    page, runner = start_page
    registrations = []
    supervisor = SimpleNamespace(register=lambda task_id, **fields: registrations.append(fields))
    page.start_mobileperf()
    wait_until(qt_application, runner.entered.is_set)
    page.register_shutdown_tasks(supervisor, owner_id="synthetic-owner", task_prefix="performance")
    task = next(item for item in registrations if item["kind"] == "performance_start_worker")
    runner.release.set()
    wait_until(qt_application, lambda: page._status_state == "running")
    task["request_stop"]()
    assert task["wait"](1)
    assert not task["is_running"]()
    assert not runner.running
    assert len(runner.stop_calls) == 1


def test_close_keeps_start_worker_until_actual_join(start_page, qt_application, monkeypatch):
    page, runner = start_page
    page.start_mobileperf()
    worker = page._run_controller._start_worker
    original_wait = worker.wait
    joined = threading.Event()
    monkeypatch.setattr(worker, "wait", lambda timeout: joined.is_set() and original_wait(timeout))
    try:
        runner.release.set()
        assert original_wait(1000)
        qt_application.processEvents()
        assert page._status_state == "starting"
        assert not page.request_dispose()
        assert not page._dispose_ready_state
        joined.set()
        wait_until(qt_application, lambda: page._dispose_ready_state)
        assert not runner.running
    finally:
        joined.set()


def test_start_thread_creation_failure_restores_actions(start_page, monkeypatch):
    from gui.dialogs.performance_launcher_run import PerformanceStartWorker

    page, runner = start_page

    def fail_start(_worker):
        raise RuntimeError("synthetic QThread creation failure")

    monkeypatch.setattr(PerformanceStartWorker, "start", fail_start)
    page.start_mobileperf()
    assert not runner.calls
    assert page._status_state == "failed"
    assert not page._configuration_locked
    assert page.start_btn.isEnabled()


def test_cancel_before_start_worker_runs_does_not_call_runner(
    start_page, monkeypatch, qt_application,
):
    from gui.dialogs.performance_launcher_run import PerformanceStartWorker

    page, runner = start_page
    delayed = []
    original_start = PerformanceStartWorker.start
    monkeypatch.setattr(PerformanceStartWorker, "start", lambda worker: delayed.append(worker))
    page.start_mobileperf()
    page.stop_mobileperf()
    original_start(delayed[0])
    wait_until(qt_application, lambda: page._runner_finished_handled)
    assert not runner.calls
    assert page._status_state == "cancelled"


def test_cancelled_spawn_preserves_report_created_during_stop(
    start_page, qt_application, monkeypatch, tmp_path,
):
    from tests.test_performance_library import _Library

    page, runner = start_page
    library = _Library()
    page.set_run_library(library)
    report = tmp_path / "summary_synthetic.xlsx"
    report.write_bytes(b"synthetic partial report")
    monkeypatch.setattr(runner, "latest_result_dir", lambda: str(tmp_path))
    monkeypatch.setattr(runner, "latest_report_file", lambda **_kwargs: str(report))
    runner.ignore_cancel_during_spawn = True
    page.start_mobileperf()
    wait_until(qt_application, runner.entered.is_set)
    assert not page.request_dispose()
    runner.release.set()
    wait_until(qt_application, lambda: page._dispose_ready_state)
    assert len(library.records) == 1
    assert library.records[0].state == "cancelled"
    assert str(report) in {artifact.path for artifact in library.records[0].artifacts}
