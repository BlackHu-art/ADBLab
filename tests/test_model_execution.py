import ctypes
import os
import subprocess
import sys
import threading
import time
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QWidget,
)

from controllers._app import ADBAppMixin
from controllers._base import _ADBControllerBase
from controllers._device import ADBDeviceMixin
from core.adb_bridge import ADBBridge, ADBInputSession
from core.log_service import LogService
from core.perf_trace import attach_perf, build_async_perf, split_perf
from gui.dialogs.app_manager import AppDetailsDialog, AppManagerDialog
from gui.dialogs.file_explorer import FileExplorerDialog
from gui.dialogs.performance_launcher import PerformanceLauncherDialog
from gui.dialogs.screenshot_viewer import ScreenshotViewer
from gui.main_frame import MainFrame, _ScanThread
from gui.panels.log_panel import LogPanel
from main import windows_app_user_model_id
from models.adb_advanced import ADBAdvanced
from models.adb_app import ADBApp
from models.adb_device import (
    ADBDevice,
    parse_connected_devices,
    parse_getprop_output,
    parse_labeled_sections,
)
from models.adb_testing import ADBTesting
from models.adb_system import ADBSystemMixin
from models.base.command_runner import CommandResult
from models.base.focus_detector import detect_current_package, extract_package_name
from models.base.process_runner import CREATE_NEW_CONSOLE, ProcessRunner
from models.file_explorer_worker import ADBWorker, TransferWorker
from models.mobileperf import MobilePerfMonkeyConfig, MobilePerfRunConfig, MobilePerfRunner
from gui.dialogs.lifecycle import WorkerSignalBinding, safe_disconnect
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.panels.app_panel import AppPanel
from gui.panels.base_panel import BasePanel
from gui.panels.device_manager import DeviceManager
from gui.panels.side_panel import SidePanel
from gui.panels.side_panel_signals import SidePanelSignals
from gui.panels.remote_panel import RemotePanel, ScrcpyLaunchWorker
from gui.styles import BaseStyles
from gui.styles import theme
from utils.app_metadata import APP_RELEASE_TAG, APP_VERSION
from utils.adb_targets import normalize_adb_connect_target
from utils.batch_tracker import BatchOperationTracker


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


def test_live_logcat_batches_visible_line_appends():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    appended = []
    dialog.output = Mock()
    dialog.output.appendPlainText.side_effect = appended.append

    try:
        dialog._on_line("05-27 12:00:00.000 1 1 I Tag: one", "I")
        dialog._on_line("05-27 12:00:00.000 1 1 I Tag: two", "I")

        dialog.output.appendPlainText.assert_not_called()
        dialog._flush_pending_lines()

        assert appended == [
            "05-27 12:00:00.000 1 1 I Tag: one\n"
            "05-27 12:00:00.000 1 1 I Tag: two"
        ]
        assert len(dialog.entries) == 2
    finally:
        dialog.close()


def test_scrcpy_launch_args_include_selected_ui_options():
    cfg = {
        "exe": "scrcpy.exe",
        "device": "device-1",
        "maxsize": "1080p",
        "fps": "60",
        "bitrate": "12",
        "codec": "h265",
        "buffer": "50",
        "orientation": "1",
        "fullscreen": True,
        "always_on_top": True,
        "no_audio": True,
        "show_touches": True,
        "stay_awake": True,
        "turn_screen_off": True,
        "record_path": "C:/tmp/out.mp4",
        "no_window": True,
    }

    args = ScrcpyLaunchWorker._build_args(cfg, "OMX.test.encoder")

    assert args[:3] == ["scrcpy.exe", "-s", "device-1"]
    assert ["-m", "1080"] == args[3:5]
    assert "--video-codec" in args
    assert "h265" in args
    assert "--video-encoder" in args
    assert "OMX.test.encoder" in args
    assert "--record" in args
    assert "C:/tmp/out.mp4" in args
    assert "--no-playback" in args
    assert "--no-window" in args
    assert args[-1] == "--print-fps"


def test_scrcpy_launch_args_omit_defaults():
    cfg = {
        "exe": "scrcpy.exe",
        "device": "device-1",
        "maxsize": "Default",
        "fps": "30",
        "bitrate": "8",
        "codec": "h264",
        "buffer": "0",
        "orientation": "0",
        "fullscreen": False,
        "always_on_top": False,
        "no_audio": False,
        "show_touches": False,
        "stay_awake": False,
        "turn_screen_off": False,
        "record_path": "",
        "no_window": False,
    }

    args = ScrcpyLaunchWorker._build_args(cfg, None)

    assert "-m" not in args
    assert "--video-codec" not in args
    assert "--video-encoder" not in args
    assert "--video-buffer=0" not in args
    assert not any(arg.startswith("--lock-video-orientation") for arg in args)
    assert "--record" not in args
    assert "--no-window" not in args
    assert args[-1] == "--print-fps"


def test_safe_disconnect_ignores_already_disconnected_signals():
    class AlreadyDisconnectedSignal:
        def disconnect(self, _handler=None):
            raise RuntimeError("already disconnected")

    safe_disconnect(AlreadyDisconnectedSignal(), Mock())


def test_safe_disconnect_suppresses_pyside_disconnect_warnings():
    class WarningSignal:
        def disconnect(self, _handler=None):
            warnings.warn("Failed to disconnect from signal", RuntimeWarning)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        safe_disconnect(WarningSignal(), Mock())

    assert caught == []


def test_worker_signal_binding_connects_and_disconnects_handlers():
    class FakeSignal:
        def __init__(self):
            self.connected = []
            self.disconnected = []

        def connect(self, handler):
            self.connected.append(handler)

        def disconnect(self, handler=None):
            self.disconnected.append(handler)

    class FakeWorker:
        def __init__(self):
            self.finished = FakeSignal()

    worker = FakeWorker()
    result_signal = FakeSignal()
    result_handler = Mock()
    finished_handler = Mock()
    binding = WorkerSignalBinding(
        worker=worker,
        handlers=((result_signal, result_handler),),
        finished_handler=finished_handler,
    )

    binding.connect()
    binding.disconnect()
    binding.disconnect()

    assert result_signal.connected == [result_handler]
    assert worker.finished.connected == [finished_handler]
    assert result_signal.disconnected == [result_handler]
    assert worker.finished.disconnected == [finished_handler]


def test_process_runner_start_replaces_existing_process_without_deadlock():
    ProcessRunner._global_procs.clear()
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
    ProcessRunner._global_procs.clear()
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


def test_process_runner_start_forwards_stream_kwargs():
    ProcessRunner._global_procs.clear()
    runner = ProcessRunner()
    proc = Mock()

    with patch("models.base.process_runner.subprocess.Popen", return_value=proc) as popen:
        started = runner.start(
            "logcat_device",
            ["adb", "logcat"],
            stdout=Mock(),
            stderr=Mock(),
            cwd="C:/work",
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
            env={"ADB_PATH": "adb-test"},
        )

    assert started is proc
    assert popen.call_args.kwargs["cwd"] == "C:/work"
    assert popen.call_args.kwargs["text"] is True
    assert popen.call_args.kwargs["encoding"] == "utf-8"
    assert popen.call_args.kwargs["errors"] == "ignore"
    assert popen.call_args.kwargs["bufsize"] == 1
    assert popen.call_args.kwargs["env"] == {"ADB_PATH": "adb-test"}


def test_process_runner_spawn_supports_untracked_external_launches():
    ProcessRunner._global_procs.clear()
    runner = ProcessRunner()
    proc = Mock()

    with patch("models.base.process_runner.subprocess.Popen", return_value=proc) as popen:
        started = runner.spawn(
            ["cmd.exe", "/K", "echo hi"],
            cwd="C:/work",
            creationflags=123,
        )

    assert started is proc
    assert runner.active_keys == []
    assert popen.call_args.args[0] == ["cmd.exe", "/K", "echo hi"]
    assert popen.call_args.kwargs["cwd"] == "C:/work"
    assert popen.call_args.kwargs["creationflags"] == 123


def test_command_runner_run_to_file_streams_binary_stdout(tmp_path):
    from models.base.command_runner import CommandRunner

    output_path = tmp_path / "out.bin"
    proc_result = Mock(returncode=0, stderr=b"")

    with patch("models.base.command_runner.subprocess.run", return_value=proc_result) as run:
        result = CommandRunner.run_to_file(["python", "-c", "print('ok')"], str(output_path))

    assert result.success is True
    assert result.output == str(output_path)
    assert run.call_args.kwargs["stdout"].name == str(output_path)
    assert run.call_args.kwargs["stderr"] == subprocess.PIPE


def test_command_runner_logs_slow_sanitized_command():
    from models.base.command_runner import CommandRunner

    proc_result = Mock(returncode=0, stdout="ok", stderr="")

    with patch("models.base.command_runner._get_adb_path", return_value="adb.exe"), \
         patch("models.base.command_runner.subprocess.run", return_value=proc_result), \
         patch("models.base.command_runner.perf_counter", side_effect=[1.0, 1.5]), \
         patch("models.base.command_runner._slow_threshold_ms", return_value=100), \
         patch("core.log_service.LogService") as log_service_cls:
        result = CommandRunner.run(
            ["adb", "-s", "device-1", "shell", "input", "text", "secret text"],
            timeout=5,
        )

    assert result.success is True
    log_service_cls.return_value.log.assert_called_once()
    message = log_service_cls.return_value.log.call_args.args[1]
    assert "adb shell input text" in message
    assert "secret text" not in message


def test_main_frame_open_cmd_launches_terminal_via_process_runner():
    frame = SimpleNamespace()
    runner = Mock()

    with patch("gui.main_frame.ProcessRunner", return_value=runner), \
         patch("platform.system", return_value="Windows"), \
         patch("gui.main_frame.os.path.abspath", return_value="D:/VSCodeStation/ADBLab/gui/main_frame.py"), \
         patch(
             "gui.main_frame.os.path.dirname",
             side_effect=["D:/VSCodeStation/ADBLab/gui", "D:/VSCodeStation/ADBLab"],
         ):
        MainFrame._open_cmd(frame)

    runner.spawn.assert_called_once()
    assert runner.spawn.call_args.args[0][0] == "cmd.exe"
    assert runner.spawn.call_args.kwargs["creationflags"] == CREATE_NEW_CONSOLE


def test_scan_thread_uses_command_runner_for_device_polling():
    _app = QApplication.instance() or QApplication([])
    thread = _ScanThread()
    emitted = []
    thread.devices_changed.connect(emitted.append)

    with patch("gui.main_frame.CommandRunner.run") as run, \
         patch.object(_ScanThread, "msleep", side_effect=lambda _ms: setattr(thread, "_stop_flag", True)):
        run.return_value = CommandResult(success=True, output="List of devices attached\ndevice-1\tdevice\n")
        thread.run()

    run.assert_called_once_with(["adb", "devices"], timeout=5)
    assert emitted == [["device-1"]]


def test_scan_thread_skips_polling_while_command_runner_is_busy():
    _app = QApplication.instance() or QApplication([])
    thread = _ScanThread(interval_ms=3000)

    with patch("gui.main_frame.CommandRunner.active_count", return_value=1), \
         patch("gui.main_frame.CommandRunner.run") as run, \
         patch.object(_ScanThread, "msleep", side_effect=lambda _ms: setattr(thread, "_stop_flag", True)):
        thread.run()

    run.assert_not_called()


def test_scan_thread_emits_when_device_set_changes_with_same_count():
    _app = QApplication.instance() or QApplication([])
    thread = _ScanThread(interval_ms=3000)
    emitted = []
    sleeps = {"count": 0}
    thread.devices_changed.connect(emitted.append)

    def stop_after_two_polls(_ms):
        sleeps["count"] += 1
        if sleeps["count"] >= 60:
            thread._stop_flag = True

    with patch("gui.main_frame.CommandRunner.active_count", return_value=0), \
         patch("gui.main_frame.CommandRunner.run") as run, \
         patch.object(_ScanThread, "msleep", side_effect=stop_after_two_polls):
        run.side_effect = [
            CommandResult(success=True, output="List of devices attached\ndevice-a\tdevice\n"),
            CommandResult(success=True, output="List of devices attached\ndevice-b\tdevice\n"),
        ]
        thread.run()

    assert emitted == [["device-a"], ["device-b"]]


def test_main_frame_starts_scan_thread_with_debounced_refresh():
    frame = SimpleNamespace()
    frame._scan_thread = None
    frame.adb_controller = Mock()
    frame._schedule_scan_refresh = Mock()

    class FakeScanThread:
        def __init__(self, interval_ms=15000):
            self.interval_ms = interval_ms
            self.devices_changed = Mock()
            self.started = False

        def isRunning(self):
            return False

        def start(self):
            self.started = True

    with patch("gui.main_frame._ScanThread", FakeScanThread), \
         patch("core.settings_manager.AppSettings") as settings_cls:
        settings_cls.instance.return_value.get.return_value = 12000
        MainFrame._start_scan_thread(frame)

    frame._scan_thread.devices_changed.connect.assert_called_once_with(
        frame._schedule_scan_refresh
    )
    frame.adb_controller.refresh_devices.assert_not_called()
    assert frame._scan_thread.interval_ms == 12000
    assert frame._scan_thread.started is True


def test_main_frame_init_defers_adb_bootstrap_until_ui_is_built():
    _app = QApplication.instance() or QApplication([])
    created = {}

    def fake_bootstrap(self):
        created["central_widget_ready"] = self.centralWidget() is not None
        created["scan_thread"] = self._scan_thread

    fake_log_panel = QWidget()
    fake_log_panel._append_log = Mock()
    fake_side_panel = QWidget()
    fake_side_panel.device_widget = QWidget()
    fake_side_panel.signals = Mock()
    fake_side_panel.apply_device_theme = Mock()
    fake_side_panel.update_device_list = Mock()
    fake_side_panel.refresh_device_choices = Mock()
    fake_side_panel.update_email = Mock()
    fake_side_panel.update_vercode = Mock()
    fake_side_panel.on_recording_finished = Mock()
    fake_side_panel.on_operation_completed = Mock()
    fake_side_panel.update_current_package = Mock()
    fake_side_panel.current_package_text = Mock(return_value="")
    fake_side_panel.selected_devices = []

    with patch("gui.main_frame.LogService"), \
         patch("gui.main_frame.LogPanel", return_value=fake_log_panel), \
         patch("gui.main_frame.SidePanel") as side_panel_cls, \
         patch("gui.main_frame.ADBController") as controller_cls, \
         patch("gui.main_frame.resource_path", return_value=""), \
         patch("gui.main_frame.MainFrame._bootstrap_adb_async", fake_bootstrap), \
         patch("utils.adb_resolver.resolve_adb_path") as resolve:
        side_panel_cls.return_value = fake_side_panel
        controller_cls.return_value.signals = Mock()
        frame = MainFrame()

    try:
        assert created == {"central_widget_ready": True, "scan_thread": None}
        resolve.assert_not_called()
    finally:
        # 本用例只验证初始化顺序，避免在 teardown 启动异步应用级关机。
        frame._close_ready = True
        frame.close()


def test_main_frame_start_device_discovery_respects_scan_setting():
    frame = SimpleNamespace()
    frame._closing = False
    frame._start_scan_thread = Mock()
    frame._initial_refresh_timer = Mock()
    frame.adb_controller = Mock()

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings_cls.instance.return_value.get.return_value = True

        MainFrame._start_device_discovery(frame)

    frame._start_scan_thread.assert_called_once()
    frame._initial_refresh_timer.start.assert_not_called()
    frame.adb_controller.refresh_devices.assert_not_called()


def test_main_frame_start_device_discovery_uses_cancelable_initial_refresh_timer():
    frame = SimpleNamespace()
    frame._closing = False
    frame._start_scan_thread = Mock()
    frame._initial_refresh_timer = Mock()

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings_cls.instance.return_value.get.return_value = False

        MainFrame._start_device_discovery(frame)

    frame._start_scan_thread.assert_not_called()
    frame._initial_refresh_timer.start.assert_called_once_with(0)


