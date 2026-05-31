import ctypes
import os
import subprocess
import threading
import time
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QListWidget, QPushButton, QWidget

from controllers._app import ADBAppMixin
from controllers._base import _ADBControllerBase
from controllers._device import ADBDeviceMixin
from core.adb_bridge import ADBBridge, ADBInputSession
from core.log_service import LogService
from core.perf_trace import attach_perf, build_async_perf, split_perf
from gui.dialogs.app_manager import AppManagerDialog
from gui.dialogs.file_explorer import FileExplorerDialog
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
from gui.dialogs.lifecycle import safe_disconnect
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.panels.base_panel import BasePanel
from gui.panels.device_manager import DeviceManager
from gui.panels.side_panel import SidePanel
from gui.panels.remote_panel import ScrcpyLaunchWorker
from gui.styles import BaseStyles
from gui.styles import theme
from utils.app_metadata import APP_RELEASE_TAG, APP_VERSION
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
        )

    assert started is proc
    assert popen.call_args.kwargs["cwd"] == "C:/work"
    assert popen.call_args.kwargs["text"] is True
    assert popen.call_args.kwargs["encoding"] == "utf-8"
    assert popen.call_args.kwargs["errors"] == "ignore"
    assert popen.call_args.kwargs["bufsize"] == 1


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


def test_main_frame_open_cmd_launches_terminal_via_process_runner():
    frame = MainFrame.__new__(MainFrame)
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
    thread.devices_changed.connect(lambda: emitted.append(True))

    with patch("gui.main_frame.CommandRunner.run") as run, \
         patch.object(_ScanThread, "msleep", side_effect=lambda _ms: setattr(thread, "_stop_flag", True)):
        run.return_value = CommandResult(success=True, output="List of devices attached\n")
        thread.run()

    run.assert_called_once_with(["adb", "devices"], timeout=5)
    assert emitted == [True]


def test_main_frame_starts_scan_thread_with_debounced_refresh():
    frame = MainFrame.__new__(MainFrame)
    frame._scan_thread = None
    frame.adb_controller = Mock()
    frame._schedule_scan_refresh = Mock()

    class FakeScanThread:
        def __init__(self, parent):
            self.parent = parent
            self.devices_changed = Mock()
            self.started = False

        def isRunning(self):
            return False

        def start(self):
            self.started = True

    with patch("gui.main_frame._ScanThread", FakeScanThread):
        MainFrame._start_scan_thread(frame)

    frame._scan_thread.devices_changed.connect.assert_called_once_with(
        frame._schedule_scan_refresh
    )
    frame.adb_controller.refresh_devices.assert_not_called()
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
    fake_side_panel._device_widget = QWidget()
    fake_side_panel.signals = Mock()
    fake_side_panel._devices_tab = Mock()
    fake_side_panel._devices_tab._apply_device_list_style = Mock()
    fake_side_panel.update_device_list = Mock()
    fake_side_panel._refresh_device_combobox = Mock()
    fake_side_panel.update_email = Mock()
    fake_side_panel.update_vercode = Mock()
    fake_side_panel.on_recording_finished = Mock()
    fake_side_panel.update_current_package = Mock()
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
        frame.close()


def test_main_frame_start_device_discovery_respects_scan_setting():
    frame = MainFrame.__new__(MainFrame)
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
    frame = MainFrame.__new__(MainFrame)
    frame._closing = False
    frame._start_scan_thread = Mock()
    frame._initial_refresh_timer = Mock()

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings_cls.instance.return_value.get.return_value = False

        MainFrame._start_device_discovery(frame)

    frame._start_scan_thread.assert_not_called()
    frame._initial_refresh_timer.start.assert_called_once_with(0)


def test_main_frame_start_device_discovery_skips_after_close():
    frame = MainFrame.__new__(MainFrame)
    frame._closing = True
    frame._start_scan_thread = Mock()
    frame._initial_refresh_timer = Mock()
    frame.adb_controller = Mock()

    MainFrame._start_device_discovery(frame)

    frame._start_scan_thread.assert_not_called()
    frame._initial_refresh_timer.start.assert_not_called()
    frame.adb_controller.refresh_devices.assert_not_called()


def test_main_frame_stop_scan_thread_uses_short_ui_wait():
    frame = MainFrame.__new__(MainFrame)
    frame._initial_refresh_timer = Mock()
    frame._initial_refresh_timer.isActive.return_value = True
    frame._scan_refresh_timer = Mock()
    frame._scan_refresh_timer.isActive.return_value = True
    frame._scan_thread = Mock()
    frame._scan_thread.isRunning.return_value = True
    frame._scan_thread.wait.return_value = True

    MainFrame._stop_scan_thread(frame)

    frame._initial_refresh_timer.stop.assert_called_once()
    frame._scan_refresh_timer.stop.assert_called_once()
    frame._scan_thread.stop.assert_called_once()
    frame._scan_thread.wait.assert_called_once_with(150)


