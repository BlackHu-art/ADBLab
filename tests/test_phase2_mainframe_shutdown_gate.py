import os
import threading
import time
from itertools import pairwise
from queue import Empty, SimpleQueue
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRunnable, Qt, QThread, Signal
from PySide6.QtWidgets import QApplication

from adblab.application.supervision import StopDisposition, TaskSupervisor
from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from gui.features import FeatureSessionKey, FeatureSessionRegistry
from gui.features.logcat import LiveLogcatPage
from gui.features.performance import PerformancePage
from gui.main_frame import MainFrame


class CloseEvent:
    def __init__(self):
        self.accepted = 0
        self.ignored = 0

    def accept(self):
        self.accepted += 1

    def ignore(self):
        self.ignored += 1


class ScanThread(QThread):
    def __init__(self):
        super().__init__()
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.wait(0.005):
            pass


class FakeLeftPanel:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.shutdown_calls = 0

    def register_shutdown_tasks(self, supervisor, *, owner_id):
        running = {"one": True, "two": True}
        for name in running:
            supervisor.register(
                f"{owner_id}-{name}",
                owner_id=owner_id,
                kind="panel_test",
                request_stop=lambda name=name: (
                    self.events.append(("request", name)),
                    running.__setitem__(name, False),
                ),
                wait=lambda _timeout, name=name: (
                    self.events.append(("wait", name)) is None and not running[name]
                ),
                is_running=lambda name=name: running[name],
            )
        return tuple(running)

    def shutdown(self):
        self.shutdown_calls += 1


def _frame(controller_shutdown, *, scan_thread=None, deadline=0.5, left_panel=None):
    frame = MainFrame.__new__(MainFrame)
    frame.task_supervisor = QtTaskSupervisor()
    frame._test_signal_queue = SimpleQueue()
    frame.task_supervisor.application_stopped.connect(
        lambda results, residual: frame._test_signal_queue.put(
            (frame._on_application_stopped, (results, residual))
        ),
        Qt.ConnectionType.DirectConnection,
    )
    frame.task_supervisor.application_finalized.connect(
        lambda result, residual: frame._test_signal_queue.put(
            (frame._on_application_finalized, (result, residual))
        ),
        Qt.ConnectionType.DirectConnection,
    )
    frame._shutdown_owner_id = f"test-application-{id(frame)}"
    frame._shutdown_handles = []
    frame._shutdown_results = ()
    frame._shutdown_residual = ()
    frame._shutdown_finalizer_started = False
    frame._close_started = False
    frame._close_ready = False
    frame._closing = False
    frame.SHUTDOWN_DEADLINE_SECONDS = deadline
    frame._scan_thread = scan_thread
    frame._initial_refresh_timer = Mock()
    frame._initial_refresh_timer.isActive.return_value = False
    frame._scan_refresh_timer = Mock()
    frame._scan_refresh_timer.isActive.return_value = False
    frame._panel_size_save_timer = Mock()
    frame._panel_size_save_timer.isActive.return_value = False
    frame._save_pending_panel_sizes = Mock()
    # 此工厂绕过 QMainWindow.__init__，只验证应用关闭编排；真实窗口布局快照由
    # test_main_window_layout.py 使用完整 MainFrame 独立覆盖。
    frame._flush_pending_layout_state = Mock()
    frame.left_panel = left_panel or FakeLeftPanel()
    frame.adb_controller = Mock()
    frame.adb_controller.shutdown.side_effect = controller_shutdown
    frame.log_service = Mock()
    frame._workspace_feature_hosts = {}
    frame.setEnabled = Mock()
    frame.setWindowTitle = Mock()
    frame.close = Mock()
    return frame


def _bind_settings_finalizer(frame, settings):
    """让关机用例只保存自身设置，避免共享事件队列命中其他用例的全局补丁。"""

    def flush():
        if settings._save_timer:
            settings._save_timer.cancel()
        settings._save_atomic()

    frame._flush_shutdown_state = flush


