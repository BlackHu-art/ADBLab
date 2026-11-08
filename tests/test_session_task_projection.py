"""验证持续资源投影、旧版本停止隔离及真实 owner 的释放屏障。"""

import gc
import importlib
import importlib.util
import threading
import time
import weakref
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.test_remote_sessions import remote_session as remote_session
from tests.ui_geometry_helpers import wait_until


def _api():
    assert importlib.util.find_spec("gui.session_tasks") is not None, "持续会话投影尚未实现"
    return importlib.import_module("gui.session_tasks")


class _Owner:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.stops = []

    def task_snapshot(self):
        return self.snapshot

    def request_task_stop(self, expected_revision):
        self.stops.append(expected_revision)
        return True


def test_registry_revalidates_original_owner_revision_and_shutdown():
    api = _api()
    original = _Owner(api.SessionTaskSnapshot(
        "session:opaque", "one", "logcat", "running", True, True, ("设备",),
    ))
    owners = [original]
    registry = api.SessionTaskRegistry(lambda: tuple(owners))
    assert registry.collect() == (original.snapshot,)
    original.snapshot = replace(original.snapshot, revision="two")
    assert not registry.request_stop("session:opaque", "one")
    assert original.stops == []
    assert registry.request_stop("session:opaque", "two")
    assert original.stops == ["two"]
    replacement = _Owner(original.snapshot)
    owners[:] = [replacement]
    assert not registry.request_stop("session:opaque", "two")
    assert replacement.stops == []
    registry.collect()
    assert registry.request_stop("session:opaque", "two")
    registry.shutdown()
    assert registry.collect() == ()
    assert not registry.request_stop("session:opaque", "two")


def test_registry_routes_are_weak_and_disabled_or_released_resources_do_not_stop():
    api = _api()
    snapshot = api.SessionTaskSnapshot(
        "session:opaque", "run", "performance", "failed", True, False, ("设备",),
    )
    owner = _Owner(snapshot)
    owners = [owner]
    registry = api.SessionTaskRegistry(lambda: tuple(owners))
    assert registry.collect()[0].resource_owned
    assert not registry.request_stop(snapshot.key, snapshot.revision)
    owner.snapshot = replace(snapshot, stop_enabled=True, resource_owned=False)
    assert not registry.request_stop(snapshot.key, snapshot.revision)
    reference = weakref.ref(owner)
    owners.clear()
    del owner
    gc.collect()
    assert reference() is None
    assert registry.collect() == ()


def test_registry_label_override_preserves_identity_and_original_stop_route():
    api = _api()
    snapshot = api.SessionTaskSnapshot(
        "session:opaque", "run", "logcat", "running", True, True, ("设备",),
    )
    owner = _Owner(snapshot)
    registry = api.SessionTaskRegistry(lambda: (owner,), labels=lambda _owner: ("设备 2",))
    projected = registry.collect()[0]
    assert projected == replace(snapshot, target_labels=("设备 2",))
    assert owner.snapshot == snapshot
    assert registry.request_stop(projected.key, projected.revision)
    assert owner.stops == ["run"]


@pytest.fixture
def performance_page(qt_application):
    from gui.features.performance.page import PerformancePage

    page = PerformancePage("synthetic-private-device", "com.example.task")
    original_runner = page._runner
    yield page
    page._runner = original_runner
    page._run_controller._start_worker = None
    page._stop_thread = None
    page._runner_finished_handled = True
    page._result_loader._workers.clear()
    page.request_dispose()
    wait_until(qt_application, lambda: page._dispose_ready_state)
    page.close()


def _performance_run(page, monkeypatch, *, resources=True, running=True):
    from services.mobileperf_runner import MobilePerfResourceSnapshot
    from services.performance.config import MobilePerfRunConfig

    state = SimpleNamespace(resources=resources, running=running)
    page._run_controller._generation += 1
    page._library_controller.begin(MobilePerfRunConfig(
        device_id="synthetic-private-device", package="com.example.task",
    ))
    page._runner = SimpleNamespace(
        has_active_resources=lambda: state.resources,
        is_running=lambda: state.running,
        resource_snapshot=lambda: MobilePerfResourceSnapshot(state.resources, state.running),
    )
    page._set_running(True)
    page._set_status("Running", "running")
    return state


