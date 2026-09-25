"""配对协调器的请求隔离、二维码显示确认与真实资源退出屏障。"""

import threading

import pytest
from PySide6.QtTest import QSignalSpy

from adblab.presentation.qt_adb_pairing import QtAdbPairing
from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from services.adb_pairing import (
    PairingContext,
    PairingContinuation,
    PairingOutcome,
    PairingProgress,
)
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


class Scope:
    def __init__(self):
        self.running = False
        self.stopped = False

    def request_stop(self):
        self.stopped = True

    def is_running(self):
        return self.running

    def wait(self, timeout):
        return not self.running


@pytest.fixture
def pairing(qt_application, tmp_path):
    services = []
    scopes = []

    def service_factory():
        return services.pop(0)

    def scope_factory():
        scope = Scope()
        scopes.append(scope)
        return scope

    supervisor = QtTaskSupervisor()
    coordinator = QtAdbPairing(
        supervisor,
        service_factory=service_factory,
        scope_factory=scope_factory,
        context_factory=lambda revision: PairingContext(str(tmp_path / "adb.exe"), {}, revision),
    )
    yield coordinator, services, scopes, supervisor
    coordinator.prepare_shutdown()
    for scope in scopes:
        scope.running = False
    supervisor.stop_all_async(deadline=1)
    wait_until(qt_application, lambda: not coordinator.busy)
    coordinator.deleteLater()
    supervisor.deleteLater()


class WaitService:
    def __init__(self, state="Pairing"):
        self.entered = threading.Event()
        self.state = state
        self.request = None

    def run(self, request, context, cancel_event, command_scope, on_progress, on_qr):
        self.request = request
        self.entered.set()
        on_progress(PairingProgress(request.request_id, self.state))
        assert cancel_event.wait(5)
        return PairingOutcome(
            request.request_id,
            context.context_revision,
            True,
            True,
            "",
            "Connected",
            guid="guid",
            device_id="test-transport",
        )


def test_cancel_rejects_late_success_and_blocks_duplicate_start(pairing, qt_application):
    coordinator, services, _scopes, _supervisor = pairing
    service = WaitService()
    services.append(service)
    connected = QSignalSpy(coordinator.connected)
    assert coordinator.start_code("192.0.2.1:37123", "001234")
    wait_until(qt_application, service.entered.is_set)
    assert not coordinator.start_qr()
    coordinator.cancel()
    wait_until(qt_application, lambda: not coordinator.busy)
    assert connected.count() == 0
    assert coordinator.continuation is None
    assert coordinator.state == "Idle"


def test_finished_thread_with_live_scope_keeps_admission_closed(pairing, qt_application):
    coordinator, services, scopes, supervisor = pairing

    class Residual:
        def run(self, request, context, cancel_event, command_scope, on_progress, on_qr):
            command_scope.running = True
            return PairingOutcome(
                request.request_id,
                context.context_revision,
                None,
                False,
                "cleanup_failed",
                "CleanupFailed",
            )

    services.append(Residual())
    assert coordinator.start_qr()
    coordinator.register_shutdown_tasks(supervisor.supervisor)
    coordinator.register_shutdown_tasks(supervisor.supervisor)
    assert supervisor.supervisor.active_count == 1
    wait_until(qt_application, lambda: coordinator.state == "CleanupFailed")
    assert coordinator.busy
    assert not coordinator.start_qr()
    scopes[0].running = False
    coordinator.retry_stop()
    wait_until(qt_application, lambda: not coordinator.busy)
    assert supervisor.supervisor.active_count == 0


def test_invalidation_clears_continuation_without_active_worker(pairing, qt_application):
    coordinator, services, _scopes, _supervisor = pairing

    class Paired:
        def run(self, request, context, cancel_event, command_scope, on_progress, on_qr):
            return PairingOutcome(
                request.request_id,
                context.context_revision,
                True,
                False,
                "connection_timeout",
                "PairedOnly",
                guid="guid",
                continuation=PairingContinuation("guid", context),
            )

    services.append(Paired())
    assert coordinator.start_code("192.0.2.1:37123", "001234")
    wait_until(qt_application, lambda: not coordinator.busy)
    assert coordinator.continuation is not None
    coordinator.invalidate("client_changed")
    assert coordinator.continuation is None
    assert not coordinator.continue_connection("192.0.2.1:42222")
    assert coordinator.reason == "context_changed"


