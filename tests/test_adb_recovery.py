from unittest.mock import patch

from core.exec import CommandResult
from services.adb_recovery import recover_adb_server


def test_recover_adb_server_uses_graceful_restart_first():
    with (
        patch("services.adb_recovery.adb_path", return_value="C:/tools/adb.exe"),
        patch("services.adb_recovery.CommandRunner.run") as run,
        patch("services.adb_recovery.find_pids_listening_on") as find_listeners,
    ):
        run.side_effect = [CommandResult(success=True), CommandResult(success=True)]

        result = recover_adb_server()

    assert result.success is True
    assert result.forced is False
    assert result.detail == "graceful-restart"
    assert [call.args[0] for call in run.call_args_list] == [
        ["C:/tools/adb.exe", "kill-server"],
        ["C:/tools/adb.exe", "start-server"],
    ]
    find_listeners.assert_not_called()


def test_recover_adb_server_forces_only_matching_bundled_listener():
    with (
        patch("services.adb_recovery.adb_path", return_value="C:/tools/adb.exe"),
        patch("services.adb_recovery.CommandRunner.run") as run,
        patch("services.adb_recovery.find_pids_listening_on", return_value=[111]),
        patch(
            "services.adb_recovery.process_executable",
            return_value="C:/tools/adb.exe",
        ),
        patch(
            "services.adb_recovery.kill_process_tree",
            return_value=(True, "terminated"),
        ) as kill,
    ):
        run.side_effect = [
            CommandResult(success=False, error="Timeout(3s)"),
            CommandResult(success=True),
        ]

        result = recover_adb_server()

    assert result.success is True
    assert result.forced is True
    assert result.detail == "forced-restart"
    kill.assert_called_once_with(111, timeout=2.0)


def test_recover_adb_server_does_not_terminate_foreign_listener():
    with (
        patch("services.adb_recovery.adb_path", return_value="C:/tools/adb.exe"),
        patch("services.adb_recovery.CommandRunner.run") as run,
        patch("services.adb_recovery.find_pids_listening_on", return_value=[222]),
        patch(
            "services.adb_recovery.process_executable",
            return_value="C:/Android/platform-tools/adb.exe",
        ),
        patch("services.adb_recovery.kill_process_tree") as kill,
    ):
        run.return_value = CommandResult(success=False, error="protocol fault")

        result = recover_adb_server()

    assert result.success is False
    assert result.detail == "foreign-listener"
    assert run.call_count == 1
    kill.assert_not_called()
