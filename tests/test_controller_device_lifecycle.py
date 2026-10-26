"""Controller 只消费连接生命周期接口，保留关闭、结果分派与默认构造兼容。"""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from controllers import ADBController
from gui.adapters.device_connection_lifecycle import QtDeviceConnectionLifecycle
from models.device_store import DeviceStore
from services.adb_pairing import PairingOutcome
from services.tasks.action_results import ActionResults


def make_lifecycle(guard=None):
    return SimpleNamespace(
        capture_wireless_history=Mock(return_value=guard),
        invalidate_wireless_pairing=Mock(),
        note_adb_server_restarted=Mock(),
    )


@pytest.fixture
def outcome():
    return PairingOutcome(
        request_id=4, context_revision=7, paired=True, connected=True,
        reason="connected", state="Connected", device_id="synthetic-transport",
        connection_endpoint="192.0.2.10:41000",
    )


@pytest.fixture
def controller_factory(monkeypatch, isolated_app_settings):
    monkeypatch.setattr(DeviceStore, "load", Mock())
    instances = []

    def build(**kwargs):
        controller = ADBController(Mock(), **kwargs)
        instances.append(controller)
        return controller

    yield build
    with ThreadPoolExecutor(max_workers=1) as executor:
        for controller in instances:
            executor.submit(controller.shutdown).result(timeout=5)


@pytest.mark.ui
def test_explicit_falsey_lifecycle_is_preserved(controller_factory, monkeypatch):
    class FalseyLifecycle(SimpleNamespace):
        def __bool__(self):
            return False

    lifecycle = FalseyLifecycle(**vars(make_lifecycle()))
    monkeypatch.setattr(
        "gui.adapters.device_connection_lifecycle.QtDeviceConnectionLifecycle",
        Mock(side_effect=AssertionError("不应构造默认适配器")),
    )
    controller = controller_factory(device_lifecycle=lifecycle)
    assert controller.device_lifecycle is lifecycle
    for callback in vars(lifecycle).values():
        callback.assert_not_called()


@pytest.mark.ui
def test_default_lifecycle_is_lazy_and_resolves_late_owner(controller_factory, outcome):
    controller = controller_factory()
    lifecycle = controller.device_lifecycle
    assert isinstance(lifecycle, QtDeviceConnectionLifecycle)
    assert controller.window_owner is None
    assert lifecycle.capture_wireless_history(outcome) is None
    lifecycle.invalidate_wireless_pairing("server_restart")
    lifecycle.note_adb_server_restarted()
    pairing = SimpleNamespace(context_revision=7, accepts_outcome=lambda value: value is outcome)
    guard = None
    for _ in range(2):
        owner = SimpleNamespace(
            _closing=False, _adb_pairing=pairing,
            invalidate_wireless_pairing=Mock(), note_adb_server_restarted=Mock(),
        )
        controller.window_owner = owner
        if guard is not None:
            assert not guard.is_current()
        guard = lifecycle.capture_wireless_history(outcome)
        assert guard is not None and guard.is_current()
        lifecycle.invalidate_wireless_pairing("server_restart")
        lifecycle.note_adb_server_restarted()
        owner.invalidate_wireless_pairing.assert_called_once_with("server_restart")
        owner.note_adb_server_restarted.assert_called_once_with()


@pytest.fixture
def windowless_controller(monkeypatch):
    class WindowlessController(ADBController):
        @property
        def window_owner(self):
            raise AssertionError("业务入口不能穿透窗口")

    controller = WindowlessController.__new__(WindowlessController)
    controller.device_lifecycle = make_lifecycle()
    controller._shutting_down = False
    controller.action_results = ActionResults(lambda _result: None)
    controller._overview_store_lock = None
    controller._device_topology_lock = threading.Lock()
    controller.signals = Mock()
    controller.log_service = Mock()
    controller._log_perf_if_slow = Mock()
    controller.device_model = SimpleNamespace(
        restart_adb_async=Mock(), get_connected_devices_async=Mock(),
    )
    controller.executor = SimpleNamespace(submit=Mock())
    controller._handler_map = {"restart_adb": controller._process_restart_adb_result}
    monkeypatch.setattr(DeviceStore, "get_all", Mock(return_value=[]))
    monkeypatch.setattr(DeviceStore, "add_device", Mock())
    return controller


