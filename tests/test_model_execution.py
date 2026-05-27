import ctypes
import os
import threading
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from main import windows_app_user_model_id
from models.adb_app import ADBApp
from models.adb_device import parse_connected_devices
from models.adb_testing import ADBTesting
from models.base.command_runner import CommandResult
from models.base.focus_detector import detect_current_package, extract_package_name
from models.base.process_runner import ProcessRunner
from models.file_explorer_worker import ADBWorker
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.styles import BaseStyles
from gui.styles import theme
from utils.app_metadata import APP_RELEASE_TAG, APP_VERSION


def test_app_metadata_derives_release_tag_and_windows_app_id():
    assert APP_RELEASE_TAG == f"v{APP_VERSION}"
    major_minor = APP_VERSION.rsplit(".", 1)[0]
    assert windows_app_user_model_id() == f"ADBLab.Frankie.{major_minor}"


def test_apply_dark_title_bar_calls_dwm_without_ctypes_side_effect_imports():
    had_wintypes = hasattr(ctypes, "wintypes")
    original_wintypes = getattr(ctypes, "wintypes", None)
    if had_wintypes:
        delattr(ctypes, "wintypes")

    window = Mock()
    window.winId.return_value = 12345
    calls = []

    class DwmApi:
        @staticmethod
        def DwmSetWindowAttribute(*args):
            calls.append(args)
            return 0

    try:
        with patch.object(theme.sys, "platform", "win32"), \
             patch.object(theme.ctypes, "windll", Mock(dwmapi=DwmApi()), create=True):
            theme.apply_dark_title_bar(window)
    finally:
        if had_wintypes:
            ctypes.wintypes = original_wintypes

    assert len(calls) == 1


def test_panel_base_status_bar_style_has_theme_background():
    current_theme = BaseStyles.current_theme()
    try:
        BaseStyles.switch_theme("Dark")
        expected_bg = BaseStyles.color("PANEL_BG")
        style = BaseStyles.PANEL_BASE_STYLE()
        marker = "QStatusBar {"
        start = style.index(marker) + len(marker)
        status_bar_block = style[start:style.index("}", start)]
    finally:
        BaseStyles.switch_theme(current_theme)

    assert f"background-color: {expected_bg}" in status_bar_block


def test_dialog_status_bar_style_has_theme_background():
    current_theme = BaseStyles.current_theme()
    try:
        BaseStyles.switch_theme("Dark")
        expected_bg = BaseStyles.color("PANEL_BG")
        style = BaseStyles.STATUS_BAR_STYLE()
    finally:
        BaseStyles.switch_theme(current_theme)

    assert f"background-color: {expected_bg}" in style


def test_live_logcat_worker_finished_during_close_does_not_touch_deleted_buttons():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    dialog._closing = True
    dialog.start_btn = Mock()
    dialog.stop_btn = Mock()

    try:
        dialog._on_worker_finished()

        dialog.start_btn.setEnabled.assert_not_called()
        dialog.stop_btn.setEnabled.assert_not_called()
        assert dialog.worker is None
    finally:
        dialog.close()


def test_live_logcat_apply_theme_does_not_reconnect_theme_signal():
    _app = QApplication.instance() or QApplication([])

    class CountingLiveLogcatDialog(LiveLogcatDialog):
        def __init__(self, *args, **kwargs):
            self.theme_calls = 0
            super().__init__(*args, **kwargs)

        def _apply_theme(self, *args, **kwargs):
            self.theme_calls += 1
            return super()._apply_theme(*args, **kwargs)

    dialog = CountingLiveLogcatDialog(device_ip="device-1")
    try:
        BaseStyles.switch_theme("Dark")
        BaseStyles.switch_theme("Light")

        assert dialog.theme_calls == 3
    finally:
        dialog.close()


def test_live_logcat_ignores_queued_status_after_close():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    dialog._closing = True
    dialog.status_bar = Mock()

    try:
        dialog._on_status("Logcat stopped")

        dialog.status_bar.showMessage.assert_not_called()
    finally:
        dialog.close()


def test_live_logcat_ignores_queued_line_after_close():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    dialog._closing = True
    dialog.output = Mock()

    try:
        dialog._on_line("05-27 12:00:00.000 1 1 I Tag: message", "I")

        dialog.output.appendPlainText.assert_not_called()
        assert dialog.entries == []
    finally:
        dialog.close()


