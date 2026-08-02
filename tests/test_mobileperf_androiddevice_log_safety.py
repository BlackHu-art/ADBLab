from types import SimpleNamespace
from unittest.mock import Mock

from mobileperf.android.tools import androiddevice
from mobileperf.android.tools.androiddevice import ADB


def _all_log_arguments(mock_logger: Mock) -> str:
    """汇总传给日志器的原始参数，避免格式化过程掩盖敏感值泄露。"""
    calls = []
    for level in ("debug", "info", "warning", "error", "critical"):
        calls.extend(getattr(mock_logger, level).call_args_list)
    return "\n".join(str(call) for call in calls)


def test_androiddevice_logs_only_safe_metadata_for_devices_commands_and_apps(monkeypatch):
    serial_one = "SERIAL-RAW-ALPHA"
    serial_two = "SERIAL-RAW-BETA"
    package_one = "com.private.customer.alpha"
    package_two = "com.private.customer.beta"
    command_argument = "--private-token=command-secret"
    process_id = 987654
    raw_devices = "List of devices attached\n" f"{serial_one}\tdevice\n" f"{serial_two}\tdevice\n"
    completed = SimpleNamespace(stdout=raw_devices, stderr="", returncode=0)
    mock_logger = Mock()

    monkeypatch.setattr(androiddevice, "logger", mock_logger)
    monkeypatch.setattr(ADB, "get_adb_path", staticmethod(lambda: "adb"))
    monkeypatch.setattr(androiddevice.subprocess, "run", lambda *_args, **_kwargs: completed)

    assert ADB.list_device() == [serial_one, serial_two]
    assert ADB.checkAdbNormal() is True

    launched_commands = []

    class FakeProcess:
        pid = process_id

        def communicate(self, timeout=None):
            return b"", f"permission denied {package_one} {command_argument}".encode()

        def poll(self):
            return 1

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(command, **_kwargs):
        launched_commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(androiddevice.subprocess, "Popen", fake_popen)
    adb = ADB.__new__(ADB)
    adb._adb_path = "adb"
    adb._device_id = serial_one
    adb.before_connect = True
    adb.after_connect = True

    raw_command_result = adb._run_cmd_once(
        "shell",
        f"pm path {package_one}",
        command_argument,
    )
    assert raw_command_result == f"permission denied {package_one} {command_argument}"
    assert launched_commands == [
        [
            "adb",
            "-s",
            serial_one,
            "shell",
            f"pm path {package_one}",
            command_argument,
        ]
    ]

    monkeypatch.setattr(
        adb,
        "run_shell_cmd",
        lambda *_args, **_kwargs: f"package:{package_one}\npackage:{package_two}\n",
    )
    assert adb.list_installed_app() == [package_one, package_two]

    logged = _all_log_arguments(mock_logger)
    for sensitive_value in (
        serial_one,
        serial_two,
        package_one,
        package_two,
        command_argument,
        str(process_id),
        raw_devices,
    ):
        assert sensitive_value not in logged

    assert "device_count=%s" in logged
    assert "verb=%s" in logged
    assert "package_count=%s" in logged
