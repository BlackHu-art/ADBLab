"""验证清数据权限拒绝的反馈、原始诊断和单次命令边界。"""

import threading
from unittest.mock import Mock, patch

import pytest

from adblab.application.action_results import (
    ActionResults,
    ActionSpec,
    capture_action_job,
    report_action_message,
)
from controllers._app_install import ADBAppInstallMixin
from core.exec import CommandResult
from models.adb_app import ADBApp
from models.app_manager_worker import AppManagerWorker

DENIED = (
    "Exception occurred while executing 'clear':\n"
    "java.lang.SecurityException: PID 1234 does not have permission "
    "android.permission.CLEAR_APP_USER_DATA to clear data of package com.example.app\n"
    "\tat com.android.server.am.ActivityManagerService.clearApplicationUserData"
    "(ActivityManagerService.java:3552)\n"
)
HINT = (
    "系统拒绝通过 ADB 清除应用数据。请在手机的应用信息页手动清除；"
    "若入口也受限，请联系设备管理员或系统厂商。"
)


@pytest.mark.parametrize("diagnostic", [
    DENIED,
    "Permission Denial: cannot clear application data",
    "java.lang.SecurityException: Cannot clear data for a protected package: com.example.app",
    "Permission denied: requires android.permission.CLEAR_APP_USER_DATA",
])
def test_clear_model_classifies_denial_without_retry_or_replacing_diagnostics(diagnostic):
    with patch("models.adb_model.CommandRunner.run", return_value=CommandResult(
        False, error=diagnostic, returncode=1,
    )) as execute:
        result = ADBApp.clear_app_data_async.__wrapped__(
            ADBApp(), "clear-demo", "com.example.app", 2,
        )

    execute.assert_called_once_with(
        ["adb", "-s", "clear-demo", "shell", "pm", "clear", "com.example.app"],
        timeout=30, shell=False,
    )
    assert result["success"] is False
    assert result["error"] == diagnostic
    assert result["error_code"] == "clear_data_permission_denied"
    assert result["user_message"] == HINT
    assert (result["device_ip"], result["package_name"], result["index"]) == (
        "clear-demo", "com.example.app", 2,
    )


@pytest.mark.parametrize("raw", [
    {"success": True, "output": "Success\n"},
    {"success": False, "error": "device offline"},
    {"success": False, "error": "Timed out after 30s"},
    {"success": False, "error": "Cancelled", "cancelled": True},
    {"success": False, "error": "", "stale": True},
    {"success": False, "error": "android.permission.CLEAR_APP_USER_DATA granted=true"},
    {"success": False, "error": "adb: insufficient permissions for device"},
])
def test_clear_model_preserves_unrelated_result_semantics(raw):
    model = ADBApp()
    with patch.object(model, "_run", return_value=dict(raw)) as execute:
        result = ADBApp.clear_app_data_async.__wrapped__(
            model, "clear-demo", "com.example.app", 1,
        )
    execute.assert_called_once()
    assert result == raw


def test_clear_model_keeps_output_if_execution_boundary_supplies_it():
    model = ADBApp()
    with patch.object(model, "_run", return_value={
        "success": False, "output": "Failed\n", "error": DENIED,
    }):
        result = ADBApp.clear_app_data_async.__wrapped__(
            model, "clear-demo", "com.example.app", 1,
        )
    assert result["output"] == "Failed\n"
    assert result["error"] == DENIED
    assert result["user_message"] == HINT


@pytest.mark.parametrize("output,error", [("", DENIED), (DENIED, ""), ("Failed\n", DENIED)])
def test_clear_worker_reports_actionable_denial_but_logs_complete_diagnostic(output, error):
    worker = AppManagerWorker("clear-demo", "clear_app", package_name="com.example.app")
    logs, feedback, completed = [], [], []
    worker.log_message.connect(logs.append)
    worker.operation_feedback.connect(lambda level, text: feedback.append((level, text)))
    worker.operation_done.connect(completed.append)
    with patch("models.app_manager_worker.CommandRunner.run", return_value=CommandResult(
        False, output=output, error=error, returncode=1,
    )) as execute:
        worker.run()
    execute.assert_called_once_with(
        ["adb", "-s", "clear-demo", "shell", "pm", "clear", "com.example.app"], timeout=30,
    )
    assert completed == []
    assert feedback == [("error", HINT)]
    assert DENIED in "\n".join(logs)
    if output:
        assert output in "\n".join(logs)


def test_clear_controller_exposes_hint_and_action_results_retain_original_trace():
    store = ActionResults(lambda _result: None)
    jobs = []
    store.run(
        ActionSpec("clear_data", "apps", "清除应用数据"), ("clear-demo",),
        lambda: jobs.append(capture_action_job("clear_app_data_async", "clear-demo")),
    )
    controller = Mock()
    controller._pending_lock = threading.Lock()
    controller._batch_starts = {}
    controller._emit_operation.side_effect = (
        lambda _operation, success, text: report_action_message(success, text)
    )
    payload = {
        "device_ip": "clear-demo", "package_name": "com.example.app", "success": False,
        "error": DENIED, "error_code": "clear_data_permission_denied", "user_message": HINT,
    }
    job = jobs[0]
    with store.scope(job.request_id, job):
        ADBAppInstallMixin._process_clear_app_data_result(controller, payload)
    store.complete(job, payload)
    controller._emit_operation.assert_called_once()
    assert controller._emit_operation.call_args.args[:2] == ("clear_data", False)
    assert HINT in controller._emit_operation.call_args.args[2].splitlines()[0]
    result = store.recent()[0]
    assert result.state == "failed"
    assert HINT in result.items[0].detail.splitlines()[0]
    assert "SecurityException" not in result.items[0].detail.splitlines()[0]
    assert DENIED.strip() in result.items[0].detail
