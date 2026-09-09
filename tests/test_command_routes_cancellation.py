"""验证固定命令路由、查询取消和兼容清理预算，所有设备调用均为替身。"""

import shlex
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from controllers._input import ADBInputMixin
from controllers.action_catalog import ACTION_SIGNALS
from controllers.signals import ADBControllerSignals
from core.exec import CommandResult
from models.adb_advanced import ADBAdvanced
from models.adb_system import ADBSystemMixin
from models.adb_testing import ADBTesting


@pytest.mark.parametrize("service", ["wifi", "data", "bluetooth", "nfc"])
@pytest.mark.parametrize("action", ["enable", "disable"])
def test_fixed_svc_is_validated_targeted_shell(service, action, qt_application):
    model = ADBAdvanced()
    model._run = Mock(return_value={"success": True, "output": ""})
    result = ADBSystemMixin.svc_async.__wrapped__(model, "demo", service, action)
    assert result["success"]
    assert model._run.call_args.args[0] == ["adb", "-s", "demo", "shell", "svc", service, action]
    assert not model._run.call_args.kwargs.get("native_only", False)
    model.deleteLater()


@pytest.mark.parametrize("service,action", [
    ("wifi; reboot", "enable"), ("wifi", "enable; reboot"), ("power", "enable"),
])
def test_svc_rejects_non_allowlisted_input(service, action, qt_application):
    model = ADBAdvanced()
    model._run = Mock()
    result = ADBSystemMixin.svc_async.__wrapped__(model, "demo", service, action)
    assert not result["success"]
    model._run.assert_not_called()
    model.deleteLater()


def test_controller_fixed_command_uses_svc_method_and_rejects_extra_tokens():
    controller = SimpleNamespace(
        _require_devices=Mock(return_value=True), _emit_operation=Mock(), advanced_model=Mock(),
    )
    ADBInputMixin.system_service(controller, ["demo"], "svc wifi enable")
    controller.advanced_model.svc_async.assert_called_once_with("demo", "wifi", "enable")
    ADBInputMixin.system_service(controller, ["demo"], "svc wifi enable; reboot")
    assert controller.advanced_model.svc_async.call_count == 1
    controller.advanced_model.run_shell_command_async.assert_not_called()


@pytest.mark.parametrize("success", [False, True])
def test_svc_async_dispatch_retains_action_identity_and_feedback(qt_application, success):
    from adblab.application.action_results import ActionResults

    controller = ADBInputMixin.__new__(ADBInputMixin)
    controller.signals = ADBControllerSignals()
    controller.log_service = Mock()
    controller._build_handler_map()
    controller.action_results = ActionResults(lambda _result: None)
    model = ADBAdvanced()
    controller.advanced_model = model
    queued = []
    model.thread_pool = SimpleNamespace(start=queued.append)
    model._run = Mock(return_value={
        "success": success, "device_ip": "demo", "service": "wifi", "action": "enable",
        "output": "", "error": "Permission denied" if not success else "",
    })
    model.command_finished.connect(controller._handle_async_response)
    feedback = []
    controller.signals.operation_completed.connect(lambda *args: feedback.append(args))
    spec = ACTION_SIGNALS["system_service_requested"]
    controller.action_results.run(
        spec, ("demo",), lambda: controller.system_service(["demo"], "svc wifi enable"),
    )
    assert len(queued) == 1
    queued[0].run()
    result = controller.action_results.recent()[0]
    assert result.spec.key == "system_service"
    assert result.spec.section == "system.services"
    assert result.state == ("succeeded" if success else "failed")
    assert feedback[0][:2] == ("system_service", success)
    if not success:
        assert "Permission denied" in feedback[0][2]
    controller.action_results.close()
    model.deleteLater()