def _drain_frame_signals(frame):
    while True:
        try:
            handler, args = frame._test_signal_queue.get_nowait()
        except Empty:
            return
        if handler == frame._on_application_finalized:
            with patch(
                "gui.main_frame.QTimer.singleShot",
                side_effect=lambda *args: args[-1](),
            ):
                handler(*args)
        else:
            handler(*args)


def _drive_until(_app, predicate, timeout=2.0, *, frame, heartbeat=None):
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        _drain_frame_signals(frame)
        if heartbeat is not None:
            heartbeat()
        time.sleep(0.003)
    _drain_frame_signals(frame)


def test_application_stop_broadcasts_across_owners_before_any_wait():
    supervisor = TaskSupervisor()
    events = []
    running = {"one": True, "two": True}
    for name, owner in (("one", "owner-a"), ("two", "owner-b")):
        supervisor.register(
            name,
            owner_id=owner,
            kind="test",
            request_stop=lambda name=name: events.append(("request", name)),
            wait=lambda _timeout, name=name: (
                events.append(("wait", name)) is None and not running[name]
            ),
            is_running=lambda name=name: running[name],
            force_stop=lambda _timeout, name=name: (running.__setitem__(name, False) is None),
        )

    results = supervisor.stop_all(deadline=0.05)

    first_wait = next(index for index, item in enumerate(events) if item[0] == "wait")
    assert events[:first_wait] == [("request", "one"), ("request", "two")]
    assert {result.disposition for result in results} == {StopDisposition.FORCED}
    assert supervisor.active_count == 0


def test_application_stop_uses_one_wall_clock_deadline_for_many_slow_tasks():
    supervisor = TaskSupervisor()
    for index in range(5):
        supervisor.register(
            f"slow-{index}",
            owner_id="application",
            kind="slow",
            request_stop=lambda: None,
            wait=lambda timeout: (time.sleep(timeout), False)[1],
            is_running=lambda: True,
        )

    started = time.perf_counter()
    results = supervisor.stop_all(deadline=0.06)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.14
    assert len(results) == 5
    assert {result.disposition for result in results} == {StopDisposition.TIMED_OUT}
    assert supervisor.active_count == 5


def test_preclaimed_task_remains_visible_to_application_residual_snapshot():
    supervisor = TaskSupervisor()
    entered = threading.Event()
    release = threading.Event()
    running = {"value": True}

    def wait(_timeout):
        entered.set()
        release.wait(1)
        running["value"] = False
        return True

    supervisor.register(
        "preclaimed",
        owner_id="dialog",
        kind="worker",
        request_stop=lambda: None,
        wait=wait,
        is_running=lambda: running["value"],
    )
    owner_stop = threading.Thread(
        target=lambda: supervisor.stop(
            "preclaimed",
            graceful_timeout=1,
            force_timeout=0,
        ),
        daemon=True,
    )
    owner_stop.start()
    assert entered.wait(0.5)

    assert supervisor.stop_all(deadline=0.01) == ()
    snapshot = supervisor.active_snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].task_id == "preclaimed"
    release.set()
    owner_stop.join(1)


def test_application_shutdown_lane_is_not_starved_by_owner_cleanup_pool():
    _app = QApplication.instance() or QApplication([])
    adapter = QtTaskSupervisor()
    pool_release = threading.Event()

    class BlockingRunnable(QRunnable):
        def run(self):
            pool_release.wait(0.4)

    blocking_runnables = [BlockingRunnable(), BlockingRunnable()]
    for runnable in blocking_runnables:
        adapter._pool.start(runnable)
    emitted = []
    stopped = threading.Event()

    def record_stopped(results, residual):
        emitted.append((results, residual, time.perf_counter()))
        stopped.set()

    adapter.application_stopped.connect(
        record_stopped,
        Qt.ConnectionType.DirectConnection,
    )
    adapter.supervisor.register(
        "application-task",
        owner_id="application",
        kind="test",
        request_stop=lambda: None,
        wait=lambda timeout: (time.sleep(timeout), False)[1],
        is_running=lambda: True,
    )

    started = time.perf_counter()
    adapter.stop_all_async(deadline=0.05)
    assert stopped.wait(0.25)
    pool_release.set()
    adapter._pool.waitForDone(1000)

    assert emitted
    assert emitted[0][2] - started < 0.16
    assert emitted[0][1]


