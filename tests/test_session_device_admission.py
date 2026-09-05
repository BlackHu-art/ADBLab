"""固定设备会话只为当前明确选中的在线设备接受新操作。"""

from concurrent.futures import Future
from unittest.mock import Mock, patch

import pytest

from gui.dialogs.live_logcat import LiveLogcatPage
from gui.dialogs.live_logcat_worker import CurrentPackageWorker as LogcatPackageWorker
from gui.dialogs.performance_launcher import CurrentPackageWorker as PerfPackageWorker
from gui.features.performance import PerformancePage
from gui.panels.remote_panel import RemotePanel


def _remote():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["other-device"])
    panel._workspace_device_id = "session-device"
    panel._workspace_device_connected = True
    panel._device_selected = False
    panel._active_device = None
    panel._process = None
    panel._launch_worker = None
    panel._remote_control = Mock()
    panel._remote_executor = Mock()
    panel._scrcpy_service = Mock()
    panel._scrcpy_service.resolve_executable.return_value = "C:/tools/scrcpy.exe"
    panel._log = Mock()
    panel._update_action_states = Mock()
    panel._emit_remote_queue_status = Mock()
    return panel


@pytest.mark.parametrize("action", ["key", "gesture", "start"])
def test_remote_viewed_device_cannot_accept_commands_without_selection(action):
    panel = _remote()
    with patch("gui.panels.remote_panel.os.path.isfile", return_value=True):
        if action == "key":
            panel._send_keyevent("HOME")
        elif action == "gesture":
            panel._send_remote_action("swipe_up")
        else:
            panel._set_session_state = Mock()
            panel._update_status = Mock()
            panel._scrcpy_config = Mock()
            with patch("gui.panels.remote_panel.ScrcpyLaunchWorker") as worker:
                panel._start_scrcpy()
                worker.assert_not_called()
    panel._remote_executor.submit.assert_not_called()


def test_remote_reselection_does_not_revive_cancelled_queued_input():
    panel = _remote()
    panel.set_device_selected(True)
    panel._send_keyevent("HOME")
    queued = panel._remote_executor.submit.call_args.args[0]
    panel.set_device_selected(False)
    panel.set_device_selected(True)
    queued()
    panel._remote_control.send_keyevent.assert_not_called()

    panel._send_keyevent("BACK")
    panel._remote_executor.submit.call_args.args[0]()
    panel._remote_control.send_keyevent.assert_called_once_with("session-device", "BACK")


def test_remote_reselection_does_not_revive_pending_input_warmup():
    panel = _remote()
    panel.set_device_selected(True)
    panel._warm_remote_input_session = Mock()
    with patch("gui.panels.remote_panel_input.threading.Thread") as thread:
        panel._start_warm_remote_input_session()
        warmup = thread.call_args.kwargs["target"]
        panel.set_device_selected(False)
        panel.set_device_selected(True)
        warmup()
    panel._warm_remote_input_session.assert_not_called()


@pytest.mark.parametrize("revoke", ["selection", "offline"])
@pytest.mark.parametrize("worker_finished", [False, True])
def test_remote_late_preflight_does_not_start_after_admission_was_revoked(revoke, worker_finished):
    panel = _remote()
    panel.set_device_selected(True)
    panel._active_device = "session-device"
    worker = Mock()
    worker.isInterruptionRequested.side_effect = (
        lambda: not worker_finished and worker.requestInterruption.called
    )
    panel._launch_worker = worker
    if revoke == "selection":
        panel.set_device_selected(False)
        panel.set_device_selected(True)
    else:
        panel.set_workspace_device("session-device", connected=False)
        panel.set_workspace_device("session-device", connected=True)
    panel._on_launch_ready(["scrcpy", "-s", "session-device"], "1080x2400")
    worker.requestInterruption.assert_called_once()
    panel._scrcpy_service.start.assert_not_called()


