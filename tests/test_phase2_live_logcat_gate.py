import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMainWindow

from adblab.application.supervision import (
    StopDisposition,
    TaskStopResult,
    TaskSupervisor,
)
from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from core.exec import CommandResult, ProcessRunner
from gui.dialogs.live_logcat import (
    CurrentPackageWorker,
    LogcatBatch,
    LogcatWorker,
)
from gui.dialogs.live_logcat_worker import LogcatTerminationKind
from gui.features.logcat import LiveLogcatPage


@pytest.fixture(scope="module", autouse=True)
def drain_live_logcat_deferred_deletes(qt_application):
    """在 QApplication 存活时收口本模块积累的 Qt 延迟销毁事件。"""

    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class FakeQtTaskSupervisor(QObject):
    task_stopped = Signal(object)
    owner_stopped = Signal(str, object)
    application_stopped = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.supervisor = TaskSupervisor()
        self.stop_requests = []
        self.owner_stop_requests = []

    def stop_async(self, task_id, **_kwargs):
        self.stop_requests.append(task_id)

    def stop_owner_async(self, owner_id, **_kwargs):
        self.owner_stop_requests.append(owner_id)


class FakePageWorker(QObject):
    lines_ready = Signal(object)
    dropped_ready = Signal(int)
    status_changed = Signal(str)
    terminated = Signal(object)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self._active = True

    def is_active(self):
        return self._active


class FakeStdout:
    def __init__(self, lines):
        self._lines = iter(lines)
        self.exhausted = False
        self.closed = False

    def readline(self):
        try:
            return next(self._lines)
        except StopIteration:
            self.exhausted = True
            return ""

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, lines, returncode=0):
        self.stdout = FakeStdout(lines)
        self.returncode = returncode

    def poll(self):
        return self.returncode if self.stdout.exhausted else None


class YieldingProcess(FakeProcess):
    def __init__(self, lines, returncode=0):
        super().__init__(lines, returncode)
        original_readline = self.stdout.readline

        def readline():
            time.sleep(0.0002)
            return original_readline()

        self.stdout.readline = readline


class BlockingProcess:
    def __init__(self):
        self.returncode = None
        self.terminated_threads = []
        self._stopped = threading.Event()
        self.stdout = self
        self.closed = False

    def readline(self):
        self._stopped.wait(2)
        return ""

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated_threads.append(threading.get_ident())
        self.returncode = 0
        self._stopped.set()

    def kill(self):
        self.returncode = -9
        self._stopped.set()

    def wait(self, timeout=None):
        if not self._stopped.wait(timeout):
            raise TimeoutError
        return self.returncode

    def close(self):
        self.closed = True


class StreamingStdout:
    """提供可从测试线程逐行喂入、并能被 terminate 解锁的阻塞 stdout。"""

    def __init__(self):
        self._lines = queue.Queue()
        self.closed = False

    def feed(self, line: str) -> None:
        self._lines.put(line)

    def finish(self) -> None:
        self._lines.put(None)

    def readline(self):
        item = self._lines.get(timeout=2)
        return "" if item is None else item

    def close(self):
        self.closed = True
        self.finish()


class StreamingProcess:
    """保持存活直到显式停止，便于验证稀疏流和运行中筛选切换。"""

    def __init__(self):
        self.stdout = StreamingStdout()
        self.returncode = None
        self._stopped = threading.Event()

    def poll(self):
        return self.returncode

    def terminate(self):
        if self.returncode is None:
            self.returncode = 0
            self._stopped.set()
            self.stdout.finish()

    def kill(self):
        if self.returncode is None:
            self.returncode = -9
            self._stopped.set()
            self.stdout.finish()

    def wait(self, timeout=None):
        if not self._stopped.wait(timeout):
            raise subprocess.TimeoutExpired("fake-logcat", timeout)
        return self.returncode


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def test_task_supervisor_distinguishes_graceful_and_forced_stop():
    supervisor = TaskSupervisor()
    graceful_running = [True]
    supervisor.register(
        "graceful",
        owner_id="owner",
        kind="test",
        request_stop=lambda: graceful_running.__setitem__(0, False),
        wait=lambda _timeout: not graceful_running[0],
        is_running=lambda: graceful_running[0],
    )
    graceful = supervisor.stop("graceful", graceful_timeout=0, force_timeout=0)

    forced_running = [True]
    wait_calls = [0]

    def wait(_timeout):
        wait_calls[0] += 1
        return wait_calls[0] > 1 and not forced_running[0]

    supervisor.register(
        "forced",
        owner_id="owner",
        kind="test",
        request_stop=lambda: None,
        wait=wait,
        is_running=lambda: forced_running[0],
        force_stop=lambda _timeout: (forced_running.__setitem__(0, False) is None),
    )
    forced = supervisor.stop("forced", graceful_timeout=0, force_timeout=0)

    assert graceful.disposition is StopDisposition.GRACEFUL
    assert forced.disposition is StopDisposition.FORCED
    assert supervisor.active_count == 0