def test_application_shutdown_releases_live_logcat_feature_session():
    """全局停止接管页面 owner 后仍须完成资源屏障并移除会话。"""

    app = QApplication.instance() or QApplication([])
    adapter = QtTaskSupervisor()
    stop_requested = threading.Event()

    class BlockingLogcatWorker(QThread):
        lines_ready = Signal(object)
        dropped_ready = Signal(int)
        status_changed = Signal(str)
        terminated = Signal(object)

        def __init__(self, _device_ip: str, package: str = ""):
            super().__init__()
            self.package = package

        def run(self):
            stop_requested.wait(1.0)

        def request_stop(self):
            stop_requested.set()

        def wait_for_stop(self, timeout: float) -> bool:
            return self.wait(max(0, int(timeout * 1000))) and not self.isRunning()

        def force_stop(self, _timeout: float) -> bool:
            stop_requested.set()
            return True

        def is_active(self) -> bool:
            return self.isRunning()

    registry = FeatureSessionRegistry()
    key = FeatureSessionKey("logcat", "device-1")
    page, _ = registry.get_or_create(
        key,
        lambda _key: LiveLogcatPage(
            device_ip="device-1",
            task_supervisor=adapter,
        ),
    )
    emitted = []
    page.dispose_ready.connect(emitted.append)
    with patch("gui.dialogs.live_logcat.LogcatWorker", BlockingLogcatWorker):
        page._start()
    worker = page.worker
    assert worker is not None
    start_deadline = time.perf_counter() + 1.0
    while not worker.isRunning() and time.perf_counter() < start_deadline:
        app.processEvents()
        time.sleep(0.002)
    assert worker.isRunning()

    assert adapter.begin_application_shutdown() is True
    assert registry.request_dispose(key, "application_shutdown") is False
    assert page._application_cleanup_fallback is True
    assert adapter.stop_all_async(deadline=1.0) is True

    deadline = time.perf_counter() + 2.0
    while registry.get(key) is not None and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()

    assert emitted
    assert registry.get(key) is None
    assert page.worker is None
    assert adapter.supervisor.active_count == 0
    adapter._pool.waitForDone(1000)


def test_performance_page_dispose_delegates_running_stop_without_waiting():
    _app = QApplication.instance() or QApplication([])
    page = PerformancePage(device_ip="target")
    page._runner = Mock()
    page._runner.is_running.return_value = True
    page.stop_mobileperf = Mock()

    started = time.perf_counter()
    ready = page.request_dispose("test")
    elapsed = time.perf_counter() - started

    assert ready is False
    assert elapsed < 0.1
    page.stop_mobileperf.assert_called_once()
    page._runner.stop.assert_not_called()


def test_performance_page_application_shutdown_does_not_start_second_stop_thread():
    _app = QApplication.instance() or QApplication([])
    page = PerformancePage(device_ip="target")
    page._runner = Mock()
    page._runner.is_running.return_value = True
    page._shutdown_registered = True
    page.stop_mobileperf = Mock()

    page._begin_dispose()

    page._runner.request_stop.assert_called_once_with()
    page.stop_mobileperf.assert_not_called()
    page._runner.is_running.return_value = False
    page._poll_dispose_ready()
    page.deleteLater()