def test_main_window_updates_hidden_remote_admission_on_global_selection_changes(
    monkeypatch, qt_application
):
    from PySide6.QtCore import QSize

    from models.device_store import DeviceStore
    from tests.test_main_window_layout import _FakeScreen, _FakeScreenAdapter, build_main_frame

    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda devices: [])
    window = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("test", QSize(1600, 1100)))
    )
    try:
        window._on_devices_updated(["demo-a", "demo-b"])
        window.left_panel._devices_tab.set_selected_devices(["demo-a"])
        window._open_workspace_feature("devices", "remote", device_id="demo-a")
        remote = window.left_panel._scrcpy_tab
        remote._remote_control = Mock()
        window._on_nav_requested("home")

        def run_input(task):
            future = Future()
            future.set_result(task())
            return future

        with patch.object(remote._remote_executor, "submit", side_effect=run_input) as submit:
            for selected in ([], ["demo-b"]):
                window.left_panel._devices_tab.set_selected_devices(selected)
                remote._send_keyevent("HOME")
                assert not remote.btn_start.isEnabled()
            submit.assert_not_called()
            remote._remote_control.send_keyevent.assert_not_called()
            window.left_panel._devices_tab.set_selected_devices(["demo-a"])
            assert remote.btn_start.isEnabled()
            remote._send_keyevent("HOME")
            remote._remote_control.send_keyevent.assert_called_once_with("demo-a", "HOME")
    finally:
        window.left_panel._scrcpy_tab.shutdown()
        window._unbind_window_screen()
        window._close_ready = True
        window.close()


def test_remote_deselection_keeps_existing_session_stop_available(qt_application):
    from gui.panels.side_panel import SidePanel

    side = SidePanel()
    try:
        page = side._ensure_tab_loaded(2)
        page.set_device_selected(True)
        page.set_workspace_device("session-device", connected=True)
        page._active_device = "session-device"
        page._set_session_state(page._SESSION_RUNNING)
        page.set_device_selected(False)
        assert page.btn_stop.isEnabled()
        assert not page.btn_start.isEnabled()
        assert all(not button.isEnabled() for button in page._remote_control_buttons)
        page._launch_worker = Mock()
        page._launch_worker.isRunning.return_value = True
        page._stop_scrcpy()
        page._launch_worker.requestInterruption.assert_called_once()
    finally:
        page._launch_worker = None
        page._active_device = None
        page._set_session_state(page._SESSION_IDLE)
        side.close()


@pytest.mark.parametrize("action", ["start", "query", "filter"])
def test_logcat_unselected_session_rejects_new_device_actions(action):
    page = LiveLogcatPage(device_ip="session-device")
    page._device_selected = False
    worker = Mock()
    worker.is_active.return_value = True
    if action == "filter":
        page.worker = worker
    try:
        with (
            patch("gui.dialogs.live_logcat.LogcatWorker") as stream,
            patch("gui.dialogs.live_logcat_stream.CurrentPackageWorker") as query,
        ):
            if action == "start":
                page._start()
            elif action == "query":
                page._fetch_current_pkg()
            else:
                page.pkg_input.setText("com.example.next")
                page._submit_package_filter()
            stream.assert_not_called()
            query.assert_not_called()
            worker.update_package.assert_not_called()
    finally:
        page.worker = None
        page._pkg_worker = None
        page.close()


@pytest.mark.parametrize("action", ["start", "query"])
def test_performance_unselected_session_rejects_new_device_actions(action):
    page = PerformancePage(device_ip="session-device", package_name="com.example.app")
    page._device_selected = False
    try:
        with (
            patch.object(page._runner, "start") as start,
            patch("gui.dialogs.performance_launcher.CurrentPackageWorker") as query,
            patch("gui.dialogs.performance_launcher_run.FluentMessageBox.warning"),
        ):
            if action == "start":
                page.start_mobileperf()
            else:
                page.fetch_current_package()
            start.assert_not_called()
            query.assert_not_called()
    finally:
        page._package_worker = None
        page.close()


