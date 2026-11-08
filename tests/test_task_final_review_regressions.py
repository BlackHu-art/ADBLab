"""验证跨代归档、镜像线程及只读投影、失效详情动画的真实交接边界。"""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, QRect, QSize, Qt

from gui.features.performance.page import PerformancePage
from gui.pages.tasks_page import TaskCenterPage
from gui.session_tasks import SessionTaskRegistry
from services.mobileperf_runner import MobilePerfRunConfig
from services.performance.results import PerformanceArtifacts
from services.remote.encoder_probe import ScrcpyEncoderScope
from services.remote.scrcpy_service import ScrcpyService
from services.tasks.operations import OperationState
from tests.test_performance_library import _Library
from tests.test_remote_sessions import remote_session as remote_session
from tests.test_task_feedback import task_feedback as task_feedback
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def test_failed_new_performance_run_keeps_old_archive_until_join(
    qt_application, monkeypatch, tmp_path
):
    page = PerformancePage("test-device", "com.example.offline")
    center = TaskCenterPage(external_details=True)
    page.set_run_library(_Library())
    page.save_path_edit.setText(str(tmp_path / "results"))
    library = page._library_controller
    loader = page._result_loader
    entered, release = threading.Event(), threading.Event()
    at_tail, join_tail = threading.Event(), threading.Event()

    def discover():
        entered.set()
        assert release.wait(5)
        return PerformanceArtifacts("result", "first-report")

    def native_tail():
        at_tail.set()
        join_tail.wait(5)

    try:
        library.begin(MobilePerfRunConfig(package="com.example.first"))
        page._run_controller._generation = 1
        page._runner_finished_handled = False
        monkeypatch.setattr(
            page._runner, "freeze_result_query", lambda: SimpleNamespace(discover=discover)
        )
        page._mark_runner_finished()
        assert entered.wait(1) and page.start_btn.isEnabled()
        archive = loader._workers[0]
        archive.finished.connect(native_tail, Qt.ConnectionType.DirectConnection)
        first = page.task_snapshot()
        center.set_session_snapshots((first,))
        assert first.resource_owned
        monkeypatch.setattr(page._runner, "start", Mock(side_effect=OSError("second start failed")))
        page.start_btn.click()
        wait_until(
            qt_application,
            lambda: page._run_controller._generation == 2 and not page._run_controller.starting,
        )
        failed = page.task_snapshot()
        center.set_session_snapshots((failed,))
        assert loader._workers[0].isRunning() and not loader._workers[0].artifacts_delivered
        assert failed.revision != first.revision and failed.state == "failed"
        assert failed.resource_owned and not failed.stop_enabled
        assert not page.request_task_stop(failed.revision)
        assert (
            center.navigation_snapshot().active_count,
            center.navigation_snapshot().unread_count,
        ) == (1, 1)
        release.set()
        assert at_tail.wait(2)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
        assert archive.artifacts_delivered and not archive.wait(0)
        assert page.task_snapshot() == failed
        join_tail.set()
        wait_until(qt_application, lambda: not loader._workers)
        ended = page.task_snapshot()
        center.set_session_snapshots((ended,))
        assert ended.revision == failed.revision and ended.state == "failed"
        assert not ended.resource_owned and center.navigation_snapshot().success_event_id is None
    finally:
        release.set()
        join_tail.set()
        wait_until(qt_application, lambda: not loader._workers)
        center.shutdown()
        page.request_dispose()
        wait_until(qt_application, lambda: page._dispose_ready_state)
        page.close()