def test_performance_snapshot_keeps_old_residual_and_exact_run_identity(
    performance_page, monkeypatch,
):
    _api()
    page = performance_page
    assert page.task_snapshot() is None
    state = _performance_run(page, monkeypatch)
    first = page.task_snapshot()
    assert first.kind == "performance" and first.resource_owned
    assert first.state == "running" and not first.busy
    assert first.run_id == page._library_controller._active.run_id
    assert "synthetic-private-device" not in repr(first)
    page._set_status("Completed", "completed")
    state.running = False
    residual = page.task_snapshot()
    assert residual.key == first.key and residual.resource_owned
    assert residual.state == "stopping"
    _performance_run(page, monkeypatch)
    second = page.task_snapshot()
    assert second.key == first.key and second.revision != first.revision
    assert second.resource_owned
    stop = Mock()
    monkeypatch.setattr(page, "stop_mobileperf", stop)
    assert not page.request_task_stop(first.revision)
    assert page.request_task_stop(second.revision)
    stop.assert_called_once_with()


def test_performance_start_stop_and_current_result_join_remain_owned(performance_page, monkeypatch):
    _api()
    page = performance_page
    state = _performance_run(page, monkeypatch, resources=False, running=False)
    page._run_controller._start_worker = SimpleNamespace()
    page._set_status("Starting", "starting")
    assert page.task_snapshot().state == "starting"
    page._run_cancel_requested = True
    page._set_status("Stopping", "stopping")
    assert page.task_snapshot().resource_owned
    assert not page.task_snapshot().stop_enabled
    page._run_controller._start_worker = None
    page._stopping = False
    page._set_status("Idle", "idle")
    active = page._library_controller._active
    current = SimpleNamespace(active=active)
    unrelated = SimpleNamespace(active=None)
    page._result_loader._workers[:] = [current, unrelated]
    assert page.task_snapshot().state == "finalizing"
    assert page.task_snapshot().resource_owned
    page._result_loader._workers[:] = [unrelated]
    assert not page.task_snapshot().resource_owned
    assert page.task_snapshot().state == "cancelled"
    state.resources = True
    page._set_status("Stop failed", "warning")
    assert page.task_snapshot().resource_owned
    assert page.task_snapshot().state == "failed"


@pytest.fixture
def logcat_page(qt_application):
    from gui.features.logcat.page import LiveLogcatPage
    from tests.test_phase2_live_logcat_gate import FakeQtTaskSupervisor

    page = LiveLogcatPage(
        device_ip="synthetic-private-device", task_supervisor=FakeQtTaskSupervisor(),
    )
    yield page
    page.worker = None
    page._supervisor_task_id = None
    page.close()


def _logcat_capture(page, *, joined=False):
    from tests.test_phase2_live_logcat_gate import FakePageWorker

    worker = FakePageWorker()
    worker._active = False
    worker.wait = lambda _timeout: joined
    worker._supervisor_task_id = "capture-one"
    page.worker = worker
    page._supervisor_task_id = "capture-one"
    page._set_running_actions(True)
    return worker


def test_logcat_capture_stays_active_until_native_join_not_finished_signal(logcat_page):
    _api()
    page = logcat_page
    assert page.task_snapshot() is None
    worker = _logcat_capture(page)
    first = page.task_snapshot()
    assert first.resource_owned and first.kind == "logcat"
    assert first.state == "running" and not first.busy
    assert "synthetic-private-device" not in repr(first)
    assert not page._release_logcat_worker(worker)
    assert page.task_snapshot().resource_owned
    worker.wait = lambda _timeout: True
    assert page._release_logcat_worker(worker)
    ended = page.task_snapshot()
    assert ended.key == first.key and ended.revision == first.revision
    assert not ended.resource_owned and ended.state == "cancelled"


def test_logcat_timeout_is_failed_but_owned_and_old_stop_revision_is_rejected(
    logcat_page, monkeypatch,
):
    _api()
    from core.tasks.supervision import StopDisposition, TaskStopResult

    page = logcat_page
    _logcat_capture(page)
    original = page.task_snapshot()
    page._on_task_stopped(TaskStopResult(
        "capture-one", page._supervisor_owner_id, StopDisposition.TIMED_OUT,
    ))
    failed = page.task_snapshot()
    assert failed.state == "failed" and failed.resource_owned
    page._supervisor_task_id = "capture-two"
    page._set_running_actions(True)
    next_run = page.task_snapshot()
    stop = Mock()
    monkeypatch.setattr(page, "_stop", stop)
    assert not page.request_task_stop(original.revision)
    assert page.request_task_stop(next_run.revision)
    stop.assert_called_once_with()