@pytest.mark.parametrize("page_type", [LiveLogcatPage, PerformancePage])
def test_workspace_selection_is_closed_until_explicitly_projected(page_type):
    page = page_type(device_ip="session-device")
    try:
        page.prepare_for_workspace()
        assert not page.start_btn.isEnabled()
        page.set_device_connected(True)
        assert not page.start_btn.isEnabled()
        page.set_device_selected(True)
        assert page.start_btn.isEnabled()
        page.set_device_connected(False)
        assert not page.start_btn.isEnabled()
    finally:
        page.close()


@pytest.mark.parametrize("page_type", [LiveLogcatPage, PerformancePage])
def test_current_package_callback_stays_invalid_after_reselection(page_type):
    page = page_type(device_ip="session-device")
    is_logcat = page_type is LiveLogcatPage
    worker_type = LogcatPackageWorker if is_logcat else PerfPackageWorker
    worker_path = (
        "gui.dialogs.live_logcat_stream.CurrentPackageWorker"
        if is_logcat else "gui.dialogs.performance_launcher.CurrentPackageWorker"
    )
    worker = worker_type("session-device")
    field = page.pkg_input if is_logcat else page.package_edit
    field.setText("com.example.keep")
    try:
        with patch(worker_path, return_value=worker), patch.object(worker, "start"):
            if is_logcat:
                page._fetch_current_pkg()
            else:
                page.fetch_current_package()
        page.set_device_selected(False)
        page.set_device_selected(True)
        worker.package_ready.emit("com.example.stale")
        assert field.text() == "com.example.keep"
    finally:
        if is_logcat:
            page._on_pkg_worker_finished(worker)
        else:
            page._on_package_worker_finished(worker)
        page.close()


def test_logcat_stop_remains_targeted_to_existing_task_when_unselected():
    page = LiveLogcatPage(device_ip="session-device")
    page.worker = Mock()
    page.worker.is_active.return_value = True
    page._supervisor_task_id = "existing-logcat-task"
    try:
        page.set_device_selected(False)
        with patch.object(page._task_supervisor, "stop_async") as stop:
            page._stop()
        stop.assert_called_once_with("existing-logcat-task")
    finally:
        page.worker = None
        page.close()


@pytest.mark.parametrize("page_type", [LiveLogcatPage, PerformancePage])
def test_unselected_running_session_retains_stop_and_rejects_late_query(page_type):
    page = page_type(device_ip="session-device")
    is_logcat = page_type is LiveLogcatPage
    worker_type = LogcatPackageWorker if is_logcat else PerfPackageWorker
    worker = worker_type("session-device")
    try:
        if is_logcat:
            page.worker = Mock()
            page.worker.is_active.return_value = True
            page._pkg_worker = worker
            page.pkg_input.setText("com.example.keep")
            worker._package_filter_revision = page._package_filter_revision
            worker.package_ready.connect(page._on_current_pkg)
        else:
            page._set_running(True)
            page._package_worker = worker
            page.package_edit.setText("com.example.keep")
            worker.package_ready.connect(page._on_current_package)
        page.set_device_selected(False)
        assert page.stop_btn.isEnabled()
        page.set_device_selected(True)
        worker.package_ready.emit("com.example.stale")
        field = page.pkg_input if is_logcat else page.package_edit
        assert field.text() == "com.example.keep"
        page.set_device_selected(False)
        if is_logcat:
            page._on_pkg_worker_finished(worker)
            assert not page.btn_get_pkg.isEnabled()
        else:
            page._on_package_worker_finished(worker)
            page._set_running(False)
            assert not page.get_package_btn.isEnabled()
        assert not page.start_btn.isEnabled()
    finally:
        if is_logcat:
            page.worker = None
            page._pkg_worker = None
        else:
            page._package_worker = None
        page.close()
