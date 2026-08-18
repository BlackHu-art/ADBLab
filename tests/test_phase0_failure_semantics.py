import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from models.adb_testing import ADBTesting
from models.app_manager_worker import AppManagerWorker
from models.base.command_runner import CommandResult
from utils.batch_tracker import BatchOperationTracker


def test_batch_tracker_reports_partial_failure_and_completes_once_under_concurrency():
    summaries = []
    tracker = BatchOperationTracker(
        64,
        "Batch Install",
        lambda operation, success, message: summaries.append((operation, success, message)),
    )
    outcomes = [True] * 63 + [False]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(tracker.record, outcomes))
        list(executor.map(tracker.record, [True] * 16))

    assert tracker.finished == 64
    assert tracker.success == 63
    assert len(summaries) == 1
    assert summaries[0][0] == "Batch Install"
    assert summaries[0][1] is False
    assert "Success: 63" in summaries[0][2]
    assert "Failed: 1" in summaries[0][2]


def _run_monkey_with_failed_focus_probes(tmp_path, command_result):
    model = ADBTesting()
    model._procs = Mock()
    logcat_proc = Mock()
    monkey_proc = Mock(pid=1234)
    monkey_proc.poll.return_value = None
    model._procs.start.side_effect = [logcat_proc, monkey_proc]
    model._procs.stop.return_value = None

    with (
        patch.object(model, "_run", return_value={"success": True, "output": ""}),
        patch.object(model, "_get_current_package", return_value=""),
        patch.object(model, "_wait_for_monkey_abort", return_value=False),
        patch("models.adb_testing.CommandRunner.run", return_value=command_result),
        patch("models.adb_testing.time.sleep"),
    ):
        result = ADBTesting.run_monkey_test_async.__wrapped__(
            model,
            "device-1",
            "com.example.app",
            {"events": 10},
            "com_example_app",
            str(tmp_path),
            1,
        )
    return model, result


@pytest.mark.parametrize(
    ("command_result", "expected_error"),
    [
        (CommandResult(success=False, error="Timeout(5s)"), "Device appears disconnected"),
        (
            SimpleNamespace(
                success=False,
                output="",
                error="transport stalled",
                returncode=1,
                timed_out=True,
            ),
            "Device appears disconnected",
        ),
        (CommandResult(success=True, output="ok"), "No foreground package detected"),
    ],
)
def test_monkey_focus_probe_failures_fail_closed_and_stop_process(
    tmp_path, command_result, expected_error
):
    model, result = _run_monkey_with_failed_focus_probes(tmp_path, command_result)

    assert result["success"] is False
    if command_result.success:
        assert "3 consecutive" in result["error"]
        assert expected_error in result["error"]
    else:
        assert result["error"] == expected_error
    model._procs.stop.assert_any_call("device-1_monkey")
    model._procs.stop.assert_any_call("device-1_logcat")


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("_launch_app", ("com.example.app",)),
        ("_clear_app", ("com.example.app",)),
        (
            "_modify_permission",
            ("com.example.app", "android.permission.CAMERA", "grant"),
        ),
    ],
)
def test_app_manager_simple_command_failure_never_reports_success(method_name, args):
    worker = AppManagerWorker("device-1", "unused")
    logs = []
    completed = []
    worker.log_message.connect(logs.append)
    worker.operation_done.connect(completed.append)
    worker._adb = Mock(
        return_value=CommandResult(success=False, error="device offline", returncode=1)
    )

    getattr(worker, method_name)(*args)

    assert completed == []
    assert any("Failed" in message and "device offline" in message for message in logs)
    assert not any(
        token in message
        for message in logs
        for token in ("Launched ", "Cleared data:", "Permission grant:")
    )


def test_app_manager_backup_pull_failure_does_not_create_success_zip(tmp_path):
    worker = AppManagerWorker("device-1", "unused")
    logs = []
    worker.log_message.connect(logs.append)

    def adb_result(*args, **_kwargs):
        if args[:2] == ("shell", "pm path com.example.app"):
            return CommandResult(
                success=True,
                output=(
                    "package:/data/app/com.example.app/base.apk\n"
                    "package:/data/app/com.example.app/split_config.apk"
                ),
            )
        if args[:1] == ("pull",) and str(args[1]).endswith("base.apk"):
            return CommandResult(success=True, output="pulled")
        return CommandResult(success=False, error="pull failed", returncode=1)

    worker._adb = Mock(side_effect=adb_result)
    worker._backup_app("com.example.app", str(tmp_path))

    assert not (tmp_path / "backup_com.example.app.zip").exists()
    assert any("Backup failed" in message and "pull failed" in message for message in logs)
    assert not any(message.startswith("Backup: ") for message in logs)


def test_app_manager_backup_all_pulls_success_creates_zip_and_completion(tmp_path):
    worker = AppManagerWorker("device-1", "unused")
    completed = []
    worker.operation_done.connect(completed.append)

    def adb_result(*args, **_kwargs):
        if args[:2] == ("shell", "pm path com.example.app"):
            return CommandResult(
                success=True,
                output=(
                    "package:/data/app/com.example.app/base.apk\n"
                    "package:/data/app/com.example.app/split_config.apk"
                ),
            )
        destination = Path(args[2])
        (destination / Path(args[1]).name).write_bytes(b"apk")
        return CommandResult(success=True, output="pulled")

    worker._adb = Mock(side_effect=adb_result)
    worker._backup_app("com.example.app", str(tmp_path))

    assert (tmp_path / "backup_com.example.app.zip").is_file()
    assert completed == ["backup"]


def _write_backup(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("base.apk", b"apk")


def test_app_manager_restore_partial_failure_does_not_emit_completion(tmp_path):
    first = tmp_path / "backup_one.zip"
    second = tmp_path / "backup_two.zip"
    _write_backup(first)
    _write_backup(second)

    worker = AppManagerWorker("device-1", "unused")
    logs = []
    completed = []
    worker.log_message.connect(logs.append)
    worker.operation_done.connect(completed.append)
    worker._adb = Mock(
        side_effect=[
            CommandResult(success=True, output="Success"),
            CommandResult(success=False, error="install failed", returncode=1),
        ]
    )

    worker._restore_apps([str(first), str(second)])

    assert completed == []
    assert any("Restore failed" in message and "install failed" in message for message in logs)
    assert any("Restore incomplete" in message for message in logs)


def test_app_manager_restore_all_success_emits_completion_once(tmp_path):
    backup = tmp_path / "backup_app.zip"
    _write_backup(backup)

    worker = AppManagerWorker("device-1", "unused")
    completed = []
    worker.operation_done.connect(completed.append)
    worker._adb = Mock(return_value=CommandResult(success=True, output="Success"))

    worker._restore_apps([str(backup)])

    assert completed == ["restore"]