def test_remote_preflight_cancel_preserves_batch_until_worker_exits(remote_session, qt_application):
    _api()
    remote, service = remote_session
    assert remote.task_snapshot() is None
    gate = threading.Event()
    service.gates["synthetic-private-device"] = gate
    remote.set_target_devices(["synthetic-private-device"])
    remote._start_scrcpy()
    try:
        wait_until(qt_application, lambda: bool(service.inflight))
        first = remote.task_snapshot()
        assert first.resource_owned and first.state == "starting"
        assert "synthetic-private-device" not in repr(first)
        assert remote.request_task_stop(first.revision)
        pending = remote.task_snapshot()
        assert pending.key == first.key and pending.revision == first.revision
        assert pending.resource_owned and pending.state == "stopping"
        assert not pending.stop_enabled
    finally:
        gate.set()
    wait_until(qt_application, lambda: remote._launch_worker is None)
    assert not remote.task_snapshot().resource_owned
    assert remote.task_snapshot().state == "cancelled"


def test_remote_retry_keeps_one_target_label_and_original_batch_revision(
    remote_session, qt_application,
):
    _api()
    remote, service = remote_session
    gate = threading.Event()
    service.gates["synthetic-private-device"] = gate
    remote.set_target_devices(["synthetic-private-device"])
    remote._start_scrcpy()
    try:
        wait_until(qt_application, lambda: bool(service.inflight))
        first = remote.task_snapshot()
        remote._stop_device_scrcpy("synthetic-private-device")
        remote._retry_device_scrcpy("synthetic-private-device")
        retried = remote.task_snapshot()
        assert retried.resource_owned and retried.revision == first.revision
        assert len(retried.target_labels) == 1
    finally:
        gate.set()
    wait_until(qt_application, lambda: remote._launch_worker is None)


def test_remote_failed_stop_and_tail_threads_keep_batch_active_and_old_revision_cannot_stop_new(
    remote_session, qt_application, monkeypatch,
):
    _api()
    remote, service = remote_session
    remote.set_target_devices(["synthetic-private-device"])
    remote._start_scrcpy()
    wait_until(qt_application, lambda: bool(service.started) and remote._launch_worker is None)
    first = remote.task_snapshot()
    session = remote._device_sessions["synthetic-private-device"]
    session.error_type = "StopFailed"
    assert remote.task_snapshot().state == "failed"
    assert remote.task_snapshot().resource_owned
    session.error_type = ""
    gate = threading.Event()
    tail = threading.Thread(target=gate.wait)
    tail.start()
    remote._scrcpy_threads.append(tail)
    try:
        remote._stop_scrcpy()
        wait_until(qt_application, lambda: not session.resource_owned)
        assert remote.task_snapshot().resource_owned
        assert remote.task_snapshot().key == first.key
    finally:
        gate.set()
        tail.join(1)
    wait_until(qt_application, lambda: not remote.task_snapshot().resource_owned)
    wait_until(qt_application, lambda: remote._session_state == remote._SESSION_IDLE)
    remote._start_scrcpy()
    wait_until(qt_application, lambda: len(service.started) == 2)
    new = remote.task_snapshot()
    assert new.revision != first.revision
    stop = Mock()
    monkeypatch.setattr(remote, "_stop_scrcpy", stop)
    assert not remote.request_task_stop(first.revision)
    assert remote.request_task_stop(new.revision)
    stop.assert_called_once_with()


def test_new_mirror_batch_after_tail_release_rejects_old_stop_without_intermediate_snapshot(
    remote_session, qt_application,
):
    remote, service = remote_session
    remote.set_target_devices(["original"])
    remote._start_scrcpy()
    wait_until(qt_application, lambda: bool(service.started) and remote._launch_worker is None)
    original = remote.task_snapshot()
    gate = threading.Event()
    tail = threading.Thread(target=gate.wait)
    tail.start()
    remote._scrcpy_threads.append(tail)
    try:
        service.processes["original"].finish()
        remote._poll_process()
        assert remote.task_snapshot().resource_owned
    finally:
        gate.set()
        tail.join(1)
    remote._start_scrcpy()
    wait_until(qt_application, lambda: len(service.started) == 2)
    assert remote.task_snapshot().revision != original.revision
    assert not remote.request_task_stop(original.revision)


@pytest.mark.parametrize("stop", [False, True])
def test_performance_projection_and_cancel_do_not_wait_for_startup_io_lock(
    performance_page, stop,
):
    page = performance_page
    page._run_controller._generation = 1
    cancelled = threading.Event()
    page._run_controller._start_worker = SimpleNamespace(abort=cancelled.set)
    entered, release = threading.Event(), threading.Event()

    def hold_startup():
        with page._runner._state_lock:
            entered.set()
            release.wait(.3)

    worker = threading.Thread(target=hold_startup)
    worker.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        if stop:
            assert page.request_task_stop("1")
            assert cancelled.is_set()
        else:
            assert page.task_snapshot().resource_owned
        assert time.monotonic() - started < .05
    finally:
        release.set()
        worker.join(1)