def test_main_frame_refresh_toolbar_icons_updates_registered_buttons():
    _app = QApplication.instance() or QApplication([])
    frame = MainFrame.__new__(MainFrame)
    button = QPushButton()
    button.setProperty("iconName", "palette.svg")
    frame.findChildren = Mock(return_value=[button])

    with patch("gui.main_frame.get_themed_icon", return_value=QIcon()) as themed_icon:
        MainFrame._refresh_toolbar_icons(frame)

    themed_icon.assert_called_once_with("palette.svg")


def test_main_frame_signal_maps_keep_expected_coverage():
    frame = MainFrame.__new__(MainFrame)
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
    _app = QApplication.instance() or QApplication([])
    frame = MainFrame.__new__(MainFrame)
    frame.adb_controller = Mock()
    frame._scan_refresh_timer = QTimer()
    frame._scan_refresh_timer.setSingleShot(True)
    frame._scan_refresh_timer.timeout.connect(frame.adb_controller.refresh_devices)

    old_debounce = MainFrame.DEVICE_SCAN_DEBOUNCE_MS
    MainFrame.DEVICE_SCAN_DEBOUNCE_MS = 20
    try:
        MainFrame._schedule_scan_refresh(frame)
        MainFrame._schedule_scan_refresh(frame)
        MainFrame._schedule_scan_refresh(frame)

        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not frame.adb_controller.refresh_devices.called:
            _app.processEvents()
            time.sleep(0.01)
    finally:
        MainFrame.DEVICE_SCAN_DEBOUNCE_MS = old_debounce
        frame._scan_refresh_timer.stop()

    frame.adb_controller.refresh_devices.assert_called_once()


def test_main_frame_splitter_size_save_is_debounced():
    _app = QApplication.instance() or QApplication([])
    frame = MainFrame.__new__(MainFrame)
    frame._panel_splitter = Mock()
    frame._panel_splitter.sizes.side_effect = [[300, 700], [320, 680]]
    frame._pending_panel_sizes = None
    frame._panel_size_save_timer = QTimer()
    frame._panel_size_save_timer.setSingleShot(True)
    frame._panel_size_save_timer.timeout.connect(lambda: MainFrame._save_pending_panel_sizes(frame))

    old_debounce = MainFrame.SPLITTER_SAVE_DEBOUNCE_MS
    MainFrame.SPLITTER_SAVE_DEBOUNCE_MS = 20
    try:
        with patch("core.settings_manager.AppSettings") as settings_cls:
            settings = Mock()
            settings_cls.instance.return_value = settings

            MainFrame._on_splitter_moved(frame, 0, 0)
            MainFrame._on_splitter_moved(frame, 0, 0)

            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline and settings.set.call_count < 2:
                _app.processEvents()
                time.sleep(0.01)
    finally:
        MainFrame.SPLITTER_SAVE_DEBOUNCE_MS = old_debounce
        frame._panel_size_save_timer.stop()

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
    viewer = ScreenshotViewer.__new__(ScreenshotViewer)
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
        assert viewer._save_btn.text() == ""
        assert viewer._bottom_bar.objectName() == "bottomBar"
        assert not hasattr(viewer, "_close_btn")
        expected_tips = {
            viewer._prev_btn: "Previous screenshot (Left)",
            viewer._next_btn: "Next screenshot (Right)",
            viewer._zoom_out_btn: "Zoom out (Ctrl+-)",
            viewer._zoom_in_btn: "Zoom in (Ctrl+=)",
            viewer._fit_btn: "Fit to window (Ctrl+0)",
            viewer._actual_btn: "Actual size",
            viewer._copy_btn: "Copy to clipboard (Ctrl+C)",
            viewer._save_btn: "Save as (Ctrl+S)",
            viewer._folder_btn: "Open file location",
            viewer._delete_btn: "Delete screenshot",
        }
        assert all(button.toolTip() == tooltip for button, tooltip in expected_tips.items())
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
    manager = DeviceManager.__new__(DeviceManager)
    manager.panel = panel
    manager.listbox_devices = QListWidget()

    with patch("gui.panels.device_manager.DeviceStore.get_full_devices_info", return_value=[]):
        DeviceManager.update_device_list(manager, ["emulator-5554"])

    assert manager.listbox_devices.count() == 1
    item = manager.listbox_devices.item(0)
    assert "Detecting" in item.text()
    assert item.data(Qt.UserRole)["ip"] == "emulator-5554"