def test_registry_never_checks_client_or_polls_process_on_gui(remote_session, qt_application):
    panel, original = remote_session
    panel.set_target_devices(["original"])
    panel._start_scrcpy()
    wait_until(qt_application, lambda: bool(original.started) and panel._launch_worker is None)
    panel._stop_scrcpy()
    wait_until(qt_application, lambda: not panel.task_snapshot().resource_owned)
    historical_key = panel._device_sessions["original"].key
    service = ScrcpyService()
    scope = ScrcpyEncoderScope("/synthetic/scrcpy", "/synthetic/adb")
    gui_thread = threading.get_ident()
    callers = []
    alive = threading.Event()
    alive.set()
    scanning, resume, scan_timed_out = threading.Event(), threading.Event(), threading.Event()

    class ResidualClient:
        def is_running(self):
            callers.append(threading.get_ident())
            if threading.get_ident() != gui_thread:
                scanning.set()
                if not resume.wait(2):
                    scan_timed_out.set()
            return alive.is_set()

    def exited_process():
        callers.append(threading.get_ident())
        return 0

    service.process_runner._procs[historical_key] = SimpleNamespace(poll=exited_process)
    scope._token = object()
    scope._process = Mock(poll=Mock(return_value=0))
    scope._clients.add(ResidualClient())
    service._encoder_scopes.add(scope)
    panel._scrcpy_service = service
    try:
        registry = SessionTaskRegistry(lambda: (panel,))
        assert registry.collect()[0].resource_owned
        assert scanning.wait(1)
        for _ in range(3):
            (snap,) = registry.collect()
            assert snap.resource_owned
            assert not registry.request_stop(snap.key, "stale")
        assert not scan_timed_out.is_set() and gui_thread not in callers
        alive.clear()
        resume.set()
        wait_until(qt_application, lambda: not registry.collect()[0].resource_owned)
        assert callers and gui_thread not in callers
    finally:
        alive.clear()
        resume.set()
        panel._scrcpy_service = original
        service.process_runner._procs.clear()


def test_finished_preflight_keeps_ownership_until_real_join(remote_session, qt_application):
    panel, service = remote_session
    gate = service.gates["original"] = threading.Event()
    entered, release = threading.Event(), threading.Event()
    panel.set_target_devices(["original"])
    panel._start_scrcpy()
    worker = panel._launch_worker

    def native_tail():
        entered.set()
        release.wait(5)

    try:
        wait_until(qt_application, lambda: bool(service.inflight))
        worker.finished.connect(native_tail, Qt.ConnectionType.DirectConnection)
        before = panel.task_snapshot()
        assert panel.request_task_stop(before.revision)
        gate.set()
        assert entered.wait(2)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
        assert not worker.wait(0)
        pending = panel.task_snapshot()
        assert pending.resource_owned and pending.revision == before.revision
        assert not pending.stop_enabled and pending.state == "stopping"
        assert not service.started
    finally:
        gate.set()
        release.set()
        assert worker.wait(1500)
        wait_until(qt_application, lambda: panel._launch_worker is None)
    assert not panel.task_snapshot().resource_owned
    panel._start_scrcpy()
    wait_until(qt_application, lambda: bool(service.started))
    assert panel.task_snapshot().revision != before.revision
    assert not panel.request_task_stop(before.revision)


@pytest.mark.parametrize("closing", [False, True])
def test_preflight_tail_hands_off_queue_or_shutdown_only_after_join(
    remote_session, qt_application, closing
):
    from core.tasks.supervision import StopDisposition, TaskSupervisor

    panel, service = remote_session
    gate = service.gates["first"] = threading.Event()
    service.failures.add("first")
    entered, release = threading.Event(), threading.Event()
    panel.set_target_devices(["first"])
    panel._start_scrcpy()
    worker = panel._launch_worker

    def tail():
        entered.set()
        release.wait(5)

    try:
        wait_until(qt_application, lambda: bool(service.inflight))
        worker.finished.connect(tail, Qt.ConnectionType.DirectConnection)
        gate.set()
        assert entered.wait(2)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
        assert not worker.wait(0)
        if closing:
            supervisor = TaskSupervisor()
            assert panel.register_shutdown_task(supervisor, owner_id="test", task_id="mirror")
            panel.shutdown()
            (result,) = supervisor.stop_all(deadline=0.03)
            assert panel.task_snapshot().resource_owned
            assert result.disposition is StopDisposition.TIMED_OUT
            assert not service.started
        else:
            panel.set_target_devices(["second"])
            panel._start_scrcpy()
            assert panel._launch_worker is worker and "second" not in service.prepared
    finally:
        gate.set()
        release.set()
        assert worker.wait(1500)
    if closing:
        wait_until(qt_application, lambda: not panel.task_snapshot().resource_owned)
        assert not service.started
    else:
        wait_until(qt_application, lambda: service.started == ["second"])