def test_main_frame_start_device_discovery_skips_after_close():
    frame = SimpleNamespace()
    frame._closing = True
    frame._start_scan_thread = Mock()
    frame._initial_refresh_timer = Mock()
    frame.adb_controller = Mock()

    MainFrame._start_device_discovery(frame)

    frame._start_scan_thread.assert_not_called()
    frame._initial_refresh_timer.start.assert_not_called()
    frame.adb_controller.refresh_devices.assert_not_called()


def test_main_frame_stop_scan_thread_uses_short_ui_wait():
    frame = SimpleNamespace()
    frame._initial_refresh_timer = Mock()
    frame._initial_refresh_timer.isActive.return_value = True
    frame._scan_refresh_timer = Mock()
    frame._scan_refresh_timer.isActive.return_value = True
    frame._scan_thread = Mock()
    frame._scan_thread.isRunning.return_value = True
    frame._scan_thread.wait.return_value = True
    scan_thread = frame._scan_thread

    MainFrame._stop_scan_thread(frame)

    frame._initial_refresh_timer.stop.assert_called_once()
    frame._scan_refresh_timer.stop.assert_called_once()
    scan_thread.stop.assert_called_once()
    scan_thread.wait.assert_called_once_with(150)


def test_main_frame_stop_scan_thread_uses_blocking_wait_on_close():
    frame = SimpleNamespace()
    frame._initial_refresh_timer = Mock()
    frame._initial_refresh_timer.isActive.return_value = False
    frame._scan_refresh_timer = Mock()
    frame._scan_refresh_timer.isActive.return_value = False
    frame._scan_thread = Mock()
    frame._scan_thread.isRunning.return_value = True
    frame._scan_thread.wait.return_value = True
    scan_thread = frame._scan_thread

    MainFrame._stop_scan_thread(frame, blocking=True)

    scan_thread.stop.assert_called_once()
    scan_thread.wait.assert_called_once_with(6000)
    assert frame._scan_thread is None


def test_main_frame_refresh_toolbar_icons_updates_registered_buttons():
    _app = QApplication.instance() or QApplication([])
    frame = SimpleNamespace()
    button = QPushButton()
    button.setProperty("iconName", "circle-half-tilt.svg")
    frame.findChildren = Mock(return_value=[button])
    frame._refresh_always_on_top_button = lambda: MainFrame._refresh_always_on_top_button(
        frame
    )

    with patch("gui.main_frame.get_themed_icon", return_value=QIcon()) as themed_icon:
        MainFrame._refresh_toolbar_icons(frame)

    themed_icon.assert_called_once_with("circle-half-tilt.svg")


def test_main_frame_does_not_import_performance_monitor_at_module_load():
    import gui.main_frame as main_frame_module

    assert not hasattr(main_frame_module, "PerformanceMonitorDialog")


def test_main_frame_performance_button_opens_launcher_dialog():
    _app = QApplication.instance() or QApplication([])
    frame = SimpleNamespace()
    frame.left_panel = Mock()
    frame.left_panel.selected_devices = ["device-1"]
    frame.left_panel.current_package_text.return_value = "com.example.app"
    frame._find_active_dialog = Mock(return_value=None)
    frame._register_dialog = Mock(side_effect=lambda dialog, *_args: dialog)

    with patch("gui.dialogs.performance_launcher.PerformanceLauncherDialog.show") as show:
        MainFrame._show_performance_monitor(frame)

    frame._register_dialog.assert_called_once()
    dialog = frame._register_dialog.call_args.args[0]
    assert isinstance(dialog, PerformanceLauncherDialog)
    assert dialog.windowTitle() == "Performance - device-1"
    assert not hasattr(dialog, "device_edit")
    assert dialog.package_edit.text() == "com.example.app"
    assert dialog.save_path_edit.text().replace("\\", "/").endswith("/mobileperf/device-1")
    show.assert_called_once()
    dialog.close()


def test_main_frame_performance_button_requires_selected_device():
    frame = SimpleNamespace()
    frame.left_panel = Mock()
    frame.left_panel.selected_devices = []
    frame.log_panel = Mock()
    frame.log_service = Mock()
    frame._find_active_dialog = Mock()
    frame._register_dialog = Mock()

    MainFrame._show_performance_monitor(frame)

    assert frame.log_service.log.call_args_list[-1].args == (
        "WARNING",
        "No device selected",
    )
    assert [call.args[0] for call in frame.log_service.log.call_args_list[:-1]] == [
        "DEBUG",
        "DEBUG",
    ]
    frame.log_panel._append_log.assert_not_called()
    frame._register_dialog.assert_not_called()


def test_main_frame_theme_change_forces_running_performance_dialog_refresh():
    frame = SimpleNamespace()
    dialog = Mock()
    stale_dialog = Mock()
    stale_dialog._sync_theme_state.side_effect = RuntimeError("deleted")
    frame._active_dialogs = [dialog, stale_dialog]

    MainFrame._refresh_active_dialog_themes(frame)

    dialog._sync_theme_state.assert_called_once_with(force=True)
    assert frame._active_dialogs == [dialog]


def test_main_frame_always_on_top_updates_state_without_recreating_window_when_native_fails():
    _app = QApplication.instance() or QApplication([])
    frame = SimpleNamespace()
    frame._always_on_top = False
    frame._set_always_on_top_native = Mock(return_value=False)
    frame._apply_window_flags = Mock()
    frame.setWindowFlags = Mock()
    frame.show = Mock()
    button = QPushButton()
    button.setCheckable(True)
    frame.tb_always_on_top = button
    frame._refresh_always_on_top_button = lambda: MainFrame._refresh_always_on_top_button(
        frame
    )

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = settings_cls.instance.return_value
        MainFrame.set_always_on_top(frame, True)

    assert frame._always_on_top is True
    frame._set_always_on_top_native.assert_called_once_with(True)
    frame._apply_window_flags.assert_not_called()
    frame.setWindowFlags.assert_not_called()
    frame.show.assert_not_called()
    settings.set.assert_called_once_with("always_on_top", True)
    assert button.toolTip() == "Unpin from top"
    assert button.isChecked() is True
    assert button.property("iconName") == "push-pin-slash.svg"


def test_main_frame_always_on_top_native_path_does_not_recreate_window():
    _app = QApplication.instance() or QApplication([])
    frame = SimpleNamespace()
    frame._always_on_top = False
    frame._set_always_on_top_native = Mock(return_value=True)
    frame._apply_window_flags = Mock()
    frame.show = Mock()
    button = QPushButton()
    button.setCheckable(True)
    frame.tb_always_on_top = button
    frame._refresh_always_on_top_button = lambda: MainFrame._refresh_always_on_top_button(
        frame
    )

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = settings_cls.instance.return_value
        MainFrame.set_always_on_top(frame, True)

    frame._set_always_on_top_native.assert_called_once_with(True)
    frame._apply_window_flags.assert_not_called()
    frame.show.assert_not_called()
    settings.set.assert_called_once_with("always_on_top", True)
    assert button.property("iconName") == "push-pin-slash.svg"


def test_performance_launcher_perfetto_button_opens_perfetto_home():
    _app = QApplication.instance() or QApplication([])
    with patch("gui.dialogs.performance_launcher.QDesktopServices.openUrl") as open_url:
        PerformanceLauncherDialog.open_perfetto()

    open_url.assert_called_once()
    assert open_url.call_args.args[0].toString() == "https://ui.perfetto.dev/"


def test_performance_launcher_get_current_package_updates_package_field():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")

    with patch("gui.dialogs.performance_launcher.detect_current_package") as detect, patch(
        "gui.dialogs.performance_launcher.CurrentPackageWorker.start"
    ) as start_worker:
        detect.return_value = {
            "success": True,
            "device_ip": "device-1",
            "package_name": "com.example.app",
        }
        dialog.fetch_current_package()
        start_worker.assert_called_once_with()
        dialog._package_worker.run()
        dialog._package_worker.finished.emit()

    assert dialog.package_edit.text() == "com.example.app"
    assert dialog.get_package_btn.isEnabled() is True
    dialog.close()


def test_performance_launcher_build_config_uses_title_device_and_device_save_dir(tmp_path):
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="127.0.0.1:5555", package_name="com.example.app")
    dialog.save_path_edit.setText(str(tmp_path / "mobileperf"))

    cfg = dialog.build_config()

    assert cfg.device_id == "127.0.0.1:5555"
    assert cfg.package == "com.example.app"
    assert cfg.mailbox == ""
    assert not hasattr(dialog, "mailbox_edit")
    assert "mailbox" not in [label.text() for label in dialog.findChildren(QLabel)]
    assert Path(cfg.save_path).name == "127.0.0.1_5555"
    assert dialog.serialnum_label.text() == "127.0.0.1:5555"
    assert dialog.serialnum_label.objectName() == "onlineDeviceLabel"
    assert BaseStyles.color("LOG_SUCCESS") in dialog.styleSheet()
    dialog.close()


def test_performance_launcher_collects_monkey_config_from_controls():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1", package_name="com.example.app")
    try:
        dialog.monkey_check.setChecked(True)
        dialog.monkey_throttle_combo.setCurrentText("1000")
        dialog.monkey_seed_edit.setText("42")
        dialog.monkey_ignore_crashes.setChecked(False)
        dialog.monkey_ignore_timeouts.setChecked(True)
        dialog.monkey_ignore_security.setChecked(False)
        dialog.monkey_kill_after_error.setChecked(True)
        dialog.monkey_pct_combos["pct_touch"].setCurrentText("40")
        dialog.monkey_pct_combos["pct_motion"].setCurrentText("20")
        dialog.monkey_pct_combos["pct_nav"].setCurrentText("30")
        dialog.monkey_pct_combos["pct_anyevent"].setCurrentText("10")
        for key in [
            "pct_trackball",
            "pct_majornav",
            "pct_syskeys",
            "pct_appswitch",
            "pct_flip",
            "pct_pinchzoom",
        ]:
            dialog.monkey_pct_combos[key].setCurrentText("0")

        cfg = dialog.build_config()

        assert cfg.monkey_enabled is True
        assert cfg.monkey_config.throttle_ms == 1000
        assert cfg.monkey_config.seed == 42
        assert cfg.monkey_config.ignore_crashes is False
        assert cfg.monkey_config.ignore_timeouts is True
        assert cfg.monkey_config.ignore_security is False
        assert cfg.monkey_config.kill_after_error is True
        assert cfg.monkey_config.total_percentage == 100
        assert dialog.monkey_total_label.text() == "Total: 100%"
    finally:
        dialog.close()


def test_performance_launcher_monkey_total_uses_uncommitted_edit_text_and_full_labels():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1", package_name="com.example.app")
    try:
        dialog.monkey_check.setChecked(True)
        values = {
            "pct_touch": "35",
            "pct_motion": "15",
            "pct_trackball": "0",
            "pct_nav": "20",
            "pct_majornav": "10",
            "pct_syskeys": "5",
            "pct_appswitch": "5",
            "pct_anyevent": "10",
            "pct_flip": "0",
            "pct_pinchzoom": "0",
        }
        for key, value in values.items():
            combo = dialog.monkey_pct_combos[key]
            combo.lineEdit().setText(value)

        cfg = dialog.build_config()
        label_texts = {label.text() for label in dialog.findChildren(QLabel)}

        assert dialog.monkey_total_label.text() == "Total: 100%"
        assert cfg.monkey_config.total_percentage == 100
        assert cfg.monkey_config.pct_touch == 35
        assert cfg.monkey_config.pct_appswitch == 5
        assert "Major navigation events" in label_texts
        assert "App switch events" in label_texts
        assert "Keyboard flip events" in label_texts
        assert "Pinch/zoom events" in label_texts
    finally:
        dialog.close()


def test_performance_launcher_monkey_throttle_width_fits_largest_value_after_font_change():
    _app = QApplication.instance() or QApplication([])
    old_ui_size = BaseStyles.DEFAULT_FONT_SIZE
    BaseStyles.DEFAULT_FONT_SIZE = 20
    dialog = PerformanceLauncherDialog(device_ip="device-1", package_name="com.example.app")
    try:
        dialog._apply_theme()
        metrics = dialog.fontMetrics()

        assert dialog.monkey_throttle_combo.minimumWidth() >= metrics.horizontalAdvance("2000") + 54
        assert dialog.monkey_seed_edit.minimumWidth() >= metrics.horizontalAdvance("1000000") + 28
    finally:
        BaseStyles.DEFAULT_FONT_SIZE = old_ui_size
        dialog.close()


def test_performance_launcher_normalizes_mixed_separator_save_path():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="emulator-5554", package_name="com.example.app")
    dialog.save_path_edit.setText("E:/Download")

    try:
        cfg = dialog.build_config()

        assert cfg.save_path == os.path.normpath(r"E:\Download\emulator-5554")
        assert "E:/Download\\" not in cfg.save_path
    finally:
        dialog.close()


def test_performance_launcher_batches_logs_and_uses_ui_font_size():
    _app = QApplication.instance() or QApplication([])
    old_ui_size = BaseStyles.DEFAULT_FONT_SIZE
    old_log_size = BaseStyles.LOG_FONT_SIZE_VAR
    BaseStyles.DEFAULT_FONT_SIZE = 17
    BaseStyles.LOG_FONT_SIZE_VAR = 11
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._apply_theme()

        dialog._append_log("INFO", "first")
        dialog._append_log("ERROR", "second")

        font = dialog.log_view.font()
        assert font.pointSize() == 17 or font.pixelSize() == 17
        assert "first" not in dialog.log_view.toPlainText()

        dialog._flush_pending_logs()

        text = dialog.log_view.toPlainText()
        assert "first" in text
        assert "second" in text
        assert "[INFO] first" in text
    finally:
        BaseStyles.DEFAULT_FONT_SIZE = old_ui_size
        BaseStyles.LOG_FONT_SIZE_VAR = old_log_size
        dialog.close()


def test_performance_launcher_config_and_log_follow_global_ui_font():
    def effective_size(widget):
        font = widget.font()
        return font.pointSize() if font.pointSize() > 0 else font.pixelSize()

    _app = QApplication.instance() or QApplication([])
    old_ui_size = BaseStyles.DEFAULT_FONT_SIZE
    old_log_size = BaseStyles.LOG_FONT_SIZE_VAR
    BaseStyles.DEFAULT_FONT_SIZE = 18
    BaseStyles.LOG_FONT_SIZE_VAR = 10
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._apply_theme()

        assert effective_size(dialog.package_edit) == 18
        assert effective_size(dialog.frequency_combo) == 18
        assert effective_size(dialog.monkey_check) == 18
        assert effective_size(dialog.log_view) == 18
        hints = [w for w in dialog.findChildren(QLabel) if w.objectName() == "configHint"]
        assert hints
        assert all(effective_size(hint) == 18 for hint in hints)
    finally:
        BaseStyles.DEFAULT_FONT_SIZE = old_ui_size
        BaseStyles.LOG_FONT_SIZE_VAR = old_log_size
        dialog.close()


def test_performance_launcher_log_ignores_log_font_size_and_uses_ui_document_font():
    def effective_font_size(font):
        return font.pointSize() if font.pointSize() > 0 else font.pixelSize()

    _app = QApplication.instance() or QApplication([])
    old_ui_size = BaseStyles.DEFAULT_FONT_SIZE
    old_log_size = BaseStyles.LOG_FONT_SIZE_VAR
    BaseStyles.DEFAULT_FONT_SIZE = 18
    BaseStyles.LOG_FONT_SIZE_VAR = 10
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._append_log("INFO", "before")
        dialog._flush_pending_logs()

        BaseStyles.LOG_FONT_SIZE_VAR = 14
        BaseStyles.DEFAULT_FONT_SIZE = 16
        dialog._apply_theme()

        assert effective_font_size(dialog.log_view.font()) == 16
        assert effective_font_size(dialog.log_view.document().defaultFont()) == 16
        assert effective_font_size(dialog.log_view.viewport().font()) == 16
        assert dialog.log_view.toPlainText().strip()
    finally:
        BaseStyles.DEFAULT_FONT_SIZE = old_ui_size
        BaseStyles.LOG_FONT_SIZE_VAR = old_log_size
        dialog.close()