def test_task_supervisor_retains_timed_out_orphan():
    supervisor = TaskSupervisor()
    supervisor.register(
        "orphan",
        owner_id="owner",
        kind="live_logcat",
        request_stop=lambda: None,
        wait=lambda _timeout: False,
        is_running=lambda: True,
        force_stop=lambda _timeout: True,
    )

    result = supervisor.stop("orphan", graceful_timeout=0, force_timeout=0)

    assert result.disposition is StopDisposition.TIMED_OUT
    assert supervisor.active_count == 1
    assert supervisor.active_snapshot()[0].running is True


def test_owner_stop_broadcasts_all_requests_before_waiting_and_shares_deadline():
    supervisor = TaskSupervisor()
    events = []
    running = {"one": True, "two": True}
    for task_id in running:
        supervisor.register(
            task_id,
            owner_id="owner",
            kind="test",
            request_stop=lambda task_id=task_id: events.append(("request", task_id)),
            wait=lambda _timeout, task_id=task_id: (
                events.append(("wait", task_id)) is None and not running[task_id]
            ),
            is_running=lambda task_id=task_id: running[task_id],
            force_stop=lambda _timeout, task_id=task_id: (
                events.append(("force", task_id)) is None
                and running.__setitem__(task_id, False) is None
            ),
        )

    results = supervisor.stop_owner("owner", deadline=0.05)

    first_wait = next(index for index, event in enumerate(events) if event[0] == "wait")
    assert events[:first_wait] == [("request", "one"), ("request", "two")]
    assert {result.disposition for result in results} == {StopDisposition.FORCED}
    assert supervisor.active_count == 0


def test_concurrent_duplicate_stop_has_only_one_resource_owner():
    supervisor = TaskSupervisor()
    entered_wait = threading.Event()
    release_wait = threading.Event()
    running = [True]

    def wait(_timeout):
        entered_wait.set()
        release_wait.wait(1)
        return not running[0]

    supervisor.register(
        "task",
        owner_id="owner",
        kind="test",
        request_stop=lambda: None,
        wait=wait,
        is_running=lambda: running[0],
        force_stop=lambda _timeout: True,
    )
    results = []
    thread = threading.Thread(
        target=lambda: results.append(supervisor.stop("task", graceful_timeout=1, force_timeout=0))
    )
    thread.start()
    assert entered_wait.wait(1)

    duplicate = supervisor.stop("task", graceful_timeout=0, force_timeout=0)
    running[0] = False
    release_wait.set()
    thread.join(1)

    assert duplicate is None
    assert results[0].disposition is StopDisposition.GRACEFUL


def test_process_runner_does_not_untrack_a_process_that_survives_stop():
    runner = ProcessRunner()
    process = Mock()
    process.poll.return_value = None
    runner._procs["live"] = process

    with patch.object(runner, "_stop_proc", return_value=None):
        result = runner.stop("live", timeout=0)

    assert result is None
    assert runner._procs["live"] is process


def test_live_logcat_stop_and_close_only_schedule_background_cleanup():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    worker = FakePageWorker()
    dialog.worker = worker
    dialog._supervisor_task_id = "task"
    dialog.setAttribute(Qt.WA_DeleteOnClose, False)

    started = time.perf_counter()
    dialog._stop()
    stop_elapsed = time.perf_counter() - started
    started = time.perf_counter()
    dialog.close()
    close_elapsed = time.perf_counter() - started

    assert stop_elapsed < 0.1
    assert close_elapsed < 0.1
    assert adapter.stop_requests == ["task"]
    assert adapter.owner_stop_requests == [dialog._supervisor_owner_id]
    worker._active = False
    dialog._on_worker_finished(worker)
    adapter.owner_stopped.emit(dialog._supervisor_owner_id, ())


def test_logcat_worker_release_waits_for_native_thread_join():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    worker = FakePageWorker()
    worker._active = False
    worker.wait = Mock(return_value=False)
    worker.deleteLater = Mock()
    dialog.worker = worker

    assert dialog._release_logcat_worker(worker) is False
    worker.wait.assert_called_once_with(0)
    assert dialog.worker is worker
    worker.deleteLater.assert_not_called()

    dialog.worker = None
    dialog.close()


def test_package_worker_release_waits_for_native_thread_join():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    worker = Mock()
    worker.isRunning.return_value = False
    worker.wait.return_value = False
    dialog._pkg_worker = worker

    assert dialog._release_pkg_worker(worker) is False
    worker.wait.assert_called_once_with(0)
    assert dialog._pkg_worker is worker
    worker.deleteLater.assert_not_called()

    dialog._pkg_worker = None
    dialog.close()


