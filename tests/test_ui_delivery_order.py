"""发现顺序、销毁期间结果投递和元数据增量更新的回归。"""

import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from gui.main_frame import MainFrame
from gui.pages.workspace_features import WorkspaceFeatureHost
from tests.test_main_window_layout import build_main_frame


def test_manual_refresh_result_discards_older_debounced_scan():
    accepted = []
    frame = SimpleNamespace(
        _closing=False, _scan_thread=Mock(), _task_page=None,
        left_panel=Mock(), _scan_refresh_timer=Mock(),
        _pending_scanned_devices=None, DEVICE_SCAN_DEBOUNCE_MS=300,
        adb_controller=SimpleNamespace(publish_detected_devices=accepted.append),
    )
    MainFrame._schedule_scan_refresh(frame, [])
    accepted.append(["new-device"])
    MainFrame._on_operation_completed(frame, "refresh", True, "Found 1 device")
    MainFrame._publish_scanned_devices(frame)
    assert accepted == [["new-device"]]


class _PayloadPage(QWidget):
    dispose_ready = Signal(object)

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.paths = []

    def receive_payload(self, payload):
        if payload:
            self.paths.extend(payload["image_paths"])

    def activate(self, payload=None):
        self.receive_payload(payload)

    def request_dispose(self, _reason):
        return False


@pytest.mark.parametrize("foreground", [False, True])
@pytest.mark.ui
def test_media_batches_survive_disposal_without_navigation_change(qt_application, foreground):
    host = WorkspaceFeatureHost("apps", "Apps", QWidget())
    host.register_feature(
        "media", "Media", FluentIcon.PHOTO, _PayloadPage,
        requires_device=False, defer_payload_while_disposing=True,
    )
    host.open_feature("media", payload={"image_paths": ["old.png"]})
    old = host.registry.get(host.registry.current_key)
    host.close_current_session()
    if not foreground:
        host.show_overview()
    for path in ("new-1.png", "new-2.png"):
        if foreground:
            host.open_feature("media", payload={"image_paths": [path]})
        else:
            host.update_feature("media", {"image_paths": [path]})
    route_before = host.current_feature
    old.dispose_ready.emit(old.key.generation)
    assert host.current_feature == route_before
    keys = host.registry.keys()
    assert len(keys) == 1
    page = host.registry.get(keys[0])
    assert page is not old
    assert page.paths == ["new-1.png", "new-2.png"]
    host.close()


@pytest.mark.ui
def test_device_metadata_updates_only_changed_card(qt_application, monkeypatch):
    monkeypatch.setattr(
        "models.device_store.DeviceStore.get_full_devices_info", lambda _devices: [],
    )
    monkeypatch.setattr("models.device_store.DeviceStore.get_basic_devices_info", lambda: [])
    frame = build_main_frame()
    try:
        frame._on_devices_updated(["device-a", "device-b"])
        first, second = frame._device_hub.device_cards
        first_calls, second_calls, contexts = [], [], []
        first_setter, second_setter = first.set_snapshot, second.set_snapshot
        monkeypatch.setattr(
            first, "set_snapshot", lambda *args: (first_calls.append(args), first_setter(*args)),
        )
        monkeypatch.setattr(
            second, "set_snapshot", lambda *args: (second_calls.append(args), second_setter(*args)),
        )
        monkeypatch.setattr(
            frame._home_page, "set_device_context", lambda *args: contexts.append(args),
        )
        frame._on_device_info_updated("device-a", {"Model": "New model", "Battery Level": "71"})
        assert len(first_calls) == 1
        assert first_calls[0][0]["Battery Level"] == "71"
        assert second_calls == []
        assert contexts == []
        assert "New model" in frame._global_device_bar.device_label("device-a")
        frame._on_device_info_updated("device-a", {"Model": "New model"})
        assert "Battery Level" not in first_calls[-1][0]
        assert len(first_calls) == 2
        frame._on_device_info_updated("device-a", {"Model": "New model"})
        frame._on_device_info_updated("offline-device", {"Model": "Offline"})
        assert len(first_calls) == 2
        assert second_calls == []
        assert contexts == []
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def _discovery_controller():
    from controllers._device import ADBDeviceMixin

    controller = object.__new__(ADBDeviceMixin)
    controller._device_topology_lock = threading.Lock()
    controller._device_topology_generation = 0
    controller._device_topology = ()
    controller.device_model = Mock()
    controller.signals = Mock()
    controller._emit_operation = Mock()
    controller._async_update_devices = Mock()
    controller._log_perf_if_slow = Mock()
    return controller


