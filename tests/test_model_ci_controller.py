# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from controllers._app import ADBAppMixin
from controllers._base import _ADBControllerBase
from controllers._device import ADBDeviceMixin
from core.perf_trace import attach_perf, build_async_perf, split_perf


@pytest.mark.parametrize("success", [True, False])
def test_restart_refresh_does_not_claim_unverified_reboot_completion(success):
    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller.signals = Mock()
    controller.log_service = Mock()
    controller.refresh_devices = Mock()
    result = {
        "device_ip": "device-1", "success": success, "requires_refresh": True,
        "error": "Reboot result unknown after timeout",
    }

    with patch("controllers._device.QTimer.singleShot") as timer:
        controller._process_restart_devices_result(result)

    controller.signals.operation_completed.emit.assert_called_once()
    operation, actual_success, message = controller.signals.operation_completed.emit.call_args.args
    assert operation == "restart"
    assert actual_success is success
    assert ("submitted" if success else "unknown") in message.lower()
    timer.assert_called_once()
    timer.call_args.args[-1]()
    controller.refresh_devices.assert_called_once()
    controller.signals.operation_completed.emit.assert_called_once()


def test_cross_platform_builds_do_not_run_full_gui_test_suite():
    workflow = Path(".github/workflows/Build-exe.yaml").read_text(encoding="utf-8")

    # a0d9711 起打包流程不再运行 pytest：Windows 只安装静态分析依赖并跑
    # ruff/pyright，非 Windows 只跑源码自检；pytest 留在独立的开发验证流程。
    assert (
        "name: Install static analysis dependencies\n        if: runner.os == 'Windows'"
        in workflow
    )
    assert "name: Run tests" not in workflow
    assert "python -m pytest" not in workflow
    assert "name: Source self-check\n        if: runner.os != 'Windows'" in workflow


def test_release_job_keeps_same_version_immutable_and_prunes_old_tags():
    workflow = Path(".github/workflows/Build-exe.yaml").read_text(encoding="utf-8")

    assert 'gh release view "$TAG"' in workflow
    assert "git ls-remote --exit-code --tags origin" in workflow
    assert "exit 1" in workflow
    assert 'gh release create "$TAG"' in workflow
    assert "softprops/action-gh-release" not in workflow
    # 同版本不可变之外，发布完成后保留最新 5 个版本 tag，更旧的自动删除。
    assert "name: Retain latest 5 version tags" in workflow
    assert "KEEP=5" in workflow


def test_cross_platform_release_assets_are_single_archives():
    workflow = Path(".github/workflows/Build-exe.yaml").read_text(encoding="utf-8")

    assert "name: Zip macOS app artifact" in workflow
    assert "ditto -c -k --sequesterRsrc --keepParent" in workflow
    assert 'rm -f "dist/$name"' in workflow
    assert "name: Archive Linux artifact" in workflow
    assert "tar -C dist -czf" in workflow


def test_emit_operation_flushes_user_visible_result_immediately():
    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.log_service = Mock()
    controller.signals = Mock()

    _ADBControllerBase._emit_operation(controller, "input_keyevent", True, "Key sent")

    controller.log_service.log.assert_called_once_with("INFO", "Key sent", flush_immediately=True)
    controller.signals.operation_completed.emit.assert_called_once_with(
        "input_keyevent", True, "Key sent"
    )


def test_perf_payload_wrapper_preserves_list_results():
    perf = build_async_perf("get_connected_devices_async", 10.0, 10.1, 10.2)
    wrapped = attach_perf(["device-1"], perf)

    result, extracted = split_perf(wrapped)

    assert result == ["device-1"]
    assert extracted["method"] == "get_connected_devices_async"


def test_handle_async_response_logs_slow_perf_trace_only_above_threshold():
    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.log_service = Mock()
    controller._settings = Mock()
    controller._settings.get.return_value = 100
    controller._handler_map = {"input_keyevent": Mock()}
    slow_result = attach_perf(
        {"success": True, "device_ip": "device-1"},
        {
            "queued_at": 1.0,
            "started_at": 1.01,
            "finished_at": 1.4,
            "queue_ms": 10.0,
            "model_ms": 390.0,
        },
    )

    with patch("controllers._base.perf_counter", side_effect=[1.42, 1.43]):
        _ADBControllerBase._handle_async_response(
            controller,
            "input_keyevent_async",
            slow_result,
        )

    controller._handler_map["input_keyevent"].assert_called_once_with(
        {"success": True, "device_ip": "device-1"}
    )
    controller.log_service.log.assert_called_once()
    assert controller.log_service.log.call_args.args[0] == "DEBUG"
    assert controller.log_service.log.call_args.args[1].startswith("[PERF] input_keyevent")
    assert "model=390.0ms" in controller.log_service.log.call_args.args[1]


