# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import os
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import SmoothScrollArea

from core.exec import CREATE_NEW_CONSOLE
from gui.main_frame import MainFrame, _ScanThread
from gui.pages.workspace_features import WorkspaceRoute


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
    def __init__(self, output: str, return_code: int = 0):
        self._output = output
        self._return_code = return_code

    def poll(self):
        return self._return_code

    def communicate(self):
        return self._output, ""


class _FakeScanRunner:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.started = []
        self.stopped = []

    def start(self, key, cmd, **kwargs):
        self.started.append(cmd)
        result = self._outputs.pop(0) if self._outputs else ""
        if isinstance(result, tuple):
            output, return_code = result
            return _FakeScanProc(output, return_code)
        return _FakeScanProc(result)

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


def test_scan_thread_republishes_same_snapshot_after_unavailable():
    _app = QApplication.instance() or QApplication([])
    thread = _ScanThread(interval_ms=3000)
    emitted_devices = []
    emitted_states = []
    sleeps = {"count": 0}
    thread.devices_changed.connect(emitted_devices.append)
    thread.discovery_state_changed.connect(emitted_states.append)
    runner = _FakeScanRunner(
        [
            "List of devices attached\ndevice-a\tdevice\n",
            ("adb failed", 1),
            "List of devices attached\ndevice-a\tdevice\n",
        ]
    )

    def stop_after_three_polls(_ms):
        sleeps["count"] += 1
        if sleeps["count"] >= 90:
            thread._stop_flag = True

    with (
        patch("gui.main_frame.CommandRunner.active_count", return_value=0),
        patch("gui.main_frame.ProcessRunner", return_value=runner),
        patch.object(_ScanThread, "msleep", side_effect=stop_after_three_polls),
    ):
        thread.run()

    # 成功状态由对应设备快照在主线程发布，避免状态先于列表更新；
    # 从 unavailable 恢复时即使集合未变，也必须重发快照恢复界面。
    assert emitted_devices == [["device-a"], ["device-a"]]
    assert emitted_states == ["unavailable"]


def test_scan_thread_republishes_same_snapshot_after_external_invalidation():
    _app = QApplication.instance() or QApplication([])
    thread = _ScanThread(interval_ms=3000)
    emitted_devices = []
    sleeps = {"count": 0}
    thread.devices_changed.connect(emitted_devices.append)
    runner = _FakeScanRunner(
        [
            "List of devices attached\ndevice-a\tdevice\n",
            "List of devices attached\ndevice-a\tdevice\n",
        ]
    )

    def invalidate_before_second_poll(_ms):
        sleeps["count"] += 1
        if sleeps["count"] == 1:
            thread.invalidate_snapshot()
        if sleeps["count"] >= 60:
            thread._stop_flag = True

    with (
        patch("gui.main_frame.CommandRunner.active_count", return_value=0),
        patch("gui.main_frame.ProcessRunner", return_value=runner),
        patch.object(_ScanThread, "msleep", side_effect=invalidate_before_second_poll),
    ):
        thread.run()

    assert emitted_devices == [["device-a"], ["device-a"]]


def test_scan_thread_treats_nonzero_adb_exit_as_unavailable():
    thread = _ScanThread()
    runner = _FakeScanRunner([("List of devices attached\n", 1)])

    output = thread._run_devices_scan(runner)

    assert output is None


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
    fake_side_panel.device_discovery_state_changed = Mock()
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
    fake_side_panel._tab_scroll_areas = {}
    fake_side_panel._apps_tab = SimpleNamespace(
        panel_header=QWidget(),
        apps_status_badge=QWidget(),
        category_stack=Mock(),
    )
    fake_side_panel._advanced_tab = SimpleNamespace(
        panel_header=QWidget(),
        system_status_badge=QWidget(),
        category_stack=Mock(),
    )
    fake_side_panel._scrcpy_tab = SimpleNamespace(
        panel_header=QWidget(),
        remote_status_badge=QWidget(),
        category_stack=Mock(),
        set_workspace_device=Mock(side_effect=lambda device_id: device_id),
        apply_responsive_width=Mock(),
    )

    def ensure_feature_page(index):
        scroll = SmoothScrollArea()
        scroll.setWidget(QWidget())
        fake_side_panel._tab_scroll_areas[index] = scroll
        return Mock()

    fake_side_panel._ensure_tab_loaded = ensure_feature_page

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
    assert frame._continuous_scan_enabled is True


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
    assert frame._continuous_scan_enabled is False


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


def test_main_frame_disabling_continuous_scan_releases_scanning_state():
    panel = SimpleNamespace(
        _device_discovery_state="scanning",
        _connected_device_cache=["device-1"],
        set_device_discovery_state=Mock(),
    )
    frame = SimpleNamespace(
        left_panel=panel,
        _start_scan_thread=Mock(),
        _stop_scan_thread=Mock(),
    )

    MainFrame.set_continuous_scan(frame, False)

    assert frame._continuous_scan_enabled is False
    frame._stop_scan_thread.assert_called_once_with()
    panel.set_device_discovery_state.assert_called_once_with("ready")


def test_scan_thread_finish_restarts_after_fast_disable_enable_toggle():
    scan_thread = Mock()
    frame = SimpleNamespace(
        _scan_thread=scan_thread,
        _continuous_scan_enabled=True,
        _closing=False,
        _start_scan_thread=Mock(),
    )

    MainFrame._on_scan_thread_finished(frame, scan_thread)

    assert frame._scan_thread is None
    frame._start_scan_thread.assert_called_once_with()