def test_performance_launcher_syncs_theme_when_signal_was_missed():
    _app = QApplication.instance() or QApplication([])
    old_theme = BaseStyles.current_theme()
    BaseStyles.switch_theme("Light")
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    dialog._theme_sync_timer.stop()
    try:
        light_style = dialog.styleSheet()

        theme._current_theme = "Dark"
        dialog._sync_theme_state()

        assert dialog._applied_theme_signature[0] == "Dark"
        assert BaseStyles.color("PANEL_BG") in dialog.styleSheet()
        assert dialog.styleSheet() != light_style
    finally:
        theme._current_theme = old_theme
        BaseStyles.switch_theme(old_theme)
        dialog.close()


def test_performance_launcher_monkey_parameter_text_follows_dark_theme_colors():
    _app = QApplication.instance() or QApplication([])
    old_theme = BaseStyles.current_theme()
    BaseStyles.switch_theme("Dark")
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    dialog._theme_sync_timer.stop()
    try:
        dialog.monkey_check.setChecked(True)
        style = dialog.styleSheet()

        assert "QLabel#inlineLabel" in style
        assert "QWidget#inlineRow QComboBox QLineEdit" in style
        assert BaseStyles.color("TEXT_PRIMARY") in style
        assert BaseStyles.color("INPUT_BG") in style
        assert "color: #000" not in style
        assert "color: black" not in style.lower()
        assert "monkeyOptionCheck" not in style
        assert "monkeyOption" not in style
        assert "QCheckBox::indicator" not in style
        assert dialog.monkey_check.property("monkeyOption") is None
        for checkbox in (
            dialog.monkey_ignore_crashes,
            dialog.monkey_ignore_timeouts,
            dialog.monkey_ignore_security,
            dialog.monkey_kill_after_error,
        ):
            assert checkbox.property("monkeyOption") is None
            assert checkbox.objectName() == ""
    finally:
        BaseStyles.switch_theme(old_theme)
        dialog.close()


def test_performance_launcher_raw_mobileperf_logs_are_not_reprefixed():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        raw_line = "[2026-06-13 10:00:00,000]INFO:mobileperf:startup:time is up"

        dialog._append_log("RAW", raw_line)
        dialog._flush_pending_logs()

        text = dialog.log_view.toPlainText().strip()
        assert text == raw_line
        assert "[RAW]" not in text
    finally:
        dialog.close()


def test_performance_launcher_running_status_is_green_and_progress_updates():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._set_running(True)
        dialog._run_duration_seconds = 100
        dialog._run_started_at = time.monotonic() - 25
        dialog._runner.is_running = Mock(return_value=True)

        dialog._update_progress()

        assert dialog.status_label.text() == "Running"
        assert BaseStyles.color("LOG_SUCCESS") in dialog.status_label.styleSheet()
        assert 20 <= dialog.progress_bar.value() <= 30
        assert dialog.progress_bar.format() == f"{dialog.progress_bar.value()}%"

        dialog._run_started_at = time.monotonic() - 500
        dialog._update_progress()

        assert dialog.progress_bar.value() == 99
    finally:
        dialog.close()


def test_performance_launcher_finished_sets_progress_to_complete():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._runner_finished_handled = False
        dialog._run_started_at = time.monotonic()
        dialog._run_duration_seconds = 100
        dialog._runner.latest_result_dir = Mock(return_value="")
        dialog._runner.latest_report_file = Mock(return_value="")

        dialog._mark_runner_finished()

        assert dialog.progress_bar.value() == 100
        assert dialog.progress_bar.format() == "100%"
        assert dialog.status_label.text() == "Idle"
    finally:
        dialog.close()


def test_performance_launcher_stopping_status_is_warning_color():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._set_status("Stopping", "stopping")

        assert dialog.status_label.text() == "Stopping"
        assert BaseStyles.color("LOG_WARNING") in dialog.status_label.styleSheet()
    finally:
        dialog.close()


def test_performance_launcher_runner_finished_restores_buttons_once():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._set_running(True)
        dialog._runner_finished_handled = False
        dialog._poll_timer.start()

        dialog._on_runner_finished()
        dialog._on_runner_finished()

        assert dialog.start_btn.isEnabled() is True
        assert dialog.stop_btn.isEnabled() is False
        assert dialog.status_label.text() == "Idle"
        assert dialog._poll_timer.isActive() is False
        assert dialog.log_view.toPlainText().count("MobilePerf ended") == 1
    finally:
        dialog.close()


def test_mobileperf_config_generation_does_not_touch_default_config(tmp_path):
    default_config = Path("mobileperf/config.conf")
    before = default_config.read_text(encoding="utf-8")
    cfg = MobilePerfRunConfig(
        device_id="device-1",
        package="com.example.app",
        frequency_seconds=2,
        timeout_minutes=3,
        dumpheap_minutes=4,
        monkey_enabled=True,
        exception_keywords=["fatal exception", "has died"],
        phone_log_paths=["/data/anr", "/sdcard/logs"],
        save_path=str(tmp_path / "out"),
        mailbox="qa@example.com",
        monkey_config=MobilePerfMonkeyConfig(
            throttle_ms=1000,
            seed=42,
            ignore_crashes=False,
            ignore_timeouts=True,
            ignore_security=False,
            kill_after_error=True,
            pct_touch=40,
            pct_motion=20,
            pct_nav=30,
            pct_anyevent=10,
            pct_trackball=0,
            pct_majornav=0,
            pct_syskeys=0,
            pct_appswitch=0,
            pct_flip=0,
            pct_pinchzoom=0,
        ),
    )

    generated = Path(cfg.write_config(tmp_path))

    assert generated.name == "mobileperf_run.conf"
    text = generated.read_text(encoding="utf-8")
    assert "package = com.example.app" in text
    assert "monkey = true" in text
    assert "monkey_throttle = 1000" in text
    assert "monkey_seed = 42" in text
    assert "monkey_ignore_crashes = false" in text
    assert "monkey_pct_touch = 40" in text
    assert "monkey_pct_nav = 30" in text
    assert "mailbox = qa@example.com" in text
    assert "phone_log_path = /data/anr;/sdcard/logs" in text
    assert default_config.read_text(encoding="utf-8") == before


def test_mobileperf_config_normalizes_save_path_before_write(tmp_path):
    cfg = MobilePerfRunConfig(
        device_id="emulator-5554",
        package="com.example.app",
        save_path="E:/Download\\mobileperf\\emulator-5554",
    )

    generated = Path(cfg.write_config(tmp_path))
    text = generated.read_text(encoding="utf-8")
    expected_save_path = os.path.normpath(r"E:\Download\mobileperf\emulator-5554")

    assert f"save_path = {expected_save_path}" in text


def test_mobileperf_excel_truncates_long_csv_sheet_names_for_report(tmp_path):
    from mobileperf.android.excel import Excel

    csv_file = tmp_path / "pss_com.google.android.apps.nexuslauncher.csv"
    csv_file.write_text(
        "datatime,package,pss,java_heap,native_heap,system\n"
        "2026-06-13 20:51:00,com.google.android.apps.nexuslauncher,1,2,3,4\n"
        "2026-06-13 20:51:01,com.google.android.apps.nexuslauncher,2,3,4,5\n",
        encoding="utf-8",
    )
    excel = Excel(str(tmp_path / "summary.xlsx"))

    excel.csv_to_xlsx(
        str(csv_file),
        "pss_detail",
        "datatime",
        "mem(MB)",
        ["pss", "java_heap", "native_heap", "system"],
    )
    excel.save()

    assert (tmp_path / "summary.xlsx").exists()
    assert "pss_com.google.android.apps.nex" in excel._worksheet_names
    assert all(len(name) <= 31 for name in excel._worksheet_names)


def test_mobileperf_excel_generates_unique_valid_sheet_names(tmp_path):
    from mobileperf.android.excel import Excel

    excel = Excel(str(tmp_path / "summary.xlsx"))
    sheet_name = "bad:name?with/slash\\andaverylongworksheetname"

    excel.add_sheet(sheet_name, "time", "value", ["time", "value"], [["1", "2"], ["2", "3"]])
    excel.add_sheet(sheet_name, "time", "value", ["time", "value"], [["1", "2"], ["2", "3"]])
    excel.save()

    names = sorted(excel._worksheet_names)
    assert len(names) == 2
    assert names[0] != names[1]
    assert all(len(name) <= 31 for name in names)
    assert all(not any(char in name for char in "[]:*?/\\") for name in names)


def test_mobileperf_runner_starts_python_module_with_generated_config(tmp_path):
    runner_process = Mock(spec=ProcessRunner)
    proc = Mock()
    proc.stdout = []
    proc.poll.return_value = None
    runner_process.start.return_value = proc
    runner = MobilePerfRunner(
        process_runner=runner_process,
        project_root=tmp_path,
        python_executable="python-test",
    )
    cfg = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "out"))

    with patch.object(MobilePerfRunner, "_resolve_adb_path", return_value="adb-test"):
        runner.start(cfg)

    args = runner_process.start.call_args.args
    kwargs = runner_process.start.call_args.kwargs
    assert args[1][:3] == ["python-test", "-m", "mobileperf.android.startup"]
    assert "--config" in args[1]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["ADB_PATH"] == "adb-test"
    assert "MOBILEPERF_STOP_FILE" in kwargs["env"]
    assert Path(args[1][-1]).name == "mobileperf_run.conf"
    runner.stop()


def test_mobileperf_runner_uses_worker_entry_when_frozen(tmp_path, monkeypatch):
    runner_process = Mock(spec=ProcessRunner)
    proc = Mock()
    proc.stdout = []
    proc.poll.return_value = None
    runner_process.start.return_value = proc
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    runner = MobilePerfRunner(
        process_runner=runner_process,
        project_root=tmp_path,
        python_executable="ADBLab.exe",
    )
    cfg = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "out"))

    with patch.object(MobilePerfRunner, "_resolve_adb_path", return_value="adb-test"):
        runner.start(cfg)

    args = runner_process.start.call_args.args
    kwargs = runner_process.start.call_args.kwargs
    assert args[1][:2] == ["ADBLab.exe", "--mobileperf-worker"]
    assert "-m" not in args[1]
    assert "--config" in args[1]
    assert kwargs["env"]["MOBILEPERF_LOG_DIR"].endswith(os.path.join("ADBLab", "logs"))
    runner.stop()


def test_mobileperf_runner_stop_requests_mobileperf_report_shutdown(tmp_path):
    runner_process = Mock(spec=ProcessRunner)
    proc = Mock()
    proc.stdout = []
    proc.poll.return_value = None
    proc.wait.return_value = None
    proc.returncode = 0
    runner_process.start.return_value = proc
    runner = MobilePerfRunner(
        process_runner=runner_process,
        project_root=tmp_path,
        python_executable="python-test",
    )
    cfg = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "out"))

    runner.start(cfg)
    with patch.object(
        runner,
        "_request_stop_context",
        wraps=runner._request_stop_context,
    ) as request_stop:
        code = runner.stop(timeout=7)

    assert code == 0
    request_stop.assert_called_once()
    assert request_stop.call_args.args[0] is not None
    proc.wait.assert_called_once_with(timeout=7)
    runner_process.stop.assert_called_once()
    assert runner_process.stop.call_args.kwargs["timeout"] == 0


def test_mobileperf_runner_request_stop_writes_stop_file(tmp_path):
    runner = MobilePerfRunner(project_root=tmp_path)
    runner._stop_path = str(tmp_path / "mobileperf.stop")

    runner.request_stop()

    assert Path(runner._stop_path).read_text(encoding="utf-8") == "stop"


def test_mobileperf_runner_stop_force_stops_after_report_timeout(tmp_path):
    runner_process = Mock(spec=ProcessRunner)
    proc = Mock()
    proc.stdout = []
    proc.poll.return_value = None
    proc.wait.side_effect = subprocess.TimeoutExpired(cmd="mobileperf", timeout=7)
    runner_process.start.return_value = proc
    runner_process.stop.return_value = -9
    runner = MobilePerfRunner(
        process_runner=runner_process,
        project_root=tmp_path,
        python_executable="python-test",
    )
    cfg = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "out"))

    runner.start(cfg)
    code = runner.stop(timeout=7)

    assert code == -9
    runner_process.stop.assert_called_once()


def test_mobileperf_runner_finds_latest_result_and_report(tmp_path):
    root = tmp_path / "mobileperf" / "com.example.app"
    old_dir = root / "2026_06_13_10_00_00"
    new_dir = root / "2026_06_13_10_05_00"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    old_report = old_dir / "summary_old.xlsx"
    new_report = new_dir / "summary_new.xlsx"
    old_report.write_text("old", encoding="utf-8")
    new_report.write_text("new", encoding="utf-8")
    os.utime(old_dir, (1, 1))
    os.utime(new_dir, (2, 2))
    os.utime(old_report, (1, 1))
    os.utime(new_report, (2, 2))
    runner = MobilePerfRunner(project_root=tmp_path)
    cfg = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "mobileperf"))
    runner._last_config = cfg

    assert runner.latest_result_dir() == str(new_dir)
    assert runner.latest_report_file() == str(new_report)


def test_mobileperf_startup_detects_adblab_stop_file(tmp_path):
    from mobileperf.android.startup import StartUp

    startup = StartUp.__new__(StartUp)
    startup.stop_file = str(tmp_path / "mobileperf.stop")

    assert startup.check_stop_file_quit() is False
    Path(startup.stop_file).write_text("stop", encoding="utf-8")
    assert startup.check_stop_file_quit() is True


def test_mobileperf_monkey_derives_event_count_from_collection_timeout():
    from mobileperf.android.monkey import Monkey

    monkey = Monkey.__new__(Monkey)
    monkey.throttle_ms = 500

    assert Monkey._event_count_for_timeout(monkey, 600) == 1201
    assert Monkey._event_count_for_timeout(monkey, 1) == 3


def test_mobileperf_monkey_keeps_legacy_large_timeout_as_event_count():
    from mobileperf.android.monkey import Monkey

    with patch("mobileperf.android.monkey.AndroidDevice") as android_device:
        monkey = Monkey("device-1", "com.example.app")

    android_device.assert_called_once_with("device-1")
    assert monkey.timeout is None
    assert monkey.event_count == Monkey.DEFAULT_EVENT_COUNT


def test_mobileperf_monkey_builds_command_from_configurable_options():
    from mobileperf.android.monkey import Monkey

    with patch("mobileperf.android.monkey.AndroidDevice"):
        monkey = Monkey(
            "device-1",
            "com.example.app",
            timeout=10,
            throttle_ms=1000,
            seed=42,
            ignore_crashes=False,
            ignore_timeouts=True,
            ignore_security=False,
            kill_after_error=False,
            pct_touch=40,
            pct_motion=20,
            pct_nav=30,
            pct_anyevent=10,
            pct_trackball=0,
            pct_majornav=0,
            pct_syskeys=0,
            pct_appswitch=0,
            pct_flip=0,
            pct_pinchzoom=0,
        )

    cmd = monkey._build_monkey_cmd("com.example.app", 11)

    assert "-s 42" in cmd
    assert "--throttle 1000 11" in cmd
    assert "--pct-touch 40" in cmd
    assert "--pct-motion 20" in cmd
    assert "--pct-nav 30" in cmd
    assert "--pct-anyevent 10" in cmd
    assert "--ignore-timeouts" in cmd
    assert "--ignore-crashes" not in cmd
    assert "--ignore-security-exceptions" not in cmd
    assert "--kill-process-after-error" not in cmd
    assert monkey._event_percentage_total() == 100