def test_active_embedded_logcat_close_keeps_main_window_open_until_cleanup_finishes():
    _app = QApplication.instance() or QApplication([])
    main_window = QMainWindow()
    main_window.show()
    adapter = FakeQtTaskSupervisor()
    log_service = Mock()
    dialog = LiveLogcatPage(
        parent=main_window,
        device_ip="target",
        task_supervisor=adapter,
        log_service=log_service,
    )
    worker = FakePageWorker()
    dialog.worker = worker
    dialog._supervisor_task_id = "task"
    dialog.setAttribute(Qt.WA_DeleteOnClose, False)
    dialog.show()

    assert not dialog.isWindow()
    assert dialog.window() is main_window
    dialog.close()

    assert main_window.isVisible()
    assert not dialog.isVisible()
    assert dialog._close_pending is True
    assert dialog._close_ready is False
    assert adapter.owner_stop_requests == [dialog._supervisor_owner_id]

    worker._active = False
    dialog._on_worker_finished(worker)
    assert dialog.worker is worker
    assert dialog._close_ready is False
    adapter.owner_stopped.emit(dialog._supervisor_owner_id, ())
    dialog.close()

    assert main_window.isVisible()
    assert dialog._close_ready is True
    messages = [call.args[1] for call in log_service.log.call_args_list]
    assert all(call.args[0] == "DEBUG" for call in log_service.log.call_args_list)
    assert any("phase=close_requested" in message for message in messages)
    assert any("phase=hidden_for_cleanup" in message for message in messages)
    assert any("phase=resources_stopped" in message for message in messages)
    assert any("phase=close_accepted" in message for message in messages)
    assert all("target" not in message for message in messages)
    main_window.close()


def test_owner_timeout_keeps_logcat_page_alive_until_worker_really_finishes():
    _app = QApplication.instance() or QApplication([])
    main_window = QMainWindow()
    main_window.show()
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(
        parent=main_window,
        device_ip="target",
        task_supervisor=adapter,
    )
    worker = FakePageWorker()
    task_id = "stubborn-logcat"
    worker._supervisor_task_id = task_id
    dialog.worker = worker
    dialog._supervisor_task_id = task_id
    adapter.supervisor.register(
        task_id,
        owner_id=dialog._supervisor_owner_id,
        kind="live_logcat",
        request_stop=lambda: None,
        wait=lambda _timeout: False,
        is_running=worker.is_active,
        force_stop=lambda _timeout: False,
    )
    dialog.setAttribute(Qt.WA_DeleteOnClose, False)
    dialog.show()

    dialog.close()
    timed_out = TaskStopResult(
        task_id,
        dialog._supervisor_owner_id,
        StopDisposition.TIMED_OUT,
    )
    adapter.owner_stopped.emit(dialog._supervisor_owner_id, (timed_out,))

    assert main_window.isVisible()
    assert not dialog.isVisible()
    assert dialog._close_pending is True
    assert dialog._close_ready is False
    assert dialog.worker is worker
    assert adapter.supervisor.active_count == 1

    worker._active = False
    dialog._on_worker_finished(worker)

    assert dialog._close_ready is True
    assert adapter.supervisor.active_count == 0
    assert main_window.isVisible()
    main_window.close()


def test_finished_before_timeout_rechecks_process_that_exits_later():
    """线程完成信号早到时，仍要观察随后退出的外部进程并最终销毁窗口。"""
    _app = QApplication.instance() or QApplication([])
    main_window = QMainWindow()
    main_window.show()
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(
        parent=main_window,
        device_ip="target",
        task_supervisor=adapter,
    )
    worker = FakePageWorker()
    task_id = "late-process-exit"
    worker._supervisor_task_id = task_id
    dialog.worker = worker
    dialog._supervisor_task_id = task_id
    adapter.supervisor.register(
        task_id,
        owner_id=dialog._supervisor_owner_id,
        kind="live_logcat",
        request_stop=lambda: None,
        wait=lambda _timeout: False,
        is_running=worker.is_active,
        force_stop=lambda _timeout: False,
    )
    dialog.setAttribute(Qt.WA_DeleteOnClose, False)
    dialog.show()

    dialog.close()
    # QThread 已发 finished，但受跟踪的外部进程此时仍未退出。
    dialog._on_worker_finished(worker)
    adapter.owner_stopped.emit(
        dialog._supervisor_owner_id,
        (
            TaskStopResult(
                task_id,
                dialog._supervisor_owner_id,
                StopDisposition.TIMED_OUT,
            ),
        ),
    )

    assert dialog._close_ready is False
    assert dialog.worker is worker
    assert dialog._cleanup_recheck_timer.isActive()
    assert adapter.supervisor.active_count == 1

    worker._active = False
    dialog._poll_close_cleanup()

    assert dialog._close_ready is True
    assert dialog.worker is None
    assert not dialog._cleanup_recheck_timer.isActive()
    assert adapter.supervisor.active_count == 0
    assert main_window.isVisible()
    main_window.close()


