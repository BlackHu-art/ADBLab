import subprocess
from unittest.mock import Mock, patch

from gui.panels.remote_panel import RemotePanel
from models.base.command_runner import CommandResult
from models.remote import RemoteControlService, ScrcpyConfig, ScrcpyService, build_scrcpy_args
from models.remote.control_mapping import directional_swipe, notification_swipe


def _scrcpy_config(**overrides):
    values = {
        "exe": "scrcpy.exe",
        "adb": "adb.exe",
        "device": "device-1",
        "maxsize": "1080p",
        "fps": "60",
        "bitrate": "12",
        "codec": "h264",
        "buffer": "50",
        "orientation": "0",
    }
    values.update(overrides)
    return ScrcpyConfig(**values)


def test_scrcpy_service_builds_launch_plan_with_preflight_and_encoder():
    runner = Mock()
    runner.run.side_effect = [
        CommandResult(success=True, output="scrcpy 3.3.1"),
        CommandResult(success=True, output="ok"),
        CommandResult(success=True, output="1024 bytes copied"),
        CommandResult(success=True, output="Physical size: 1080x2400"),
        CommandResult(success=True, output="OMX.qcom.video.encoder.avc h264 encoder"),
    ]
    service = ScrcpyService(command_runner=runner)

    plan = service.build_launch_plan(_scrcpy_config(hw_encoder=True))

    assert plan.version == "3.3.1"
    assert plan.device_info == "1080x2400"
    assert plan.encoder == "OMX.qcom.video.encoder.avc"
    assert "--video-encoder" in plan.args
    assert ("INFO", "Using encoder: OMX.qcom.video.encoder.avc") in plan.messages
    assert runner.run.call_count == 5


def test_scrcpy_service_launch_plan_warns_and_skips_device_info_when_preflight_fails():
    runner = Mock()
    runner.run.side_effect = [
        CommandResult(success=True, output="scrcpy 3.3.1"),
        CommandResult(success=False, error="device offline"),
    ]
    service = ScrcpyService(command_runner=runner)

    plan = service.build_launch_plan(_scrcpy_config())

    assert plan.args[:3] == ["scrcpy.exe", "-s", "device-1"]
    assert plan.device_info == ""
    assert ("WARNING", "Device device-1 not responding") in plan.messages
    assert ("WARNING", "Pre-flight check failed - launching anyway...") in plan.messages
    assert runner.run.call_count == 2


def test_scrcpy_service_caches_version_per_executable():
    runner = Mock()
    runner.run.return_value = CommandResult(success=True, output="scrcpy 3.3.1")
    service = ScrcpyService(command_runner=runner)

    assert service.version("scrcpy.exe") == "3.3.1"
    assert service.version("scrcpy.exe") == "3.3.1"

    runner.run.assert_called_once_with(["scrcpy.exe", "--version"], timeout=3)


def test_scrcpy_service_start_and_stop_delegate_to_process_runner():
    process_runner = Mock()
    proc = Mock()
    process_runner.start.return_value = proc
    service = ScrcpyService(process_runner=process_runner)

    assert service.start("scrcpy_device", ["scrcpy.exe"]) is proc
    service.stop("scrcpy_device", timeout=2)

    process_runner.start.assert_called_once_with(
        "scrcpy_device",
        ["scrcpy.exe"],
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
        bufsize=1,
    )
    process_runner.stop.assert_called_once_with("scrcpy_device", timeout=2)


def test_scrcpy_service_parse_fps_returns_status_text():
    assert ScrcpyService.parse_fps("[server] INFO: [59.8 fps]") == "59.8 fps"
    assert ScrcpyService.parse_fps("INFO: renderer ready") is None


def test_remote_control_service_sends_keyevent_and_directional_swipe():
    adb = Mock()
    adb.get_dimensions.return_value = ["1080", "2400"]
    service = RemoteControlService(adb)

    service.send_keyevent("device-1", "HOME")
    service.directional_swipe("device-1", "up", duration_ms=200)

    adb.shell_input.assert_any_call("keyevent 3", device_id="device-1")
    adb.shell_input.assert_any_call("swipe 540 2160 540 240 200", device_id="device-1")


def test_remote_control_service_reuses_cached_dimensions_for_fast_gestures():
    adb = Mock()
    adb.get_dimensions.return_value = ["1080", "2400"]
    service = RemoteControlService(adb)

    service.directional_swipe("device-1", "up")
    service.directional_swipe("device-1", "down")

    adb.get_dimensions.assert_called_once_with(device_id="device-1")


