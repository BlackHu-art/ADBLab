"""主窗分段启动、默认同步兼容和中断清理的无设备回归。"""

import threading
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from adblab.application.action_results import ActionResults
from core.settings_manager import AppSettings
from gui.main_frame import MainFrame
from tests.test_main_window_layout import _MainFrameSettings
from tests.ui_geometry_helpers import wait_until

STARTUP_POSITIONS = (40, 45, 50, 55, 60, 65, 70, 85, 95)


@pytest.fixture
def startup(qt_application, monkeypatch):
    settings = _MainFrameSettings()
    settings._save_timer = None
    settings._save_atomic = Mock(return_value=True)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    logger = Mock()
    logger.diagnostics.entries = ()
    logger.diagnostics.text.return_value = ""
    monkeypatch.setattr("gui.main_frame.LogService", lambda: logger)
    controllers = []

    def controller_factory(_logger):
        controller = Mock()
        controller.signals = Mock()
        controller.action_results = ActionResults(controller.signals.action_result_changed.emit)
        controller.operation_manager.active_snapshot.return_value = ()
        controllers.append(controller)
        return controller

    monkeypatch.setattr("gui.main_frame.ADBController", controller_factory)
    bootstrap = Mock()
    detection = Mock()
    monkeypatch.setattr(MainFrame, "_bootstrap_adb_async", bootstrap)
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", detection,
    )
    frames = []

    def create(**kwargs):
        frame = MainFrame(**kwargs)
        frames.append(frame)
        return frame

    yield create, bootstrap, detection, controllers
    for frame in frames:
        if not isValid(frame):
            continue
        aborted = QSignalSpy(frame.startup_aborted)
        frame.abort_startup()
        wait_until(qt_application, lambda: not isValid(frame) or aborted.count() == 1)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def page_names(frame):
    return [frame.stackedWidget.widget(index).objectName()
            for index in range(frame.stackedWidget.count())]


def test_default_constructor_keeps_synchronous_startup_and_deferral_matches_it(
    startup, qt_application,
):
    create, bootstrap, detection, controllers = startup
    immediate = create()
    assert immediate._layout_ready
    assert immediate.advance_startup() is None
    assert bootstrap.call_count == 1
    qt_application.processEvents()
    assert detection.call_count == 1

    deferred = create(deferred_startup=True)
    assert not deferred.isVisible()
    assert not deferred._layout_ready
    assert len(controllers) == 1
    for position in STARTUP_POSITIONS:
        assert deferred.advance_startup() == position
        events = []
        QTimer.singleShot(0, lambda: events.append("tick"))
        wait_until(qt_application, lambda: bool(events))
        assert not deferred.isVisible()
        assert bootstrap.call_count == 1
        assert detection.call_count == 1
    assert deferred._layout_ready
    assert page_names(deferred) == page_names(immediate)
    connections = controllers[-1].signals.operation_completed.connect.call_count
    for _ in range(3):
        assert deferred.advance_startup() is None
    assert controllers[-1].signals.operation_completed.connect.call_count == connections
    deferred.show()
    qt_application.processEvents()
    assert bootstrap.call_count == 2
    assert detection.call_count == 2
    deferred.hide()
    deferred.show()
    qt_application.processEvents()
    assert bootstrap.call_count == 2
    assert detection.call_count == 2


@pytest.mark.parametrize("completed_steps", range(len(STARTUP_POSITIONS) + 1))
def test_partial_startup_abort_releases_window_once_without_starting_adb(
    startup, qt_application, completed_steps,
):
    create, bootstrap, detection, controllers = startup
    frame = create(deferred_startup=True)
    for _ in range(completed_steps):
        frame.advance_startup()
        qt_application.processEvents()
    children = frame.findChildren(QWidget)
    library = getattr(frame, "run_library", None)
    aborted = QSignalSpy(frame.startup_aborted)
    frame.abort_startup()
    frame.abort_startup()
    wait_until(qt_application, lambda: aborted.count() == 1)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(frame)
    assert all(not isValid(child) for child in children)
    assert bootstrap.call_count == detection.call_count == 0
    if controllers:
        controllers[0].shutdown.assert_called_once_with()
    if library is not None:
        assert library._queue.close(0)


def test_stage_failure_preserves_exception_and_cleans_partial_children(
    startup, qt_application, monkeypatch,
):
    create, bootstrap, detection, _controllers = startup
    frame = create(deferred_startup=True)
    leaked = []

    def broken_settings(_owner, parent, **_kwargs):
        child = QWidget(parent)
        timer = QTimer(child)
        timer.start(1000)
        leaked.extend((child, timer))
        raise ValueError("synthetic settings failure")

    monkeypatch.setattr("gui.main_frame.SettingsPage", broken_settings)
    for position in STARTUP_POSITIONS[:-2]:
        assert frame.advance_startup() == position
    with pytest.raises(ValueError, match="synthetic settings failure"):
        frame.advance_startup()
    aborted = QSignalSpy(frame.startup_aborted)
    frame.abort_startup()
    wait_until(qt_application, lambda: aborted.count() == 1)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert all(not isValid(child) for child in leaked)
    assert bootstrap.call_count == detection.call_count == 0


