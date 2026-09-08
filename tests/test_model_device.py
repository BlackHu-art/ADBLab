# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

from unittest.mock import patch

import pytest

from core.exec import CommandResult
from models.adb_device import (
    OVERVIEW_MARKERS,
    ADBDevice,
    parse_connected_devices,
    parse_device_overview,
    parse_labeled_sections,
)


@pytest.mark.parametrize("error", ["Timeout(15s)", "device offline", "Cancelled"])
def test_overview_transport_failure_does_not_start_more_queries(error):
    with patch(
        "models.adb_device.CommandRunner.run",
        return_value=CommandResult(False, error=error),
    ) as run:
        assert ADBDevice.get_device_overview_info("device-1") == {}
    assert run.call_count == 1


def test_overview_compatibility_fallback_uses_remaining_total_budget():
    clock = [10.0]
    budgets = []

    def run(_command, *, timeout, **_kwargs):
        budgets.append(timeout)
        clock[0] += 4.0
        return CommandResult(True, output="unmarked response")

    with (
        patch("models.adb_device.time.monotonic", side_effect=lambda: clock[0]),
        patch("models.adb_device.CommandRunner.run", side_effect=run),
    ):
        info = ADBDevice.get_device_overview_info("device-1", timeout=6)
    assert budgets == [6.0, 2.0]
    assert info["Model"] == "unmarked response"


def test_overview_does_not_fallback_after_cancelled_success():
    stopped = [False]

    def run(_command, *, cancelled=None, **_kwargs):
        stopped[0] = True
        assert cancelled is not None and cancelled()
        return CommandResult(True, output="unmarked response")

    with patch("models.adb_device.CommandRunner.run", side_effect=run) as command:
        info = ADBDevice.get_device_overview_info("device-1", cancelled=lambda: stopped[0])
    assert info == {}
    assert command.call_count == 1


def test_basic_compatibility_queries_stop_when_shared_budget_is_spent():
    clock = [10.0]
    budgets = []

    def run(_command, *, timeout, **_kwargs):
        budgets.append(timeout)
        clock[0] += 2.0
        if len(budgets) == 1:
            return CommandResult(False, error="sh: syntax error", returncode=2)
        return CommandResult(True, output="Example")

    with (
        patch("models.adb_device.time.monotonic", side_effect=lambda: clock[0]),
        patch("models.adb_device.CommandRunner.run", side_effect=run),
    ):
        info = ADBDevice.get_devices_basic_info("device-1", timeout=4)
    assert info == {"Model": "Example"}
    assert budgets == [4.0, 2.0]


def test_device_discovery_query_observes_model_shutdown_in_flight():
    model = ADBDevice()
    observed = []

    def run(_command, *, cancelled=None, **_kwargs):
        model.begin_shutdown()
        observed.append(callable(cancelled) and cancelled())
        return CommandResult(False, error="Cancelled")

    with patch("models.adb_device.CommandRunner.run", side_effect=run):
        result = ADBDevice.get_connected_devices_async.__wrapped__(model)
    assert observed == [True]
    assert not result["success"]
    assert result["devices"] == []


def test_device_discovery_preserves_stale_result_as_cancelled():
    model = ADBDevice()
    with patch(
        "models.adb_device.CommandRunner.run",
        return_value=CommandResult(False, stale=True),
    ) as run:
        result = ADBDevice.get_connected_devices_async.__wrapped__(model)

    assert result.get("stale") is True
    assert result.get("cancelled") is True
    assert not result["success"]
    assert result["devices"] == []
    assert result["error"] == ""
    assert result["message"]
    run.assert_called_once()


def test_parse_connected_devices_ignores_adb_banner_and_header():
    output = (
        "* daemon not running; starting now at tcp:5037\n"
        "* daemon started successfully\n"
        "List of devices attached\n"
        "emulator-5554\tdevice\n"
        "emulator-5556\tdevice product:sdk model:Pixel\n"
        "offline-1\toffline\n"
        "unauth-1\tunauthorized\n"
    )

    assert parse_connected_devices(output) == ["emulator-5554", "emulator-5556"]


def test_device_store_load_migrates_legacy_file(tmp_path):
    from models.device_store import DeviceStore

    legacy_file = tmp_path / "legacy.yaml"
    user_file = tmp_path / "config" / "connected_devices.yaml"
    legacy_file.write_text(
        "device_1:\n  ip: 192.0.2.1:5555\n  Brand: Demo\n  Model: Phone\n  Aversion: '14'\n",
        encoding="utf-8",
    )
    old_file_path = DeviceStore._file_path
    old_legacy_path = DeviceStore._legacy_file_path
    old_devices = dict(DeviceStore._devices)
    try:
        DeviceStore._file_path = str(user_file)
        DeviceStore._legacy_file_path = str(legacy_file)
        DeviceStore.load()

        assert user_file.exists()
        assert DeviceStore.get_basic_devices_info() == [("Demo", "Phone", "192.0.2.1:5555")]
    finally:
        DeviceStore._file_path = old_file_path
        DeviceStore._legacy_file_path = old_legacy_path
        DeviceStore._devices = old_devices


