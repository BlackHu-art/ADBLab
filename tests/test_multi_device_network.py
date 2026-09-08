"""多设备操作不能抢占其他设备的本机端口或复用设备私有 PID。"""

from unittest.mock import Mock, call

import pytest

from controllers._file import ADBFileMixin
from controllers._media import ADBMediaMixin
from models.adb_network import ADBNetworkMixin


def test_forward_rejects_multiple_devices_before_submitting_any_command():
    controller = Mock()
    controller._require_devices.return_value = True
    ADBFileMixin.forward_port(controller, ["demo-a", "demo-b"], "8080", "80")
    controller.advanced_model.forward_port_async.assert_not_called()
    assert controller._emit_operation.call_args.args[1] is False


def test_pid_operation_rejects_multiple_devices_before_submitting_any_command():
    controller = Mock()
    controller._require_devices.return_value = True
    ADBMediaMixin.kill_process(controller, ["demo-a", "demo-b"], "1234")
    controller.advanced_model.kill_process_async.assert_not_called()


def test_forward_list_contains_only_requested_device_rules():
    model = ADBNetworkMixin()
    model._run = Mock(return_value={
        "success": True,
        "output": "demo-b tcp:9000 tcp:90\ndemo-a tcp:8000 tcp:80\n",
    })
    result = ADBNetworkMixin.list_forwards_async.__wrapped__(model, "demo-a")
    assert result["output"] == "demo-a tcp:8000 tcp:80"


def test_remove_forwards_removes_only_requested_device_ports():
    model = ADBNetworkMixin()
    model._run = Mock(side_effect=[
        {"success": True, "output": "demo-b tcp:9000 tcp:90\ndemo-a tcp:8000 tcp:80"},
        {"success": True, "output": ""},
    ])
    result = ADBNetworkMixin.remove_all_forwards_async.__wrapped__(model, "demo-a")
    assert result["success"]
    assert model._run.call_args_list == [
        call(["adb", "forward", "--list"], device_ip="demo-a"),
        call(["adb", "-s", "demo-a", "forward", "--remove", "tcp:8000"], device_ip="demo-a"),
    ]


def test_forward_creation_never_rebinds_an_existing_host_port():
    model = ADBNetworkMixin()
    model._run = Mock(return_value={"success": True})
    ADBNetworkMixin.forward_port_async.__wrapped__(model, "demo-a", "8000", "80")
    assert "--no-rebind" in model._run.call_args.args[0]


@pytest.mark.parametrize("response, success", [
    ({"success": True, "output": "demo-b tcp:9000 tcp:90"}, True),
    ({"success": True, "output": "malformed rule"}, False),
    ({"success": False, "error": "server unavailable"}, False),
])
def test_remove_forward_never_guesses_rules_when_absent_or_query_failed(response, success):
    model = ADBNetworkMixin()
    model._run = Mock(return_value=response)
    result = ADBNetworkMixin.remove_all_forwards_async.__wrapped__(model, "demo-a")
    assert result["success"] is success
    assert model._run.call_count == 1


def test_remove_forward_stops_and_reports_partial_progress_on_failure():
    model = ADBNetworkMixin()
    model._run = Mock(side_effect=[
        {"success": True, "output": "demo-a tcp:8000 tcp:80\ndemo-a tcp:8001 tcp:81"},
        {"success": True},
        {"success": False, "error": "listener missing"},
    ])
    result = ADBNetworkMixin.remove_all_forwards_async.__wrapped__(model, "demo-a")
    assert result["success"] is False
    assert result["error"] == "listener missing"
    assert "1" in result["output"]
    assert model._run.call_count == 3


def test_single_device_forward_and_pid_keep_existing_submission_path():
    controller = Mock()
    controller._require_devices.return_value = True
    ADBFileMixin.forward_port(controller, ["demo-a", "demo-a"], "8080", "80")
    controller.advanced_model.forward_port_async.assert_called_once()
    ADBMediaMixin.kill_process(controller, ["demo-a"], "1234")
    controller.advanced_model.kill_process_async.assert_called_once()