def test_mobileperf_startup_passes_collection_timeout_to_monkey():
    from mobileperf.android.startup import StartUp
    from mobileperf.android import startup as startup_module

    startup = StartUp.__new__(StartUp)
    startup.serialnum = "device-1"
    startup.packages = ["com.example.app"]
    startup.frequency = 5
    startup.timeout = 600
    startup.config_dic = {
        "monkey": "true",
        "main_activity": "",
        "activity_list": "",
        "save_path": "",
        "monkey_throttle": 1000,
        "monkey_seed": 42,
        "monkey_ignore_crashes": "false",
        "monkey_ignore_timeouts": "true",
        "monkey_ignore_security": "false",
        "monkey_kill_after_error": "true",
        "monkey_pct_touch": 40,
        "monkey_pct_motion": 20,
        "monkey_pct_trackball": 0,
        "monkey_pct_nav": 30,
        "monkey_pct_majornav": 0,
        "monkey_pct_syskeys": 0,
        "monkey_pct_appswitch": 0,
        "monkey_pct_anyevent": 10,
        "monkey_pct_flip": 0,
        "monkey_pct_pinchzoom": 0,
    }
    startup.exceptionlog_list = []
    startup.monitors = []
    startup.device = Mock()
    startup.device.adb.is_connected.return_value = True
    startup.device.adb.is_app_installed.return_value = False

    with patch.object(startup_module, "CpuMonitor"), \
         patch.object(startup_module, "MemMonitor"), \
         patch.object(startup_module, "TrafficMonitor"), \
         patch.object(startup_module, "FPSMonitor"), \
         patch.object(startup_module, "FdMonitor"), \
         patch.object(startup_module, "ThreadNumMonitor"), \
         patch.object(startup_module, "Monkey") as monkey_cls:
        startup.add_monitor = Mock()
        startup.clear_heapdump = Mock()
        startup.run()

    monkey_cls.assert_not_called()

    startup.device.adb.is_app_installed.return_value = True
    with patch.object(startup_module, "CpuMonitor"), \
         patch.object(startup_module, "MemMonitor"), \
         patch.object(startup_module, "TrafficMonitor"), \
         patch.object(startup_module, "FPSMonitor"), \
         patch.object(startup_module, "FdMonitor"), \
         patch.object(startup_module, "ThreadNumMonitor"), \
         patch.object(startup_module, "Monkey") as monkey_cls, \
         patch.object(startup_module, "LogcatMonitor"), \
         patch.object(startup_module.FileUtils, "makedir"), \
         patch.object(startup_module.TimeUtils, "getCurrentTimeUnderline", return_value="2026_06_13_10_00_00"):
        startup.monitors = []
        startup.add_monitor = Mock(side_effect=lambda monitor: startup.monitors.append(monitor))
        startup.save_device_info = Mock()
        startup.stop = Mock(side_effect=SystemExit)
        monkey_cls.return_value = Mock()

        try:
            startup.run(time_out=0)
        except SystemExit:
            pass

    monkey_cls.assert_called_once_with(
        "device-1",
        "com.example.app",
        timeout=600,
        throttle_ms=1000,
        seed=42,
        ignore_crashes=False,
        ignore_timeouts=True,
        ignore_security=False,
        kill_after_error=True,
        pct_touch=40,
        pct_motion=20,
        pct_trackball=0,
        pct_nav=30,
        pct_majornav=0,
        pct_syskeys=0,
        pct_appswitch=0,
        pct_anyevent=10,
        pct_flip=0,
        pct_pinchzoom=0,
    )


def test_mobileperf_startup_uses_default_monkey_options_for_legacy_config():
    from mobileperf.android.startup import StartUp

    startup = StartUp.__new__(StartUp)
    startup.config_dic = {}

    defaults = startup._optional_config_defaults()
    options = startup._monkey_options()

    assert defaults["monkey_throttle"] == 500
    assert options["throttle_ms"] == 500
    assert options["seed"] == 1000000
    assert options["ignore_crashes"] is True
    assert options["pct_touch"] == 15
    assert options["pct_nav"] == 40


def test_mobileperf_runner_batches_subprocess_log_lines_and_notifies_finish():
    runner = MobilePerfRunner(process_runner=Mock(spec=ProcessRunner))
    runner.LOG_BATCH_SIZE = 3
    runner.LOG_BATCH_INTERVAL_SECONDS = 60
    proc = Mock()
    proc.stdout = iter(["one\n", "two\n", "three\n", "four\n"])
    proc.poll.return_value = 0
    runner._proc = proc
    received = []
    runner._on_log = received.append
    runner._on_finished = Mock()

    runner._read_logs()

    assert received == ["one\ntwo\nthree", "four"]
    runner._on_finished.assert_called_once()


def test_performance_monitor_page_code_is_not_bundled():
    spec = Path("ADBLab.spec").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/Build-exe.yaml").read_text(encoding="utf-8")

    assert "gui/performance_web/assets" not in spec
    assert "gui/performance_web/assets" not in workflow
    assert "PySide6.QtWebEngine" not in spec
    assert "PySide6.QtWebChannel" not in spec
    assert "COLLECT(" in spec
    assert "package_mode: --onedir" in workflow
    assert "Compress-Archive" in workflow


def test_cross_platform_builds_do_not_run_full_gui_test_suite():
    workflow = Path(".github/workflows/Build-exe.yaml").read_text(encoding="utf-8")

    assert "name: Install test dependencies\n        if: runner.os == 'Windows'" in workflow
    assert "name: Run tests\n        if: runner.os == 'Windows'" in workflow
    assert "name: Source self-check\n        if: runner.os != 'Windows'" in workflow


def test_release_job_keeps_existing_versions_immutable():
    workflow = Path(".github/workflows/Build-exe.yaml").read_text(encoding="utf-8")

    assert "gh release delete" not in workflow
    assert "gh release view \"$TAG\"" in workflow
    assert "git ls-remote --exit-code --tags origin" in workflow
    assert "exit 1" in workflow
    assert "gh release create \"$TAG\"" in workflow
    assert "softprops/action-gh-release" not in workflow


def test_cross_platform_release_assets_are_single_archives():
    workflow = Path(".github/workflows/Build-exe.yaml").read_text(encoding="utf-8")

    assert "name: Zip macOS app artifact" in workflow
    assert "ditto -c -k --sequesterRsrc --keepParent" in workflow
    assert "rm -f \"dist/$name\"" in workflow
    assert "name: Archive Linux artifact" in workflow
    assert "tar -C dist -czf" in workflow


def test_main_frame_device_dialogs_reuses_existing_per_device_window():
    frame = SimpleNamespace()
    frame.left_panel = Mock()
    frame.left_panel.selected_devices = ["device-1"]
    frame.log_panel = Mock()
    existing = Mock()
    frame._find_active_dialog = Mock(return_value=existing)
    frame._register_dialog = Mock()

    MainFrame._show_device_dialogs(frame, AppManagerDialog)

    existing.show.assert_called_once()
    existing.raise_.assert_called_once()
    existing.activateWindow.assert_called_once()
    frame._register_dialog.assert_not_called()


def test_main_frame_device_dialogs_create_independent_window():
    frame = SimpleNamespace()
    frame.left_panel = Mock()
    frame.left_panel.selected_devices = ["device-1"]
    frame.log_service = Mock()
    frame._find_active_dialog = Mock(return_value=None)
    created = []

    class DeviceDialog:
        def __init__(self, parent=None, device_ip=""):
            self.parent = parent
            self.device_ip = device_ip

        def show(self):
            return None

        def close(self):
            return None

    def register(dialog, *_args):
        created.append(dialog)
        return dialog

    frame._register_dialog = register

    MainFrame._show_device_dialogs(frame, DeviceDialog)

    assert len(created) == 1
    assert created[0].parent is None
    assert created[0].device_ip == "device-1"
    created[0].close()


def test_performance_dialog_creation_uses_no_qt_parent():
    frame = QMainWindow()
    frame.left_panel = Mock()
    frame.left_panel.selected_devices = ["device-1"]
    frame.left_panel.current_package_text.return_value = "com.example"
    frame.log_service = Mock()
    frame._find_active_dialog = Mock(return_value=None)
    created = Mock()
    frame._register_dialog = Mock(return_value=created)

    with patch("gui.dialogs.performance_launcher.PerformanceLauncherDialog") as dialog_cls:
        MainFrame._show_performance_monitor(frame)

    dialog_cls.assert_called_once_with(
        device_ip="device-1",
        package_name="com.example",
    )
    created.show.assert_called_once_with()


def test_main_frame_registers_independent_non_modal_secondary_window():
    frame = QMainWindow()
    frame._active_dialogs = []
    frame.log_service = Mock()
    frame._on_dialog_destroyed = Mock()
    dialog = QDialog(frame, Qt.Window | Qt.WindowStaysOnTopHint)

    registered = MainFrame._register_dialog(frame, dialog, QDialog, "device-1")

    assert registered is dialog
    assert dialog.parentWidget() is None
    assert dialog.windowModality() == Qt.NonModal
    assert not dialog.windowFlags() & Qt.WindowStaysOnTopHint
    assert dialog.windowFlags() & Qt.WindowCloseButtonHint
    assert not dialog.testAttribute(Qt.WA_QuitOnClose)
    dialog.setAttribute(Qt.WA_DeleteOnClose, False)
    dialog.close()
    frame.close()


def test_main_frame_signal_maps_keep_expected_coverage():
    frame = SimpleNamespace()
    lp = Mock()
    ac = Mock()

    signal_map = (
        MainFrame._device_signal_map(frame, lp, ac)
        + MainFrame._app_signal_map(frame, lp, ac)
        + MainFrame._testing_signal_map(frame, lp, ac)
        + MainFrame._system_signal_map(frame, lp, ac)
    )

    assert len(signal_map) == 61
    assert (lp.connect_requested, ac.connect_device) in signal_map
    assert (lp.open_deep_link_requested, ac.open_deep_link) in signal_map
    assert (lp.dumpsys_battery_requested, ac.dumpsys_battery) in signal_map
    assert (lp.emu_geo_requested, ac.emu_geo) in signal_map


def test_main_frame_scan_refresh_debounce_collapses_bursts():
    frame = SimpleNamespace()
    frame.adb_controller = Mock()
    frame._scan_refresh_timer = Mock()
    frame._pending_scanned_devices = []
    frame.DEVICE_SCAN_DEBOUNCE_MS = 20

    MainFrame._schedule_scan_refresh(frame, ["device-1"])
    MainFrame._schedule_scan_refresh(frame, ["device-1", "device-2"])
    MainFrame._schedule_scan_refresh(frame, ["device-3"])
    MainFrame._publish_scanned_devices(frame)

    assert frame._scan_refresh_timer.start.call_args_list == [call(20), call(20), call(20)]
    frame.adb_controller.refresh_devices.assert_not_called()
    frame.adb_controller.publish_detected_devices.assert_called_once_with(["device-3"])
    frame.adb_controller._process_device_list.assert_not_called()


def test_main_frame_splitter_size_save_is_debounced():
    frame = SimpleNamespace()
    frame._panel_splitter = Mock()
    frame._panel_splitter.sizes.side_effect = [[300, 700], [320, 680]]
    frame._pending_panel_sizes = None
    frame._panel_size_save_timer = Mock()
    frame.SPLITTER_SAVE_DEBOUNCE_MS = 20

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = Mock()
        settings_cls.instance.return_value = settings

        MainFrame._on_splitter_moved(frame, 0, 0)
        MainFrame._on_splitter_moved(frame, 0, 0)
        MainFrame._save_pending_panel_sizes(frame)

    assert frame._panel_size_save_timer.start.call_args_list == [call(20), call(20)]
    assert settings.set.call_args_list == [
        call("left_panel_width", 320),
        call("right_panel_width", 680),
    ]


def test_emit_operation_flushes_user_visible_result_immediately():
    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.log_service = Mock()
    controller.signals = Mock()

    _ADBControllerBase._emit_operation(controller, "input_keyevent", True, "Key sent")

    controller.log_service.log.assert_called_once_with(
        "INFO", "Key sent", flush_immediately=True
    )
    controller.signals.operation_completed.emit.assert_called_once_with(
        "input_keyevent", True, "Key sent"
    )


def test_perf_payload_wrapper_preserves_list_results():
    perf = build_async_perf("get_connected_devices_async", 10.0, 10.1, 10.2)
    wrapped = attach_perf(["device-1"], perf)

    result, extracted = split_perf(wrapped)

    assert result == ["device-1"]
    assert extracted["method"] == "get_connected_devices_async"


def test_handle_async_response_logs_slow_perf_trace_only_above_threshold():
    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.log_service = Mock()
    controller._settings = Mock()
    controller._settings.get.return_value = 100
    controller._handler_map = {"input_keyevent": Mock()}
    slow_result = attach_perf(
        {"success": True, "device_ip": "device-1"},
        {
            "queued_at": 1.0,
            "started_at": 1.01,
            "finished_at": 1.4,
            "queue_ms": 10.0,
            "model_ms": 390.0,
        },
    )

    with patch("controllers._base.perf_counter", side_effect=[1.42, 1.43]):
        _ADBControllerBase._handle_async_response(
            controller,
            "input_keyevent_async",
            slow_result,
        )

    controller._handler_map["input_keyevent"].assert_called_once_with(
        {"success": True, "device_ip": "device-1"}
    )
    controller.log_service.log.assert_called_once()
    assert controller.log_service.log.call_args.args[0] == "DEBUG"
    assert controller.log_service.log.call_args.args[1].startswith("[PERF] input_keyevent")
    assert "model=390.0ms" in controller.log_service.log.call_args.args[1]


def test_handle_async_response_skips_perf_trace_for_fast_path():
    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.log_service = Mock()
    controller._settings = Mock()
    controller._settings.get.return_value = 300
    controller._handler_map = {"input_keyevent": Mock()}
    fast_result = attach_perf(
        {"success": True, "device_ip": "device-1"},
        {
            "queued_at": 1.0,
            "started_at": 1.01,
            "finished_at": 1.05,
            "queue_ms": 10.0,
            "model_ms": 40.0,
        },
    )

    with patch("controllers._base.perf_counter", side_effect=[1.06, 1.07]):
        _ADBControllerBase._handle_async_response(
            controller,
            "input_keyevent_async",
            fast_result,
        )

    controller.log_service.log.assert_not_called()


def test_async_update_devices_batches_store_write_and_refreshes_ui():
    class ImmediateExecutor:
        def submit(self, func):
            func()

    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller.executor = ImmediateExecutor()
    controller.signals = Mock()

    with patch("controllers._device.ADBDevice.get_devices_basic_info") as get_info, \
         patch("controllers._device.DeviceStore.upsert_devices") as upsert:
        get_info.side_effect = [
            {"Brand": "Google", "Model": "Pixel", "Aversion": "15"},
            {"Brand": "Redmi", "Model": "22127", "Aversion": "9"},
        ]

        ADBDeviceMixin._async_update_devices(controller, ["device-1", "device-2"])

    upsert.assert_called_once()
    records = upsert.call_args.args[0]
    assert [record["ip"] for record in records] == ["device-1", "device-2"]
    controller.signals.devices_updated.emit.assert_called_once_with(["device-1", "device-2"])


def test_screenshot_viewer_opens_folder_via_process_runner():
    path = os.path.abspath(__file__)
    viewer = SimpleNamespace()
    viewer._current_path = lambda: path
    runner = Mock()

    with patch("gui.dialogs.screenshot_viewer.ProcessRunner", return_value=runner), \
         patch("gui.dialogs.screenshot_viewer.os.path.exists", return_value=True), \
         patch("gui.dialogs.screenshot_viewer.os.name", "nt"):
        ScreenshotViewer._open_file_location(viewer)

    runner.spawn.assert_called_once()
    assert runner.spawn.call_args.args[0][0] == "explorer"


