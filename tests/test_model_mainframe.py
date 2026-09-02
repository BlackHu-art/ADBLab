# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import os
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QPushButton, QWidget

from core.exec import CREATE_NEW_CONSOLE
from gui.dialogs.app_manager import AppManagerDialog
from gui.dialogs.performance_launcher import PerformanceLauncherDialog
from gui.main_frame import MainFrame, _ScanThread
from gui.widgets.responsive_controller import ReflowReason


def test_main_frame_open_cmd_launches_terminal_via_process_runner():
    frame = SimpleNamespace()
    runner = Mock()

    with (
        patch("gui.main_frame.ProcessRunner", return_value=runner),
        patch("platform.system", return_value="Windows"),
        patch(
            "gui.main_frame.os.path.abspath",
            return_value="D:/VSCodeStation/ADBLab/gui/main_frame.py",
        ),
        patch(
            "gui.main_frame.os.path.dirname",
            side_effect=["D:/VSCodeStation/ADBLab/gui", "D:/VSCodeStation/ADBLab"],
        ),
    ):
        MainFrame._open_cmd(frame)

    runner.spawn.assert_called_once()
    assert runner.spawn.call_args.args[0][0] == "cmd.exe"
    assert runner.spawn.call_args.kwargs["creationflags"] == CREATE_NEW_CONSOLE


class _FakeScanProc:
    def __init__(self, output: str):
        self._output = output

    def poll(self):
        return 0

    def communicate(self):
        return self._output, ""


class _FakeScanRunner:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.started = []
        self.stopped = []

    def start(self, key, cmd, **kwargs):
        self.started.append(cmd)
        return _FakeScanProc(self._outputs.pop(0) if self._outputs else "")

    def stop(self, key, timeout=5.0):
        self.stopped.append(key)


def test_scan_thread_uses_command_runner_for_device_polling():
    _app = QApplication.instance() or QApplication([])
    thread = _ScanThread()
    emitted = []
    thread.devices_changed.connect(emitted.append)
    runner = _FakeScanRunner(["List of devices attached\ndevice-1\tdevice\n"])

    with (
        patch("gui.main_frame.ProcessRunner", return_value=runner),
        patch.object(
            _ScanThread, "msleep", side_effect=lambda _ms: setattr(thread, "_stop_flag", True)
        ),
    ):
        thread.run()

    assert runner.started == [["adb", "devices"]]
    assert emitted == [["device-1"]]


def test_scan_thread_skips_polling_while_command_runner_is_busy():
    _app = QApplication.instance() or QApplication([])
    thread = _ScanThread(interval_ms=3000)

    with (
        patch("gui.main_frame.CommandRunner.active_count", return_value=1),
        patch("gui.main_frame.ProcessRunner") as runner_cls,
        patch.object(
            _ScanThread, "msleep", side_effect=lambda _ms: setattr(thread, "_stop_flag", True)
        ),
    ):
        thread.run()

    runner_cls.assert_not_called()


def test_scan_thread_rechecks_shortly_after_command_runner_becomes_idle():
    _app = QApplication.instance() or QApplication([])
    thread = _ScanThread(interval_ms=15000)
    waits = []
    runner = _FakeScanRunner(["List of devices attached\n"])

    def stop_after_first_normal_wait(delay_ms):
        waits.append(delay_ms)
        # 忙碌周期跳过轮询并等待完整间隔（150 个 100ms 分片），
        # 下一周期空闲后才执行一次轮询，此时停止线程。
        if len(waits) >= 151:
            thread._stop_flag = True

    with (
        patch("gui.main_frame.CommandRunner.active_count", side_effect=[1, 0]),
        patch("gui.main_frame.ProcessRunner", return_value=runner),
        patch.object(_ScanThread, "msleep", side_effect=stop_after_first_normal_wait),
    ):
        thread.run()

    assert runner.started == [["adb", "devices"]]
    assert waits[:150] == [100] * 150


def test_scan_thread_emits_when_device_set_changes_with_same_count():
    _app = QApplication.instance() or QApplication([])
    thread = _ScanThread(interval_ms=3000)
    emitted = []
    sleeps = {"count": 0}
    thread.devices_changed.connect(emitted.append)
    runner = _FakeScanRunner(
        [
            "List of devices attached\ndevice-a\tdevice\n",
            "List of devices attached\ndevice-b\tdevice\n",
        ]
    )

    def stop_after_two_polls(_ms):
        sleeps["count"] += 1
        if sleeps["count"] >= 60:
            thread._stop_flag = True

    with (
        patch("gui.main_frame.CommandRunner.active_count", return_value=0),
        patch("gui.main_frame.ProcessRunner", return_value=runner),
        patch.object(_ScanThread, "msleep", side_effect=stop_after_two_polls),
    ):
        thread.run()

    assert emitted == [["device-a"], ["device-b"]]