@pytest.mark.parametrize("method,args", [
    ("list_processes_async", ()), ("top_snapshot_async", ()),
    ("gfxinfo_async", ("com.example.app",)), ("wakelocks_async", ()),
    ("netstats_detail_async", ()), ("content_query_async", ("content://settings/system",)),
    ("cmd_dumpsys_service_async", ("battery",)), ("cmd_dumpsys_service_async", ("",)),
    ("ime_list_async", ()), ("pm_list_features_async", ()),
])
def test_system_reads_forward_live_shutdown(method, args, qt_application, monkeypatch):
    model = ADBAdvanced()
    callbacks = []

    def run(_cmd, **kwargs):
        callbacks.append(kwargs.get("cancelled"))
        return CommandResult(success=True, output="ok")

    monkeypatch.setattr("models.adb_model.CommandRunner.run", run)
    getattr(ADBSystemMixin, method).__wrapped__(model, "demo", *args)
    assert callable(callbacks[0])
    assert not callbacks[0]()
    model.begin_shutdown()
    assert callbacks[0]()
    model.deleteLater()


@pytest.mark.parametrize("tags", ["", "Demo:D *:S", "quoted'$(reboot)"])
@pytest.mark.parametrize("clear", [False, True])
def test_oneshot_logs_preserve_filter_env_and_failures(
    tags, clear, qt_application, monkeypatch, tmp_path,
):
    model = ADBTesting()
    monkeypatch.setenv("ANDROID_LOG_TAGS", tags)
    model._run = Mock(return_value={"success": False, "error": "Permission denied"})
    if clear:
        result = ADBTesting.cleanup_device_logs_async.__wrapped__(model, "demo")
    else:
        result = ADBTesting.retrieve_device_logs_async.__wrapped__(
            model, "demo", str(tmp_path / "out.txt"),
        )
    assert not result["success"] and result["error"] == "Permission denied"
    call = model._run.call_args
    assert call.args[0][:4] == ["adb", "-s", "demo", "shell"]
    assert shlex.split(" ".join(call.args[0][4:])) == [
        f"ANDROID_LOG_TAGS={tags}", "logcat", "-c" if clear else "-d",
    ]
    assert 0 < call.kwargs["timeout"] <= 30
    if not clear:
        assert callable(call.kwargs["cancelled"])
    assert model._run.call_count == 1
    assert not (tmp_path / "out.txt").exists()
    model.deleteLater()


@pytest.mark.parametrize("reason", ["abort", "shutdown"])
def test_monkey_probe_cancels_inflight_and_skips_connectivity(reason, qt_application, monkeypatch):
    model = ADBTesting()
    observed = []

    def detect(_device, **kwargs):
        callback = kwargs.get("cancelled")
        observed.append(callback)
        if reason == "abort":
            model._aborted_devices.add("demo")
        else:
            model.begin_shutdown()
        return {"success": False}

    monkeypatch.setattr("models.adb_testing.detect_current_package", detect)
    connectivity = Mock(return_value=CommandResult(success=True))
    monkeypatch.setattr("models.adb_testing.CommandRunner.run", connectivity)
    result = model._probe_current_package("demo")
    assert callable(observed[0]) and observed[0]()
    assert result["cancelled"] and not result["success"]
    connectivity.assert_not_called()
    model.deleteLater()


def test_monkey_probe_connectivity_shares_remaining_deadline(qt_application, monkeypatch):
    model = ADBTesting()
    clock = [100.0]
    monkeypatch.setattr("models.adb_testing.time.monotonic", lambda: clock[0])

    def detect(_device, **kwargs):
        assert kwargs["timeout"] == 15
        clock[0] += 14
        return {"success": False}

    monkeypatch.setattr("models.adb_testing.detect_current_package", detect)
    connectivity = Mock(return_value=CommandResult(success=True))
    monkeypatch.setattr("models.adb_testing.CommandRunner.run", connectivity)
    assert not model._probe_current_package("demo")["success"]
    assert connectivity.call_args.kwargs["timeout"] == 1
    assert callable(connectivity.call_args.kwargs["cancelled"])
    model.deleteLater()