def test_mainframe_two_stage_close_is_nonblocking_broadcast_first_and_idempotent():
    app = QApplication.instance() or QApplication([])
    scan = ScanThread()
    scan.start()
    events = []
    controller_threads = []

    def controller_shutdown():
        controller_threads.append(threading.get_ident())
        time.sleep(0.08)

    frame = _frame(
        controller_shutdown,
        scan_thread=scan,
        deadline=0.5,
        left_panel=FakeLeftPanel(events),
    )
    settings = Mock()
    settings._save_timer = None
    shutdown_events = []
    frame.log_service.shutdown.side_effect = lambda: shutdown_events.append(
        ("log_shutdown", threading.get_ident())
    )
    settings._save_atomic.side_effect = lambda: shutdown_events.append(
        ("settings_save", threading.get_ident())
    )
    _bind_settings_finalizer(frame, settings)
    ticks = []
    first_event = CloseEvent()
    gui_thread = threading.get_ident()

    started = time.perf_counter()
    frame.closeEvent(first_event)
    elapsed = time.perf_counter() - started
    frame.closeEvent(CloseEvent())
    _drive_until(
        app,
        lambda: frame._close_ready,
        frame=frame,
        heartbeat=lambda: ticks.append(time.perf_counter()),
    )
    observation_end = time.perf_counter() + 0.1
    while time.perf_counter() < observation_end:
        ticks.append(time.perf_counter())
        time.sleep(0.003)

    assert elapsed < 0.1
    assert first_event.ignored == 1
    assert frame.left_panel.shutdown_calls == 1
    first_wait = next(index for index, item in enumerate(events) if item[0] == "wait")
    assert events[:first_wait] == [("request", "one"), ("request", "two")]
    assert controller_threads and controller_threads[0] != gui_thread
    assert not scan.isRunning()
    assert frame.task_supervisor.supervisor.active_count == 0
    assert frame._shutdown_residual == ()
    assert len(ticks) >= 5
    assert max(b - a for a, b in pairwise(ticks)) < 0.1
    settings._save_atomic.assert_called_once()
    frame.log_service.shutdown.assert_called_once()
    assert [name for name, _thread_id in shutdown_events] == [
        "log_shutdown",
        "settings_save",
    ]
    assert shutdown_events[0][1] == gui_thread
    assert shutdown_events[1][1] != gui_thread
    frame.close.assert_called_once()

    second_event = CloseEvent()
    frame.closeEvent(second_event)
    assert second_event.accepted == 1


def test_shutdown_callable_failure_is_failed_and_remains_residual():
    app = QApplication.instance() or QApplication([])

    def broken_shutdown():
        raise RuntimeError("injected cleanup failure")

    frame = _frame(broken_shutdown, deadline=0.3)
    settings = Mock()
    settings._save_timer = None
    _bind_settings_finalizer(frame, settings)

    frame.closeEvent(CloseEvent())
    _drive_until(app, lambda: frame._close_ready, frame=frame)

    controller_results = [
        result for result in frame._shutdown_results if result.task_id.endswith("-controller")
    ]
    assert len(controller_results) == 1
    assert controller_results[0].disposition == StopDisposition.FAILED
    assert controller_results[0].error_type == "RuntimeError"
    assert any(item.kind == "controller_shutdown" for item in frame._shutdown_residual)
    assert frame.log_service.log.called


def test_slow_shutdown_finalizer_does_not_block_gui_and_is_reported_residual():
    app = QApplication.instance() or QApplication([])
    finalizer_release = threading.Event()
    frame = _frame(lambda: None, deadline=0.09)
    settings = Mock()
    settings._save_timer = None
    settings._save_atomic.side_effect = lambda: finalizer_release.wait(1)
    _bind_settings_finalizer(frame, settings)
    ticks = []

    started = time.perf_counter()
    frame.closeEvent(CloseEvent())
    _drive_until(
        app,
        lambda: frame._close_ready,
        timeout=0.4,
        frame=frame,
        heartbeat=lambda: ticks.append(time.perf_counter()),
    )
    elapsed = time.perf_counter() - started

    assert frame._close_ready
    assert elapsed < 0.22
    assert len(ticks) >= 5
    assert any(item.kind == "shutdown_finalizer" for item in frame._shutdown_residual)
    finalizer_release.set()