def test_handle_async_response_skips_perf_trace_for_fast_path():
    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.log_service = Mock()
    controller._settings = Mock()
    controller._settings.get.return_value = 300
    controller._handler_map = {"input_keyevent": Mock()}
    fast_result = attach_perf(
        {"success": True, "device_ip": "device-1"},
        {
            "queued_at": 1.0,
            "started_at": 1.01,
            "finished_at": 1.05,
            "queue_ms": 10.0,
            "model_ms": 40.0,
        },
    )

    with patch("controllers._base.perf_counter", side_effect=[1.06, 1.07]):
        _ADBControllerBase._handle_async_response(
            controller,
            "input_keyevent_async",
            fast_result,
        )

    controller.log_service.log.assert_not_called()


def test_async_update_devices_batches_store_write_and_refreshes_ui():
    class ImmediateExecutor:
        def submit(self, func):
            func()

    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller.executor = ImmediateExecutor()
    controller.signals = Mock()
    controller.log_service = Mock()
    controller._shutting_down = False
    controller._device_topology_lock = threading.Lock()
    controller._device_topology_generation = 1
    controller._device_topology = ("device-1", "device-2")

    with (
        patch("controllers._device.ADBDevice.get_device_overview_info") as get_info,
        patch("controllers._device.DeviceStore.upsert_devices") as upsert,
    ):
        get_info.side_effect = [
            {"Brand": "Google", "Model": "Pixel", "Aversion": "15", "SDK Version": "35"},
            {"Brand": "Redmi", "Model": "22127", "Aversion": "9"},
        ]

        ADBDeviceMixin._async_update_devices(
            controller,
            ["device-1", "device-2"],
            generation=1,
        )

    upsert.assert_called_once()
    records = upsert.call_args.args[0]
    assert [record["ip"] for record in records] == ["device-1", "device-2"]
    controller.signals.devices_updated.emit.assert_called_once_with(["device-1", "device-2"])
    metadata_events = controller.signals.device_info_updated.emit.call_args_list
    assert len(metadata_events) == 2
    assert metadata_events[0].args[0] == "device-1"
    assert metadata_events[0].args[1]["SDK Version"] == "35"


def _device_metadata_controller():
    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller.executor = Mock()
    controller.signals = Mock()
    controller.log_service = Mock()
    controller._shutting_down = False
    controller._device_topology_lock = threading.Lock()
    controller._device_topology_generation = 1
    controller._device_topology = ("device-1", "device-2")
    return controller


def test_same_topology_refreshes_share_one_job_and_one_followup():
    controller = _device_metadata_controller()
    with (
        patch(
            "controllers._device.ADBDevice.get_device_overview_info",
            return_value={"Model": "Phone"},
        ) as query,
        patch("controllers._device.DeviceStore.upsert_devices") as write,
    ):
        for _ in range(5):
            controller._async_update_devices(["device-1", "device-2"], generation=1)
        assert controller.executor.submit.call_count == 1
        controller.executor.submit.call_args.args[0]()
    assert query.call_count == 4
    assert write.call_count == 2
    assert controller.signals.device_info_updated.emit.call_count == 4


@pytest.mark.parametrize("invalidation", ["topology", "shutdown"])
def test_metadata_query_receives_cancellation_when_controller_is_invalidated(invalidation):
    controller = _device_metadata_controller()
    callbacks = []

    def query(_device, *, cancelled=None, **_kwargs):
        callbacks.append(cancelled)
        if invalidation == "shutdown":
            controller._shutting_down = True
        else:
            with controller._device_topology_lock:
                controller._device_topology_generation += 1
                controller._device_topology = ()
        return {"Model": "Stale"}

    with (
        patch("controllers._device.ADBDevice.get_device_overview_info", side_effect=query),
        patch("controllers._device.DeviceStore.upsert_devices") as write,
    ):
        controller._async_update_devices(["device-1", "device-2"], generation=1)
        controller.executor.submit.call_args.args[0]()
    assert len(callbacks) == 1
    assert callable(callbacks[0]) and callbacks[0]()
    write.assert_not_called()
    controller.signals.device_info_updated.emit.assert_not_called()