def test_screenshot_viewer_uses_bottom_toolbar_with_tooltips(tmp_path):
    _app = QApplication.instance() or QApplication([])
    image_path = tmp_path / "shot.png"
    pixmap = QPixmap(120, 80)
    pixmap.fill(Qt.GlobalColor.red)
    assert pixmap.save(str(image_path))

    viewer = ScreenshotViewer([str(image_path)])
    try:
        assert "120 x 80" in viewer._info_label.text()
        assert "shot.png" not in viewer._info_label.text()
        assert viewer._path_label.text().endswith("shot.png")
        assert viewer._path_label.toolTip() == str(image_path)
        assert viewer._copy_btn.text() == ""
        assert viewer._bottom_bar.objectName() == "bottomBar"
        assert viewer._bottom_dock.objectName() == "bottomDock"
        assert viewer._thumb_list.isHidden()
        assert not hasattr(viewer, "_close_btn")
        assert not hasattr(viewer, "_copy_path_btn")
        assert not hasattr(viewer, "_save_btn")
        assert not hasattr(viewer, "copy_path_to_clipboard")
        assert not hasattr(viewer, "save_as")
        expected_tips = {
            viewer._prev_btn: "Previous screenshot (Left)",
            viewer._next_btn: "Next screenshot (Right)",
            viewer._zoom_out_btn: "Zoom out (Ctrl+-)",
            viewer._zoom_in_btn: "Zoom in (Ctrl+=)",
            viewer._fit_btn: "Fit to window (Ctrl+0)",
            viewer._actual_btn: "Actual size (Ctrl+1)",
            viewer._copy_btn: "Copy image to clipboard (Ctrl+C)",
            viewer._folder_btn: "Open file location",
            viewer._delete_btn: "Delete screenshot",
        }
        assert all(button.toolTip() == tooltip for button, tooltip in expected_tips.items())
    finally:
        viewer.close()


def test_screenshot_viewer_thumbnail_and_navigation_update_current_image(tmp_path):
    _app = QApplication.instance() or QApplication([])
    paths = []
    for name, color in (
        ("first.png", Qt.GlobalColor.red),
        ("second.png", Qt.GlobalColor.green),
        ("third.png", Qt.GlobalColor.blue),
    ):
        path = tmp_path / name
        pixmap = QPixmap(80, 60)
        pixmap.fill(color)
        assert pixmap.save(str(path))
        paths.append(str(path))

    viewer = ScreenshotViewer(paths)
    try:
        assert not viewer._thumb_list.isHidden()
        assert viewer._thumb_list.count() == 3
        assert viewer._nav_label.text() == "1 / 3"

        viewer.navigate_next()
        assert viewer._current_idx == 1
        assert viewer._path_label.text() == "second.png"
        assert viewer._nav_label.text() == "2 / 3"
        assert viewer._thumb_list.currentRow() == 1

        viewer._on_thumbnail_clicked(viewer._thumb_list.item(2))
        assert viewer._current_idx == 2
        assert viewer._path_label.text() == "third.png"
        assert viewer._nav_label.text() == "3 / 3"

        viewer.navigate_prev()
        assert viewer._current_idx == 1
        assert viewer._path_label.text() == "second.png"
    finally:
        viewer.close()


def test_screenshot_viewer_refreshes_themed_icons(tmp_path):
    _app = QApplication.instance() or QApplication([])
    image_path = tmp_path / "shot.png"
    pixmap = QPixmap(120, 80)
    pixmap.fill(Qt.GlobalColor.green)
    assert pixmap.save(str(image_path))

    viewer = ScreenshotViewer([str(image_path)])
    try:
        with patch("gui.dialogs.screenshot_viewer.get_themed_icon", return_value=QIcon()) as themed_icon:
            viewer._refresh_button_icons()

        icon_names = [call.args[0] for call in themed_icon.call_args_list]
        assert "camera.svg" in icon_names
        assert {button.property("iconName") for button in viewer._icon_buttons}.issubset(icon_names)
    finally:
        viewer.close()


def test_screenshot_viewer_actual_size_updates_zoom_label(tmp_path):
    _app = QApplication.instance() or QApplication([])
    image_path = tmp_path / "shot.png"
    pixmap = QPixmap(120, 80)
    pixmap.fill(Qt.GlobalColor.blue)
    assert pixmap.save(str(image_path))

    viewer = ScreenshotViewer([str(image_path)])
    try:
        viewer._actual_size()

        assert viewer._fit_to_window is False
        assert viewer._zoom_label.text() == "100%"
    finally:
        viewer.close()


def test_screenshot_viewer_delete_without_confirmation_auto_closes_when_last_image_removed(tmp_path):
    _app = QApplication.instance() or QApplication([])
    image_path = tmp_path / "shot.png"
    pixmap = QPixmap(120, 80)
    pixmap.fill(Qt.GlobalColor.magenta)
    assert pixmap.save(str(image_path))

    viewer = ScreenshotViewer([str(image_path)])
    try:
        viewer._delete_file()

        assert not image_path.exists()
        assert viewer._image_paths == []
        assert not viewer.isVisible()
    finally:
        if viewer.isVisible():
            viewer.close()



def test_process_runner_stop_all_without_deadlock():
    ProcessRunner._global_procs.clear()
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


def test_process_runner_stop_all_tracked_is_global_fallback():
    ProcessRunner._global_procs.clear()
    runner_a = ProcessRunner()
    runner_b = ProcessRunner()
    proc_a = Mock()
    proc_b = Mock()
    for proc in (proc_a, proc_b):
        proc.poll.return_value = None
        proc.wait.return_value = 0
    runner_a._procs["logcat"] = proc_a
    runner_b._procs["scrcpy"] = proc_b
    runner_a._register_global("logcat", proc_a)
    runner_b._register_global("scrcpy", proc_b)

    ProcessRunner.stop_all_tracked()

    proc_a.terminate.assert_called_once()
    proc_b.terminate.assert_called_once()
    assert ProcessRunner._global_procs == {}



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
    with patch("models.adb_device.CommandRunner.run") as run, \
         patch("models.adb_device.ADBModelCore._fetch_device_info") as fetch:
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


def test_device_manager_shows_placeholder_for_new_unstored_device():
    _app = QApplication.instance() or QApplication([])
    panel = Mock(selected_devices=[])
    manager = SimpleNamespace(selected_devices=[])
    manager.panel = panel
    manager.listbox_devices = QListWidget()
    manager._device_items_by_ip = lambda: DeviceManager._device_items_by_ip(manager)

    with patch("gui.panels.device_manager.DeviceStore.get_full_devices_info", return_value=[]):
        DeviceManager.update_device_list(manager, ["emulator-5554"])

    assert manager.listbox_devices.count() == 1
    item = manager.listbox_devices.item(0)
    assert "Detecting" in item.text()
    assert item.data(Qt.UserRole)["ip"] == "emulator-5554"


def test_device_manager_updates_device_list_incrementally():
    _app = QApplication.instance() or QApplication([])
    panel = Mock(selected_devices=[])
    manager = SimpleNamespace(selected_devices=[])
    manager.panel = panel
    manager.listbox_devices = QListWidget()
    manager._device_items_by_ip = lambda: DeviceManager._device_items_by_ip(manager)

    first_infos = [
        {"Brand": "Google", "Model": "Pixel", "Aversion": "15", "ip": "device-1"},
        {"Brand": "Redmi", "Model": "K70", "Aversion": "14", "ip": "device-2"},
    ]
    second_infos = [
        {"Brand": "Google", "Model": "Pixel", "Aversion": "15", "ip": "device-1"},
    ]
    with patch(
        "gui.panels.device_manager.DeviceStore.get_full_devices_info",
        side_effect=[first_infos, second_infos],
    ):
        DeviceManager.update_device_list(manager, ["device-1", "device-2"])
        first_item = manager.listbox_devices.item(0)
        first_item.setCheckState(Qt.Checked)
        manager.selected_devices = ["device-1"]

        DeviceManager.update_device_list(manager, ["device-1", "device-3"])

    assert manager.listbox_devices.count() == 2
    assert manager.listbox_devices.item(0) is first_item
    assert first_item.checkState() == Qt.Checked
    assert manager.listbox_devices.item(1).data(Qt.UserRole)["ip"] == "device-3"
    assert "Detecting" in manager.listbox_devices.item(1).text()


def test_device_manager_none_device_list_clears_without_model_lookup():
    _app = QApplication.instance() or QApplication([])
    panel = Mock(selected_devices=[])
    manager = SimpleNamespace(selected_devices=["device-1"])
    manager.panel = panel
    manager.listbox_devices = QListWidget()
    manager._device_items_by_ip = lambda: DeviceManager._device_items_by_ip(manager)
    item = QListWidgetItem("device-1")
    item.setData(Qt.UserRole, {"ip": "device-1"})
    item.setCheckState(Qt.Checked)
    manager.listbox_devices.addItem(item)

    with patch("models.adb_device.ADBDevice.get_connected_devices_async") as get_devices:
        DeviceManager.update_device_list(manager, None)

    get_devices.assert_not_called()
    assert manager.listbox_devices.count() == 0
    assert panel._connected_device_cache == []


def _build_connect_device_manager():
    panel = Mock()
    panel.signals = SidePanelSignals()
    panel._font_sm = QFont()
    panel._font_mono = QFont()
    panel._font_base = QFont()
    panel._user_selected_ip = False
    panel._current_ip = ""
    panel._apply_completer_style = Mock()
    panel.selected_devices = []
    manager = DeviceManager(panel)
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        widget = manager.build_ui()
    manager.connect_signals()
    return manager, widget, panel


def test_adb_connect_target_validation_requires_complete_ip_and_port():
    assert normalize_adb_connect_target(" 10.0.0.195 : 5555 ") == (
        "10.0.0.195:5555",
        "",
    )
    assert normalize_adb_connect_target("[::1]:5555") == ("[::1]:5555", "")
    assert "IP and port" in normalize_adb_connect_target("10.0.0.195")[1]
    assert "valid IP" in normalize_adb_connect_target("10.0.0.999:5555")[1]
    assert "65535" in normalize_adb_connect_target("10.0.0.195:70000")[1]


def test_device_manager_return_pressed_requests_connect_with_normalized_target():
    _app = QApplication.instance() or QApplication([])
    manager, widget, panel = _build_connect_device_manager()
    emitted = []
    panel.signals.connect_requested.connect(emitted.append)

    try:
        manager.ip_entry.setCurrentText(" 10.0.0.195 : 5555 ")
        manager.ip_entry.lineEdit().returnPressed.emit()
    finally:
        widget.close()
        manager.close()

    assert emitted == ["10.0.0.195:5555"]


def test_device_manager_rejects_incomplete_connect_target_before_signal_emit():
    _app = QApplication.instance() or QApplication([])
    manager, widget, panel = _build_connect_device_manager()
    emitted = []
    logs = []
    panel.signals.connect_requested.connect(emitted.append)
    panel.signals.log_message.connect(lambda level, message: logs.append((level, message)))

    try:
        manager.ip_entry.setCurrentText("10.0.0.195")
        manager.btn_connect_devices.click()
    finally:
        widget.close()
        manager.close()

    assert emitted == []
    assert logs
    assert logs[-1][0] == "WARNING"
    assert "IP and port" in logs[-1][1]


def test_base_panel_button_factory_adds_tooltip_and_icon_name():
    panel = Mock()
    panel._font_sm = QFont()
    base = BasePanel(panel)

    button = base._b("Refresh", "arrows-clockwise.svg")

    assert button.toolTip() == "Refresh"
    assert button.property("iconName") == "arrows-clockwise.svg"
    assert button.cursor().shape() == Qt.PointingHandCursor


def test_base_panel_text_factories_apply_panel_fonts():
    _app = QApplication.instance() or QApplication([])
    panel = Mock()
    panel._font_sm = QFont("Arial", 13)
    panel._font_base = QFont("Arial", 15)
    base = BasePanel(panel)

    label = base._label("Events:")
    status = base._status_text("Total")
    checkbox = base._checkbox("Ignore crashes")

    assert label.font().pointSize() == 15
    assert status.objectName() == "statusLabel"
    assert checkbox.font().pointSize() == 15


def test_base_panel_row_helper_adds_weighted_widgets():
    _app = QApplication.instance() or QApplication([])
    panel = Mock()
    panel._font_sm = QFont()
    base = BasePanel(panel)
    left = QPushButton("Left")
    right = QPushButton("Right")

    row = base._row((left, 2), right, spacing=7)

    assert row.spacing() == 7
    assert row.count() == 2
    assert row.stretch(0) == 2
    assert row.stretch(1) == 0


def test_device_manager_skips_unchanged_device_combo_refresh():
    _app = QApplication.instance() or QApplication([])
    panel = Mock()
    manager = SimpleNamespace()
    manager.panel = panel
    manager._device_model = Mock()
    manager.ip_entry = Mock()

    with patch(
        "gui.panels.device_manager.DeviceStore.get_basic_devices_info",
        return_value=[("Google", "Pixel", "device-1")],
    ), patch("gui.panels.device_manager.QCompleter", return_value=Mock()):
        DeviceManager._refresh_device_combobox(manager)
        DeviceManager._refresh_device_combobox(manager)

    manager._device_model.removeRows.assert_called_once()


def test_side_panel_theme_refresh_updates_button_icons():
    _app = QApplication.instance() or QApplication([])
    panel = SimpleNamespace()
    panel._font_sm = QFont()
    panel._font_base = QFont()
    panel._font_mono = QFont()
    panel._font_tab = QFont()
    panel._create_fonts = Mock()
    panel.tabs = Mock()
    panel._apply_tab_style = Mock()
    panel._devices_tab = Mock()
    panel._devices_tab._apply_device_list_style = Mock()
    panel._devices_tab.ip_entry.completer.return_value = None
    panel._apps_tab = Mock()
    panel._apps_tab.completer = None
    button = QPushButton("Refresh")
    button.setProperty("iconName", "arrows-clockwise.svg")
    panel.findChildren = Mock(return_value=[button])
    panel.setStyleSheet = Mock()
    panel._apply_completer_style = Mock()
    panel.apply_device_theme = Mock()

    with patch("gui.panels.side_panel.get_themed_icon", return_value=QIcon()) as themed_icon:
        SidePanel._on_theme_changed(panel, "Dark")

    themed_icon.assert_called_once_with("arrows-clockwise.svg")


def test_side_panel_public_helpers_wrap_internal_tabs():
    device_widget = QWidget()
    panel = SimpleNamespace()
    panel._device_widget = device_widget
    panel._devices_tab = Mock()
    panel._devices_tab.ip_entry.completer.return_value = None
    panel._apps_tab = Mock(package_text="com.example.app")
    panel._apply_completer_style = Mock()

    assert SidePanel.device_widget.fget(panel) is device_widget
    assert SidePanel.current_package_text(panel) == "com.example.app"

    SidePanel.refresh_device_choices(panel)
    SidePanel.apply_device_theme(panel)

    panel._devices_tab._refresh_device_combobox.assert_called_once()
    panel._devices_tab._apply_device_list_style.assert_called_once()


def test_side_panel_initializes_only_default_function_tab():
    _app = QApplication.instance() or QApplication([])
    panel = SidePanel()
    try:
        assert panel._apps_tab is not None
        assert panel._advanced_tab is None
        assert panel._scrcpy_tab is None
        assert panel._loaded_lazy_tabs == {0}
        assert panel._connected_lazy_tabs == {0}
    finally:
        panel.close()


def test_side_panel_lazy_loads_and_connects_later_tabs():
    _app = QApplication.instance() or QApplication([])
    panel = SidePanel()
    try:
        panel._ensure_tab_loaded(2)

        assert panel._scrcpy_tab is not None
        assert 2 in panel._loaded_lazy_tabs
        assert 2 in panel._connected_lazy_tabs
    finally:
        panel.close()