@pytest.mark.parametrize("reverse", [False, True])
def test_disappeared_operation_keeps_same_reader_until_closed(
    task_feedback, qt_application, reverse, tmp_path
):
    coordinator, page, manager, _view, _sources = task_feedback()
    op = manager.begin("install")
    manager.mark_running(op.operation_id)
    key = f"operation:{op.operation_id}"
    page.refresh()
    assert coordinator.open_entry(key)
    drawer = coordinator.drawer
    wait_until(qt_application, lambda: drawer.animation.state() == QAbstractAnimation.State.Stopped)
    reader = page.operation_output
    parent = reader.parentWidget()
    original_text = reader.toPlainText()
    assert original_text and reader.isVisible()

    def text_pixels(frame_name):
        host = drawer.parentWidget()
        point = reader.viewport().mapTo(host, QPoint(3, 2))
        sample = QRect(point, QSize(72, 40))
        assert host.rect().contains(sample)
        # 从宿主实际绘制的范围取字形；单独 grab 阅读器会把隐藏控件也绘制出来。
        shot = host.grab()
        assert shot.save(str(tmp_path / f"{frame_name}.png"))
        image = host.grab(sample).toImage()
        return [image.pixelColor(x, y).lightness() for y in range(image.height())
                for x in range(image.width())]

    first_pixels = text_pixels("opened")
    assert max(first_pixels) - min(first_pixels) > 40
    x = drawer.x()
    manager.finish(op.operation_id, OperationState.CANCELLED)
    page.refresh()
    assert page.selected_key == "" and page.detail_row(key) is None
    assert page.navigation_snapshot().active_count == 0
    assert not drawer.opened and drawer.animation.state() == QAbstractAnimation.State.Running
    drawer.animation.setCurrentTime(drawer.animation.duration() // 4)
    assert x < drawer.x() < drawer.parentWidget().width()
    moving_pixels = text_pixels("closing")
    assert sum(abs(a - b) for a, b in zip(first_pixels, moving_pixels)) / len(first_pixels) < 5
    assert (
        reader.isVisible()
        and reader.parentWidget() is parent
        and reader.toPlainText() == original_text
    )
    if reverse:
        other = manager.begin("screenshot")
        other_key = f"operation:{other.operation_id}"
        page.refresh()
        assert coordinator.open_entry(other_key)
        wait_until(
            qt_application, lambda: drawer.animation.state() == QAbstractAnimation.State.Stopped
        )
        assert drawer.opened and page.selected_key == other_key and reader.isVisible()
    else:
        wait_until(qt_application, lambda: not drawer.isVisible())
        assert not reader.isVisible()


def test_recent_shortcuts_compare_observed_session_release_with_later_commands(task_feedback):
    from dataclasses import replace

    from tests.test_session_task_center import _session
    from tests.test_task_feedback import _result

    _coordinator, page, *_ = task_feedback()
    old = _session("old", state="cancelled", owned=False, stop_enabled=False)
    current = _session("current")
    page.set_session_snapshots((old, current))
    page.present_action_result(_result("early", state="succeeded"))
    page.set_session_snapshots((old, replace(current, state="cancelled", resource_owned=False)))
    page.present_action_result(_result("late", state="succeeded"))
    assert tuple(row.key for row in page.recent_rows()) == (
        "action:late",
        "session:current",
        "action:early",
        "session:old",
    )
