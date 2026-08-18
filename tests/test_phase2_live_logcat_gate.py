import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMainWindow

from adblab.application.supervision import (
    StopDisposition,
    TaskStopResult,
    TaskSupervisor,
)
from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from gui.dialogs.live_logcat import (
    LiveLogcatDialog,
    LogcatBatch,
    LogcatTerminationKind,
    LogcatWorker,
)
from gui.main_frame import MainFrame
from models.base.command_runner import CommandResult
from models.base.process_runner import ProcessRunner


class FakeQtTaskSupervisor(QObject):
    task_stopped = Signal(object)
    owner_stopped = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.supervisor = TaskSupervisor()
        self.stop_requests = []
        self.owner_stop_requests = []

    def stop_async(self, task_id, **_kwargs):
        self.stop_requests.append(task_id)

    def stop_owner_async(self, owner_id, **_kwargs):
        self.owner_stop_requests.append(owner_id)


class FakeDialogWorker(QObject):
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
        force_stop=lambda _timeout: forced_running.__setitem__(0, False) is None,
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
    dialog = LiveLogcatDialog(device_ip="target", task_supervisor=adapter)
    worker = FakeDialogWorker()
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


def test_active_logcat_close_keeps_main_window_open_until_cleanup_finishes():
    _app = QApplication.instance() or QApplication([])
    main_window = QMainWindow()
    main_window.show()
    adapter = FakeQtTaskSupervisor()
    log_service = Mock()
    dialog = LiveLogcatDialog(
        parent=main_window,
        device_ip="target",
        task_supervisor=adapter,
        log_service=log_service,
    )
    worker = FakeDialogWorker()
    dialog.worker = worker
    dialog._supervisor_task_id = "task"
    dialog.setAttribute(Qt.WA_DeleteOnClose, False)
    dialog.show()

    assert not dialog.testAttribute(Qt.WA_QuitOnClose)
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


def test_owner_timeout_keeps_logcat_dialog_alive_until_worker_really_finishes():
    _app = QApplication.instance() or QApplication([])
    main_window = QMainWindow()
    main_window.show()
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatDialog(
        parent=main_window,
        device_ip="target",
        task_supervisor=adapter,
    )
    worker = FakeDialogWorker()
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
    dialog = LiveLogcatDialog(
        parent=main_window,
        device_ip="target",
        task_supervisor=adapter,
    )
    worker = FakeDialogWorker()
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


def test_real_qthread_dialog_close_reaps_blocking_process_off_gui_thread():
    _app = QApplication.instance() or QApplication([])
    adapter = QtTaskSupervisor()
    dialog = LiveLogcatDialog(device_ip="target", task_supervisor=adapter)
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


def test_logcat_pid_probe_failure_is_start_failure_without_spawn():
    worker = LogcatWorker("target", package="package")
    terminations = []
    worker.terminated.connect(terminations.append)

    with (
        patch(
            "gui.dialogs.live_logcat.CommandRunner.run",
            return_value=CommandResult(False, error="offline", returncode=1),
        ),
        patch.object(worker._process_runner, "start") as start,
        patch.object(worker._process_runner, "stop"),
    ):
        worker.run()

    start.assert_not_called()
    assert terminations[0].kind is LogcatTerminationKind.START_FAILED
    assert terminations[0].error_type == "PidProbeFailed"


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

    def emit_batch(lines):
        original_emit_batch(lines)
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
    dialog = LiveLogcatDialog(device_ip="target", task_supervisor=adapter)
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
    dialog = LiveLogcatDialog(device_ip="target", task_supervisor=adapter)
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


def test_disconnect_clears_dialog_capturing_handlers_from_orphan_worker():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatDialog(device_ip="target", task_supervisor=adapter)
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


def test_dialog_reports_graceful_forced_and_orphan_cleanup_distinctly():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatDialog(device_ip="target", task_supervisor=adapter)
    dialog._supervisor_task_id = "task"
    messages = []
    dialog.status_bar.showMessage = messages.append

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
        "Logcat stopped",
        "Logcat force-stopped",
        "Logcat cleanup timed out; task remains supervised",
    ]


def test_dialog_acknowledges_late_batch_without_touching_closed_ui():
    _app = QApplication.instance() or QApplication([])
    adapter = FakeQtTaskSupervisor()
    dialog = LiveLogcatDialog(device_ip="target", task_supervisor=adapter)
    worker = LogcatWorker("target")
    worker._inflight_batches = 1
    dialog.worker = worker
    dialog._closing = True

    dialog._on_lines(worker, LogcatBatch((("line", "I", 0),)))

    assert worker._inflight_batches == 0
    assert dialog.entries == []
    worker._finished_event.set()
    dialog.close()


def test_mainframe_composition_root_injects_owned_supervisor_into_logcat_dialogs():
    frame = MainFrame.__new__(MainFrame)
    frame.task_supervisor = object()
    frame._show_device_dialogs = Mock()

    MainFrame._show_logcat(frame)

    frame._show_device_dialogs.assert_called_once_with(
        LiveLogcatDialog,
        task_supervisor=frame.task_supervisor,
        log_service=None,
    )


def test_mainframe_does_not_reopen_a_logcat_dialog_that_is_closing():
    frame = MainFrame.__new__(MainFrame)
    frame._active_dialogs = []
    dialog = Mock()
    dialog._closing = True
    dialog.property.side_effect = lambda name: {
        "dialog_class": LiveLogcatDialog.__name__,
        "device_ip": "target",
    }[name]
    frame._active_dialogs.append(dialog)

    match = MainFrame._find_active_dialog(frame, LiveLogcatDialog, "target")

    assert match is None
    assert frame._active_dialogs == [dialog]
    dialog.show.assert_not_called()