def test_side_panel_shutdown_forwards_to_loaded_tabs():
    panel = SimpleNamespace()
    apps_tab = object()
    remote_tab = Mock()
    panel._loaded_lazy_tabs = {0, 2}
    panel._lazy_tab_specs = [
        ("_apps_tab", AppPanel, "Apps"),
        ("_advanced_tab", object, "System"),
        ("_scrcpy_tab", RemotePanel, "Remote"),
    ]
    panel._apps_tab = apps_tab
    panel._advanced_tab = None
    panel._scrcpy_tab = remote_tab

    SidePanel.shutdown(panel)

    remote_tab.shutdown.assert_called_once()


def test_remote_status_font_size_uses_base_styles_default():
    remote = SimpleNamespace()
    remote._status_label = Mock()
    old_size = BaseStyles.DEFAULT_FONT_SIZE
    BaseStyles.DEFAULT_FONT_SIZE = 16
    try:
        RemotePanel._update_status(remote, "Running", None)
    finally:
        BaseStyles.DEFAULT_FONT_SIZE = old_size

    style = remote._status_label.setStyleSheet.call_args.args[0]
    assert "font-size: 16px" in style


def test_remote_start_stop_buttons_follow_running_state():
    _app = QApplication.instance() or QApplication([])
    owner = QWidget()
    remote = SimpleNamespace(
        btn_start=QPushButton(owner),
        btn_stop=QPushButton(owner),
    )
    remote._refresh_button_style = lambda button: BasePanel._refresh_button_style(
        remote, button
    )
    remote._set_button_enabled = lambda button, enabled: BasePanel._set_button_enabled(
        remote, button, enabled
    )
    try:
        BasePanel._apply_button_variant(remote, remote.btn_start, "accent")
        BasePanel._apply_button_variant(remote, remote.btn_stop, "danger")
        RemotePanel._set_running(remote, False)

        assert remote.btn_start.objectName() == "accent"
        assert remote.btn_start.property("buttonVariant") == "accent"
        assert remote.btn_stop.objectName() == "danger"
        assert remote.btn_stop.property("buttonVariant") == "danger"
        assert remote.btn_start.palette().button().color().name() == BaseStyles.color("BUTTON_ACCENT").lower()

        RemotePanel._set_running(remote, True)

        assert remote.btn_start.isEnabled() is False
        assert remote.btn_stop.isEnabled() is True
        assert remote.btn_start.palette().button().color().name() == BaseStyles.color("INPUT_BG").lower()
        assert remote.btn_stop.palette().button().color().name() == BaseStyles.color("BUTTON_DANGER").lower()

        RemotePanel._set_running(remote, False)

        assert remote.btn_start.isEnabled() is True
        assert remote.btn_stop.isEnabled() is False
        assert remote.btn_start.palette().button().color().name() == BaseStyles.color("BUTTON_ACCENT").lower()
        assert remote.btn_stop.palette().button().color().name() == BaseStyles.color("INPUT_BG").lower()
    finally:
        owner.close()


def test_side_panel_theme_refresh_preserves_remote_button_variants():
    _app = QApplication.instance() or QApplication([])
    owner = QWidget()
    start_button = QPushButton(owner)
    stop_button = QPushButton(owner)
    panel = SimpleNamespace(
        _font_tab=QFont(),
        _font_base=QFont(),
        _font_sm=QFont(),
        tabs=Mock(),
        _apps_tab=None,
    )
    panel._create_fonts = Mock()
    panel.setStyleSheet = Mock()
    panel._apply_tab_style = Mock()
    panel.findChildren = Mock(return_value=[start_button, stop_button])
    panel.apply_device_theme = Mock()
    panel._refresh_button_style = lambda button: BasePanel._refresh_button_style(
        panel, button
    )
    BasePanel._apply_button_variant(panel, start_button, "accent")
    BasePanel._apply_button_variant(panel, stop_button, "danger")
    try:
        SidePanel._on_theme_changed(panel, BaseStyles.current_theme())

        assert start_button.objectName() == "accent"
        assert start_button.property("buttonVariant") == "accent"
        assert start_button.palette().button().color().name() == BaseStyles.color(
            "BUTTON_ACCENT"
        ).lower()
        assert stop_button.objectName() == "danger"
        assert stop_button.property("buttonVariant") == "danger"
    finally:
        owner.close()


def test_remote_control_buttons_are_grouped_without_duplicate_shortcuts():
    _app = QApplication.instance() or QApplication([])
    side_panel = SidePanel()
    try:
        remote = side_panel._ensure_tab_loaded(2)

        key_codes = [button.property("remoteKey") for button in remote._remote_key_buttons]
        actions = [button.property("remoteAction") for button in remote._remote_action_buttons]

        assert "RECENTS" in key_codes
        assert "APP_SWITCH" not in key_codes
        assert "NOTIFICATION" not in key_codes
        assert not any(str(code).startswith("DPAD_") for code in key_codes)
        assert len(key_codes) == len(set(key_codes))
        assert {"notif_expand", "notif_collapse", "rotate_portrait", "rotate_landscape"}.issubset(actions)
        assert {"swipe_up", "swipe_down", "swipe_left", "swipe_right"}.issubset(actions)
        assert len(remote._remote_control_buttons) == len(remote._remote_key_buttons) + len(remote._remote_action_buttons)
        assert all(button.property("iconName") for button in remote._remote_control_buttons)
    finally:
        side_panel.close()


def test_remote_control_clicks_warn_when_no_device_selected():
    remote = SimpleNamespace()
    remote.selected_devices = []
    remote._remote_control = Mock()
    remote._submit_remote_input = Mock()
    remote._log = Mock()
    remote._selected_remote_device = lambda: RemotePanel._selected_remote_device(remote)

    RemotePanel._send_keyevent(remote, "HOME")
    RemotePanel._send_remote_action(remote, "swipe_up")

    assert remote._log.call_args_list == [
        call("WARNING", "No device selected"),
        call("WARNING", "No device selected"),
    ]
    remote._submit_remote_input.assert_not_called()
    remote._remote_control.send_keyevent.assert_not_called()
    remote._remote_control.perform_action.assert_not_called()


def test_app_panel_monkey_buttons_follow_start_stop_state():
    _app = QApplication.instance() or QApplication([])
    side_panel = Mock()
    side_panel._font_sm = QFont("Arial", 12)
    side_panel._font_base = QFont("Arial", 12)
    side_panel._font_mono = QFont("Courier New", 10)
    side_panel._font_tab = QFont("Arial", 12)
    side_panel._package_history = []
    side_panel._apply_completer_style = Mock()
    side_panel.selected_devices = ["device-1"]
    side_panel.signals = Mock()
    panel = AppPanel(side_panel)

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = settings_cls.instance.return_value
        settings.get.return_value = {}
        widget = panel.build_ui()
        try:
            panel.program_edit.setCurrentText("com.example.app")

            assert panel.start_monkey_btn.isEnabled() is True
            assert panel.kill_monkey_btn.isEnabled() is False

            panel._on_start_monkey()

            assert panel.start_monkey_btn.isEnabled() is False
            assert panel.kill_monkey_btn.isEnabled() is True
            side_panel.signals.start_monkey_requested.emit.assert_called_once()

            panel.on_operation_completed("monkey", True, "done")

            assert panel.start_monkey_btn.isEnabled() is True
            assert panel.kill_monkey_btn.isEnabled() is False

            panel._set_monkey_running(True)
            panel.on_operation_completed("install", True, "done")

            assert panel.start_monkey_btn.isEnabled() is False
            assert panel.kill_monkey_btn.isEnabled() is True

            panel._on_kill_monkey()

            assert panel.start_monkey_btn.isEnabled() is True
            assert panel.kill_monkey_btn.isEnabled() is False
            side_panel.signals.kill_monkey_requested.emit.assert_called_once_with(["device-1"])
        finally:
            widget.deleteLater()


def test_app_panel_screenshot_button_disables_during_operation_then_recovers():
    _app = QApplication.instance() or QApplication([])
    side_panel = Mock()
    side_panel._font_sm = QFont("Arial", 12)
    side_panel._font_base = QFont("Arial", 12)
    side_panel._font_mono = QFont("Courier New", 10)
    side_panel._font_tab = QFont("Arial", 12)
    side_panel._package_history = []
    side_panel._apply_completer_style = Mock()
    side_panel.selected_devices = ["device-1"]
    side_panel.signals = Mock()
    panel = AppPanel(side_panel)

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = settings_cls.instance.return_value
        settings.get.return_value = {}
        widget = panel.build_ui()
        try:
            assert panel.btn_screenshot.isEnabled() is True

            panel._on_screenshot()

            assert panel.btn_screenshot.isEnabled() is False
            side_panel.signals.screenshot_requested.emit.assert_called_once_with(["device-1"])

            panel.on_operation_completed("screenshot", True, "Screenshot captured")
            assert panel.btn_screenshot.isEnabled() is False

            panel.on_operation_completed("screenshot", True, "Screenshot completed: 1/1 succeeded")
            assert panel.btn_screenshot.isEnabled() is True

            panel._on_screenshot()
            panel.on_operation_completed(
                "screenshot",
                False,
                "Unable to prepare screenshot directory",
            )
            assert panel.btn_screenshot.isEnabled() is True
        finally:
            widget.deleteLater()


def test_side_panel_loaded_buttons_have_tooltips_and_registered_icons():
    _app = QApplication.instance() or QApplication([])
    panel = SidePanel()
    try:
        panel._ensure_tab_loaded(1)
        panel._ensure_tab_loaded(2)

        buttons = panel.findChildren(QPushButton)

        assert buttons
        assert [button.text() for button in buttons if not button.toolTip().strip()] == []
        assert [
            button.text()
            for button in buttons
            if not button.icon().isNull() and not button.property("iconName")
        ] == []
    finally:
        panel.close()


def _app_manager_for_unit_tests():
    class UnitDialog:
        pass

    _app = QApplication.instance() or QApplication([])
    dialog = UnitDialog()
    dialog._apps_data = []
    dialog._app_labels = {}
    dialog._app_versions = {}
    dialog._detail_cache = {}
    dialog._pending_detail_packages = set()
    dialog._detail_worker_running = False
    dialog._detail_row_by_pkg = {}
    dialog._detail_icon_by_pkg = {}
    dialog._view_mode = False
    dialog._closing = False
    dialog.device_ip = "device-1"
    dialog.status_bar = Mock()
    dialog.log = Mock()
    dialog._track_worker = Mock()
    dialog._detail_timer = Mock()
    dialog._detail_timer.isActive.return_value = False
    dialog._detail_timer.start = Mock()
    dialog._detail_timer.stop = Mock()
    dialog._filter = Mock()
    dialog.model = Mock()
    dialog.model.rowCount.return_value = 0
    dialog.model.removeRows = Mock()
    dialog.tree = Mock()
    dialog.tree.rootIndex.return_value = Mock()
    dialog.tree.viewport.return_value.rect.return_value = Mock()
    dialog.proxy = Mock()
    dialog.proxy.rowCount.return_value = 0
    dialog.icon_list = Mock()
    dialog.icon_list.clear = Mock()
    dialog.icon_list.addItem = Mock()
    dialog._gen_icon = AppManagerDialog._gen_icon
    dialog._on_detail = lambda *args: AppManagerDialog._on_detail(dialog, *args)
    dialog._on_detail_worker_finished = lambda packages=None: (
        AppManagerDialog._on_detail_worker_finished(dialog, packages)
    )
    dialog._has_unloaded_details = lambda: AppManagerDialog._has_unloaded_details(dialog)
    dialog._next_unloaded_detail_packages = lambda limit=30: (
        AppManagerDialog._next_unloaded_detail_packages(dialog, limit)
    )
    dialog._schedule_visible_detail_load = lambda delay_ms=120: (
        AppManagerDialog._schedule_visible_detail_load(dialog, delay_ms)
    )
    return dialog


def test_app_manager_populate_schedules_visible_details_only():
    dialog = _app_manager_for_unit_tests()

    with patch("gui.dialogs.app_manager.AppManagerWorker") as worker:
        AppManagerDialog._populate(dialog, [("Demo", "com.example.demo", "Enabled", "User")])

    worker.assert_not_called()
    dialog._detail_timer.start.assert_called()
    assert dialog._detail_row_by_pkg == {"com.example.demo": 0}
    assert "com.example.demo" in dialog._detail_icon_by_pkg
    dialog.status_bar.showMessage.assert_called()


def test_app_manager_detail_update_uses_cached_indexes():
    dialog = _app_manager_for_unit_tests()
    icon_item = Mock()
    name_item = Mock()
    version_item = Mock()
    dialog._detail_icon_by_pkg = {"com.example.demo": icon_item}
    dialog._detail_row_by_pkg = {"com.example.demo": 2}
    dialog.model.item.side_effect = lambda row, col: {
        (2, 1): name_item,
        (2, 3): version_item,
    }.get((row, col))

    AppManagerDialog._on_detail(dialog, "com.example.demo", "Demo", "1.0 (1)", "2026-05-31")

    assert dialog._detail_cache["com.example.demo"] == ("Demo", "1.0 (1)", "2026-05-31")
    icon_item.setToolTip.assert_called_once_with("Demo\ncom.example.demo\n1.0 (1)")
    name_item.setText.assert_called_once_with("Demo")
    version_item.setText.assert_called_once_with("1.0 (1)")
    assert dialog.model.item.call_count == 2


def test_app_manager_load_visible_details_starts_small_worker_batch():
    dialog = _app_manager_for_unit_tests()
    dialog._visible_detail_packages = Mock(return_value=["com.example.one", "com.example.two"])

    with patch("gui.dialogs.app_manager.AppManagerWorker") as worker_cls:
        worker = worker_cls.return_value
        AppManagerDialog._load_visible_details(dialog)

    worker_cls.assert_called_once_with(
        "device-1",
        "load_detail_batch",
        packages=["com.example.one", "com.example.two"],
    )
    assert dialog._pending_detail_packages == {"com.example.one", "com.example.two"}
    assert dialog._detail_worker_running is True
    worker.app_detail_batch.connect.assert_called_once_with(dialog._on_detail)
    worker.start.assert_called_once()


def test_app_manager_worker_load_detail_batch_uses_single_batched_shell():
    from models.app_manager_worker import AppManagerWorker

    worker = AppManagerWorker("device-1", "load_detail_batch", packages=[])
    emitted = []
    worker.app_detail_batch.connect(lambda *args: emitted.append(args))
    output = (
        "__ADBLAB_PKG_BEGIN_0__\n"
        "nonLocalizedLabel=One App\n"
        "versionName=1.2\n"
        "versionCode=12\n"
        "firstInstallTime=2026-01-02\n"
        "__ADBLAB_PKG_END_0__\n"
        "__ADBLAB_PKG_BEGIN_1__\n"
        "versionName=2.0\n"
        "versionCode=20\n"
        "__ADBLAB_PKG_END_1__\n"
    )

    with patch.object(worker, "_adb", return_value=CommandResult(success=True, output=output)) as adb:
        worker._load_detail_batch(["com.example.one", "com.example.two"])

    adb.assert_called_once()
    assert adb.call_args.args[0] == "shell"
    assert "dumpsys package com.example.one" in adb.call_args.args[1]
    assert emitted == [
        ("com.example.one", "One App", "1.2 (12)", "2026-01-02"),
        ("com.example.two", "two", "2.0 (20)", ""),
    ]


def test_app_manager_detail_worker_continues_after_first_visible_page():
    dialog = _app_manager_for_unit_tests()
    dialog._apps_data = [
        ("One", "com.example.one", "Enabled", "User"),
        ("Two", "com.example.two", "Enabled", "User"),
    ]
    dialog._detail_cache = {"com.example.one": ("One", "1.0", "")}
    dialog._pending_detail_packages = {"com.example.two"}

    AppManagerDialog._on_detail_worker_finished(dialog, ["com.example.two"])

    dialog._detail_timer.start.assert_called()
    dialog.status_bar.showMessage.assert_not_called()