def test_qr_acknowledgement_is_required_and_cancellation_wakes_waiter(pairing, qt_application):
    coordinator, services, _scopes, _supervisor = pairing
    observations = []

    class QR:
        def run(self, request, context, cancel_event, command_scope, on_progress, on_qr):
            observations.append(on_qr(request.request_id, b"png", 37, 5))
            return PairingOutcome(
                request.request_id, context.context_revision, None, False, "cancelled", "Idle"
            )

    services.append(QR())
    qr = QSignalSpy(coordinator.qr_ready)
    assert coordinator.start_qr()
    wait_until(qt_application, lambda: qr.count() == 1)
    assert observations == []
    coordinator.cancel()
    wait_until(qt_application, lambda: not coordinator.busy)
    assert observations == [False]


def test_connected_is_delivered_once_only_after_resources_are_idle(pairing, qt_application):
    coordinator, services, _scopes, _supervisor = pairing

    class Success:
        def run(self, request, context, cancel_event, command_scope, on_progress, on_qr):
            return PairingOutcome(
                request.request_id,
                context.context_revision,
                True,
                True,
                "",
                "Connected",
                guid="guid",
                device_id="test-transport",
                connection_endpoint="192.0.2.1:42222",
            )

    services.append(Success())
    observations = []
    coordinator.connected.connect(
        lambda outcome: observations.append(
            (coordinator.busy, coordinator.accepts_outcome(outcome))
        )
    )
    assert coordinator.start_qr()
    wait_until(qt_application, lambda: not coordinator.busy)
    assert observations == [(False, True)]


@pytest.mark.parametrize("acknowledged", [False, True])
def test_qr_ack_is_bounded_and_context_resolution_is_background(
    pairing,
    qt_application,
    acknowledged,
    tmp_path,
):
    coordinator, services, _scopes, _supervisor = pairing
    observations = []
    threads = []
    gui_thread = threading.get_ident()

    def context(revision):
        threads.append(threading.get_ident())
        return PairingContext(str(tmp_path / "adb.exe"), {}, revision)

    class QR:
        def run(self, request, context, cancel_event, command_scope, on_progress, on_qr):
            observations.append(on_qr(request.request_id, b"png", 37, 0.1))
            return PairingOutcome(
                request.request_id,
                context.context_revision,
                None,
                False,
                "scan_timeout",
                "Failed",
            )

    coordinator._context_factory = context
    services.append(QR())
    if acknowledged:
        coordinator.qr_ready.connect(
            lambda request, _png, _modules: coordinator.acknowledge_qr(request)
        )
    assert coordinator.start_qr()
    worker = coordinator._worker
    wait_until(qt_application, lambda: not coordinator.busy)
    assert observations == [acknowledged]
    assert threads and threads[0] != gui_thread
    assert worker.request is None


def test_application_shutdown_takes_over_owner_stop_without_missing_signal(pairing, qt_application):
    coordinator, services, _scopes, supervisor = pairing
    service = WaitService()
    services.append(service)
    outcomes = QSignalSpy(coordinator.connected)
    assert coordinator.start_code("192.0.2.1:37123", "001234")
    wait_until(qt_application, service.entered.is_set)
    assert supervisor.begin_application_shutdown()
    coordinator.register_shutdown_tasks(supervisor.supervisor)
    coordinator.prepare_shutdown()
    coordinator.cancel()
    assert supervisor.supervisor.active_count == 1
    assert supervisor.stop_all_async(deadline=1)
    wait_until(qt_application, lambda: not coordinator.busy)
    assert supervisor.supervisor.active_count == 0
    assert outcomes.count() == 0
    assert not coordinator.start_qr()