def test_close_during_partial_startup_uses_abort_barrier(startup, qt_application):
    create, bootstrap, _detection, controllers = startup
    frame = create(deferred_startup=True)
    frame.advance_startup()
    aborted = QSignalSpy(frame.startup_aborted)
    frame.close()
    wait_until(qt_application, lambda: aborted.count() == 1)
    controllers[0].shutdown.assert_called_once_with()
    assert bootstrap.call_count == 0


def test_abort_releases_overview_scroll_areas_before_they_are_mounted(startup, qt_application):
    create, _bootstrap, _detection, _controllers = startup
    frame = create(deferred_startup=True)
    frame.advance_startup()
    unmounted = [frame.left_panel.device_widget,
                 *frame.left_panel._tab_scroll_areas.values()]
    aborted = QSignalSpy(frame.startup_aborted)
    frame.abort_startup()
    wait_until(qt_application, lambda: aborted.count() == 1)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert all(not isValid(widget) for widget in unmounted)


def test_partial_workspace_rejects_navigation_until_startup_completes(startup):
    create, _bootstrap, _detection, _controllers = startup
    frame = create(deferred_startup=True)
    for position in STARTUP_POSITIONS[:-2]:
        assert frame.advance_startup() == position
    assert not frame._open_workspace_feature("apps", "overview")


def test_abort_waits_for_library_read_without_blocking_qt(startup, qt_application, monkeypatch):
    from services.run_library import RunLibrary

    entered = threading.Event()
    release = threading.Event()
    original_load = RunLibrary.load

    def slow_load(library):
        entered.set()
        assert release.wait(3)
        return original_load(library)

    monkeypatch.setattr(RunLibrary, "load", slow_load)
    create, _bootstrap, _detection, _controllers = startup
    frame = create(deferred_startup=True)
    try:
        frame.advance_startup()
        frame.advance_startup()
        assert entered.wait(1)
        aborted = QSignalSpy(frame.startup_aborted)
        frame.abort_startup()
        qt_application.processEvents()
        assert aborted.count() == 0
        QTimer.singleShot(0, release.set)
        wait_until(qt_application, lambda: aborted.count() == 1)
        assert frame.run_library._queue.close(0)
    finally:
        release.set()


def test_abort_before_queued_client_warmup_prevents_detection(startup, qt_application):
    create, _bootstrap, detection, _controllers = startup
    frame = create(deferred_startup=True)
    while frame.advance_startup() is not None:
        pass
    aborted = QSignalSpy(frame.startup_aborted)
    frame.show()
    frame.abort_startup()
    wait_until(qt_application, lambda: aborted.count() == 1)
    assert detection.call_count == 0


def test_real_startup_controller_hands_splash_to_deferred_mainframe_once(startup, qt_application):
    from gui.startup import StartupController
    from gui.widgets.startup_splash import StartupSplash

    create, bootstrap, detection, _controllers = startup
    splash = StartupSplash()
    coordinator = StartupController(splash)
    ready = []
    coordinator.ready.connect(ready.append)
    positions = []

    def stages():
        frame = create(deferred_startup=True)
        coordinator.set_window(frame)
        while (position := frame.advance_startup()) is not None:
            positions.append(position)
            assert bootstrap.call_count == detection.call_count == 0
            yield f"mainframe-{position}", position

    try:
        coordinator.start(stages())
        wait_until(qt_application, lambda: bool(ready))
        assert positions == list(STARTUP_POSITIONS)
        assert len(ready) == 1
        assert ready[0].isVisible()
        assert not splash.isVisible()
        assert not splash._animation.isActive()
        assert coordinator.is_settled
        wait_until(qt_application, lambda: detection.call_count == 1)
        assert bootstrap.call_count == 1
        qt_application.processEvents()
        assert len(ready) == bootstrap.call_count == detection.call_count == 1
    finally:
        splash.finish()
        splash.deleteLater()
        coordinator.deleteLater()


def test_task_page_is_owned_when_its_gallery_constructor_fails(
    startup, qt_application, monkeypatch,
):
    create, _bootstrap, _detection, _controllers = startup
    frame = create(deferred_startup=True)
    while frame.advance_startup() != 70:
        pass
    unmounted = []

    def broken_gallery(_name, _title, _subtitle, content, **_kwargs):
        unmounted.append(content)
        raise ValueError("synthetic gallery failure")

    monkeypatch.setattr("gui.main_frame.GalleryPage", broken_gallery)
    with pytest.raises(ValueError, match="synthetic gallery failure"):
        frame.advance_startup()
    aborted = QSignalSpy(frame.startup_aborted)
    frame.abort_startup()
    wait_until(qt_application, lambda: aborted.count() == 1)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert all(not isValid(widget) for widget in unmounted)
