# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import threading
from pathlib import Path
from unittest.mock import Mock, call, patch

from controllers._app import ADBAppMixin
from controllers._base import _ADBControllerBase
from controllers._device import ADBDeviceMixin
from core.perf_trace import attach_perf, build_async_perf, split_perf


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
        patch("controllers._device.ADBDevice.get_devices_basic_info") as get_info,
        patch("controllers._device.DeviceStore.upsert_devices") as upsert,
    ):
        get_info.side_effect = [
            {"Brand": "Google", "Model": "Pixel", "Aversion": "15"},
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
            "controllers._device.ADBDevice.get_devices_basic_info",
            return_value={"Brand": "Google", "Model": "Pixel", "Aversion": "15"},
        ),
        patch("controllers._device.DeviceStore.upsert_devices") as upsert,
    ):
        ADBDeviceMixin._process_device_list(controller, ["device-1"])
        ADBDeviceMixin._process_device_list(controller, [])
        controller.executor.jobs[0]()

    upsert.assert_not_called()
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
    controller.executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


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