def test_performance_projection_never_polls_owned_process_or_reads_client_directory(
    performance_page, monkeypatch, tmp_path,
):
    from pathlib import Path

    from core.owned_process import OwnedWorkerProcess

    page = performance_page
    runner = page._runner
    page._run_controller._generation = 1
    process = OwnedWorkerProcess(SimpleNamespace(poll=lambda: 0), str(tmp_path))
    old = SimpleNamespace(
        proc=process, threads_submitted=True, process_tracking_released=False,
        config_cleaned=False,
        finished_notified=True, log_thread=None, diagnostic_thread=None, mode_thread=None,
    )
    runner._resource_contexts[:] = [old]
    runner._residual_contexts[:] = [old]
    try:
        with monkeypatch.context() as guard:
            guard.setattr(Path, "iterdir", Mock(side_effect=AssertionError("GUI directory read")))
            guard.setattr(Path, "read_text", Mock(side_effect=AssertionError("GUI JSON read")))
            assert page.task_snapshot().resource_owned
            old.process_tracking_released = True
            old.config_cleaned = True
            runner._residual_contexts.clear()
            assert not page.task_snapshot().resource_owned
    finally:
        runner._resource_contexts.clear()
        runner._residual_contexts.clear()


def test_completed_performance_run_terminal_survives_offline_reconnect_and_deselection(
    performance_page, monkeypatch,
):
    from services.performance.results import PerformanceArtifacts

    page = performance_page
    _performance_run(page, monkeypatch, resources=False, running=False)
    page._run_controller._present_finished_result(
        PerformanceArtifacts(report_file="synthetic-report.html"), True, 0, False,
    )
    finished = page.task_snapshot()
    assert finished.state == "succeeded" and not finished.resource_owned
    for callback, value in (
        (page.set_device_connected, False), (page.set_device_connected, True),
        (page.set_device_selected, False), (page.set_device_selected, True),
    ):
        callback(value)
        current = page.task_snapshot()
        assert current.revision == finished.revision and current.run_id == finished.run_id
        assert current.state == "succeeded"


@pytest.mark.parametrize("after_mirror", [False, True])
def test_independent_remote_input_does_not_create_or_extend_mirror_task(
    remote_session, qt_application, after_mirror,
):
    from concurrent.futures import Future

    remote, service = remote_session
    if after_mirror:
        remote.set_target_devices(["original"])
        remote._start_scrcpy()
        wait_until(qt_application, lambda: bool(service.started) and remote._launch_worker is None)
        remote._stop_scrcpy()
        wait_until(qt_application, lambda: not remote.task_snapshot().resource_owned)
    future = Future()
    remote._track_remote_future(future)
    try:
        if after_mirror:
            assert not remote.task_snapshot().resource_owned
        else:
            assert remote.task_snapshot() is None
    finally:
        future.set_result(None)


def test_bound_mirror_input_tail_keeps_only_original_batch_owned(
    remote_session, qt_application, monkeypatch,
):
    remote, service = remote_session
    remote.set_target_devices(["original"])
    remote._start_scrcpy()
    wait_until(qt_application, lambda: bool(service.started) and remote._launch_worker is None)
    session = remote._device_sessions["original"]
    entered, release = threading.Event(), threading.Event()

    def delayed_key(*_args, **_kwargs):
        entered.set()
        assert release.wait(2)
        return True

    monkeypatch.setattr(remote._remote_control, "send_keyevent", delayed_key)
    remote._input_controller._send_session_keyevent(session, "HOME")
    try:
        assert entered.wait(1)
        original = remote.task_snapshot()
        remote._stop_scrcpy()
        wait_until(qt_application, lambda: not session.resource_owned)
        assert remote.task_snapshot().resource_owned
        assert remote.task_snapshot().revision == original.revision
    finally:
        release.set()
    wait_until(qt_application, lambda: not remote.task_snapshot().resource_owned)


def test_mirror_target_label_uses_original_global_safe_number_after_deselection(
    remote_session, qt_application, monkeypatch,
):
    remote, service = remote_session
    bar = SimpleNamespace(
        device_label=lambda _device: "设备 3 · 安全名称",
        device_display_name=lambda _device: "安全名称",
    )
    monkeypatch.setattr(remote.window(), "_global_device_bar", bar, raising=False)
    remote.set_target_devices(["original-private-target"])
    remote._start_scrcpy()
    wait_until(qt_application, lambda: bool(service.started))
    assert remote.task_snapshot().target_labels == ("设备 3 · 安全名称",)
    remote.set_target_devices([])
    assert remote.task_snapshot().target_labels == ("设备 3 · 安全名称",)
    assert "original-private-target" not in repr(remote.task_snapshot())


