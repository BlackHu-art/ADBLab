"""无线连接完成只更新现有历史缓存，不引入额外设备查询或晚到持久化。"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from controllers._device import ADBDeviceMixin
from models.adb_device import ADBDevice
from models.device_store import DeviceStore
from services.adb_pairing import PairingOutcome


class DeferredExecutor:
    def __init__(self):
        self.jobs = []

    def submit(self, function, *args):
        self.jobs.append((function, args))

    def drain(self):
        while self.jobs:
            function, args = self.jobs.pop(0)
            function(*args)


@pytest.fixture
def wireless_controller(tmp_path, monkeypatch):
    outcome = PairingOutcome(
        request_id=4, context_revision=7, paired=True, connected=True,
        reason="connected", state="Connected", guid="adb-synthetic-guid",
        device_id="adb-synthetic-guid._adb-tls-connect._tcp",
        connection_endpoint="192.0.2.10:41000",
    )
    pairing = SimpleNamespace(context_revision=7)
    pairing.accepts_outcome = lambda value: value is outcome
    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller.window_owner = SimpleNamespace(_adb_pairing=pairing, _closing=False)
    controller._shutting_down = False
    controller._overview_store_lock = None
    controller.executor = DeferredExecutor()
    controller.refresh_devices = Mock()
    controller._emit_operation = Mock()
    controller.log_service = Mock()
    controller.device_model = Mock()
    monkeypatch.setattr(DeviceStore, "_devices", {})
    monkeypatch.setattr(DeviceStore, "_file_path", str(tmp_path / "history.yaml"))

    def forbidden(*_args, **_kwargs):
        pytest.fail("无线连接历史不得额外查询 ADB 属性")

    monkeypatch.setattr(ADBDevice, "get_devices_basic_info", forbidden)
    monkeypatch.setattr(ADBDevice, "get_device_overview_info", forbidden)
    return controller, pairing, outcome, tmp_path / "history.yaml"


def test_verified_connection_defers_history_and_merges_valid_cache(wireless_controller):
    controller, _pairing, outcome, history_path = wireless_controller
    DeviceStore._devices = {
        "saved-name": {
            "ip": outcome.connection_endpoint, "Brand": "Saved Brand",
            "Model": "Saved Model", "Aversion": "14",
        },
        "live-cache": {
            "ip": outcome.device_id, "Brand": "New Brand", "Model": "Unknown", "Aversion": "",
        },
    }

    controller.accept_wireless_connection(outcome)

    assert not history_path.exists()
    assert len(controller.executor.jobs) == 1
    controller.refresh_devices.assert_called_once_with()
    controller._emit_operation.assert_not_called()
    controller.executor.drain()
    assert yaml.safe_load(history_path.read_text("utf-8")) == {
        "saved-name": {
            "ip": outcome.connection_endpoint, "Brand": "New Brand",
            "Model": "Saved Model", "Aversion": "14",
        },
    }
    controller.log_service.log.assert_not_called()


def test_new_endpoint_has_defaults_without_persisting_transport_id(wireless_controller):
    controller, _pairing, outcome, history_path = wireless_controller
    controller.accept_wireless_connection(outcome)
    controller.executor.drain()
    records = yaml.safe_load(history_path.read_text("utf-8"))
    assert list(records.values()) == [{
        "ip": outcome.connection_endpoint, "Brand": "Unknown", "Model": "Unknown", "Aversion": "",
    }]
    assert outcome.device_id not in history_path.read_text("utf-8")
    assert outcome.guid not in history_path.read_text("utf-8")


@pytest.mark.parametrize("endpoint", ["", "adb-synthetic._adb-tls-connect._tcp", "192.0.2.10"])
def test_without_valid_connection_endpoint_only_refreshes(wireless_controller, endpoint):
    controller, pairing, outcome, history_path = wireless_controller
    accepted = replace(outcome, connection_endpoint=endpoint)
    pairing.accepts_outcome = lambda value: value is accepted
    controller.accept_wireless_connection(accepted)
    assert not controller.executor.jobs
    assert not history_path.exists()
    controller.refresh_devices.assert_called_once_with()
    controller._emit_operation.assert_not_called()


@pytest.mark.parametrize("rejection", ["copied_result", "missing_owner", "no_coordinator",
                                       "owner_closing", "controller_closing", "old_revision"])
def test_unaccepted_outcomes_do_not_refresh_or_save(wireless_controller, rejection):
    controller, _pairing, outcome, history_path = wireless_controller
    if rejection == "copied_result":
        outcome = replace(outcome)
    elif rejection == "missing_owner":
        controller.window_owner = None
    elif rejection == "no_coordinator":
        controller.window_owner._adb_pairing = None
    elif rejection == "owner_closing":
        controller.window_owner._closing = True
    elif rejection == "controller_closing":
        controller._shutting_down = True
    else:
        controller.window_owner._adb_pairing.context_revision += 1
    controller.accept_wireless_connection(outcome)
    assert not controller.executor.jobs
    assert not history_path.exists()
    controller.refresh_devices.assert_not_called()
    controller._emit_operation.assert_not_called()


@pytest.mark.parametrize("change", ["revision", "owner_closing", "controller_closing",
                                    "coordinator_replaced"])
def test_queued_history_rechecks_environment_and_shutdown(wireless_controller, change):
    controller, pairing, outcome, history_path = wireless_controller
    controller.accept_wireless_connection(outcome)
    if change == "revision":
        pairing.context_revision += 1
    elif change == "owner_closing":
        controller.window_owner._closing = True
    elif change == "controller_closing":
        controller._shutting_down = True
    else:
        controller.window_owner._adb_pairing = SimpleNamespace(context_revision=7)
    controller.executor.drain()
    assert not history_path.exists()
    assert DeviceStore.get_all() == []


def test_environment_change_while_reading_cache_prevents_write(wireless_controller, monkeypatch):
    controller, pairing, outcome, history_path = wireless_controller
    original = DeviceStore.get_all

    def invalidate_after_read():
        records = original()
        pairing.context_revision += 1
        return records

    monkeypatch.setattr(DeviceStore, "get_all", invalidate_after_read)
    controller.accept_wireless_connection(outcome)
    controller.executor.drain()
    assert not history_path.exists()
    assert original() == []


def test_history_rechecks_revision_after_waiting_for_overview_write_lock(wireless_controller):
    controller, pairing, outcome, history_path = wireless_controller
    waiting = threading.Event()
    lock = threading.Lock()
    lock.acquire()

    class ObservedLock:
        def __enter__(self):
            waiting.set()
            assert lock.acquire(timeout=2)

        def __exit__(self, *_args):
            lock.release()

    controller._overview_store_lock = ObservedLock()
    with ThreadPoolExecutor(max_workers=1) as executor:
        controller.executor = executor
        controller.accept_wireless_connection(outcome)
        try:
            assert waiting.wait(2)
            pairing.context_revision += 1
        finally:
            lock.release()
    assert not history_path.exists()
    assert DeviceStore.get_all() == []


def test_history_persistence_runs_on_existing_executor(wireless_controller, monkeypatch):
    controller, _pairing, outcome, history_path = wireless_controller
    main_thread = threading.get_ident()
    write_threads = []
    original = DeviceStore.add_device

    def record_write(**kwargs):
        write_threads.append(threading.get_ident())
        original(**kwargs)

    monkeypatch.setattr(DeviceStore, "add_device", record_write)
    with ThreadPoolExecutor(max_workers=1) as executor:
        controller.executor = executor
        controller.accept_wireless_connection(outcome)
    assert history_path.exists()
    assert len(write_threads) == 1 and write_threads[0] != main_thread


def test_history_write_failure_does_not_revoke_connection_or_expose_exception(
    wireless_controller, monkeypatch,
):
    controller, _pairing, outcome, _history_path = wireless_controller

    def fail_write(*_args, **_kwargs):
        raise OSError("synthetic-secret-or-path")

    monkeypatch.setattr(DeviceStore, "add_device", fail_write)
    controller.accept_wireless_connection(outcome)
    controller.executor.drain()
    controller.refresh_devices.assert_called_once_with()
    controller._emit_operation.assert_not_called()
    controller.log_service.log.assert_called_once()
    assert "synthetic-secret-or-path" not in str(controller.log_service.log.call_args)


def test_history_submission_after_executor_shutdown_preserves_verified_refresh(
    wireless_controller,
):
    controller, _pairing, outcome, _history_path = wireless_controller
    controller.executor = Mock()
    controller.executor.submit.side_effect = RuntimeError("synthetic executor already stopped")
    controller.accept_wireless_connection(outcome)
    controller.refresh_devices.assert_called_once_with()
    controller._emit_operation.assert_not_called()
    assert "synthetic executor" not in str(controller.log_service.log.call_args)


def test_restart_invalidates_pairing_before_model_submission(wireless_controller):
    controller, _pairing, _outcome, _history_path = wireless_controller
    events = []
    controller.window_owner.invalidate_wireless_pairing = lambda reason: events.append(reason)
    controller.device_model.restart_adb_async.side_effect = lambda: events.append("restart")
    controller.restart_adb()
    assert events == ["server_restart", "restart"]


def test_restart_without_optional_owner_callback_keeps_legacy_submission(wireless_controller):
    controller, _pairing, _outcome, _history_path = wireless_controller
    controller.restart_adb()
    controller.device_model.restart_adb_async.assert_called_once_with()