def test_metadata_new_topology_can_start_while_old_job_is_waiting():
    controller = _device_metadata_controller()
    with (
        patch(
            "controllers._device.ADBDevice.get_device_overview_info",
            return_value={"Model": "Current"},
        ) as query,
        patch("controllers._device.DeviceStore.upsert_devices") as write,
    ):
        controller._async_update_devices(["device-1", "device-2"], generation=1)
        first = controller.executor.submit.call_args.args[0]
        with controller._device_topology_lock:
            controller._device_topology_generation = 2
            controller._device_topology = ("device-3",)
        controller._async_update_devices(["device-3"], generation=2)
        latest = controller.executor.submit.call_args.args[0]
        latest()
        first()
    assert query.call_count == 1
    assert query.call_args.args[0] == "device-3"
    assert [record["ip"] for record in write.call_args.args[0]] == ["device-3"]


def test_device_metadata_writes_are_serialized_across_topology_changes():
    controller = _device_metadata_controller()
    old_write_started, release_old_write = threading.Event(), threading.Event()
    new_query_finished, new_write_started = threading.Event(), threading.Event()
    stored = []

    def query(device, **_kwargs):
        if device == "device-3":
            new_query_finished.set()
        return {"Model": device}

    def write(records):
        if records[0]["ip"] == "device-1":
            old_write_started.set()
            assert release_old_write.wait(3)
        else:
            new_write_started.set()
        stored[:] = [record["ip"] for record in records]

    with (
        patch("controllers._device.ADBDevice.get_device_overview_info", side_effect=query),
        patch("controllers._device.DeviceStore.upsert_devices", side_effect=write),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        controller.executor = executor
        controller._async_update_devices(["device-1", "device-2"], generation=1)
        try:
            assert old_write_started.wait(2)
            with controller._device_topology_lock:
                controller._device_topology_generation = 2
                controller._device_topology = ("device-3",)
            controller._async_update_devices(["device-3"], generation=2)
            assert new_query_finished.wait(2)
            assert not new_write_started.wait(0.1), "new disk write overlapped the older write"
        finally:
            release_old_write.set()
    assert stored == ["device-3"]


def test_connected_device_save_is_cancelled_before_persistence_on_shutdown():
    controller = _device_metadata_controller()
    seen = []

    def query(_device, *, cancelled=None, **_kwargs):
        controller._shutting_down = True
        seen.append(callable(cancelled) and cancelled())
        return {"Model": "Stale"}

    with (
        patch("controllers._device.ADBDevice.get_devices_basic_info", side_effect=query),
        patch("controllers._device.DeviceStore.add_device") as write,
    ):
        controller._save_device_info("device-1")
    assert seen == [True]
    write.assert_not_called()


def test_metadata_rechecks_generation_after_waiting_for_disk_lock():
    controller = _device_metadata_controller()
    old_at_lock, release_old = threading.Event(), threading.Event()
    mutex = threading.Lock()

    class PauseFirstWriter:
        first = True

        def __enter__(self):
            if self.first:
                self.first = False
                old_at_lock.set()
                assert release_old.wait(3)
            mutex.acquire()

        def __exit__(self, *_args):
            mutex.release()

    controller._overview_store_lock = PauseFirstWriter()
    with (
        patch(
            "controllers._device.ADBDevice.get_device_overview_info",
            return_value={"Model": "Phone"},
        ),
        patch("controllers._device.DeviceStore.upsert_devices") as write,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        controller._async_update_devices(["device-1", "device-2"], generation=1)
        old = executor.submit(controller.executor.submit.call_args.args[0])
        try:
            assert old_at_lock.wait(2)
            with controller._device_topology_lock:
                controller._device_topology_generation = 2
                controller._device_topology = ("device-3",)
            controller._async_update_devices(["device-3"], generation=2)
            executor.submit(controller.executor.submit.call_args.args[0]).result(timeout=2)
        finally:
            release_old.set()
            old.result(timeout=2)
    assert write.call_count == 1
    assert [record["ip"] for record in write.call_args.args[0]] == ["device-3"]


@pytest.mark.parametrize("first_failure", [False, True])
def test_device_metadata_is_published_before_later_queries_finish(first_failure):
    controller = _device_metadata_controller()
    second_started = threading.Event()
    release_second = threading.Event()

    def get_info(device, *, cancelled=None):
        if device == "device-1":
            if first_failure:
                raise RuntimeError("overview unavailable")
            return {"Model": "First", "Battery Level": "90%"}
        second_started.set()
        assert release_second.wait(3), "second query was not released"
        return {"Model": "Second"}

    with (
        patch("controllers._device.ADBDevice.get_device_overview_info", side_effect=get_info),
        patch("controllers._device.DeviceStore.upsert_devices") as upsert,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        controller._async_update_devices(["device-1", "device-2"], generation=1)
        future = executor.submit(controller.executor.submit.call_args.args[0])
        try:
            assert second_started.wait(3), "second query did not start"
            metadata = controller.signals.device_info_updated.emit.call_args_list
            assert len(metadata) == 1
            assert metadata[0].args[0] == "device-1"
            if first_failure:
                assert metadata[0].args[1] == {}
            else:
                assert metadata[0].args[1]["Battery Level"] == "90%"
            upsert.assert_not_called()
            controller.signals.devices_updated.emit.assert_not_called()
        finally:
            release_second.set()
            future.result(timeout=3)

    upsert.assert_called_once()
    assert [record["ip"] for record in upsert.call_args.args[0]] == (
        ["device-2"] if first_failure else ["device-1", "device-2"]
    )
    assert [
        event.args[0] for event in controller.signals.device_info_updated.emit.call_args_list
    ] == ["device-1", "device-2"]
    controller.signals.devices_updated.emit.assert_called_once_with(["device-1", "device-2"])


@pytest.mark.parametrize("invalidation", ["topology", "shutdown"])
def test_late_metadata_and_batch_write_are_suppressed_after_invalidation(invalidation):
    controller = _device_metadata_controller()
    second_started = threading.Event()
    release_second = threading.Event()

    def get_info(device, *, cancelled=None):
        if device == "device-2":
            second_started.set()
            assert release_second.wait(3), "second query was not released"
        return {"Model": device}

    with (
        patch("controllers._device.ADBDevice.get_device_overview_info", side_effect=get_info),
        patch("controllers._device.DeviceStore.upsert_devices") as upsert,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        controller._async_update_devices(["device-1", "device-2"], generation=1)
        future = executor.submit(controller.executor.submit.call_args.args[0])
        try:
            assert second_started.wait(3), "second query did not start"
            assert controller.signals.device_info_updated.emit.call_count == 1
            if invalidation == "shutdown":
                controller._shutting_down = True
            else:
                with controller._device_topology_lock:
                    controller._device_topology_generation += 1
                    controller._device_topology = ()
        finally:
            release_second.set()
            future.result(timeout=3)

    upsert.assert_not_called()
    controller.signals.devices_updated.emit.assert_not_called()
    assert controller.signals.device_info_updated.emit.call_count == 1


def test_empty_current_package_result_releases_query_as_failure():
    controller = ADBAppMixin.__new__(ADBAppMixin)
    controller._emit_operation = Mock()
    controller.signals = Mock()
    controller._process_get_package_result({
        "device_ip": "demo-a", "success": True, "package_name": "",
    })
    assert controller._emit_operation.call_args.args[:2] == ("get_package", False)
    controller.signals.current_package_received.emit.assert_not_called()


def test_stale_device_metadata_update_does_not_restore_removed_device():
    class DeferredExecutor:
        def __init__(self):
            self.jobs = []

        def submit(self, func):
            self.jobs.append(func)

    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller.executor = DeferredExecutor()
    controller.signals = Mock()
    controller.log_service = Mock()
    controller._emit_operation = Mock()
    controller._shutting_down = False
    controller._device_topology_lock = threading.Lock()
    controller._device_topology_generation = 0
    controller._device_topology = ()

    with (
        patch(
            "controllers._device.ADBDevice.get_device_overview_info",
            return_value={"Brand": "Google", "Model": "Pixel", "Aversion": "15"},
        ),
        patch("controllers._device.DeviceStore.upsert_devices") as upsert,
    ):
        ADBDeviceMixin._process_device_list(controller, ["device-1"])
        ADBDeviceMixin._process_device_list(controller, [])
        controller.executor.jobs[0]()

    upsert.assert_not_called()
    controller.signals.device_info_updated.emit.assert_not_called()
    assert controller.signals.devices_updated.emit.call_args_list == [
        call(["device-1"]),
        call([]),
    ]


def test_controller_shutdown_stops_model_processes_and_executor():
    controller = Mock()
    controller.testing_model = Mock()
    controller.advanced_model = Mock()
    controller.executor = Mock()

    with patch("controllers._base.ProcessRunner.stop_all_tracked") as stop_all_tracked:
        _ADBControllerBase.shutdown(controller)

    controller.testing_model.shutdown.assert_called_once()
    controller.advanced_model.shutdown.assert_called_once()
    stop_all_tracked.assert_called_once()
    controller.executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)


def test_connect_device_result_uses_returned_device_ip():
    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller.executor = Mock()
    controller._save_device_info = Mock()
    controller.refresh_devices = Mock()
    controller._emit_operation = Mock()

    ADBDeviceMixin._process_connect_device_result(
        controller,
        {"success": True, "device_ip": "device-2", "output": "connected to device-2"},
    )

    controller.executor.submit.assert_called_once_with(controller._save_device_info, "device-2")
    controller.refresh_devices.assert_called_once()
    controller._emit_operation.assert_called_once_with(
        "connect", True, "Successfully connected to device-2"
    )


def test_connect_device_result_refreshes_when_already_connected():
    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller.executor = Mock()
    controller._save_device_info = Mock()
    controller.refresh_devices = Mock()
    controller._emit_operation = Mock()

    ADBDeviceMixin._process_connect_device_result(
        controller,
        {"success": True, "device_ip": "device-2", "output": "already connected to device-2"},
    )

    controller.executor.submit.assert_called_once_with(controller._save_device_info, "device-2")
    controller.refresh_devices.assert_called_once()
    controller._emit_operation.assert_called_once_with(
        "connect", True, "device-2 is already connected"
    )


def test_publish_detected_devices_uses_device_list_processing():
    controller = Mock()

    ADBDeviceMixin.publish_detected_devices(controller, ("device-1", "device-2"))

    controller._process_device_list.assert_called_once_with(["device-1", "device-2"])


def test_connect_device_validates_and_normalizes_target_before_adb_call():
    controller = Mock()

    ADBDeviceMixin.connect_device(controller, " 10.0.0.195 : 5555 ")

    controller.device_model.connect_device_async.assert_called_once_with("10.0.0.195:5555")
    controller._emit_operation.assert_not_called()


def test_connect_device_rejects_incomplete_target_before_adb_call():
    controller = Mock()

    ADBDeviceMixin.connect_device(controller, "10.0.0.195")

    controller.device_model.connect_device_async.assert_not_called()
    controller._emit_operation.assert_called_once()
    assert "IP and port" in controller._emit_operation.call_args.args[2]


def test_kill_monkey_result_logs_ack_but_waits_for_run_terminal():
    controller = Mock()
    controller._monkey_running = {"device-1"}

    ADBAppMixin._process_kill_monkey_result(
        controller,
        {
            "device_ip": "device-1",
            "index": 1,
            "success": True,
            "already_stopped": True,
            "message": "Monkey is not running",
        },
    )

    assert controller._monkey_running == {"device-1"}
    controller._emit_operation.assert_called_once_with(
        "kill_monkey", True, "ℹ️ 1. Monkey was not running on device-1"
    )


def _connected_devices_controller():
    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.log_service = Mock()
    controller._settings = Mock()
    controller._settings.get.return_value = 10_000
    controller._handler_map = {}
    controller._emit_operation = Mock()
    controller.signals = Mock()
    controller._process_device_list = Mock()
    return controller


def test_connected_devices_success_routes_to_process_device_list():
    controller = _connected_devices_controller()

    _ADBControllerBase._handle_async_response(
        controller,
        "get_connected_devices_async",
        {"success": True, "devices": ["device-1", "device-2"]},
    )

    controller._process_device_list.assert_called_once_with(["device-1", "device-2"])
    controller._emit_operation.assert_not_called()
    controller.signals.devices_updated.emit.assert_not_called()


def test_stale_device_listing_does_not_publish_or_report_failure():
    controller = _connected_devices_controller()

    controller._handle_async_response(
        "get_connected_devices_async",
        {"success": False, "devices": [], "error": "", "stale": True, "cancelled": True},
    )

    controller._process_device_list.assert_not_called()
    controller._emit_operation.assert_not_called()
    controller.signals.devices_updated.emit.assert_not_called()
    controller.signals.device_refresh_superseded.emit.assert_called_once_with()


def test_stale_manual_refresh_finishes_action_as_cancelled():
    from types import SimpleNamespace

    from PySide6.QtTest import QSignalSpy

    from adblab.application.action_results import ActionResults, ActionSpec
    from controllers.signals import ADBControllerSignals
    from core.exec import CommandResult
    from models.adb_device import ADBDevice

    controller = _connected_devices_controller()
    controller.signals = ADBControllerSignals()
    device_updates = QSignalSpy(controller.signals.devices_updated)
    superseded = QSignalSpy(controller.signals.device_refresh_superseded)
    results, tasks = [], []
    controller.action_results = ActionResults(results.append)
    model = ADBDevice()
    model.thread_pool = SimpleNamespace(start=tasks.append)
    model.command_finished.connect(controller._handle_async_response)
    controller.action_results.run(
        ActionSpec("refresh_devices", "devices", "刷新设备"), (), model.get_connected_devices_async,
    )
    with patch(
        "models.adb_device.CommandRunner.run",
        return_value=CommandResult(False, stale=True),
    ) as run:
        tasks[0].run()

    assert results[-1].state == "cancelled"
    assert len(results[-1].items) == 1
    assert results[-1].items[0].state == "cancelled"
    assert results[-1].items[0].detail
    controller._process_device_list.assert_not_called()
    controller._emit_operation.assert_not_called()
    assert device_updates.count() == 0
    assert superseded.count() == 1
    run.assert_called_once()


def test_connected_devices_failure_reports_refresh_without_clearing_list():
    controller = _connected_devices_controller()

    _ADBControllerBase._handle_async_response(
        controller,
        "get_connected_devices_async",
        {"success": False, "devices": [], "error": "adb unavailable"},
    )

    controller._process_device_list.assert_not_called()
    controller._emit_operation.assert_called_once_with(
        "refresh", False, "adb unavailable"
    )
    controller.signals.devices_updated.emit.assert_not_called()


def test_connected_devices_non_dict_result_reports_invalid_format():
    controller = _connected_devices_controller()

    _ADBControllerBase._handle_async_response(
        controller,
        "get_connected_devices_async",
        ["device-1"],
    )

    controller._process_device_list.assert_not_called()
    controller._emit_operation.assert_called_once_with(
        "refresh", False, "Invalid device list format"
    )
    controller.signals.devices_updated.emit.assert_not_called()


def test_refresh_devices_sync_failure_reports_error_without_clearing_list():
    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller._shutting_down = False
    controller.device_model = Mock()
    controller.device_model.get_connected_devices_async.side_effect = RuntimeError(
        "submission failed"
    )
    controller._emit_operation = Mock()
    controller.signals = Mock()

    ADBDeviceMixin.refresh_devices(controller)

    controller._emit_operation.assert_called_once_with(
        "refresh", False, "Failed to refresh devices: submission failed"
    )
    controller.signals.devices_updated.emit.assert_not_called()


def test_emit_operation_is_silent_while_shutting_down():
    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller._shutting_down = True
    controller.log_service = Mock()
    controller.signals = Mock()

    _ADBControllerBase._emit_operation(controller, "input_keyevent", True, "Key sent")

    controller.signals.operation_completed.emit.assert_not_called()
    controller.log_service.log.assert_not_called()


def test_refresh_devices_is_noop_while_shutting_down():
    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller._shutting_down = True
    controller.device_model = Mock()

    ADBDeviceMixin.refresh_devices(controller)

    controller.device_model.get_connected_devices_async.assert_not_called()