def test_thread_start_failure_releases_registration_without_secret(
    pairing,
    qt_application,
    monkeypatch,
):
    from adblab.presentation.qt_adb_pairing import _PairingWorker

    coordinator, _services, _scopes, supervisor = pairing
    workers = []

    def fail_start(worker):
        workers.append(worker)
        raise RuntimeError("start rejected")

    monkeypatch.setattr(_PairingWorker, "start", fail_start)
    assert coordinator.start_code("192.0.2.1:37123", "001234")
    assert coordinator.state == "Failed"
    assert not coordinator.busy
    assert workers[0].request is None
    assert supervisor.supervisor.active_count == 0


def test_success_state_waits_for_scope_cleanup_before_display(pairing, qt_application):
    coordinator, services, scopes, _supervisor = pairing
    states = []

    class SuccessWithResidual:
        def run(self, request, context, cancel_event, command_scope, on_progress, on_qr):
            command_scope.running = True
            on_progress(PairingProgress(request.request_id, "Connected"))
            return PairingOutcome(
                request.request_id,
                context.context_revision,
                True,
                True,
                "",
                "Connected",
                device_id="test-transport",
            )

    services.append(SuccessWithResidual())
    coordinator.progress.connect(lambda progress: states.append(progress.state))
    assert coordinator.start_qr()
    wait_until(qt_application, lambda: coordinator.state == "CleanupFailed")
    assert "Connected" not in states
    scopes[0].running = False
    coordinator.retry_stop()
    wait_until(qt_application, lambda: not coordinator.busy)
    assert states[-1] == "Connected"


def test_application_completion_does_not_release_owner_still_using_worker(
    pairing,
    qt_application,
    monkeypatch,
):
    coordinator, services, _scopes, supervisor = pairing
    service = WaitService()
    services.append(service)
    monkeypatch.setattr(supervisor, "stop_owner_async", lambda *_args, **_kwargs: True)
    assert coordinator.start_code("192.0.2.1:37123", "001234")
    wait_until(qt_application, service.entered.is_set)
    worker = coordinator._worker
    coordinator.cancel()
    wait_until(qt_application, lambda: not worker.isRunning())
    coordinator._application_stopped((), ())
    assert coordinator.busy
    assert coordinator._stop_inflight
    coordinator._owner_stopped(coordinator._owner_id, ())
    assert not coordinator.busy


def test_application_waiter_retains_worker_until_application_completed(
    pairing,
    qt_application,
    monkeypatch,
):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    from adblab.presentation.qt_adb_pairing import _PairingResources

    coordinator, services, _scopes, supervisor = pairing
    service_release = threading.Event()
    service_entered = threading.Event()
    wait_entered = threading.Event()
    wait_release = threading.Event()

    class DelayedCancel:
        def run(self, request, context, cancel_event, command_scope, on_progress, on_qr):
            service_entered.set()
            assert service_release.wait(2)
            return PairingOutcome(
                request.request_id,
                context.context_revision,
                None,
                False,
                "cancelled",
                "Idle",
            )

    def controlled_wait(resources, timeout):
        service_release.set()
        resources.worker.wait(1000)
        wait_entered.set()
        assert wait_release.wait(2)
        return not resources.worker.isRunning() and resources.scope.wait(timeout)

    monkeypatch.setattr(_PairingResources, "wait", controlled_wait)
    services.append(DelayedCancel())
    assert coordinator.start_qr()
    worker = coordinator._worker
    wait_until(qt_application, service_entered.is_set)
    supervisor.begin_application_shutdown()
    coordinator.prepare_shutdown()
    supervisor.stop_all_async(deadline=2)
    try:
        wait_until(qt_application, wait_entered.is_set)
        qt_application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert coordinator.busy
        assert isValid(worker)
    finally:
        wait_release.set()
    wait_until(qt_application, lambda: not coordinator.busy)
    assert supervisor.supervisor.active_count == 0