def test_late_scan_notifications_are_ignored_after_close_starts():
    frame = _frame(lambda: None)
    frame._closing = True
    frame._pending_scanned_devices = ["before"]

    frame._schedule_scan_refresh(["late"])
    frame._publish_scanned_devices()

    assert frame._pending_scanned_devices == ["before"]
    frame._scan_refresh_timer.start.assert_not_called()
    frame.adb_controller.publish_detected_devices.assert_not_called()


def test_feature_tasks_are_registered_before_host_shutdown():
    app = QApplication.instance() or QApplication([])
    events = []
    blocker = threading.Event()

    class FeatureHost:
        def register_shutdown_tasks(self, supervisor, *, owner_id, task_prefix):
            events.append("register")
            supervisor.register(
                f"{task_prefix}-worker",
                owner_id=owner_id,
                kind="feature_worker",
                request_stop=lambda: events.append("request"),
                wait=lambda timeout: blocker.wait(timeout),
                is_running=lambda: not blocker.is_set(),
            )

        def shutdown(self):
            events.append("shutdown")

    frame = _frame(lambda: None, deadline=0.06)
    host = FeatureHost()
    frame._workspace_feature_hosts = {"system": host}
    settings = Mock()
    settings._save_timer = None
    _bind_settings_finalizer(frame, settings)

    frame.closeEvent(CloseEvent())
    _drive_until(app, lambda: frame._close_ready, frame=frame)

    assert events.index("register") < events.index("shutdown")
    assert events.index("shutdown") < events.index("request")
    assert frame._workspace_feature_hosts == {"system": host}
    assert any(item.kind == "feature_worker" for item in frame._shutdown_residual)
    blocker.set()


def test_mainframe_deadline_closes_with_residual_without_claiming_resource_zero():
    app = QApplication.instance() or QApplication([])
    blocker = threading.Event()

    def controller_shutdown():
        blocker.wait(1)

    frame = _frame(
        controller_shutdown,
        deadline=0.05,
        left_panel=FakeLeftPanel(),
    )
    settings = Mock()
    settings._save_timer = None
    event = CloseEvent()
    _bind_settings_finalizer(frame, settings)

    frame.closeEvent(event)
    _drive_until(app, lambda: frame._close_ready, frame=frame)

    assert event.ignored == 1
    assert frame._close_ready is True
    assert frame._shutdown_residual
    assert any(item.kind == "controller_shutdown" for item in frame._shutdown_residual)
    assert frame.task_supervisor.supervisor.active_count >= 1
    settings._save_atomic.assert_called_once()
    frame.log_service.shutdown.assert_called_once()
    blocker.set()


def test_close_controller_flush_shutdown_state_persists_pending_settings(tmp_path, monkeypatch):
    """真实落盘：取消防抖计时器后原子保存待写设置，而非仅调用被注入的 stub。"""

    import json

    from core import settings_manager
    from gui.close_controller import CloseController

    previous_instance = settings_manager.AppSettings._instance
    settings_file = tmp_path / "config" / "app_settings.json"
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(
        settings_manager,
        "LEGACY_SETTINGS_FILE",
        str(tmp_path / "legacy" / "app_settings.json"),
    )
    settings_manager.AppSettings._instance = None
    try:
        controller = CloseController(None)
        settings = settings_manager.AppSettings.instance()
        settings.update({"theme": "Dark"})
        assert settings._save_timer is not None

        controller._flush_shutdown_state()

        stored = json.loads(settings_file.read_text(encoding="utf-8"))
        assert stored["theme"] == "Dark"
    finally:
        current = settings_manager.AppSettings._instance
        if current is not None and current is not previous_instance:
            timer = current._save_timer
            if timer is not None:
                timer.cancel()
        settings_manager.AppSettings._instance = previous_instance