def test_stopped_mirror_member_does_not_mark_running_batch_as_stopping(
    remote_session, qt_application,
):
    remote, service = remote_session
    remote.set_target_devices(["first", "second"])
    remote._start_scrcpy()
    wait_until(qt_application, lambda: len(service.started) == 2 and remote._launch_worker is None)
    remote._stop_device_scrcpy("first")
    wait_until(qt_application, lambda: not remote._device_sessions["first"].resource_owned)
    assert remote.task_snapshot().state == "running"
    remaining = remote._device_sessions["second"]
    remaining.error_type = "StopFailed"
    assert remote.task_snapshot().state == "failed"
    remote._stop_device_scrcpy("second")
    wait_until(qt_application, lambda: not remaining.resource_owned)
    wait_until(qt_application, lambda: remote._launch_worker is None)
    assert remote.task_snapshot().state == "cancelled"


def test_rejected_logcat_registration_cannot_rewrite_last_released_capture(
    logcat_page, monkeypatch,
):
    page = logcat_page
    worker = _logcat_capture(page, joined=True)
    original = page.task_snapshot()
    assert page._release_logcat_worker(worker)
    assert page.task_snapshot().state == "cancelled"
    monkeypatch.setattr(
        page._task_supervisor.supervisor, "register", Mock(side_effect=RuntimeError("rejected")),
    )
    page._start()
    rejected = page.task_snapshot()
    assert rejected.revision == original.revision
    assert rejected.state == "cancelled" and not rejected.resource_owned


def test_real_runner_callback_tail_remains_owned_then_publishes_release(
    performance_page, tmp_path,
):
    from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner
    from tests.test_mobileperf_runner_concurrency import (
        _DelayedStream,
        _StoppableProcess,
        _TrackingProcessRunner,
    )

    page = performance_page
    stream = _DelayedStream([])
    process = _StoppableProcess(stream, None)
    runner = MobilePerfRunner(
        process_runner=_TrackingProcessRunner([process]), project_root=tmp_path,
    )
    page._runner = runner
    page._run_controller._generation = 1
    entered, release = threading.Event(), threading.Event()

    def finished():
        entered.set()
        assert release.wait(2)

    runner.start(MobilePerfRunConfig(save_path=str(tmp_path / "results")), on_finished=finished)
    context = runner._active_context
    try:
        process.returncode = 0
        stream.release.set()
        assert entered.wait(1)
        assert context.process_tracking_released
        assert page.task_snapshot().resource_owned
    finally:
        release.set()
        runner._join_context_readers(context, timeout=1)
        runner.stop(timeout=1)
    assert not page.task_snapshot().resource_owned