@pytest.mark.parametrize("state", ["accepted", "rejected", "stale", "shutdown"])
def test_wireless_entry_uses_guard_without_window_access(windowless_controller, outcome, state):
    class FalseyGuard:
        def __bool__(self):
            return False

        def is_current(self):
            return state != "stale"

    controller = windowless_controller
    controller.device_lifecycle.capture_wireless_history.return_value = (
        None if state == "rejected" else FalseyGuard()
    )
    controller._shutting_down = state == "shutdown"
    controller.accept_wireless_connection(outcome)
    if state == "shutdown":
        controller.device_lifecycle.capture_wireless_history.assert_not_called()
    else:
        controller.device_lifecycle.capture_wireless_history.assert_called_once_with(outcome)
    if state == "accepted":
        controller.device_model.get_connected_devices_async.assert_called_once()
        controller.executor.submit.assert_called_once()
        controller.executor.submit.call_args.args[0]()
        DeviceStore.add_device.assert_called_once_with(
            alias="device_192.0.2.10:41000", ip="192.0.2.10:41000",
            brand="Unknown", model="Unknown", android_version="",
        )
    else:
        controller.device_model.get_connected_devices_async.assert_not_called()
        controller.executor.submit.assert_not_called()
        DeviceStore.add_device.assert_not_called()


@pytest.mark.parametrize("failure", ["invalidate", "submit", "result", "notify"])
def test_restart_failures_preserve_invalidation_and_propagation(
    windowless_controller, monkeypatch, failure,
):
    controller = windowless_controller
    events = []
    revoked = []
    error = RuntimeError("synthetic lifecycle failure")

    def invalidate(reason):
        events.append(reason)
        revoked.append(True)
        if failure == "invalidate":
            raise error

    def submit():
        events.append("submit")
        if failure == "submit":
            raise error

    controller.device_lifecycle.invalidate_wireless_pairing.side_effect = invalidate
    controller.device_model.restart_adb_async.side_effect = submit
    timer = Mock()
    monkeypatch.setattr("controllers._device.QTimer.singleShot", timer)
    if failure in {"invalidate", "submit"}:
        with pytest.raises(RuntimeError) as caught:
            controller.restart_adb()
        assert caught.value is error
        assert events == (["server_restart"] if failure == "invalidate"
                          else ["server_restart", "submit"])
        controller.device_lifecycle.note_adb_server_restarted.assert_not_called()
        controller.signals.operation_completed.emit.assert_not_called()
    else:
        controller.restart_adb()
        assert events == ["server_restart", "submit"]
        if failure == "notify":
            controller.device_lifecycle.note_adb_server_restarted.side_effect = error
            with pytest.raises(RuntimeError) as caught:
                controller._process_restart_adb_result({"success": True})
            assert caught.value is error
            controller.signals.operation_completed.emit.assert_not_called()
        controller._handle_async_response("restart_adb_async", {
            "success": failure == "notify", "error": "synthetic failure",
        })
        args = controller.signals.operation_completed.emit.call_args.args
        assert args[0:2] == ("restart_adb", False)
        if failure == "result":
            controller.device_lifecycle.note_adb_server_restarted.assert_not_called()
    assert revoked == [True]
    timer.assert_not_called()


def test_shutdown_rejects_late_restart_result_and_delayed_refresh(
    windowless_controller, monkeypatch,
):
    controller = windowless_controller
    timer = Mock()
    monkeypatch.setattr("controllers._device.QTimer.singleShot", timer)
    controller._handle_async_response("restart_adb_async", {"success": True})
    controller.device_lifecycle.note_adb_server_restarted.assert_called_once_with()
    timer.assert_called_once_with(
        3000, controller.signals, controller._refresh_devices_background,
    )
    delayed = timer.call_args.args[-1]
    controller.device_lifecycle.note_adb_server_restarted.reset_mock()
    controller.signals.operation_completed.emit.reset_mock()
    timer.reset_mock()
    controller._shutting_down = True
    controller._handle_async_response("restart_adb_async", {"success": True})
    delayed()
    controller.device_lifecycle.note_adb_server_restarted.assert_not_called()
    controller.signals.operation_completed.emit.assert_not_called()
    controller.device_model.get_connected_devices_async.assert_not_called()
    timer.assert_not_called()


def test_restart_without_owner_callbacks_keeps_success_refresh(windowless_controller, monkeypatch):
    controller = windowless_controller
    controller.device_lifecycle = QtDeviceConnectionLifecycle(lambda: None)
    timer = Mock()
    monkeypatch.setattr("controllers._device.QTimer.singleShot", timer)
    controller.restart_adb()
    controller.device_model.restart_adb_async.assert_called_once_with()
    controller._process_restart_adb_result({"success": True})
    timer.assert_called_once_with(
        3000, controller.signals, controller._refresh_devices_background,
    )
    assert controller.signals.operation_completed.emit.call_args.args[:2] == ("restart_adb", True)