def test_continuous_logcat_close_stress_never_enters_main_window_exit_path(tmp_path):
    """在隔离进程中覆盖真实延迟删除、高频输出和应用退出信号。"""
    project_root = Path(__file__).resolve().parents[1]
    probe = project_root / "tests" / "live_logcat_close_probe.py"
    user_data = tmp_path / "user-data"
    user_data.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "LOCALAPPDATA": str(user_data),
            "PYTHONUTF8": "1",
            "QT_QPA_PLATFORM": "offscreen",
            "XDG_CONFIG_HOME": str(user_data),
        }
    )

    completed = subprocess.run(
        [sys.executable, str(probe)],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    details = f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    assert completed.returncode == 0, details
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert output_lines, details
    state = json.loads(output_lines[-1])
    assert state["destroyed"] == 10
    assert state["main_close_phases"] == ["deliberate"]
    assert state["last_window_closed_phases"] == ["deliberate"]
    assert state["about_to_quit_phases"] == ["deliberate"]


def test_qt_supervisor_keeps_event_loop_responsive_during_stubborn_cleanup():
    _app = QApplication.instance() or QApplication([])
    adapter = QtTaskSupervisor()
    callback_threads = []
    adapter.supervisor.register(
        "stubborn",
        owner_id="owner",
        kind="test",
        request_stop=lambda: callback_threads.append(threading.get_ident()),
        wait=lambda timeout: (time.sleep(timeout), False)[1],
        is_running=lambda: True,
        force_stop=lambda timeout: (time.sleep(timeout), True)[1],
    )
    gui_thread = threading.get_ident()

    started = time.perf_counter()
    adapter.stop_async("stubborn", graceful_timeout=0.08, force_timeout=0.08)
    dispatch_elapsed = time.perf_counter() - started
    assert adapter._pool.waitForDone(1000)

    assert dispatch_elapsed < 0.1
    assert callback_threads and callback_threads[0] != gui_thread
    assert adapter.supervisor.active_count == 1


def test_real_qthread_page_disposal_reaps_blocking_process_off_gui_thread():
    _app = QApplication.instance() or QApplication([])
    adapter = QtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    worker = LogcatWorker("target")
    worker.deleteLater = Mock()
    process = BlockingProcess()
    process_started = threading.Event()

    def start_process(key, *_args, **_kwargs):
        worker._process_runner._procs[key] = process
        process_started.set()
        return process

    worker._process_runner.start = Mock(side_effect=start_process)
    gui_thread = threading.get_ident()
    dialog.setAttribute(Qt.WA_DeleteOnClose, False)

    with patch("gui.dialogs.live_logcat.LogcatWorker", return_value=worker):
        dialog._start()
    assert process_started.wait(1)
    started = time.perf_counter()
    dialog.close()
    close_elapsed = time.perf_counter() - started

    deadline = time.perf_counter() + 2
    while (
        worker.isRunning() or adapter.supervisor.active_count
    ) and time.perf_counter() < deadline:
        time.sleep(0.003)
    assert adapter._pool.waitForDone(1000)

    assert close_elapsed < 0.1
    assert not worker.isRunning()
    assert worker._process_runner.active_keys == []
    assert adapter.supervisor.active_count == 0
    assert process.terminated_threads
    assert all(thread_id != gui_thread for thread_id in process.terminated_threads)
    dialog._on_owner_stopped(dialog._supervisor_owner_id, ())


def test_logcat_cancel_before_run_never_spawns_process():
    worker = LogcatWorker("target")
    terminations = []
    worker.terminated.connect(terminations.append)

    with (
        patch.object(worker._process_runner, "request_stop"),
        patch.object(worker._process_runner, "start") as start,
        patch.object(worker._process_runner, "stop"),
    ):
        worker.request_stop()
        worker.run()

    start.assert_not_called()
    assert terminations[0].kind is LogcatTerminationKind.CANCELLED
    assert worker.wait_for_stop(0)


def test_current_package_probe_cancellation_skips_remaining_fallback_commands():
    worker = CurrentPackageWorker("target")
    first_probe_started = threading.Event()
    release_first_probe = threading.Event()
    command_timeouts = []

    def slow_failed_probe(_command, *, timeout):
        command_timeouts.append(timeout)
        first_probe_started.set()
        assert release_first_probe.wait(1)
        return CommandResult(False, error="timeout", returncode=1)

    with patch(
        "gui.dialogs.live_logcat_worker.CommandRunner.run",
        side_effect=slow_failed_probe,
    ):
        worker.start()
        assert first_probe_started.wait(1)
        worker.requestInterruption()
        release_first_probe.set()
        assert worker.wait(500)

    assert command_timeouts == [5]


def test_current_package_probe_bounds_every_compatibility_fallback():
    worker = CurrentPackageWorker("target")
    statuses = []
    worker.status_changed.connect(statuses.append, Qt.ConnectionType.DirectConnection)

    with patch(
        "gui.dialogs.live_logcat_worker.CommandRunner.run",
        return_value=CommandResult(False, error="timeout", returncode=1),
    ) as run_command:
        worker.run()

    assert run_command.call_count == 3
    assert [call.kwargs["timeout"] for call in run_command.call_args_list] == [5] * 3
    assert statuses == ["未找到前台应用，请在设备上打开应用后重试"]


def test_logcat_pid_probe_uses_device_tolerant_timeout():
    """周期 PID 查询沿用实机可用的五秒边界，避免慢设备清空有效过滤状态。"""

    worker = LogcatWorker("target", package="com.example.app")
    with patch(
        "gui.dialogs.live_logcat_worker.CommandRunner.run",
        return_value=CommandResult(True, output="321\n", returncode=0),
    ) as run_command:
        worker._refresh_filter_pids("com.example.app", worker.filter_generation)

    run_command.assert_called_once_with(
        ["adb", "-s", "target", "shell", "pidof", "com.example.app"],
        timeout=5,
    )
    assert worker._package_snapshot()[2] == frozenset({321})


def test_logcat_clearing_package_filter_accepts_all_device_pids():
    """空包名提交后解除 PID 限制，后续任意设备进程日志都可通过。"""

    worker = LogcatWorker("target", package="com.example.app")
    generation = worker.filter_generation
    assert worker._commit_filter_pids(
        "com.example.app", generation, frozenset({321})
    )
    other_process_line = "08-25 12:00:00.000 999 999 I Other: visible after clear"

    assert worker._filtered_line(other_process_line, generation) is None
    assert worker.update_package("") is True

    cleared_generation = worker.filter_generation
    accepted = worker._filtered_line(other_process_line, cleared_generation)
    assert accepted == (other_process_line, "I", 999)


def test_logcat_pid_probe_failure_remains_fail_closed_and_recovers_on_retry():
    worker = LogcatWorker("target", package="com.example.app")
    worker.PID_REFRESH_SECONDS = 0.02
    process = StreamingProcess()
    process_started = threading.Event()
    failed_probe = threading.Event()
    recovered_probe = threading.Event()
    allow_recovery = threading.Event()
    commands = []
    emitted = []

    def start_process(key, command, **_kwargs):
        worker._process_runner._procs[key] = process
        commands.append(tuple(command))
        process_started.set()
        return process

    def probe_pid(*_args, **_kwargs):
        if not allow_recovery.is_set():
            failed_probe.set()
            return CommandResult(False, error="offline", returncode=1)
        recovered_probe.set()
        return CommandResult(True, output="321\n", returncode=0)

    def collect(batch):
        emitted.extend(text for text, _level, _pid in batch.lines)
        worker.acknowledge_batch()

    worker._process_runner.start = Mock(side_effect=start_process)
    worker.lines_ready.connect(collect, Qt.ConnectionType.DirectConnection)
    producer = threading.Thread(target=worker.run, name="logcat-probe-retry-producer")

    with patch("gui.dialogs.live_logcat_worker.CommandRunner.run", side_effect=probe_pid):
        producer.start()
        try:
            assert process_started.wait(1)
            assert failed_probe.wait(1)
            assert "--pid" not in commands[0]
            process.stdout.feed("08-25 12:00:00.000 999 999 I Other: must-not-leak\n")
            time.sleep(worker.BATCH_INTERVAL_SECONDS * 2 + 0.05)
            assert emitted == []

            allow_recovery.set()
            assert worker.update_package("com.example.app") is True
            assert recovered_probe.wait(1)
            process.stdout.feed("08-25 12:00:01.000 321 321 I App: recovered\n")
            assert _wait_until(lambda: any("App: recovered" in line for line in emitted))
        finally:
            worker.request_stop()
            producer.join(1)

    assert not producer.is_alive()
    assert not any("must-not-leak" in line for line in emitted)


def test_logcat_sparse_tail_flushes_while_process_is_still_running():
    worker = LogcatWorker("target")
    process = StreamingProcess()
    process_started = threading.Event()
    batch_ready = threading.Event()
    batches = []

    def start_process(key, *_args, **_kwargs):
        worker._process_runner._procs[key] = process
        process_started.set()
        return process

    def collect(batch):
        batches.append(batch)
        worker.acknowledge_batch()
        batch_ready.set()

    worker._process_runner.start = Mock(side_effect=start_process)
    worker.lines_ready.connect(collect, Qt.ConnectionType.DirectConnection)
    producer = threading.Thread(target=worker.run, name="logcat-sparse-producer")
    producer.start()
    try:
        assert process_started.wait(1)
        started = time.monotonic()
        process.stdout.feed("08-25 12:00:00.000 111 111 I Demo: sparse\n")

        assert batch_ready.wait(0.4)
        assert time.monotonic() - started < 0.4
        assert process.poll() is None
        assert [line[0] for batch in batches for line in batch.lines] == [
            "08-25 12:00:00.000 111 111 I Demo: sparse"
        ]
        assert batches[0].lines[0][1] == "I"
    finally:
        worker.request_stop()
        producer.join(1)
    assert not producer.is_alive()


def test_logcat_helper_start_failure_still_finishes_and_reaps_started_reader():
    worker = LogcatWorker("target")
    process = StreamingProcess()
    terminations = []
    real_thread_start = threading.Thread.start

    def start_process(key, *_args, **_kwargs):
        worker._process_runner._procs[key] = process
        return process

    def fail_pid_helper_start(thread):
        if thread.name.startswith("live-logcat-pid-"):
            raise RuntimeError("pid helper failed to start")
        return real_thread_start(thread)

    worker._process_runner.start = Mock(side_effect=start_process)
    worker.terminated.connect(terminations.append, Qt.ConnectionType.DirectConnection)
    with patch(
        "gui.dialogs.live_logcat_worker.threading.Thread.start",
        new=fail_pid_helper_start,
    ):
        worker.run()

    assert worker._finished_event.is_set()
    assert worker._reader_thread is not None
    assert not worker._reader_thread.is_alive()
    assert process.poll() == 0
    assert terminations[0].kind is LogcatTerminationKind.UNEXPECTED_EXIT
    assert terminations[0].error_type == "RuntimeError"


def test_logcat_package_filter_switches_atomically_and_tracks_all_current_pids():
    package_a = "com.example.alpha"
    package_b = "com.example.beta"
    package_failed = "com.example.failed"
    pid_answers = {
        package_a: CommandResult(True, output="111 112\n", returncode=0),
        package_b: CommandResult(True, output="222\n", returncode=0),
        package_failed: CommandResult(False, error="offline", returncode=1),
    }
    pid_probes = []
    probe_events = {package: threading.Event() for package in pid_answers}
    package_a_rotated = threading.Event()
    rotated_probe = threading.Event()
    worker = LogcatWorker("target", package=package_a)
    worker.PID_REFRESH_SECONDS = 0.02
    process = StreamingProcess()
    process_started = threading.Event()
    started_commands = []
    emitted = []

    def probe_pid(command, **_kwargs):
        package = command[-1]
        pid_probes.append(package)
        probe_events[package].set()
        if package == package_a and package_a_rotated.is_set():
            rotated_probe.set()
        return pid_answers[package]

    def start_process(key, command, **_kwargs):
        worker._process_runner._procs[key] = process
        started_commands.append(tuple(command))
        process_started.set()
        return process

    def collect(batch):
        emitted.extend(text for text, _level, _pid in batch.lines)
        worker.acknowledge_batch()

    worker._process_runner.start = Mock(side_effect=start_process)
    worker.lines_ready.connect(collect, Qt.ConnectionType.DirectConnection)
    producer = threading.Thread(target=worker.run, name="logcat-filter-producer")
    with patch("gui.dialogs.live_logcat_worker.CommandRunner.run", side_effect=probe_pid):
        producer.start()
        try:
            assert process_started.wait(1)
            assert probe_events[package_a].wait(1)
            assert "--pid" not in started_commands[0]

            process.stdout.feed("08-25 12:00:00.000 999 999 I Other: hidden\n")
            process.stdout.feed("08-25 12:00:00.001 111 111 I Alpha: main\n")
            process.stdout.feed("08-25 12:00:00.002 112 112 I Alpha: child\n")
            assert _wait_until(lambda: any("Alpha: child" in line for line in emitted))
            assert any("Alpha: main" in line for line in emitted)
            assert not any("Other: hidden" in line for line in emitted)

            before_pid_rotation = len(emitted)
            pid_answers[package_a] = CommandResult(True, output="113\n", returncode=0)
            package_a_rotated.set()
            assert rotated_probe.wait(1)
            assert _wait_until(lambda: worker._package_snapshot()[2] == frozenset({113}))
            process.stdout.feed("08-25 12:00:00.003 111 111 I Alpha: stale-pid\n")
            process.stdout.feed("08-25 12:00:00.004 113 113 I Alpha: restarted\n")
            assert _wait_until(lambda: any("Alpha: restarted" in line for line in emitted))
            rotated_lines = emitted[before_pid_rotation:]
            assert not any("Alpha: stale-pid" in line for line in rotated_lines)

            worker.update_package(package_b)
            process.stdout.feed("08-25 12:00:01.000 999 999 I Other: wake probe\n")
            assert probe_events[package_b].wait(1)
            process.stdout.feed("08-25 12:00:01.001 111 111 I Alpha: old-after-switch\n")
            process.stdout.feed("08-25 12:00:01.002 222 222 I Beta: new-after-switch\n")
            assert _wait_until(lambda: any("Beta: new-after-switch" in line for line in emitted))
            assert not any("Alpha: old-after-switch" in line for line in emitted)

            before_failed_switch = len(emitted)
            worker.update_package(package_failed)
            process.stdout.feed("08-25 12:00:02.000 999 999 I Other: retry probe\n")
            assert probe_events[package_failed].wait(1)
            process.stdout.feed("08-25 12:00:02.001 222 222 I Beta: stale-pid\n")
            process.stdout.feed("08-25 12:00:02.002 333 333 I Failed: must-not-leak\n")
            time.sleep(worker.BATCH_INTERVAL_SECONDS * 2 + 0.05)
            assert emitted[before_failed_switch:] == []
        finally:
            worker.request_stop()
            producer.join(1)

    assert not producer.is_alive()
    assert package_a in pid_probes
    assert package_b in pid_probes
    assert package_failed in pid_probes


def test_logcat_package_switch_drops_unattributed_lines_and_stale_batches():
    worker = LogcatWorker("target", package="com.example.alpha")
    package, generation, _pids = worker._package_snapshot()
    assert worker._commit_filter_pids(package, generation, frozenset({111}))
    accepted = worker._filtered_line(
        "08-25 12:00:00.000 111 111 I Alpha: before-switch",
        generation,
    )

    assert accepted is not None
    assert worker._filtered_line("    unrelated output without PID", generation) is None

    emitted = []
    worker.lines_ready.connect(emitted.append, Qt.ConnectionType.DirectConnection)
    assert worker.update_package("com.example.beta") is True
    worker._emit_batch([accepted], generation=generation)

    assert emitted == []


def test_live_logcat_page_acknowledges_but_ignores_stale_filter_batch():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    worker = LogcatWorker("target", package="com.example.alpha")
    stale_generation = worker.filter_generation
    assert worker.update_package("com.example.beta") is True
    worker._inflight_batches = 1
    dialog.worker = worker

    try:
        dialog._on_lines(
            worker,
            LogcatBatch(
                (("08-25 12:00:00.000 111 111 I Alpha: stale", "I", 111),),
                generation=stale_generation,
            ),
        )

        assert worker._inflight_batches == 0
        assert not dialog.entries
    finally:
        worker._finished_event.set()
        dialog.worker = None
        dialog.close()


def test_live_logcat_package_switch_discards_old_generation_pending_ui_lines():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    worker = LogcatWorker("target", package="com.example.alpha")
    dialog.worker = worker
    dialog.activate()

    try:
        dialog._on_lines(
            worker,
            LogcatBatch(
                (("08-25 12:00:00.000 111 111 I Alpha: pending-old", "I", 111),),
                generation=worker.filter_generation,
            ),
        )
        assert dialog._pending_visible_lines
        assert dialog._line_flush_timer.isActive()

        dialog._on_current_pkg("com.example.beta")

        assert worker.package == "com.example.beta"
        assert not dialog._pending_visible_lines
        assert not dialog._line_flush_timer.isActive()
        dialog._flush_pending_lines()
        assert "pending-old" not in dialog.output.toPlainText()
    finally:
        worker._finished_event.set()
        dialog.worker = None
        dialog.close()


def test_logcat_producer_batches_lines_and_bounds_each_transport_message():
    worker = LogcatWorker("target")
    process = FakeProcess([f"line {index}\n" for index in range(250)], returncode=7)
    batches = []
    terminations = []
    worker.lines_ready.connect(batches.append)
    worker.terminated.connect(terminations.append)

    with (
        patch.object(worker._process_runner, "start", return_value=process),
        patch.object(worker._process_runner, "stop"),
    ):
        worker.run()

    assert len(batches) == 3
    assert sum(len(batch.lines) for batch in batches) == 250
    assert all(len(batch.lines) <= worker.BATCH_SIZE for batch in batches)
    assert terminations[0].kind is LogcatTerminationKind.UNEXPECTED_EXIT
    assert terminations[0].exit_code == 7


def test_cross_thread_burst_keeps_transport_bounded():
    _app = QApplication.instance() or QApplication([])
    worker = LogcatWorker("target")
    process = YieldingProcess([f"line {index}\n" for index in range(1000)])
    observed_inflight = []
    original_emit_batch = worker._emit_batch

    def emit_batch(lines, *, generation=None):
        original_emit_batch(lines, generation=generation)
        observed_inflight.append(worker._inflight_batches)
        worker.acknowledge_batch()

    def start_process(key, *_args, **_kwargs):
        worker._process_runner._procs[key] = process
        return process

    worker._emit_batch = emit_batch
    worker._process_runner.start = Mock(side_effect=start_process)
    producer = threading.Thread(target=worker.run, name="logcat-burst-producer")
    producer.start()
    producer.join(timeout=2)

    assert not producer.is_alive()
    assert observed_inflight
    assert max(observed_inflight) <= worker.MAX_INFLIGHT_BATCHES
    assert worker._dropped_lines == 0


def test_logcat_transport_drops_instead_of_growing_unbounded():
    worker = LogcatWorker("target")
    emitted = []
    worker.lines_ready.connect(emitted.append)

    for index in range(worker.MAX_INFLIGHT_BATCHES + 3):
        worker._emit_batch([(f"line {index}", "I", 0)])

    assert len(emitted) == worker.MAX_INFLIGHT_BATCHES
    assert worker._dropped_lines == 3


def test_logcat_transport_resumes_and_reports_drops_after_ack():
    worker = LogcatWorker("target")
    emitted = []
    dropped = []
    worker.lines_ready.connect(emitted.append)
    worker.dropped_ready.connect(dropped.append)

    for index in range(worker.MAX_INFLIGHT_BATCHES + 2):
        worker._emit_batch([(f"line {index}", "I", 0)])
    worker.acknowledge_batch()
    worker._emit_batch([("resumed", "I", 0)])
    worker._emit_remaining_drop_count()

    assert len(emitted) == worker.MAX_INFLIGHT_BATCHES + 1
    assert emitted[-1].dropped_before == 2
    assert dropped == []
    assert worker._inflight_batches <= worker.MAX_INFLIGHT_BATCHES


def test_late_old_worker_finished_cannot_clear_new_worker():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    old_worker = LogcatWorker("target")
    new_worker = LogcatWorker("target")
    new_worker._finished_event.set()
    dialog.worker = new_worker

    try:
        dialog._on_worker_finished(old_worker)

        assert dialog.worker is new_worker
    finally:
        dialog.close()


def test_worker_finished_does_not_unregister_a_surviving_process():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    worker = LogcatWorker("target")
    task_id = "surviving-process"
    worker._supervisor_task_id = task_id
    worker._finished_event.set()
    process = Mock()
    process.poll.return_value = None
    worker._process_runner._procs[worker._process_key] = process
    adapter.supervisor.register(
        task_id,
        owner_id=dialog._supervisor_owner_id,
        kind="live_logcat",
        request_stop=worker.request_stop,
        wait=worker.wait_for_stop,
        is_running=worker.is_active,
        force_stop=worker.force_stop,
    )
    dialog.worker = worker
    dialog._supervisor_task_id = task_id

    dialog._on_worker_finished(worker)

    assert adapter.supervisor.active_count == 1
    assert adapter.supervisor.active_snapshot()[0].running is True

    def force_stop(_key, _timeout):
        process.poll.return_value = 0
        worker._process_runner._procs.clear()
        return True

    worker._process_runner.force_stop = Mock(side_effect=force_stop)
    result = adapter.supervisor.stop(
        task_id,
        graceful_timeout=0,
        force_timeout=0,
    )

    assert result.disposition is StopDisposition.FORCED
    assert adapter.supervisor.active_count == 0
    dialog.close()


def test_task_stop_callback_releases_worker_after_process_exits_late():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    worker = LogcatWorker("target")
    task_id = "late-process-exit"
    worker._supervisor_task_id = task_id
    worker._finished_event.set()
    process = Mock()
    process.poll.return_value = None
    worker._process_runner._procs[worker._process_key] = process
    dialog.worker = worker
    dialog._supervisor_task_id = task_id

    dialog._on_worker_finished(worker)
    assert dialog.worker is worker
    assert dialog._worker_release_timer.isActive()

    process.poll.return_value = 0
    worker._process_runner._procs.clear()
    dialog._on_task_stopped(
        TaskStopResult(
            task_id=task_id,
            owner_id=dialog._supervisor_owner_id,
            disposition=StopDisposition.GRACEFUL,
        )
    )

    assert dialog.worker is None
    assert dialog._supervisor_task_id is None
    assert dialog.start_btn.isEnabled()
    assert not dialog.stop_btn.isEnabled()
    dialog.close()


def test_disconnect_clears_page_capturing_handlers_from_orphan_worker():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    worker = LogcatWorker("target")
    worker._dialog_lines_handler = lambda _batch: dialog.objectName()
    worker._dialog_dropped_handler = lambda _count: dialog.objectName()
    worker._dialog_status_handler = lambda _message: dialog.objectName()
    worker._dialog_ended_handler = lambda _result: dialog.objectName()
    worker._dialog_finished_handler = lambda: dialog.objectName()

    dialog._disconnect_worker(worker)

    assert worker._dialog_lines_handler is None
    assert worker._dialog_dropped_handler is None
    assert worker._dialog_status_handler is None
    assert worker._dialog_ended_handler is None
    assert worker._dialog_finished_handler is None
    worker._finished_event.set()
    dialog.close()


def test_page_reports_graceful_forced_and_orphan_cleanup_distinctly():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    dialog._supervisor_task_id = "task"
    messages = []
    dialog.status_bar.setText = messages.append

    try:
        for disposition in (
            StopDisposition.GRACEFUL,
            StopDisposition.FORCED,
            StopDisposition.TIMED_OUT,
        ):
            dialog._on_task_stopped(
                TaskStopResult(
                    task_id="task",
                    owner_id=dialog._supervisor_owner_id,
                    disposition=disposition,
                )
            )
    finally:
        dialog._supervisor_task_id = None
        dialog.close()

    assert messages == [
        "采集已停止",
        "已强制停止采集",
        "停止采集超时；任务仍受监督，请等待清理完成",
    ]


def test_page_acknowledges_late_batch_without_touching_closed_ui():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    worker = LogcatWorker("target")
    worker._inflight_batches = 1
    dialog.worker = worker
    dialog._closing = True

    dialog._on_lines(worker, LogcatBatch((("line", "I", 0),)))

    assert worker._inflight_batches == 0
    assert not dialog.entries
    worker._finished_event.set()
    dialog.close()


def test_queued_logcat_close_is_cancelled_when_page_is_destroyed(qt_application):
    """资源归零后的排队关闭不得晚于页面销毁再次调用旧窗口。"""
    from shiboken6 import delete

    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatPage(device_ip="target", task_supervisor=adapter)
    dialog._close_pending = True
    queued_close = Mock()
    dialog.close = queued_close
    assert dialog._try_finalize_close("test") is True

    delete(dialog)
    qt_application.processEvents()
    queued_close.assert_not_called()