def test_background_probe_confirms_late_remote_lease_release_without_gui_io_or_chart_change(
    performance_page, qt_application, tmp_path, monkeypatch,
):
    from pathlib import Path

    from core.monkey_process import MonkeyProcessLease
    from core.owned_process import SCOPE_ENV, OwnedWorkerProcess
    from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner
    from tests.test_mobileperf_runner_concurrency import (
        _CountingStream,
        _DelayedStream,
        _StoppableProcess,
        _TrackingProcessRunner,
    )

    scope = tmp_path / "clients"
    scope.mkdir()
    monkeypatch.setenv(SCOPE_ENV, str(scope))
    lease = MonkeyProcessLease()
    lease.command(["monkey", "1"])
    stream = _DelayedStream([])
    process = _StoppableProcess(stream, None)
    wrapped = OwnedWorkerProcess(process, str(scope))

    class StrictTracking(_TrackingProcessRunner):
        def stop(self, key, timeout=0):
            target = self._processes.get(key)
            if target is None:
                return None
            if isinstance(target, OwnedWorkerProcess) and not target.resources_released():
                return None
            code = target.poll()
            if code is not None:
                self._processes.pop(key, None)
            return code

    page = performance_page
    next_process = _StoppableProcess(_CountingStream([]), None)
    next_process.returncode = 0
    runner = MobilePerfRunner(
        process_runner=StrictTracking([wrapped, next_process]), project_root=tmp_path,
    )
    page._runner = runner
    page._run_controller._generation = 1
    done = threading.Event()
    runner.start(MobilePerfRunConfig(save_path=str(tmp_path / "results")), on_finished=done.set)
    context = runner._active_context
    chart = Mock()
    monkeypatch.setattr(page.chart_view, "set_series", chart)
    try:
        process.returncode = 0
        stream.release.set()
        assert done.wait(1)
        runner._join_context_readers(context, timeout=1)
        assert not context.process_tracking_released
        assert page.task_snapshot().resource_owned
        page.refresh_task_snapshot()
        wait_until(qt_application, lambda: not page._result_loader._workers)
        assert page.task_snapshot().resource_owned
        assert lease.stop(lambda _command: f"ADBLAB_MONKEY_STOPPED_{lease.token}")
        reads = []
        original_iterdir = Path.iterdir

        def observed_iterdir(path):
            reads.append(threading.get_ident())
            return original_iterdir(path)

        with monkeypatch.context() as guard:
            guard.setattr(Path, "iterdir", observed_iterdir)
            assert page._result_loader.request_resource_probe()
            wait_until(qt_application, lambda: not page._result_loader._workers)
            pending = page.task_snapshot()
            assert pending.resource_owned and pending.stop_enabled
            assert runner.has_active_resources()
            assert not context.process_tracking_released and not context.config_cleaned
            assert context in runner._residual_contexts
            with pytest.raises(RuntimeError, match="Previous Monkey cleanup"):
                runner.start(MobilePerfRunConfig(save_path=str(tmp_path / "retry")))
        assert reads and threading.get_ident() not in reads
        chart.assert_not_called()
        assert page.request_task_stop(pending.revision)
        wait_until(qt_application, lambda: not runner.has_active_resources())
        wait_until(qt_application, lambda: page._stop_thread is not None
                   and not page._stop_thread.is_alive())
        assert context.process_tracking_released and context.config_cleaned
        assert not runner._residual_contexts
        assert not page.task_snapshot().resource_owned
        assert page.task_snapshot().state == "cancelled"
        assert runner.start(MobilePerfRunConfig(save_path=str(tmp_path / "retry")))
    finally:
        lease.discard_unsubmitted()
        stream.release.set()
        runner.stop(timeout=1)
        wait_until(qt_application, lambda: not page._result_loader._workers)


def test_resource_probe_queue_is_bounded_cancelled_on_new_generation_and_owned_during_close(
    performance_page, qt_application, monkeypatch,
):
    from shiboken6 import isValid

    from services.mobileperf_runner import MobilePerfResourceSnapshot

    page = performance_page
    page._run_controller._generation = 1
    entered, release = threading.Event(), threading.Event()

    def query():
        entered.set()
        assert release.wait(2)
        return MobilePerfResourceSnapshot(False, False)

    monkeypatch.setattr(page._runner, "probe_resource_snapshot", query)
    loader = page._result_loader
    try:
        assert loader.request_resource_probe()
        assert entered.wait(1)
        worker = loader._workers[0]
        assert not loader.request_resource_probe()
        assert len(loader._workers) == 1
        page._run_controller._generation = 2
        loader.invalidate()
        release.set()
        wait_until(qt_application, lambda: not loader._workers)

        assert page._session_task_resources is None
        release.clear()
        entered.clear()
        assert loader.request_resource_probe()
        assert entered.wait(1)
        assert not page.request_dispose()
        assert loader.is_running()
        assert not loader.request_resource_probe()
        release.set()
        wait_until(qt_application, lambda: page._dispose_ready_state)
        assert not loader._workers
        assert page._session_task_resources is None
        wait_until(qt_application, lambda: not isValid(worker))
    finally:
        release.set()
        wait_until(qt_application, lambda: not loader._workers)


def test_new_live_memory_evidence_wins_over_same_generation_prestart_idle_cache(
    performance_page, monkeypatch,
):
    from services.mobileperf_runner import MobilePerfResourceSnapshot

    page = performance_page
    state = _performance_run(page, monkeypatch, resources=False, running=False)
    page._accept_session_resource_snapshot(MobilePerfResourceSnapshot(False, False), 1)
    state.resources = state.running = True
    page._runner_finished_handled = False
    current = page.task_snapshot()
    assert current.resource_owned and current.state == "running" and current.stop_enabled
    state.resources = state.running = False
    page._runner_finished_handled = True
    page._accept_session_resource_snapshot(MobilePerfResourceSnapshot(True, False), 1)
    assert not page.task_snapshot().resource_owned


def test_idle_or_running_owner_does_not_queue_repeated_resource_threads(
    performance_page, monkeypatch,
):
    page = performance_page
    state = _performance_run(page, monkeypatch, resources=False, running=False)
    queued = Mock()
    monkeypatch.setattr(page._result_loader, "request_resource_probe", queued)
    for _ in range(3):
        page.refresh_task_snapshot()
    queued.assert_not_called()
    state.resources = state.running = True
    for _ in range(3):
        page.refresh_task_snapshot()
    queued.assert_not_called()