def test_device_manager_updates_device_list_incrementally():
    _app = QApplication.instance() or QApplication([])
    panel = Mock(selected_devices=[])
    manager = DeviceManager.__new__(DeviceManager)
    manager.panel = panel
    manager.listbox_devices = QListWidget()

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

        DeviceManager.update_device_list(manager, ["device-1", "device-3"])

    assert manager.listbox_devices.count() == 2
    assert manager.listbox_devices.item(0) is first_item
    assert first_item.checkState() == Qt.Checked
    assert manager.listbox_devices.item(1).data(Qt.UserRole)["ip"] == "device-3"
    assert "Detecting" in manager.listbox_devices.item(1).text()


def test_base_panel_button_factory_adds_tooltip_and_icon_name():
    panel = Mock()
    panel._font_sm = QFont()
    base = BasePanel(panel)

    button = base._b("Refresh", "arrows-clockwise.svg")

    assert button.toolTip() == "Refresh"
    assert button.property("iconName") == "arrows-clockwise.svg"
    assert button.cursor().shape() == Qt.PointingHandCursor


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
    manager = DeviceManager.__new__(DeviceManager)
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
    panel = SidePanel.__new__(SidePanel)
    panel._font_sm = QFont()
    panel._font_base = QFont()
    panel._font_tab = QFont()
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

    with patch("gui.panels.side_panel.get_themed_icon", return_value=QIcon()) as themed_icon:
        SidePanel._on_theme_changed(panel, "Dark")

    themed_icon.assert_called_once_with("arrows-clockwise.svg")


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
    _app = QApplication.instance() or QApplication([])
    dialog = AppManagerDialog.__new__(AppManagerDialog)
    dialog._apps_data = []
    dialog._app_labels = {}
    dialog._app_versions = {}
    dialog._detail_cache = {}
    dialog._pending_detail_packages = set()
    dialog._detail_worker_running = False
    dialog._detail_row_by_pkg = {}
    dialog._detail_icon_by_pkg = {}
    dialog._view_mode = False
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
    controller = Mock()

    ADBDeviceMixin._process_connect_device_result(
        controller,
        {"success": True, "device_ip": "device-2", "output": "connected to device-2"},
    )

    controller._save_device_info.assert_called_once_with("device-2")
    controller.refresh_devices.assert_called_once()
    controller._emit_operation.assert_called_once_with(
        "connect", True, "Successfully connected to device-2"
    )


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
    dialog = FileExplorerDialog.__new__(FileExplorerDialog)
    dialog.current_path = "/sdcard"
    dialog.table = Mock()
    dialog.status_bar = Mock()
    dialog.symlink_targets = {}
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
    dialog.status_bar.showMessage.assert_called_once_with(
        "/sdcard  |  1 folders, 1 files"
    )


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


def test_log_service_shutdown_flushes_without_deadlock():
    _app = QApplication.instance() or QApplication([])
    service = LogService()
    service.log("INFO", "shutdown sentinel")

    thread = threading.Thread(target=service.shutdown, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    service._buffer_lock.lock()
    try:
        assert service._buffer == []
    finally:
        service._buffer_lock.unlock()


def test_log_service_worker_thread_log_flushes_on_owner_thread():
    app = QApplication.instance() or QApplication([])
    service = LogService()
    service._flush_buffer()
    sentinel = "worker-thread-flush-sentinel"
    emitted = []
    service.log_received.connect(lambda level, message: emitted.append((level, message)))

    thread = threading.Thread(target=lambda: service.log("INFO", sentinel), daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and ("INFO", sentinel) not in emitted:
        app.processEvents()
        time.sleep(0.01)

    assert ("INFO", sentinel) in emitted


def test_log_service_emits_batch_before_compat_single_signals():
    _app = QApplication.instance() or QApplication([])
    service = LogService()
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


def test_log_panel_appends_large_batch_in_one_render_pass():
    _app = QApplication.instance() or QApplication([])
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


def test_log_panel_coalesces_small_log_batches_before_rendering():
    _app = QApplication.instance() or QApplication([])
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

        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not calls:
            _app.processEvents()
            time.sleep(0.01)

        assert calls == [2]
        assert "small-2" in panel.text_output.toPlainText()
    finally:
        LogPanel.RENDER_DEBOUNCE_MS = old_debounce
        panel.close()
