# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

from unittest.mock import patch

from models.adb_device import (
    ADBDevice,
    parse_connected_devices,
    parse_getprop_output,
    parse_labeled_sections,
)
from models.base.command_runner import CommandResult


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
        "device_1:\n  ip: device-1\n  Brand: Demo\n  Model: Phone\n  Aversion: '14'\n",
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
        assert DeviceStore.get_basic_devices_info() == [("Demo", "Phone", "device-1")]
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


def test_parse_getprop_output_extracts_bracketed_properties():
    output = (
        "[ro.product.model]: [Pixel 9]\n"
        "[ro.product.brand]: [Google]\n"
        "invalid line\n"
        "[persist.sys.timezone]: []\n"
    )

    assert parse_getprop_output(output) == {
        "ro.product.model": "Pixel 9",
        "ro.product.brand": "Google",
        "persist.sys.timezone": "",
    }


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
        "raw_result": "The device is starting to restart",
    }


def test_get_devices_basic_info_uses_single_getprop_call():
    with patch("models.adb_device.CommandRunner.run") as run:
        run.return_value = CommandResult(
            success=True,
            output="22127RK46C\nRedmi\n9\n",
        )

        info = ADBDevice.get_devices_basic_info("device-1")

    assert info == {"Model": "22127RK46C", "Brand": "Redmi", "Aversion": "9"}
    run.assert_called_once_with(
        [
            "adb",
            "-s",
            "device-1",
            "shell",
            "getprop ro.product.model; getprop ro.product.brand; "
            "getprop ro.build.version.release",
        ],
        timeout=15,
    )


def test_get_devices_basic_info_falls_back_to_individual_props():
    with (
        patch("models.adb_device.CommandRunner.run") as run,
        patch("models.adb_device.ADBModelCore._fetch_device_info") as fetch,
    ):
        run.return_value = CommandResult(success=False, error="offline")
        fetch.return_value = {"Model": "N/A", "Brand": "N/A", "Aversion": "N/A"}

        info = ADBDevice.get_devices_basic_info("device-1")

    assert info == {"Model": "N/A", "Brand": "N/A", "Aversion": "N/A"}
    fetch.assert_called_once()
    commands = fetch.call_args.args[0]
    assert list(commands) == ["Model", "Brand", "Aversion"]
    assert commands["Model"] == ["adb", "-s", "device-1", "shell", "getprop", "ro.product.model"]


def test_get_device_info_batches_properties_and_probe_commands():
    model = ADBDevice()
    batched_output = (
        "__ADBLAB_PROPS__\n"
        "[ro.product.model]: [Pixel]\n"
        "[ro.product.brand]: [Google]\n"
        "[ro.build.version.release]: [15]\n"
        "[ro.serialno]: [abc]\n"
        "[ro.build.version.sdk]: [35]\n"
        "[ro.product.cpu.abi]: [arm64-v8a]\n"
        "[ro.hardware]: [ranchu]\n"
        "[persist.sys.timezone]: [Asia/Shanghai]\n"
        "__ADBLAB_DF__\n"
        "Filesystem Size Used Avail Use% Mounted on\n"
        "__ADBLAB_MEMINFO__\n"
        "MemTotal: 123 kB\n"
        "MemAvailable: 45 kB\n"
        "__ADBLAB_WM__\n"
        "Physical size: 1080x2400\n"
        "Physical density: 440\n"
        "__ADBLAB_IP__\n"
        "wlan0: inet 192.168.1.2\n"
    )

    with patch("models.adb_device.CommandRunner.run") as run:
        run.return_value = CommandResult(success=True, output=batched_output)

        info = ADBDevice.get_device_info_async.__wrapped__(model, "device-1")

    assert info["Model"] == "Pixel"
    assert info["Android Version"] == "15"
    assert info["Total Memory"] == "MemTotal: 123 kB"
    assert info["Available Memory"] == "MemAvailable: 45 kB"
    assert info["Resolution"] == "Physical size: 1080x2400"
    assert info["Density"] == "Physical density: 440"
    assert info["device_ip"] == "device-1"
    assert info["ip"] == "device-1"
    run.assert_called_once()
    assert run.call_args.args[0][:4] == ["adb", "-s", "device-1", "shell"]