def test_real_start_handoff_is_not_hidden_by_prestart_probe_idle_cache(
    performance_page, qt_application, tmp_path, monkeypatch,
):
    from services.mobileperf_runner import MobilePerfRunner
    from tests.test_mobileperf_runner_concurrency import (
        _DelayedStream,
        _StoppableProcess,
        _TrackingProcessRunner,
    )

    page = performance_page
    stream = _DelayedStream([])
    process = _StoppableProcess(stream, None)
    runner = MobilePerfRunner(
        process_runner=_TrackingProcessRunner([process]), project_root=tmp_path,
    )
    page._runner = runner
    page.save_path_edit.setText(str(tmp_path / 'results'))
    original_start = runner.start
    entered, release = threading.Event(), threading.Event()

    def delayed_start(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original_start(*args, **kwargs)

    monkeypatch.setattr(runner, 'start', delayed_start)
    page.start_mobileperf()
    try:
        assert entered.wait(1)
        assert page._result_loader.request_resource_probe()
        wait_until(qt_application, lambda: not page._result_loader._workers)
        assert page._session_task_resources[1].resource_owned is False
        release.set()
        wait_until(qt_application, lambda: not page._run_controller.starting)
        memory = runner.resource_snapshot()
        assert memory.resource_owned and memory.running
        projected = page.task_snapshot()
        assert projected.resource_owned and projected.state == 'running'
        assert projected.stop_enabled
    finally:
        release.set()
        process.returncode = 0
        stream.release.set()
        wait_until(qt_application, lambda: not page._run_controller.starting)
        runner.stop(timeout=1)
        wait_until(qt_application, lambda: not page._result_loader._workers)


@pytest.mark.parametrize('stop_before_lease_release', [False, True])
def test_archived_cleanup_stop_retries_and_restarts_through_real_page_controls(
    performance_page, qt_application, tmp_path, monkeypatch, stop_before_lease_release,
):
    from core.monkey_process import MonkeyProcessLease
    from core.owned_process import SCOPE_ENV, OwnedWorkerProcess
    from services.mobileperf_runner import MobilePerfRunner
    from services.performance.results import PerformanceArtifacts
    from tests.test_mobileperf_runner_concurrency import (
        _CountingStream,
        _DelayedStream,
        _StoppableProcess,
        _TrackingProcessRunner,
    )
    from tests.test_performance_library import _Library

    scope = tmp_path / 'clients'
    scope.mkdir()
    monkeypatch.setenv(SCOPE_ENV, str(scope))
    lease = MonkeyProcessLease()
    lease.command(['monkey', '1'])
    stream = _DelayedStream([])
    first_process = _StoppableProcess(stream, None)
    wrapped = OwnedWorkerProcess(first_process, str(scope))
    next_process = _StoppableProcess(_CountingStream([]), None)

    class StrictTracking(_TrackingProcessRunner):
        def stop(self, key, timeout=0):
            target = self._processes.get(key)
            if target is None:
                return None
            if isinstance(target, OwnedWorkerProcess) and not target.resources_released():
                return None
            code = target.poll()
            if code is not None:
                self._processes.pop(key, None)
            return code

    page = performance_page
    runner = MobilePerfRunner(
        process_runner=StrictTracking([wrapped, next_process]), project_root=tmp_path,
    )
    page._runner = runner
    page.save_path_edit.setText(str(tmp_path / 'results'))
    library = _Library()
    page.set_run_library(library)
    monkeypatch.setattr(runner, 'freeze_result_query', lambda: SimpleNamespace(
        discover=lambda: PerformanceArtifacts(report_file='synthetic-report.html'),
    ))
    page.start_btn.click()
    release_tail = threading.Event()
    entered_tail = threading.Event()
    controller = page._run_controller
    original_stop_worker = controller._stop_runner_worker

    def stop_with_notification_tail(*args):
        original_stop_worker(*args)
        entered_tail.set()
        assert release_tail.wait(2)

    try:
        wait_until(qt_application, lambda: not controller.starting)
        original = page.task_snapshot()
        first_process.returncode = 0
        stream.release.set()
        wait_until(qt_application, lambda: len(library.records) == 1
                   and not page._result_loader._workers)
        archived = library.records[0]
        assert page._runner_finished_handled
        if not stop_before_lease_release:
            assert lease.stop(lambda _command: f'ADBLAB_MONKEY_STOPPED_{lease.token}')
        monkeypatch.setattr(controller, '_stop_runner_worker', stop_with_notification_tail)
        assert page.request_task_stop(original.revision)
        assert entered_tail.wait(1)
        qt_application.processEvents()
        assert page._stopping and not page.task_snapshot().stop_enabled
        assert not page.start_btn.isEnabled()
        release_tail.set()
        wait_until(qt_application, lambda: page._stop_thread is not None
                   and not page._stop_thread.is_alive())
        wait_until(qt_application, lambda: not page._stopping)
        monkeypatch.setattr(controller, '_stop_runner_worker', original_stop_worker)
        if stop_before_lease_release:
            retry = page.task_snapshot()
            assert retry.resource_owned and retry.stop_enabled
            assert page.stop_btn.isEnabled() and not page.start_btn.isEnabled()
            assert lease.stop(lambda _command: f'ADBLAB_MONKEY_STOPPED_{lease.token}')
            assert page.request_task_stop(original.revision)
            wait_until(qt_application, lambda: not page._stopping)
        assert not runner.has_active_resources()
        assert not page.task_snapshot().resource_owned
        assert page.start_btn.isEnabled() and not page.stop_btn.isEnabled()
        assert not page._configuration_locked and page._status_state != 'stopping'
        assert library.records == (archived,)
        page.start_btn.click()
        wait_until(qt_application, lambda: controller._generation == 2 and not controller.starting)
        current = page.task_snapshot()
        assert current.resource_owned and current.state == 'running' and current.stop_enabled
        assert page.request_task_stop(current.revision)
        wait_until(qt_application, lambda: not page._stopping
                   and len(library.records) == 2 and not page._result_loader._workers)
        assert not page.task_snapshot().resource_owned
        assert page.task_snapshot().state != 'succeeded'
        assert library.records[0] == archived and library.records[1].state == 'cancelled'
    finally:
        release_tail.set()
        lease.discard_unsubmitted()
        first_process.returncode = 0
        next_process.returncode = 0
        stream.release.set()
        runner.stop(timeout=1)
        wait_until(qt_application, lambda: not controller.starting
                   and (page._stop_thread is None or not page._stop_thread.is_alive())
                   and not page._result_loader._workers)


def test_cleanup_stop_close_waits_for_real_thread_tail_and_rejects_late_delivery(
    performance_page, qt_application, monkeypatch,
):
    from tests.test_performance_start_lifecycle import ControlledRunner

    page = performance_page
    runner = ControlledRunner()
    runner.running = True
    page._runner = runner
    controller = page._run_controller
    controller._generation = 1
    entered, release = threading.Event(), threading.Event()
    original = controller._stop_runner_worker

    def tail(*args):
        original(*args)
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(controller, '_stop_runner_worker', tail)
    page.stop_mobileperf()
    pending = controller._pending_stop
    try:
        assert entered.wait(1)
        qt_application.processEvents()
        assert page._stopping and not page.start_btn.isEnabled()
        assert not page.request_dispose()
        assert not page._dispose_ready_state
        assert not controller._stop_wait_timer.isActive()
        release.set()
        wait_until(qt_application, lambda: page._dispose_ready_state)
        controller._on_stop_done(pending[0], pending[1], False)
        assert controller._pending_stop is None
        assert not controller._stop_wait_timer.isActive()
    finally:
        release.set()
        page._stop_thread.join(1)


def test_old_cleanup_stop_delivery_cannot_change_new_generation_controls(
    performance_page, qt_application, monkeypatch,
):
    from tests.test_performance_start_lifecycle import ControlledRunner

    page = performance_page
    runner = ControlledRunner()
    runner.running = True
    page._runner = runner
    controller = page._run_controller
    controller._generation = 1
    page._record_session_task_terminal("succeeded")
    original = controller._stop_runner_worker
    entered, release = threading.Event(), threading.Event()

    def tail(*args):
        original(*args)
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(controller, '_stop_runner_worker', tail)
    page.stop_mobileperf()
    pending = controller._pending_stop
    try:
        assert entered.wait(1)
        release.set()
        wait_until(qt_application, lambda: not page._stopping)
        assert page.task_snapshot().state == "cancelled"
        assert page._session_task_terminal == (1, "succeeded")
        controller._generation = 2
        runner.running = True
        page._set_running(True)
        controller._on_stop_done(pending[0], pending[1], False)
        assert page.stop_btn.isEnabled() and not page.start_btn.isEnabled()
        assert page._status_state == 'running'
        assert controller._pending_stop is None
        page.stop_mobileperf()
        current_pending = controller._pending_stop
        controller._on_stop_done(pending[0], pending[1], False)
        assert controller._pending_stop is current_pending
        assert page._stopping and not page.start_btn.isEnabled()
        wait_until(qt_application, lambda: not page._stopping)
    finally:
        release.set()
        runner.running = False
        page._stop_thread.join(1)