def test_app_manager_load_visible_details_falls_back_to_next_unloaded_batch():
    dialog = _app_manager_for_unit_tests()
    dialog._apps_data = [
        ("One", "com.example.one", "Enabled", "User"),
        ("Two", "com.example.two", "Enabled", "User"),
    ]
    dialog._detail_cache = {"com.example.one": ("One", "1.0", "")}
    dialog._visible_detail_packages = Mock(return_value=[])

    with patch("gui.dialogs.app_manager.AppManagerWorker") as worker_cls:
        AppManagerDialog._load_visible_details(dialog)

    worker_cls.assert_called_once_with(
        "device-1",
        "load_detail_batch",
        packages=["com.example.two"],
    )
    assert dialog._pending_detail_packages == {"com.example.two"}


def test_app_details_dialog_close_disconnects_theme_handler():
    _app = QApplication.instance() or QApplication([])
    with patch.object(AppDetailsDialog, "_load_data"):
        dialog = AppDetailsDialog(None, "device-1", "com.example.demo")

    with patch("gui.dialogs.app_manager.safe_disconnect") as disconnect, \
         patch("gui.dialogs.app_manager.wait_for_threads_later") as wait_threads:
        dialog.close()

    assert dialog._closing is True
    disconnect.assert_called_once_with(BaseStyles.theme_changed, dialog._apply_theme)
    wait_threads.assert_called_once_with([], 5000)
    dialog.deleteLater()



def test_extract_package_name_ignores_log_prefix_and_returns_real_package():
    output = "ACTIVITY Sys2038: com.example.app/.MainActivity pid=123"

    assert extract_package_name(output) == "com.example.app"



def test_extract_package_name_prefers_focus_line_over_other_packages():
    output = "ACTIVITY com.android.launcher3/.Launcher\n" \
             "mCurrentFocus=Window{u0 com.example.app/.MainActivity}"

    assert extract_package_name(output) == "com.example.app"


def test_extract_package_name_prefers_visible_top_activity():
    output = (
        "taskId=3: com.android.settings/com.android.settings.Settings "
        "visible=false topActivity=ComponentInfo{com.android.settings/com.android.settings.Settings}\n"
        "taskId=2: com.android.launcher3/com.android.launcher3.Launcher "
        "visible=true topActivity=ComponentInfo{com.android.launcher3/com.android.launcher3.Launcher}"
    )

    assert extract_package_name(output) == "com.android.launcher3"



def test_detect_current_package_uses_lightweight_activity_stack_first():
    runner = Mock()
    runner.run.return_value = CommandResult(
        success=True,
        output=(
            "taskId=9: com.example.app/com.example.app.MainActivity "
            "visible=true topActivity=ComponentInfo{com.example.app/com.example.app.MainActivity}"
        ),
    )

    result = detect_current_package("device-1", runner=runner)

    assert result == {
        "success": True,
        "device_ip": "device-1",
        "package_name": "com.example.app",
    }
    runner.run.assert_called_once_with(
        [
            "adb", "-s", "device-1", "shell", "cmd", "activity", "stack", "list",
        ],
        timeout=5,
    )



def test_detect_current_package_falls_back_to_resumed_activity():
    runner = Mock()
    runner.run.side_effect = [
        CommandResult(success=True, output=""),
        CommandResult(success=True, output=""),
        CommandResult(success=True, output="mResumedActivity: com.example.app/.MainActivity"),
    ]

    result = detect_current_package("device-1", runner=runner)

    assert result["success"] is True
    assert result["package_name"] == "com.example.app"
    assert runner.run.call_count == 3


def test_adb_testing_shutdown_stops_managed_processes():
    model = ADBTesting()
    model._procs = Mock()

    model.shutdown()

    model._procs.stop_all.assert_called_once()
    assert "*" in model._aborted_devices


def test_run_monkey_test_reports_nonzero_exit_as_failure(tmp_path):
    model = ADBTesting()
    model._procs = Mock()
    logcat_proc = Mock()
    monkey_proc = Mock(pid=1234)
    monkey_proc.poll.side_effect = [None, 1, 1]
    model._procs.start.side_effect = [logcat_proc, monkey_proc]
    model._procs.stop.return_value = None

    with patch.object(model, "_run", return_value={"success": True, "output": ""}), \
         patch.object(model, "_get_current_package", return_value="com.example.app"), \
         patch("models.adb_testing.time.sleep"):
        result = ADBTesting.run_monkey_test_async.__wrapped__(
            model,
            "device-1",
            "com.example.app",
            {"events": 10},
            "com_example_app",
            str(tmp_path),
            1,
        )

    assert result["success"] is False
    assert result["error"] == "Monkey exited with code 1"
    assert result["duration"]


def test_run_monkey_test_reports_repeated_timeouts_as_failure(tmp_path):
    model = ADBTesting()
    model._procs = Mock()
    logcat_proc = Mock()
    monkey_proc = Mock(pid=1234)
    monkey_proc.poll.return_value = None
    model._procs.start.side_effect = [logcat_proc, monkey_proc]
    model._procs.stop.return_value = None

    timeout = subprocess.TimeoutExpired(cmd="dumpsys", timeout=5)
    with patch.object(model, "_run", return_value={"success": True, "output": ""}), \
         patch.object(model, "_get_current_package", side_effect=[timeout, timeout, timeout]), \
         patch("models.adb_testing.time.sleep"):
        result = ADBTesting.run_monkey_test_async.__wrapped__(
            model,
            "device-1",
            "com.example.app",
            {"events": 10},
            "com_example_app",
            str(tmp_path),
            1,
        )

    assert result["success"] is False
    assert result["error"] == "Device appears disconnected"



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
        operation="install",
    )


def test_parse_apk_info_accepts_existing_apk_case_insensitively():
    controller = Mock()
    controller.app_model = Mock()

    with patch("controllers._app.QFileDialog.getOpenFileName", return_value=("C:/tmp/DEMO.APK", "")), \
         patch("controllers._app.os.path.isfile", return_value=True):
        ADBAppMixin.parse_apk_info(controller)

    controller.app_model.parse_apk_info_async.assert_called_once_with("C:/tmp/DEMO.APK")
    assert controller._emit_operation.call_args.args[1] is True


def test_parse_apk_info_rejects_missing_file():
    controller = Mock()
    controller.app_model = Mock()

    with patch("controllers._app.QFileDialog.getOpenFileName", return_value=("C:/tmp/demo.apk", "")), \
         patch("controllers._app.os.path.isfile", return_value=False):
        ADBAppMixin.parse_apk_info(controller)

    controller.app_model.parse_apk_info_async.assert_not_called()
    controller._emit_operation.assert_called_once()
    assert controller._emit_operation.call_args.args[1] is False


def test_batch_install_result_uses_batch_tracker_key():
    emitted = []

    controller = Mock()
    controller._pending_lock = threading.Lock()
    controller._batch_trackers = {
        "batch_install": BatchOperationTracker(
            2,
            "Batch Install",
            lambda op, success, msg: emitted.append((op, success, msg)),
        )
    }
    controller._emit_operation.side_effect = (
        lambda op, success, msg: emitted.append((op, success, msg))
    )

    ADBAppMixin._process_install_apk_result(
        controller,
        {
            "success": True,
            "device_ip": "device-1",
            "apk_name": "demo.apk",
            "operation": "batch_install",
        },
    )

    assert emitted == [
        ("batch_install", True, "✅ install success (1/2) demo.apk on device-1")
    ]


def test_app_controller_install_calls_model_async_directly():
    controller = Mock()
    controller._pending_lock = threading.Lock()
    controller._batch_trackers = {
        "install": BatchOperationTracker(1, "Install App", Mock())
    }
    controller._emit_operation = Mock()
    controller.app_model = Mock()
    controller.executor = Mock()

    ADBAppMixin._install_single_device(
        controller, 1, "device-1", "demo.apk", "demo.apk", "install"
    )

    controller.executor.submit.assert_not_called()
    controller.app_model.install_apk_async.assert_called_once_with(
        "device-1", "demo.apk", "demo.apk", 1, "install"
    )
    controller._emit_operation.assert_called_once_with(
        "install", True, "Start install (1/1) demo.apk on device-1 ..."
    )


def test_app_controller_direct_async_paths_skip_python_executor():
    controller = Mock()
    controller._require_devices.return_value = True
    controller._batch_trackers = {}
    controller._emit_operation = Mock()
    controller.app_model = Mock()
    controller.executor = Mock()

    ADBAppMixin.clear_app_data(controller, ["device-1"], "com.example")
    ADBAppMixin.restart_app(controller, ["device-1"], "com.example")
    ADBAppMixin.get_current_activity(controller, ["device-1"])

    controller.executor.submit.assert_not_called()
    controller.app_model.clear_app_data_async.assert_called_once_with(
        "device-1", "com.example", 1
    )
    controller.app_model.restart_app_async.assert_called_once_with(
        "device-1", "com.example", 1
    )
    controller.app_model.get_current_activity_async.assert_called_once_with("device-1", 1)


def test_controller_shutdown_stops_model_processes_and_executor():
    controller = Mock()
    controller.testing_model = Mock()
    controller.advanced_model = Mock()
    controller.executor = Mock()

    with patch("controllers._base.ProcessRunner.stop_all_tracked") as stop_all_tracked:
        _ADBControllerBase.shutdown(controller)

    controller.testing_model.shutdown.assert_called_once()
    controller.advanced_model.shutdown.assert_called_once()
    stop_all_tracked.assert_called_once()
    controller.executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


def test_connect_device_result_uses_returned_device_ip():
    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller._save_device_info = Mock()
    controller.refresh_devices = Mock()
    controller._emit_operation = Mock()

    ADBDeviceMixin._process_connect_device_result(
        controller,
        {"success": True, "device_ip": "device-2", "output": "connected to device-2"},
    )

    controller._save_device_info.assert_called_once_with("device-2")
    controller.refresh_devices.assert_called_once()
    controller._emit_operation.assert_called_once_with(
        "connect", True, "Successfully connected to device-2"
    )


def test_connect_device_result_refreshes_when_already_connected():
    controller = ADBDeviceMixin.__new__(ADBDeviceMixin)
    controller._save_device_info = Mock()
    controller.refresh_devices = Mock()
    controller._emit_operation = Mock()

    ADBDeviceMixin._process_connect_device_result(
        controller,
        {"success": True, "device_ip": "device-2", "output": "already connected to device-2"},
    )

    controller._save_device_info.assert_called_once_with("device-2")
    controller.refresh_devices.assert_called_once()
    controller._emit_operation.assert_called_once_with(
        "connect", True, "device-2 is already connected"
    )


def test_publish_detected_devices_uses_device_list_processing():
    controller = Mock()

    ADBDeviceMixin.publish_detected_devices(controller, ("device-1", "device-2"))

    controller._process_device_list.assert_called_once_with(["device-1", "device-2"])


def test_connect_device_validates_and_normalizes_target_before_adb_call():
    controller = Mock()

    ADBDeviceMixin.connect_device(controller, " 10.0.0.195 : 5555 ")

    controller.device_model.connect_device_async.assert_called_once_with("10.0.0.195:5555")
    controller._emit_operation.assert_not_called()


def test_connect_device_rejects_incomplete_target_before_adb_call():
    controller = Mock()

    ADBDeviceMixin.connect_device(controller, "10.0.0.195")

    controller.device_model.connect_device_async.assert_not_called()
    controller._emit_operation.assert_called_once()
    assert "IP and port" in controller._emit_operation.call_args.args[2]


def test_kill_monkey_result_logs_not_running_as_success():
    controller = Mock()
    controller._monkey_running = {"device-1"}

    ADBAppMixin._process_kill_monkey_result(
        controller,
        {
            "device_ip": "device-1",
            "index": 1,
            "success": True,
            "already_stopped": True,
            "message": "Monkey is not running",
        },
    )

    assert controller._monkey_running == set()
    controller._emit_operation.assert_called_once_with(
        "kill_monkey", True, "ℹ️ 1. Monkey was not running on device-1"
    )


def test_pull_recorded_video_reports_pull_failure():
    model = ADBAdvanced()

    with patch.object(model, "_run") as run:
        run.return_value = {"success": False, "error": "remote object does not exist"}

        result = ADBAdvanced.pull_recorded_video_async.__wrapped__(
            model,
            "device-1",
            "/sdcard/missing.mp4",
            "C:/tmp",
            "missing.mp4",
        )

    assert result["success"] is False
    assert result["device_ip"] == "device-1"
    assert "pull failed" in result["error"]
    run.assert_called_once()


def test_settings_get_async_returns_value_alias():
    model = ADBAdvanced()

    with patch.object(model, "_run") as run:
        run.return_value = {
            "success": True,
            "output": "1",
            "device_ip": "device-1",
            "key": "show_touches",
        }

        result = ADBAdvanced.settings_get_async.__wrapped__(
            model,
            "device-1",
            "system",
            "show_touches",
        )

    assert result["value"] == "1"
    run.assert_called_once_with(
        ["adb", "-s", "device-1", "shell", "settings", "get", "system", "show_touches"],
        device_ip="device-1",
        key="show_touches",
    )


def test_capture_bugreport_reports_command_failure(tmp_path):
    model = ADBTesting()

    with patch.object(model, "_run") as run:
        run.side_effect = [
            {"success": True, "output": "11"},
            {"success": False, "error": "bugreport crashed"},
        ]

        result = ADBTesting.capture_bugreport_async.__wrapped__(
            model,
            "device-1",
            str(tmp_path),
            1,
        )

    assert result == {
        "device_ip": "device-1",
        "index": 1,
        "success": False,
        "message": "Bugreport failed: bugreport crashed",
    }


def test_safe_extract_zip_rejects_paths_outside_target(tmp_path):
    from utils.archive import safe_extract_zip

    zip_path = tmp_path / "bad.zip"
    target = tmp_path / "target"
    target.mkdir()
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.txt", "bad")

    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            safe_extract_zip(zf, target)
            rejected = False
        except ValueError:
            rejected = True

    assert rejected is True
    assert not (tmp_path / "evil.txt").exists()


def test_take_screenshot_prefers_exec_out_direct_path(tmp_path):
    model = ADBTesting()
    save_path = tmp_path / "shot.png"

    def write_png(_cmd, path, timeout=30):
        with open(path, "wb") as image_file:
            image_file.write(b"\x89PNG\r\n\x1a\npayload")
        return CommandResult(success=True, output=path)

    with patch("models.adb_testing.CommandRunner.run_to_file", side_effect=write_png), \
         patch.object(model, "_run") as run:
        result = ADBTesting.take_screenshot_async.__wrapped__(
            model,
            "device-1",
            str(save_path),
        )

    assert result == {"success": True, "device_ip": "device-1", "screenshot_path": str(save_path)}
    run.assert_not_called()


def test_take_screenshot_falls_back_when_exec_out_is_invalid_png(tmp_path):
    model = ADBTesting()
    save_path = tmp_path / "shot.png"

    def write_bad(_cmd, path, timeout=30):
        with open(path, "wb") as image_file:
            image_file.write(b"not png")
        return CommandResult(success=True, output=path)

    with patch("models.adb_testing.CommandRunner.run_to_file", side_effect=write_bad), \
         patch.object(model, "_run") as run:
        run.side_effect = [
            {"success": True, "output": ""},
            {"success": True, "output": "ok"},
            {"success": True, "output": "pulled"},
            {"success": True, "output": ""},
        ]

        result = ADBTesting.take_screenshot_async.__wrapped__(
            model,
            "device-1",
            str(save_path),
        )

    assert result == {"success": True, "device_ip": "device-1", "screenshot_path": str(save_path)}
    assert run.call_count == 4



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