def test_scan_thread_stop_terminates_inflight_scan():
    _app = QApplication.instance() or QApplication([])
    thread = _ScanThread(interval_ms=3000)

    class _RunningProc:
        def poll(self):
            return None

    class _RunningRunner:
        def __init__(self):
            self.stopped = []

        def start(self, key, cmd, **kwargs):
            return _RunningProc()

        def stop(self, key, timeout=5.0):
            self.stopped.append(key)

    runner = _RunningRunner()
    sleeps = {"count": 0}

    def stop_after_first_poll(_ms):
        sleeps["count"] += 1
        if sleeps["count"] == 1:
            thread._stop_flag = True

    with (
        patch("gui.main_frame.CommandRunner.active_count", return_value=0),
        patch("gui.main_frame.ProcessRunner", return_value=runner),
        patch.object(_ScanThread, "msleep", side_effect=stop_after_first_poll),
    ):
        thread.run()

    # 停止请求必须终止在途的 adb 子进程，保证线程及时退出，
    # 避免关闭窗口时 QThread 仍在运行被销毁。
    assert runner.stopped == ["device_scan"]


def test_main_frame_starts_scan_thread_with_debounced_refresh():
    frame = SimpleNamespace()
    frame._scan_thread = None
    frame.adb_controller = Mock()
    frame._schedule_scan_refresh = Mock()

    class FakeScanThread:
        def __init__(self, interval_ms=15000):
            self.interval_ms = interval_ms
            self.devices_changed = Mock()
            self.discovery_state_changed = Mock()
            self.started = False

        def isRunning(self):
            return False

        def start(self):
            self.started = True

    with (
        patch("gui.main_frame._ScanThread", FakeScanThread),
        patch("core.settings_manager.AppSettings") as settings_cls,
    ):
        settings_cls.instance.return_value.get.return_value = 12000
        MainFrame._start_scan_thread(frame)

    frame._scan_thread.devices_changed.connect.assert_called_once_with(frame._schedule_scan_refresh)
    frame.adb_controller.refresh_devices.assert_not_called()
    assert frame._scan_thread.interval_ms == 12000
    assert frame._scan_thread.started is True


def test_adb_bootstrap_pre_starts_bundled_server():
    frame = SimpleNamespace(_adb_bootstrap_finished=Mock())

    with (
        patch("utils.adb_resolver.resolve_adb_path", return_value="C:/tools/adb.exe") as resolve,
        patch("gui.main_frame.CommandRunner.run") as run,
    ):
        MainFrame._bootstrap_adb_async(frame)
        frame._adb_bootstrap_thread.join(timeout=5)

    resolve.assert_called_once_with()
    run.assert_called_once_with(["C:/tools/adb.exe", "start-server"], timeout=30)
    frame._adb_bootstrap_finished.emit.assert_called_once()


def test_adb_bootstrap_skips_pre_start_when_path_unresolved():
    frame = SimpleNamespace(_adb_bootstrap_finished=Mock())

    with (
        patch("utils.adb_resolver.resolve_adb_path", return_value=None),
        patch("gui.main_frame.CommandRunner.run") as run,
    ):
        MainFrame._bootstrap_adb_async(frame)
        frame._adb_bootstrap_thread.join(timeout=5)

    run.assert_not_called()
    frame._adb_bootstrap_finished.emit.assert_called_once()