def test_metric_only_update_does_not_republish_device_names():
    from gui.widgets.device_context_bar import DeviceContextBar

    bar = Mock()
    bar._device_labels = {}
    bar._picker = Mock()
    bar.set_device_labels.side_effect = lambda names: DeviceContextBar.set_device_labels(bar, names)
    bar.device_labels.return_value = {"device-a": "Device 1 Model"}
    frame = SimpleNamespace(
        left_panel=SimpleNamespace(app_panel=Mock()),
        _global_device_bar=bar, _device_hub=Mock(), _workspace_feature_hosts={"apps": Mock()},
        _device_metadata={"device-a": {"Model": "Model"}}, adb_controller=Mock(),
    )
    with patch("gui.main_frame.DeviceStore.get_full_devices_info", return_value=[]):
        MainFrame._sync_device_metadata(frame, ["device-a"], incremental=True)
        frame._device_metadata["device-a"]["Battery Level"] = "62"
        MainFrame._sync_device_metadata(frame, ["device-a"], incremental=True)
    assert bar._sync_target_presentation.call_count == 1
    assert bar._sync_picker_session.call_count == 1
    assert frame.adb_controller.action_results.set_target_labels.call_count == 1
    assert frame.left_panel.app_panel.set_device_labels.call_count == 1
    sessions = frame._workspace_feature_hosts["apps"].performance_sessions
    assert sessions.set_device_labels.call_count == 1


@pytest.mark.parametrize("result", [
    {"success": True, "devices": ["manual-device"]},
    {"success": False, "devices": [], "error": "unavailable"},
    {"success": False, "devices": [], "stale": True},
])
def test_discovery_rejects_scans_captured_before_or_during_manual_refresh(result):
    controller = _discovery_controller()
    before = controller.device_discovery_token()
    controller.refresh_devices()
    during = controller.device_discovery_token()
    controller.publish_detected_devices(["during"], discovery_token=during)
    assert controller._device_topology == ()
    controller._handle_async_response("get_connected_devices_async", result)
    topology = controller._device_topology
    for token in (before, during):
        controller.publish_detected_devices(["old"], discovery_token=token)
        assert controller._device_topology == topology
    controller.publish_detected_devices(
        ["fresh"], discovery_token=controller.device_discovery_token(),
    )
    assert controller._device_topology == ("fresh",)


def test_discovery_launch_failure_and_shutdown_release_admission():
    controller = _discovery_controller()
    controller.device_model.get_connected_devices_async.side_effect = RuntimeError("launch")
    controller.refresh_devices()
    assert controller.device_discovery_token()[1] == 0
    controller.publish_detected_devices(
        ["fresh"], discovery_token=controller.device_discovery_token(),
    )
    assert controller._device_topology == ("fresh",)
    controller._shutting_down = True
    controller.publish_detected_devices(
        ["late"], discovery_token=controller.device_discovery_token(),
    )
    assert controller._device_topology == ("fresh",)


def test_discovery_submission_failure_result_and_raise_close_only_one_request():
    controller = _discovery_controller()
    controller.refresh_devices()

    def reject_submission():
        controller._handle_async_response(
            "get_connected_devices_async", {"success": False, "error": "submission failed"},
        )
        raise RuntimeError("submission failed")

    controller.device_model.get_connected_devices_async.side_effect = reject_submission
    controller.refresh_devices()
    assert controller.device_discovery_token()[1] == 1
    controller.publish_detected_devices(
        ["must-wait"], discovery_token=controller.device_discovery_token(),
    )
    assert controller._device_topology == ()