def test_app_settings_load_migrates_legacy_settings_file(tmp_path):
    from core import settings_manager

    legacy_file = tmp_path / "resources" / "app_settings.json"
    user_file = tmp_path / "config" / "app_settings.json"
    legacy_file.parent.mkdir()
    legacy_file.write_text('{"theme": "Dark", "continuous_device_scan": false}', encoding="utf-8")
    old_settings_file = settings_manager.SETTINGS_FILE
    old_legacy_file = settings_manager.LEGACY_SETTINGS_FILE
    old_instance = settings_manager.AppSettings._instance
    try:
        settings_manager.SETTINGS_FILE = str(user_file)
        settings_manager.LEGACY_SETTINGS_FILE = str(legacy_file)
        settings_manager.AppSettings._instance = None

        settings = settings_manager.AppSettings.instance()

        assert settings.get("theme") == "Dark"
        assert settings.get("continuous_device_scan") is False
        assert user_file.exists()
    finally:
        settings_manager.SETTINGS_FILE = old_settings_file
        settings_manager.LEGACY_SETTINGS_FILE = old_legacy_file
        settings_manager.AppSettings._instance = old_instance


def test_parse_labeled_sections_splits_batched_device_info_output():
    output = "MARK_A\none\nMARK_B\ntwo\nthree\n"

    assert parse_labeled_sections(output, {"A": "MARK_A", "B": "MARK_B"}) == {
        "A": "one",
        "B": "two\nthree",
    }


def test_restart_device_treats_reboot_returncode_zero_as_success():
    model = ADBDevice()

    with patch.object(model, "_run") as run:
        run.side_effect = [
            {"success": True, "output": "device"},
            {"success": True, "output": ""},
        ]

        result = ADBDevice.restart_device_async.__wrapped__(model, "device-1")

    assert result == {
        "device_ip": "device-1",
        "success": True,
        "requires_refresh": True,
        "raw_result": "Reboot request submitted; device startup has not been verified",
    }


def test_get_devices_basic_info_uses_single_getprop_call():
    with patch("models.adb_device.CommandRunner.run") as run:
        run.return_value = CommandResult(
            success=True,
            output="22127RK46C\nRedmi\n9\n28\narm64-v8a\nqcom\n",
        )

        info = ADBDevice.get_devices_basic_info("device-1")

    assert info == {
        "Model": "22127RK46C", "Brand": "Redmi", "Aversion": "9",
        "SDK Version": "28", "CPU Architecture": "arm64-v8a", "Hardware": "qcom",
    }
    run.assert_called_once()
    assert run.call_args.args == (
        [
            "adb",
            "-s",
            "device-1",
            "shell",
            "getprop ro.product.model; getprop ro.product.brand; "
            "getprop ro.build.version.release; getprop ro.build.version.sdk; "
            "getprop ro.product.cpu.abi; getprop ro.hardware",
        ],
    )
    assert 0 < run.call_args.kwargs["timeout"] <= 15
    assert run.call_args.kwargs["cancelled"] is None


def test_overview_reads_screen_memory_storage_and_battery_in_one_command():
    output = "\n".join([
        OVERVIEW_MARKERS["BASIC"], "Example phone", "Example", "14", "34", "arm64-v8a", "qcom",
        OVERVIEW_MARKERS["MEMORY"], "MemTotal: 8388608 kB", "MemAvailable: 3145728 kB",
        OVERVIEW_MARKERS["STORAGE"], "Filesystem 1K-blocks Used Available Use% Mounted on",
        "/dev/block/data 134217728 67108864 67108864 50% /data",
        OVERVIEW_MARKERS["SCREEN"], "Physical size: 1080x2400", "Physical density: 420",
        OVERVIEW_MARKERS["BATTERY"], "  level: 84", "  scale: 100", "  status: 2",
    ])
    with patch(
        "models.adb_device.CommandRunner.run",
        return_value=CommandResult(success=True, output=output),
    ) as run:
        info = ADBDevice.get_device_overview_info("demo-a")
    assert info == {
        "Model": "Example phone", "Brand": "Example", "Aversion": "14", "SDK Version": "34",
        "CPU Architecture": "arm64-v8a", "Hardware": "qcom", "Total Memory": "8.0 GiB",
        "Available Memory": "3.0 GiB", "Storage Total": "128.0 GiB",
        "Storage Available": "64.0 GiB", "Resolution": "1080 × 2400", "Density": "420 dpi",
        "Battery Level": "84%", "Battery Status": "充电中",
    }
    run.assert_called_once()
    assert run.call_args.args[0][:4] == ["adb", "-s", "demo-a", "shell"]
    assert "ro.serialno" not in run.call_args.args[0][-1]
    assert "ip addr" not in run.call_args.args[0][-1]
    assert 0 < run.call_args.kwargs["timeout"] <= 15