def test_legacy_screenshot_cleanup_gets_separate_budget_and_exact_owned_path(
    qt_application, monkeypatch,
):
    model = ADBTesting()
    clock = [100.0]
    calls = []
    monkeypatch.setattr("models.adb_testing.time.monotonic", lambda: clock[0])

    def run(command, **kwargs):
        calls.append((command, kwargs))
        clock[0] = 131
        return CommandResult(success=False, error="Timeout(30s)")

    monkeypatch.setattr("models.adb_testing.CommandRunner.run", run)
    result = model._capture_legacy_screenshot("demo", "unused.png", 130, lambda: False)
    assert not result.success
    assert len(calls) == 2
    assert calls[1][0] == ["adb", "-s", "demo", "shell", "rm", "-f", calls[0][0][-1]]
    assert calls[1][1]["timeout"] >= 15
    assert calls[1][1]["cancelled"] == model.is_shutting_down
    model.deleteLater()


def test_cancelled_monkey_probe_does_not_start_query(qt_application, monkeypatch):
    model = ADBTesting()
    model._aborted_devices.add("demo")
    detect = Mock()
    connectivity = Mock()
    monkeypatch.setattr("models.adb_testing.detect_current_package", detect)
    monkeypatch.setattr("models.adb_testing.CommandRunner.run", connectivity)
    assert model._probe_current_package("demo")["cancelled"]
    detect.assert_not_called()
    connectivity.assert_not_called()
    model.deleteLater()


def test_monkey_probe_timeout_does_not_start_connectivity(qt_application, monkeypatch):
    model = ADBTesting()
    clock = [100.0]
    monkeypatch.setattr("models.adb_testing.time.monotonic", lambda: clock[0])

    def detect(_device, **kwargs):
        assert kwargs["deadline"] == 115
        clock[0] = 115
        return {"success": False}

    monkeypatch.setattr("models.adb_testing.detect_current_package", detect)
    connectivity = Mock()
    monkeypatch.setattr("models.adb_testing.CommandRunner.run", connectivity)
    result = model._probe_current_package("demo")
    assert not result["success"] and result["timed_out"]
    connectivity.assert_not_called()
    model.deleteLater()


def test_monkey_probe_rejects_replaced_batch_and_ignores_other_device_abort(
    qt_application, monkeypatch,
):
    model = ADBTesting()
    model.prepare_monkey_batch("demo", "old")
    model._aborted_devices.add("other")

    def detect(_device, **kwargs):
        assert not kwargs["cancelled"]()
        model.discard_prepared_monkey_batch("demo", "old")
        assert model.prepare_monkey_batch("demo", "new")
        assert kwargs["cancelled"]()
        return {"success": True, "package_name": "com.example.app"}

    monkeypatch.setattr("models.adb_testing.detect_current_package", detect)
    result = model._probe_current_package("demo")
    assert not result["success"] and result["cancelled"]
    assert model._monkey_batches["demo"].batch_id == "new"
    model.deleteLater()


def test_monkey_preclear_failure_does_not_start_processes(qt_application, tmp_path):
    model = ADBTesting()
    model._procs = Mock()
    model._run = Mock(return_value={"success": False, "error": "Permission denied"})
    result = ADBTesting.run_monkey_test_async.__wrapped__(
        model, "demo", "com.example.app", {"events": 10}, "demo", str(tmp_path), 1,
    )
    assert not result["success"] and result["error"] == "Permission denied"
    assert model._run.call_count == 1
    assert model._run.call_args.args[0][3] == "shell"
    model._procs.start.assert_not_called()
    assert "demo" not in model._monkey_batches
    model.deleteLater()


@pytest.mark.parametrize("shutdown", [False, True])
def test_log_export_publishes_only_successful_active_result(qt_application, tmp_path, shutdown):
    model = ADBTesting()

    def run(_command, **kwargs):
        assert callable(kwargs["cancelled"])
        if shutdown:
            model.begin_shutdown()
        return {"success": True, "output": "中文日志\nSecond line"}

    model._run = Mock(side_effect=run)
    target = tmp_path / "log.txt"
    result = ADBTesting.retrieve_device_logs_async.__wrapped__(model, "demo", str(target))
    assert result["success"] is (not shutdown)
    assert target.exists() is (not shutdown)
    if not shutdown:
        assert target.read_text(encoding="utf-8") == "中文日志\nSecond line"
    model.deleteLater()