def test_process_runner_start_replaces_existing_process_without_deadlock():
    runner = ProcessRunner()
    old_proc = Mock()
    old_proc.poll.return_value = None
    old_proc.wait.return_value = 0
    new_proc = Mock()

    runner._procs["device_logcat"] = old_proc

    started = []

    def start_process():
        with patch("models.base.process_runner.subprocess.Popen", return_value=new_proc):
            started.append(runner.start("device_logcat", ["adb", "logcat"]))

    thread = threading.Thread(target=start_process, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert started == [new_proc]
    old_proc.terminate.assert_called_once()
    assert runner._procs["device_logcat"] is new_proc


def test_process_runner_start_stops_process_registered_during_start():
    runner = ProcessRunner()
    displaced_proc = Mock()
    displaced_proc.poll.return_value = None
    displaced_proc.wait.return_value = 0
    new_proc = Mock()

    def popen_side_effect(*args, **kwargs):
        runner._procs["device_logcat"] = displaced_proc
        return new_proc

    with patch("models.base.process_runner.subprocess.Popen", side_effect=popen_side_effect):
        started = runner.start("device_logcat", ["adb", "logcat"])

    assert started is new_proc
    displaced_proc.terminate.assert_called_once()
    assert runner._procs["device_logcat"] is new_proc



def test_process_runner_stop_all_without_deadlock():
    runner = ProcessRunner()
    old_proc = Mock()
    old_proc.poll.return_value = None
    old_proc.wait.return_value = 0
    runner._procs["device_logcat"] = old_proc

    thread = threading.Thread(target=runner.stop_all, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    old_proc.terminate.assert_called_once()
    assert runner._procs == {}



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



def test_extract_package_name_ignores_log_prefix_and_returns_real_package():
    output = "ACTIVITY Sys2038: com.example.app/.MainActivity pid=123"

    assert extract_package_name(output) == "com.example.app"



def test_extract_package_name_prefers_focus_line_over_other_packages():
    output = "ACTIVITY com.android.launcher3/.Launcher\n" \
             "mCurrentFocus=Window{u0 com.example.app/.MainActivity}"

    assert extract_package_name(output) == "com.example.app"



def test_detect_current_package_uses_window_focus_first():
    runner = Mock()
    runner.run.return_value = CommandResult(
        success=True,
        output="mCurrentFocus=Window{u0 com.example.app/.MainActivity}",
    )

    result = detect_current_package("device-1", runner=runner)

    assert result == {
        "success": True,
        "device_ip": "device-1",
        "package_name": "com.example.app",
    }
    runner.run.assert_called_once_with(
        [
            "adb", "-s", "device-1", "shell", "sh", "-c",
            "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'",
        ],
        timeout=5,
    )



def test_detect_current_package_falls_back_to_resumed_activity():
    runner = Mock()
    runner.run.side_effect = [
        CommandResult(success=True, output=""),
        CommandResult(success=True, output="mResumedActivity: com.example.app/.MainActivity"),
    ]

    result = detect_current_package("device-1", runner=runner)

    assert result["success"] is True
    assert result["package_name"] == "com.example.app"
    assert runner.run.call_count == 2



def test_get_current_package_uses_shared_detector():
    model = ADBApp()

    with patch("models.adb_app.detect_current_package") as detect:
        detect.return_value = {"success": True, "device_ip": "device-1", "package_name": "com.example.app"}

        result = model.get_current_package("device-1")

    assert result["success"] is True
    assert result["package_name"] == "com.example.app"
    detect.assert_called_once_with("device-1")



def test_install_apk_uses_run_helper_and_preserves_result_fields():
    model = ADBApp()

    with patch.object(model, "_run") as run:
        run.return_value = {
            "success": True,
            "output": "Success",
            "device_ip": "device-1",
            "apk_path": "demo.apk",
            "index": 1,
            "apk_name": "demo.apk",
        }

        result = model.install_apk("device-1", "demo.apk", "demo.apk", 1)

    assert result["success"] is True
    assert result["apk_name"] == "demo.apk"
    run.assert_called_once_with(
        ["adb", "-s", "device-1", "install", "-r", "demo.apk"],
        timeout=120,
        device_ip="device-1",
        apk_path="demo.apk",
        index=1,
        apk_name="demo.apk",
    )



def test_list_installed_packages_parses_command_output():
    model = ADBApp()

    with patch.object(model, "_run") as run:
        run.return_value = {
            "success": True,
            "output": "package:com.example.one\npackage:com.example.two\n",
            "device_ip": "device-1",
        }

        result = model.list_installed_packages("device-1", 3)

    assert result == {
        "device_ip": "device-1",
        "success": True,
        "packages": ["com.example.one", "com.example.two"],
        "index": 3,
    }



def test_file_explorer_worker_uses_command_runner_for_short_commands():
    worker = ADBWorker("device-1", ["shell", "ls", "/sdcard"])
    emitted = []
    worker.finished.connect(lambda output, failed: emitted.append((output, failed)))

    with patch("models.file_explorer_worker.CommandRunner.run") as run:
        run.return_value = CommandResult(success=True, output="Download\nPictures")

        worker.run()

    assert emitted == [("Download\nPictures", False)]
    run.assert_called_once_with(
        ["adb", "-s", "device-1", "shell", "ls", "/sdcard"],
        timeout=30,
    )



def test_testing_model_current_package_uses_shared_detector():
    model = ADBTesting()

    with patch("models.adb_testing.detect_current_package") as detect:
        detect.return_value = {"success": True, "device_ip": "device-1", "package_name": "com.example.app"}

        package_name = model._get_current_package("device-1")

    assert package_name == "com.example.app"
    detect.assert_called_once_with("device-1")



def test_kill_monkey_stops_local_process_and_reports_clear_message_on_empty_error():
    model = ADBTesting()
    proc = Mock()
    proc.poll.return_value = None
    proc.wait.return_value = 0
    model._procs._procs["device-1_monkey"] = proc

    with patch.object(model, "_run") as run:
        run.return_value = {"success": False, "error": "", "device_ip": "device-1"}

        result = model.kill_monkey_async.__wrapped__(model, "device-1", 1)

    assert result == {
        "device_ip": "device-1",
        "index": 1,
        "success": False,
        "message": "Monkey stop command failed with no error output",
    }
    proc.terminate.assert_called_once()
    assert model._procs._procs == {}