def test_main_frame_device_selection_updates_home_action_cards():
    cards = {key: Mock() for key in ("app_mgr", "file_explorer", "logcat", "performance")}
    frame = SimpleNamespace(
        left_panel=SimpleNamespace(selected_devices=["device-1"]),
        _home_page=SimpleNamespace(tool_cards=cards),
        _sync_device_context=Mock(),
    )

    MainFrame._update_device_actions(frame)

    assert all(cards[key].setEnabled.call_args.args == (True,) for key in cards)
    frame._sync_device_context.assert_called_once_with()


def test_main_frame_keeps_home_feature_cards_openable_without_device():
    cards = {key: Mock() for key in ("app_mgr", "file_explorer", "logcat", "performance")}
    frame = SimpleNamespace(
        left_panel=SimpleNamespace(selected_devices=[]),
        _home_page=SimpleNamespace(tool_cards=cards),
        _sync_device_context=Mock(),
    )

    MainFrame._update_device_actions(frame)

    for card in cards.values():
        card.setEnabled.assert_called_once_with(True)
        card.setToolTip.assert_called_once_with("打开后可前往设备页选择操作设备")
    frame._sync_device_context.assert_called_once_with()


def test_main_frame_workspace_route_is_forwarded_without_top_level_window():
    page = Mock()
    page.supports_route.return_value = True
    events = []
    page.open_route.side_effect = lambda route: events.append(("open", route)) or True
    switch_to = Mock(side_effect=lambda target: events.append(("switch", target)))
    frame = SimpleNamespace(
        _pending_workspace_route=WorkspaceRoute("devices", "files"),
        _workspace_pages={"system": page},
        switchTo=switch_to,
        log_service=Mock(),
    )

    assert MainFrame._open_workspace_feature(
        frame,
        "system",
        "performance",
        device_id="device-1",
        payload={"package_name": "com.example.app"},
    )

    route = WorkspaceRoute(
        "system",
        "performance",
        "device-1",
        {"package_name": "com.example.app"},
    )
    switch_to.assert_called_once_with(page)
    page.open_route.assert_called_once_with(route)
    assert events == [("open", route), ("switch", page)]
    assert frame._pending_workspace_route is None


def test_main_frame_unknown_workspace_route_does_not_switch_page():
    page = Mock()
    page.supports_route.return_value = False
    frame = SimpleNamespace(
        _pending_workspace_route=None,
        _workspace_pages={"system": page},
        switchTo=Mock(),
        log_service=Mock(),
    )

    assert not MainFrame._open_workspace_feature(frame, "system", "missing")
    frame.switchTo.assert_not_called()
    page.open_route.assert_not_called()
    frame.log_service.log.assert_called_once_with(
        "WARNING",
        "Unknown workspace route: system/missing",
    )


def test_main_frame_syncs_device_context_to_every_task_page():
    home = Mock()
    pages = {key: Mock() for key in ("devices", "apps", "system")}
    frame = SimpleNamespace(
        left_panel=SimpleNamespace(
            selected_devices=["device-1"],
            _connected_device_cache=["device-1", "device-2"],
            _device_discovery_state="ready",
        ),
        _home_page=home,
        _workspace_pages=pages,
    )

    MainFrame._sync_device_context(frame)

    expected = (["device-1"], ["device-1", "device-2"], "ready")
    home.set_device_context.assert_called_once_with(*expected)
    for page in pages.values():
        page.set_device_context.assert_called_once_with(*expected)


def test_main_frame_always_on_top_updates_state_without_recreating_window_when_native_fails():
    _app = QApplication.instance() or QApplication([])
    frame = SimpleNamespace()
    frame._always_on_top = False
    frame._set_always_on_top_native = Mock(return_value=False)
    frame._apply_window_flags = Mock()
    frame.setWindowFlags = Mock()
    frame.show = Mock()
    pin_card = Mock()
    pin_card.isChecked.return_value = False
    frame._settings_page = SimpleNamespace(pin_card=pin_card)
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
    pin_card.setChecked.assert_called_once_with(True)


def test_main_frame_always_on_top_native_path_does_not_recreate_window():
    _app = QApplication.instance() or QApplication([])
    frame = SimpleNamespace()
    frame._always_on_top = False
    frame._set_always_on_top_native = Mock(return_value=True)
    frame._apply_window_flags = Mock()
    frame.show = Mock()
    pin_card = Mock()
    pin_card.isChecked.return_value = False
    frame._settings_page = SimpleNamespace(pin_card=pin_card)
    frame._refresh_always_on_top_button = lambda: MainFrame._refresh_always_on_top_button(frame)

    with patch("core.settings_manager.AppSettings") as settings_cls:
        settings = settings_cls.instance.return_value
        MainFrame.set_always_on_top(frame, True)

    frame._set_always_on_top_native.assert_called_once_with(True)
    frame._apply_window_flags.assert_not_called()
    frame.show.assert_not_called()
    settings.set.assert_called_once_with("always_on_top", True)
    pin_card.setChecked.assert_called_once_with(True)


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


def test_manual_refresh_failure_invalidates_continuous_scan_snapshot():
    frame = SimpleNamespace(
        left_panel=Mock(),
        _task_history=None,
        _task_page=None,
        _scan_thread=Mock(),
    )

    with patch("gui.main_frame.QTimer.singleShot") as single_shot:
        MainFrame._on_operation_completed(frame, "refresh", False, "adb unavailable")

    frame._scan_thread.invalidate_snapshot.assert_called_once_with()
    single_shot.assert_called_once()


def test_main_frame_device_refresh_uses_side_panel_state_owner():
    frame = SimpleNamespace(left_panel=Mock())

    MainFrame._request_device_refresh(frame)

    frame.left_panel.request_device_refresh.assert_called_once_with()
    frame.left_panel.signals.refresh_devices_requested.emit.assert_not_called()
