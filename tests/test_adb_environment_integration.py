"""应用组合根的客户端重检与会话归属接线回归。"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gui.main_frame import MainFrame


def test_recheck_retires_input_sessions_before_probing_new_client():
    calls = []
    frame = SimpleNamespace(
        _closing=False,
        invalidate_wireless_pairing=lambda reason: calls.append(("invalidate", reason)),
        _adb_environment=SimpleNamespace(recheck=lambda: calls.append("recheck")),
        left_panel=SimpleNamespace(_scrcpy_tab=SimpleNamespace(
            invalidate_adb_input_sessions=lambda: calls.append("retire"),
        )),
    )
    MainFrame.recheck_adb_environment(frame)
    assert calls == [("invalidate", "environment_recheck"), "retire", "recheck"]


@pytest.mark.parametrize("closing,environment,scan", [
    (False, True, True), (True, True, True), (False, False, True), (False, True, False),
    (False, False, False),
])
def test_server_restart_facade_preserves_runtime_scan_order(closing, environment, scan):
    events = []
    frame = SimpleNamespace(_closing=closing)
    if environment:
        frame._adb_environment = SimpleNamespace(
            note_server_restart=lambda: events.append("runtime"),
            recheck=Mock(side_effect=AssertionError("重启通知不能替换为环境重检")),
        )
    if scan:
        frame._scan_thread = SimpleNamespace(invalidate_snapshot=lambda: events.append("scan"))
    MainFrame.note_adb_server_restarted(frame)
    expected = (["runtime"] if environment and not closing else []) + (["scan"] if scan else [])
    assert events == expected


@pytest.mark.parametrize("closing,created", [(False, True), (True, True), (False, False)])
def test_pairing_invalidation_preserves_optional_and_closing_behavior(closing, created):
    invalidate = Mock()
    frame = SimpleNamespace(_closing=closing)
    if created:
        frame._adb_pairing = SimpleNamespace(invalidate=invalidate)
    MainFrame.invalidate_wireless_pairing(frame, "server_restart")
    if created and not closing:
        invalidate.assert_called_once_with("server_restart")
    else:
        invalidate.assert_not_called()


@pytest.mark.parametrize("result", ["accepted", "copied", "old_request", "old_revision"])
def test_wireless_forwarding_and_history_guard_preserve_window_close_boundary(monkeypatch, result):
    from controllers._device import ADBDeviceMixin
    from gui.adapters.adb_pairing import QtAdbPairing
    from gui.adapters.device_connection_lifecycle import QtDeviceConnectionLifecycle
    from models.device_store import DeviceStore
    from services.adb_pairing import PairingOutcome

    outcome = PairingOutcome(
        request_id=4, context_revision=7, paired=True, connected=True,
        reason="connected", state="Connected", device_id="synthetic-transport",
        connection_endpoint="192.0.2.10:41000",
    )
    pairing = SimpleNamespace(
        _closing=False, _verified_outcome=outcome, _context_revision=7,
        context_revision=7, _current_request=4,
    )
    pairing.accepts_outcome = Mock(wraps=QtAdbPairing.accepts_outcome.__get__(pairing))
    frame = SimpleNamespace(_closing=False, _adb_pairing=pairing)
    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller.window_owner = frame
    controller.device_lifecycle = QtDeviceConnectionLifecycle(lambda: controller.window_owner)
    controller._shutting_down = False
    controller._overview_store_lock = None
    controller.refresh_devices = Mock()
    controller._emit_operation = Mock()
    controller.log_service = Mock()
    jobs = []
    controller.executor = SimpleNamespace(submit=lambda job: jobs.append(job))
    controller.accept_wireless_connection = Mock(wraps=controller.accept_wireless_connection)
    frame.adb_controller = controller
    get_all = Mock(return_value=[])
    save = Mock()
    monkeypatch.setattr(DeviceStore, "get_all", get_all)
    monkeypatch.setattr(DeviceStore, "add_device", save)
    if result == "copied":
        outcome = replace(outcome)
    elif result == "old_request":
        pairing._current_request += 1
    elif result == "old_revision":
        pairing._context_revision += 1
        pairing.context_revision += 1
    MainFrame._on_wireless_connected(frame, outcome)
    if result == "accepted":
        controller.accept_wireless_connection.assert_called_once_with(outcome)
        controller.refresh_devices.assert_called_once_with()
        assert pairing.accepts_outcome.call_count == 2
        assert len(jobs) == 1
        frame._closing = True
        assert controller._shutting_down is False
        MainFrame._on_wireless_connected(frame, outcome)
        assert controller.accept_wireless_connection.call_count == 1
        jobs[0]()
        assert pairing.accepts_outcome.call_count == 2
    else:
        controller.accept_wireless_connection.assert_not_called()
        controller.refresh_devices.assert_not_called()
        assert jobs == []
    get_all.assert_not_called()
    save.assert_not_called()
    controller._emit_operation.assert_not_called()
    controller.log_service.log.assert_not_called()