def test_file_explorer_worker_passes_custom_timeout_to_command_runner():
    worker = ADBWorker("device-1", ["shell", "du", "-sh", "/sdcard"], timeout=120)
    emitted = []
    worker.finished.connect(lambda output, failed: emitted.append((output, failed)))

    with patch("models.file_explorer_worker.CommandRunner.run") as run:
        run.return_value = CommandResult(success=True, output="1G /sdcard")

        worker.run()

    assert emitted == [("1G /sdcard", False)]
    run.assert_called_once_with(
        ["adb", "-s", "device-1", "shell", "du", "-sh", "/sdcard"],
        timeout=120,
    )


def test_file_explorer_transfer_failure_does_not_refresh():
    dialog = SimpleNamespace()
    dialog.status_bar = Mock()
    dialog._refresh = Mock()

    with patch("gui.dialogs.file_explorer.QMessageBox.critical") as critical:
        FileExplorerDialog._on_transfer_done(dialog, "failed to copy", True, "Pulled demo.txt")

    critical.assert_called_once()
    dialog.status_bar.showMessage.assert_called_once_with("Failed: failed to copy")
    dialog._refresh.assert_not_called()


def test_file_explorer_file_operation_failure_does_not_show_success():
    dialog = SimpleNamespace()
    dialog.status_bar = Mock()
    dialog._refresh = Mock()

    with patch("gui.dialogs.file_explorer.QMessageBox.critical") as critical:
        FileExplorerDialog._on_file_op_done(dialog, "Permission denied", True, "Deleted demo.txt")

    critical.assert_called_once()
    dialog.status_bar.showMessage.assert_called_once_with("Failed: Permission denied")
    dialog._refresh.assert_not_called()


def test_transfer_worker_uses_process_runner_for_streaming_transfer(tmp_path):
    class FakeStdout:
        def __init__(self):
            self.lines = iter(["pulled file\n", ""])

        def readline(self):
            return next(self.lines)

    proc = Mock()
    proc.stdout = FakeStdout()
    proc.poll.return_value = 0
    proc.wait.return_value = 0

    worker = TransferWorker("device-1", ["pull", "/sdcard/demo.txt", "demo.txt"], cwd=str(tmp_path))
    progress = []
    finished = []
    worker.progress.connect(progress.append)
    worker.finished.connect(lambda message, failed, local: finished.append((message, failed, local)))

    with patch.object(worker._process_runner, "start", return_value=proc) as start, \
         patch.object(worker._process_runner, "stop") as stop:
        worker.run()

    start.assert_called_once_with(
        worker._process_key,
        ["adb", "-s", "device-1", "pull", "/sdcard/demo.txt", "demo.txt"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(tmp_path),
        text=True,
        encoding="utf-8",
        errors="ignore",
        bufsize=1,
    )
    stop.assert_called_once_with(worker._process_key, timeout=0)
    assert progress == ["pulled file"]
    assert finished == [("pulled file", False, "demo.txt")]


def test_file_explorer_ls_result_prefills_rows_without_insert_loop():
    _app = QApplication.instance() or QApplication([])
    dialog = SimpleNamespace()
    dialog.current_path = "/sdcard"
    dialog.TYPE_COL = FileExplorerDialog.TYPE_COL
    dialog.NAME_COL = FileExplorerDialog.NAME_COL
    dialog.SIZE_COL = FileExplorerDialog.SIZE_COL
    dialog.MODIFIED_COL = FileExplorerDialog.MODIFIED_COL
    dialog.table = Mock()
    dialog.status_bar = Mock()
    dialog.symlink_targets = {}
    dialog._file_type_icon = Mock(return_value=QIcon())
    dialog._set_file_row = lambda row, name, file_type, size, modified: (
        FileExplorerDialog._set_file_row(dialog, row, name, file_type, size, modified)
    )
    output = """
total 8
drwxr-xr-x 2 shell shell 4096 May 30 DCIM
-rw-r--r-- 1 shell shell 1024 May 30 readme.txt
"""

    FileExplorerDialog._on_ls_result(dialog, output, "")

    dialog.table.setUpdatesEnabled.assert_any_call(False)
    dialog.table.setUpdatesEnabled.assert_any_call(True)
    dialog.table.setSortingEnabled.assert_any_call(False)
    dialog.table.setSortingEnabled.assert_any_call(True)
    dialog.table.setRowCount.assert_called_once_with(3)
    dialog.table.insertRow.assert_not_called()
    assert dialog.table.setItem.call_count == 12
    first_row_calls = dialog.table.setItem.call_args_list[:4]
    assert [call_.args[1] for call_ in first_row_calls] == [
        FileExplorerDialog.TYPE_COL,
        FileExplorerDialog.NAME_COL,
        FileExplorerDialog.SIZE_COL,
        FileExplorerDialog.MODIFIED_COL,
    ]
    assert first_row_calls[0].args[2].text() == "Folder"
    assert first_row_calls[1].args[2].text() == ".."
    dialog.status_bar.showMessage.assert_called_once_with(
        "/sdcard  |  1 folders, 1 files"
    )


def test_file_explorer_table_moves_type_first_and_hides_row_numbers():
    _app = QApplication.instance() or QApplication([])
    with patch.object(FileExplorerDialog, "_refresh"):
        dialog = FileExplorerDialog(device_ip="device-1")

    try:
        assert dialog.table.horizontalHeaderItem(0).text() == "Type"
        assert dialog.table.horizontalHeaderItem(1).text() == "Name"
        assert dialog.table.verticalHeader().isVisible() is False
        assert dialog.NAME_COL == 1
        assert dialog._file_type_icon_name("demo.apk", "APK") == "android-logo.svg"
        assert dialog._file_type_icon_name("photo.png", "PNG") == "file-png.svg"
        assert dialog._file_type_icon_name("movie.mp4", "MP4") == "file-video.svg"
        assert dialog._file_type_icon_name("notes.txt", "TXT") == "file-txt.svg"
    finally:
        dialog.close()


def test_adb_bridge_shell_uses_command_runner():
    bridge = ADBBridge(path="adb.exe")

    with patch("core.adb_bridge.CommandRunner.run") as run:
        run.return_value = CommandResult(success=True, output="ok")

        result = bridge.shell("wm size", device_id="device-1")

    assert result.output == "ok"
    run.assert_called_once_with(["adb.exe", "-s", "device-1", "shell", "wm size"], timeout=15)


def test_adb_bridge_shell_input_uses_process_runner_spawn():
    bridge = ADBBridge(path="adb.exe")
    proc = Mock()

    with patch.object(bridge, "_input_session") as input_session, \
         patch.object(bridge._process_runner, "spawn", return_value=proc) as spawn:
        input_session.return_value.send.return_value = False
        result = bridge.shell_input("keyevent 3", device_id="device-1")

    assert result is proc
    input_session.assert_called_once_with("device-1")
    spawn.assert_called_once_with(["adb.exe", "-s", "device-1", "shell", "input keyevent 3"])


def test_adb_bridge_shell_input_prefers_persistent_session():
    bridge = ADBBridge(path="adb.exe")
    session = Mock()
    session.send.return_value = True

    with patch.object(bridge, "_input_session", return_value=session), \
         patch.object(bridge._process_runner, "spawn") as spawn:
        result = bridge.shell_input("keyevent 3", device_id="device-1")

    assert result is session
    session.send.assert_called_once_with("keyevent 3")
    spawn.assert_not_called()


def test_adb_bridge_close_input_sessions_closes_and_removes_sessions():
    bridge = ADBBridge(path="adb.exe")
    session_1 = Mock()
    session_2 = Mock()
    bridge._input_sessions = {"device-1": session_1, "device-2": session_2}

    bridge.close_input_sessions("device-1")

    session_1.close.assert_called_once()
    session_2.close.assert_not_called()
    assert "device-1" not in bridge._input_sessions
    assert "device-2" in bridge._input_sessions

    bridge.close_input_sessions()

    session_2.close.assert_called_once()
    assert bridge._input_sessions == {}


def test_adb_advanced_input_uses_persistent_shell_bridge():
    model = ADBAdvanced()
    model._adb_bridge = Mock()

    result = ADBAdvanced.input_tap_async.__wrapped__(model, "device-1", 10, 20)

    assert result == {"success": True, "device_ip": "device-1", "x": 10, "y": 20}
    model._adb_bridge.shell_input.assert_called_once_with(
        "tap 10 20", device_id="device-1"
    )


def test_adb_advanced_input_failure_is_reported():
    model = ADBAdvanced()
    model._adb_bridge = Mock()
    model._adb_bridge.shell_input.side_effect = OSError("adb died")

    result = ADBAdvanced.input_keyevent_async.__wrapped__(model, "device-1", "3")

    assert result == {"success": False, "device_ip": "device-1", "keycode": "3"}


def test_adb_advanced_shutdown_stops_recording_and_input_sessions():
    model = ADBAdvanced()
    model._rec_procs = Mock()
    model._adb_bridge = Mock()

    model.shutdown()

    model._rec_procs.stop_all.assert_called_once()
    model._adb_bridge.close_input_sessions.assert_called_once_with(None)


def test_quick_setting_batches_animation_commands_into_one_shell():
    model = ADBAdvanced()

    with patch.object(model, "_run") as run:
        run.return_value = {"success": True, "device_ip": "device-1"}

        result = ADBSystemMixin.quick_setting_async.__wrapped__(
            model, "device-1", "anim_off"
        )

    assert result == {"success": True, "device_ip": "device-1", "action": "anim_off"}
    run.assert_called_once_with(
        [
            "adb",
            "-s",
            "device-1",
            "shell",
            "settings put global animator_duration_scale 0 && "
            "settings put global transition_animation_scale 0 && "
            "settings put global window_animation_scale 0",
        ],
        device_ip="device-1",
        action="anim_off",
    )


def test_adb_input_session_writes_input_command_to_stdin():
    proc = Mock()
    proc.stdin = Mock()
    proc.poll.return_value = None
    session = ADBInputSession("adb.exe", "device-1")

    with patch("core.adb_bridge.subprocess.Popen", return_value=proc) as popen:
        assert session.send("keyevent 3") is True

    popen.assert_called_once()
    assert popen.call_args.args[0] == ["adb.exe", "-s", "device-1", "shell"]
    proc.stdin.write.assert_called_once_with("input keyevent 3\n")
    proc.stdin.flush.assert_called_once()


def test_adb_input_session_returns_false_when_process_cannot_start():
    session = ADBInputSession("adb.exe", "device-1")

    with patch("core.adb_bridge.subprocess.Popen", side_effect=OSError("boom")):
        assert session.send("keyevent 3") is False


def test_adb_bridge_devices_parses_command_runner_output():
    bridge = ADBBridge(path="adb.exe")

    with patch("core.adb_bridge.CommandRunner.run") as run:
        run.return_value = CommandResult(
            success=True,
            output="List of devices attached\ndevice-1\tdevice\ndevice-2\toffline",
        )

        devices = bridge.devices()

    assert devices == [["device-1", "device"], ["device-2", "offline"]]
    run.assert_called_once_with(["adb.exe", "devices"], timeout=15)



def test_testing_model_current_package_uses_shared_detector():
    model = ADBTesting()

    with patch("models.adb_testing.detect_current_package") as detect:
        detect.return_value = {"success": True, "device_ip": "device-1", "package_name": "com.example.app"}

        package_name = model._get_current_package("device-1")

    assert package_name == "com.example.app"
    detect.assert_called_once_with("device-1")



def test_kill_monkey_treats_empty_device_stop_error_as_idempotent_success():
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
        "success": True,
        "message": "Monkey process stopped",
        "already_stopped": False,
    }
    proc.terminate.assert_called_once()
    assert model._procs._procs == {}


def test_kill_monkey_reports_not_running_when_no_local_process_and_empty_device_error():
    model = ADBTesting()

    with patch.object(model, "_run") as run:
        run.return_value = {"success": False, "error": "", "device_ip": "device-1"}

        result = model.kill_monkey_async.__wrapped__(model, "device-1", 1)

    assert result == {
        "device_ip": "device-1",
        "index": 1,
        "success": True,
        "message": "Monkey is not running",
        "already_stopped": True,
    }


def test_kill_monkey_reports_real_device_stop_error_without_local_process():
    model = ADBTesting()

    with patch.object(model, "_run") as run:
        run.return_value = {"success": False, "error": "device offline", "device_ip": "device-1"}

        result = model.kill_monkey_async.__wrapped__(model, "device-1", 1)

    assert result == {
        "device_ip": "device-1",
        "index": 1,
        "success": False,
        "message": "device offline",
        "already_stopped": False,
    }


@pytest.fixture
def isolated_log_service():
    """隔离日志服务的进程级单例，避免停止状态在测试用例之间传播。"""
    previous_instance = LogService._instance
    LogService._instance = None
    service = LogService()
    try:
        yield service
    finally:
        if service._state == service._STATE_ACCEPTING:
            service.shutdown()
        LogService._instance = previous_instance


def test_log_service_shutdown_rejects_background_thread_without_deadlock(isolated_log_service):
    _app = QApplication.instance() or QApplication([])
    service = isolated_log_service
    service.log("INFO", "shutdown sentinel")
    errors = []

    def shutdown_from_worker():
        try:
            service.shutdown()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=shutdown_from_worker, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    service._buffer_lock.lock()
    try:
        assert service._buffer == [("INFO", "shutdown sentinel")]
    finally:
        service._buffer_lock.unlock()


def test_log_service_worker_thread_log_flushes_on_owner_thread(isolated_log_service):
    _app = QApplication.instance() or QApplication([])
    service = isolated_log_service
    service._flush_buffer()
    sentinel = "worker-thread-flush-sentinel"
    emitted = []
    owner_thread_id = threading.get_ident()
    service.log_received.connect(
        lambda level, message: emitted.append((level, message, threading.get_ident()))
    )

    thread = threading.Thread(target=lambda: service.log("INFO", sentinel), daemon=True)
    thread.start()
    thread.join(timeout=0.5)
    service._flush_buffer()

    assert ("INFO", sentinel, owner_thread_id) in emitted


def test_log_service_emits_batch_before_compat_single_signals(isolated_log_service):
    _app = QApplication.instance() or QApplication([])
    service = isolated_log_service
    service._flush_buffer()
    batch_emitted = []
    singles = []
    service.logs_received.connect(lambda records: batch_emitted.append(records))
    service.log_received.connect(lambda level, message: singles.append((level, message)))

    service.log("INFO", "batched-1")
    service.log("WARNING", "batched-2")
    service._flush_buffer()

    assert batch_emitted[-1] == [("INFO", "batched-1"), ("WARNING", "batched-2")]
    assert singles[-2:] == [("INFO", "batched-1"), ("WARNING", "batched-2")]


def test_log_panel_appends_large_batch_in_one_render_pass(isolated_log_service):
    _app = QApplication.instance() or QApplication([])
    assert LogService() is isolated_log_service
    panel = LogPanel()
    try:
        calls = []
        original = panel._render_entries

        def counted(rows):
            calls.append(len(rows))
            return original(rows)

        panel._render_entries = counted
        records = [("INFO", f"line-{i}") for i in range(1000)]

        panel._append_logs(records)

        assert calls == [1000]
        assert len(panel._entries) == 1000
        assert "line-999" in panel.text_output.toPlainText()
    finally:
        panel.close()


def test_log_panel_coalesces_small_log_batches_before_rendering(isolated_log_service):
    _app = QApplication.instance() or QApplication([])
    assert LogService() is isolated_log_service
    panel = LogPanel()
    old_debounce = LogPanel.RENDER_DEBOUNCE_MS
    LogPanel.RENDER_DEBOUNCE_MS = 20
    try:
        calls = []
        original = panel._render_entries

        def counted(rows):
            calls.append(len(rows))
            return original(rows)

        panel._render_entries = counted

        panel._append_logs([("INFO", "small-1")])
        panel._append_logs([("INFO", "small-2")])

        assert calls == []
        panel._flush_pending_rows()

        assert calls == [2]
        assert "small-2" in panel.text_output.toPlainText()
    finally:
        LogPanel.RENDER_DEBOUNCE_MS = old_debounce
        panel.close()