def test_scan_state_from_older_generation_does_not_revoke_manual_success():
    from gui.main_frame import _ScanThread

    controller = _discovery_controller()
    states = []
    thread = _ScanThread()
    thread.discovery_token = controller.device_discovery_token
    thread._run_devices_scan = lambda *_args, **_kwargs: None
    thread._sleep_interruptibly = lambda _delay: True
    thread.discovery_state_changed.connect(states.append)
    with patch("gui.main_frame.adb_runtime", return_value=None), patch(
        "gui.main_frame.CommandRunner.active_count", return_value=0,
    ), patch("gui.main_frame.ProcessRunner"):
        thread.run()
    assert len(states) == 1
    controller.refresh_devices()
    controller._handle_async_response(
        "get_connected_devices_async", {"success": True, "devices": ["new-device"]},
    )
    visible_states = ["ready"]
    frame = SimpleNamespace(
        _closing=False, adb_controller=controller,
        left_panel=SimpleNamespace(set_device_discovery_state=visible_states.append),
    )
    MainFrame._on_scan_discovery_state(frame, states[0])
    assert visible_states == ["ready"]


def test_scan_republishes_same_devices_after_manual_generation_changes():
    from gui.main_frame import _ScanThread

    controller = _discovery_controller()
    snapshots = []
    thread = _ScanThread()
    thread.discovery_token = controller.device_discovery_token
    thread.devices_changed.connect(snapshots.append)
    thread._run_devices_scan = lambda *_a, **_k: "List of devices attached\nscan-device\tdevice\n"

    polls = 0

    def advance_manual_refresh(_delay):
        nonlocal polls
        polls += 1
        if polls >= 2:
            return True
        controller.refresh_devices()
        controller._handle_async_response(
            "get_connected_devices_async", {"success": False, "devices": [], "error": "offline"},
        )
        return False

    thread._sleep_interruptibly = advance_manual_refresh
    with patch("gui.main_frame.adb_runtime", return_value=None), patch(
        "gui.main_frame.CommandRunner.active_count", return_value=0,
    ), patch("gui.main_frame.ProcessRunner"):
        thread.run()
    assert snapshots == [["scan-device"], ["scan-device"]]
    assert snapshots[0].discovery_token != snapshots[1].discovery_token
    accepted = []
    controller.signals.devices_updated.emit.side_effect = accepted.append
    frame = SimpleNamespace(
        _closing=False, _scan_refresh_timer=Mock(), DEVICE_SCAN_DEBOUNCE_MS=300,
        adb_controller=controller,
    )
    for snapshot in snapshots:
        MainFrame._schedule_scan_refresh(frame, snapshot)
        MainFrame._publish_scanned_devices(frame)
    assert accepted == [["scan-device"]]


@pytest.mark.parametrize("pending_route", [False, True])
@pytest.mark.ui
def test_media_replay_preserves_inactive_host_and_pending_device_route(
    qt_application, pending_route,
):
    from gui.pages.workspace_features import WorkspaceRoute

    host = WorkspaceFeatureHost("apps", "Apps", QWidget())
    host.register_feature(
        "media", "Media", FluentIcon.PHOTO, _PayloadPage,
        requires_device=False, defer_payload_while_disposing=True,
    )
    host.register_feature("files", "Files", FluentIcon.FOLDER, _PayloadPage)
    host.open_feature("media")
    old = host.registry.get(host.registry.current_key)
    host.close_current_session()
    if pending_route:
        host.open_feature("files", payload={"path": "/original"})
    host.deactivate()
    host.update_feature("media", {"image_paths": ["new.png"]})
    old.dispose_ready.emit(old.key.generation)
    page = host.registry.get(host.registry.keys()[0])
    assert page.paths == ["new.png"]
    assert host.registry.current_key is None
    if pending_route:
        assert host.pending_route == WorkspaceRoute("apps", "files", payload={"path": "/original"})
        assert host.current_feature == "files"
    else:
        assert host.current_feature == "media"
        host.activate()
        assert host.registry.current_key.feature == "media"
        assert page.paths == ["new.png"]
    host.close()


@pytest.mark.ui
def test_deferred_media_payload_is_discarded_at_application_shutdown(qt_application):
    host = WorkspaceFeatureHost("apps", "Apps", QWidget())
    host.register_feature(
        "media", "Media", FluentIcon.PHOTO, _PayloadPage,
        requires_device=False, defer_payload_while_disposing=True,
    )
    host.open_feature("media")
    old = host.registry.get(host.registry.current_key)
    host.close_current_session()
    host.update_feature("media", {"image_paths": ["new.png"]})
    host.shutdown()
    old.dispose_ready.emit(old.key.generation)
    assert host.registry.keys() == ()
    assert host._deferred_payloads == {}
    host.close()