def test_main_frame_init_defers_adb_bootstrap_until_ui_is_built():
    _app = QApplication.instance() or QApplication([])
    created = {}

    def fake_bootstrap(self):
        created["central_widget_ready"] = self._central_widget is not None
        created["scan_thread"] = self._scan_thread

    fake_log_panel = QWidget()
    fake_log_panel._append_log = Mock()
    fake_side_panel = QWidget()
    fake_side_panel.device_widget = QWidget()
    fake_side_panel.signals = Mock()
    fake_side_panel.selected_devices_changed = Mock()
    fake_side_panel.apply_device_theme = Mock()
    fake_side_panel.update_device_list = Mock()
    fake_side_panel.refresh_device_choices = Mock()
    fake_side_panel.set_restricted_width_mode = Mock()
    fake_side_panel.responsive_layout_settled = Mock()
    fake_side_panel.on_recording_finished = Mock()
    fake_side_panel.on_recording_target_finished = Mock()
    fake_side_panel.on_monkey_target_finished = Mock()
    fake_side_panel.on_operation_completed = Mock()
    fake_side_panel.update_current_package = Mock()
    fake_side_panel.current_package_text = Mock(return_value="")
    fake_side_panel.selected_devices = []

    with (
        patch("gui.main_frame.LogService"),
        patch("gui.main_frame.LogPanel", return_value=fake_log_panel),
        patch("gui.main_frame.SidePanel") as side_panel_cls,
        patch("gui.main_frame.ADBController") as controller_cls,
        patch("gui.main_frame.resource_path", return_value=""),
        patch("gui.main_frame.MainFrame._bootstrap_adb_async", fake_bootstrap),
        patch("utils.adb_resolver.resolve_adb_path") as resolve,
    ):
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
    frame._refresh_always_on_top_button = lambda: MainFrame._refresh_always_on_top_button(frame)

    with patch("gui.main_frame_toolbar.get_themed_icon", return_value=QIcon()) as themed_icon:
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
    frame._refresh_always_on_top_button = lambda: MainFrame._refresh_always_on_top_button(frame)

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = settings_cls.instance.return_value
        MainFrame.set_always_on_top(frame, True)

    assert frame._always_on_top is True
    frame._set_always_on_top_native.assert_called_once_with(True)
    frame._apply_window_flags.assert_not_called()
    frame.setWindowFlags.assert_not_called()
    frame.show.assert_not_called()
    settings.set.assert_called_once_with("always_on_top", True)
    assert button.toolTip() == "Allow other windows above the main window"
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
    frame._refresh_always_on_top_button = lambda: MainFrame._refresh_always_on_top_button(frame)

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = settings_cls.instance.return_value
        MainFrame.set_always_on_top(frame, True)

    frame._set_always_on_top_native.assert_called_once_with(True)
    frame._apply_window_flags.assert_not_called()
    frame.show.assert_not_called()
    settings.set.assert_called_once_with("always_on_top", True)
    assert button.property("iconName") == "push-pin-slash.svg"


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

    assert len(signal_map) == 72
    assert (lp.connect_requested, ac.connect_device) in signal_map
    assert (lp.open_deep_link_requested, ac.open_deep_link) in signal_map
    assert (lp.disable_app_requested, ac.disable_app) in signal_map
    assert (
        lp.disable_app_for_user_requested,
        ac.disable_app_for_user,
    ) in signal_map
    assert (lp.dumpsys_battery_requested, ac.dumpsys_battery) in signal_map
    assert (lp.screen_record_batch_requested, ac.start_screen_record) in signal_map
    assert (lp.start_monkey_batch_requested, ac.run_monkey_test) in signal_map
    assert (lp.top_snapshot_requested, ac.top_snapshot) in signal_map
    assert (lp.gfxinfo_requested, ac.gfxinfo) in signal_map
    assert (lp.wakelocks_requested, ac.wakelocks) in signal_map
    assert (lp.netstats_detail_requested, ac.netstats_detail) in signal_map
    assert (lp.dumpsys_service_requested, ac.dumpsys_service) in signal_map
    assert (lp.kernel_version_requested, ac.kernel_version) in signal_map
    assert (lp.cpu_info_requested, ac.cpu_info) in signal_map
    assert (lp.stop_screen_record_batch_requested, ac.stop_screen_record) in signal_map
    assert (lp.kill_monkey_batch_requested, ac.kill_monkey) in signal_map
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
    frame._panel_splitter.sizes.side_effect = [[300, 700], [320, 680], [320, 680]]
    frame._pending_panel_sizes = None
    frame._panel_size_save_timer = Mock()
    frame.left_panel = SimpleNamespace(request_responsive_reflow=Mock())
    frame.SPLITTER_SAVE_DEBOUNCE_MS = 20

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = Mock()
        settings_cls.instance.return_value = settings

        MainFrame._on_splitter_moved(frame, 0, 0)
        MainFrame._on_splitter_moved(frame, 0, 0)
        MainFrame._save_pending_panel_sizes(frame)

    assert frame._panel_size_save_timer.start.call_args_list == [call(20), call(20)]
    assert frame.left_panel.request_responsive_reflow.call_args_list == [
        call(ReflowReason.SPLITTER),
        call(ReflowReason.SPLITTER),
    ]
    assert settings.set.call_args_list == [
        call("left_panel_width", 320),
        call("right_panel_width", 680),
        call("panel_split_ratio", 0.32),
    ]