def test_remote_control_service_uses_launch_plan_dimensions_without_adb_query():
    adb = Mock()
    service = RemoteControlService(adb)
    service.remember_dimensions("device-1", ["720", "1280"])

    service.expand_notifications("device-1")

    adb.get_dimensions.assert_not_called()
    adb.shell_input.assert_called_once_with("swipe 360 0 360 1279 300", device_id="device-1")


def test_remote_control_service_rotation_clears_dimension_cache():
    adb = Mock()
    adb.shell.return_value = CommandResult(success=True)
    adb.get_dimensions.return_value = ["1080", "2400"]
    service = RemoteControlService(adb)
    service.remember_dimensions("device-1", ["720", "1280"])

    service.rotate_portrait("device-1")
    service.directional_swipe("device-1", "up")

    adb.get_dimensions.assert_called_once_with(device_id="device-1")


def test_remote_control_service_rotation_falls_back_to_legacy_setting():
    adb = Mock()
    adb.shell.side_effect = [
        CommandResult(success=True),
        CommandResult(success=False, error="unknown setting"),
        CommandResult(success=True),
    ]
    service = RemoteControlService(adb)

    service.rotate_landscape("device-1")

    assert adb.shell.call_args_list[0].args[0] == "settings put system accelerometer_rotation 0"
    assert adb.shell.call_args_list[1].args[0] == "settings put system user_rotation 1"
    assert adb.shell.call_args_list[2].args[0] == "settings put system rotation 1"


def test_remote_mapping_uses_safe_default_dimensions():
    assert notification_swipe(None, expand=True) == (540, 0, 540, 1919)
    assert directional_swipe(None, "left") == (972, 960, 108, 960)


def test_build_scrcpy_args_appends_extra_args_before_print_fps():
    args = build_scrcpy_args(_scrcpy_config(extra_args=["--window-title", "ADBLab"]))

    assert args[-3:] == ["--window-title", "ADBLab", "--print-fps"]


def test_remote_panel_launch_ready_uses_scrcpy_service_start():
    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = None
    panel._active_device = "device-1"
    panel._device_info = Mock()
    panel._update_status = Mock()
    panel._log = Mock()
    panel._scrcpy_service = Mock()
    panel._remote_control = Mock()
    panel._process_key = "scrcpy_test"
    panel._watchdog = Mock()
    panel._process = None
    proc = Mock()
    proc.stderr = None
    panel._scrcpy_service.start.return_value = proc

    with patch("gui.panels.remote_panel.threading.Thread") as thread_cls:
        RemotePanel._on_launch_ready(panel, ["scrcpy.exe", "-s", "device-1"], "1080x2400")

    panel._device_info.setText.assert_called_once_with("1080x2400")
    panel._remote_control.remember_dimensions.assert_called_once_with("device-1", ["1080", "2400"])
    panel._scrcpy_service.start.assert_called_once_with(
        "scrcpy_test",
        ["scrcpy.exe", "-s", "device-1"],
    )
    assert panel._process is proc
    thread_cls.return_value.start.assert_called_once()
    panel._watchdog.start.assert_called_once_with(500)


def test_remote_panel_stop_scrcpy_uses_scrcpy_service_stop():
    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = None
    panel._active_device = "device-1"
    panel._process = Mock()
    panel._watchdog = Mock()
    panel._set_running = Mock()
    panel._update_status = Mock()
    panel._scrcpy_service = Mock()
    panel._process_key = "scrcpy_test"
    panel._log = Mock()

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    with patch("gui.panels.remote_panel.threading.Thread", ImmediateThread):
        RemotePanel._stop_scrcpy(panel)

    assert panel._process is None
    assert panel._active_device is None
    panel._watchdog.stop.assert_called_once()
    panel._set_running.assert_called_once_with(False)
    panel._update_status.assert_called_once_with("Idle", None)
    panel._scrcpy_service.stop.assert_called_once_with("scrcpy_test", timeout=2)


def test_remote_panel_launch_finished_clears_active_device_when_start_fails():
    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = Mock()
    panel._active_device = "device-1"
    panel._process = None
    panel._set_running = Mock()
    panel._update_status = Mock()
    worker = Mock()
    worker.isInterruptionRequested.return_value = False
    panel._launch_worker = worker

    RemotePanel._on_launch_finished(panel, worker)

    assert panel._active_device is None
    panel._set_running.assert_called_once_with(False)
    panel._update_status.assert_called_once_with("Error", "#DC3545")
    worker.deleteLater.assert_called_once()