def test_overview_keeps_empty_basic_fields_and_ignores_invalid_metrics():
    output = "\n".join([
        OVERVIEW_MARKERS["BASIC"], "", "Example", "14", "34", "", "",
        OVERVIEW_MARKERS["MEMORY"], "cat: permission denied",
        OVERVIEW_MARKERS["STORAGE"], "/dev/data 100 50 900 50% /data",
        OVERVIEW_MARKERS["SCREEN"], "Physical size: 0x0", "Physical density: 0",
        OVERVIEW_MARKERS["BATTERY"], "level: 120", "scale: 100", "status: 99",
    ])
    assert parse_device_overview(output) == {
        "Model": "", "Brand": "Example", "Aversion": "14", "SDK Version": "34",
        "CPU Architecture": "", "Hardware": "",
    }


def test_unmarked_overview_read_falls_back_to_basic_information():
    # 超时不再回退；仍验证设备返回有效但缺少分段标记时的兼容路径。
    with patch("models.adb_device.CommandRunner.run") as run:
        run.side_effect = [
            CommandResult(True, output="unmarked response"),
            CommandResult(True, output="Example\nBrand\n14\n34\narm64\nqcom"),
        ]
        info = ADBDevice.get_device_overview_info("demo-a")
    assert info["Model"] == "Example"
    assert info["CPU Architecture"] == "arm64"
    assert run.call_count == 2


def test_get_devices_basic_info_falls_back_to_individual_props():
    with patch("models.adb_device.CommandRunner.run") as run:
        run.side_effect = [CommandResult(False, error="sh: syntax error", returncode=2)] + [
            CommandResult(True, output=value)
            for value in ("Example", "Brand", "14", "34", "arm64", "qcom")
        ]
        info = ADBDevice.get_devices_basic_info("device-1")
    assert info == {
        "Model": "Example", "Brand": "Brand", "Aversion": "14", "SDK Version": "34",
        "CPU Architecture": "arm64", "Hardware": "qcom",
    }
    assert run.call_count == 7
    assert run.call_args_list[1].args[0] == [
        "adb", "-s", "device-1", "shell", "getprop", "ro.product.model",
    ]


def test_restart_device_reports_abnormal_status():
    model = ADBDevice()
    with patch.object(model, "_run") as run:
        run.return_value = {"success": False, "error": "offline"}
        result = ADBDevice.restart_device_async.__wrapped__(model, "device-1")

    assert result["success"] is False
    assert "Abnormal device status" in result["error"]
    assert result["requires_refresh"] is False


def test_restart_device_reports_reboot_timeout_as_unknown():
    model = ADBDevice()
    with patch.object(model, "_run") as run:
        run.side_effect = [
            {"success": True, "output": "device"},
            {"success": False, "error": "Timeout(3s)"},
        ]
        result = ADBDevice.restart_device_async.__wrapped__(model, "device-1")

    assert result["success"] is False
    assert result["requires_refresh"] is True
    assert "unknown" in result["error"].lower()


def test_restart_device_allows_slow_native_launch_and_only_confirms_submission():
    model = ADBDevice()

    def run(command, *, timeout, **_kwargs):
        if command[-1] == "get-state":
            return CommandResult(True, output="device")
        if timeout <= 6.227:
            return CommandResult(False, error=f"Timeout({timeout}s)")
        return CommandResult(True)

    with patch("models.adb_model.CommandRunner.run", side_effect=run):
        result = ADBDevice.restart_device_async.__wrapped__(model, "device-1")

    assert result["success"] is True
    assert result["requires_refresh"] is True
    assert "submitted" in result["raw_result"].lower()


def test_restart_adb_allows_slow_native_server_start():
    model = ADBDevice()

    def run(_command, *, timeout, **_kwargs):
        if timeout <= 6.227:
            return CommandResult(False, error=f"Timeout({timeout}s)")
        return CommandResult(True)

    with (
        patch("models.adb_model.CommandRunner.run", side_effect=run),
        patch("models.adb_device.time.sleep"),
    ):
        result = ADBDevice.restart_adb_async.__wrapped__(model)

    assert result["success"] is True


def test_restart_device_reports_other_reboot_failure():
    model = ADBDevice()
    with patch.object(model, "_run") as run:
        run.side_effect = [
            {"success": True, "output": "device"},
            {"success": False, "error": "adb died"},
        ]
        result = ADBDevice.restart_device_async.__wrapped__(model, "device-1")

    assert result["success"] is False
    assert result["requires_refresh"] is False
    assert "adb died" in result["error"]
