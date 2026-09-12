"""ADB 运行实例的 Qt 延迟启动、扫描、展示和资源收口验证。"""

import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QPoint
from PySide6.QtWidgets import QWidget

from adblab.presentation.qt_adb_runtime import QtAdbRuntime
from core import adb_transport
from core import exec as execution
from core.adb_runtime import AdbRuntime, RuntimeSnapshot
from core.settings_manager import DEFAULTS, AppSettings
from gui.i18n import install_translators
from gui.main_frame import MainFrame, _ScanThread
from gui.pages.fluent_pages import SettingsPage
from gui.styles import BaseStyles
from gui.widgets.adb_client_card import AdbClientSettingCard
from services.adb_clients import ERROR_MISSING, ClientProbe
from tests.ui_geometry_helpers import wait_for_stable_geometry
from utils.adb_resolver import AdbCandidate


def test_adapter_defers_resolution_and_cancels_before_event_loop(monkeypatch):
    resolver = Mock(return_value=None)
    monkeypatch.setattr("adblab.presentation.qt_adb_runtime.resolve_adb_path", resolver)
    owner = QObject()
    adapter = QtAdbRuntime(owner)
    adapter.schedule()
    resolver.assert_not_called()
    adapter.prepare_shutdown()
    QCoreApplication.processEvents()
    resolver.assert_not_called()
    adapter.close()
    assert adapter.runtime.wait(1)


def test_adapter_publishes_ready_on_gui_thread_and_releases_runtime(monkeypatch):
    monkeypatch.setattr("adblab.presentation.qt_adb_runtime.resolve_adb_path", lambda: None)
    adapter = QtAdbRuntime()
    delivered = []
    adapter.ready.connect(lambda: delivered.append(threading.get_ident()))
    adapter.schedule()
    QCoreApplication.processEvents()
    assert adapter.runtime.wait(2)
    QCoreApplication.processEvents()
    assert delivered == [threading.get_ident()]
    assert execution.adb_runtime() is adapter.runtime
    adapter.close()
    assert execution.adb_runtime() is None


def test_adapter_queued_notification_keeps_latest_manual_selection(monkeypatch):
    adapter = QtAdbRuntime()
    monkeypatch.setattr(adapter.runtime, "start", lambda **_kwargs: False)
    delivered = []
    adapter.changed.connect(
        lambda snapshot: delivered.append((snapshot.native_only, threading.get_ident()))
    )
    worker = threading.Thread(target=lambda: adapter.runtime.set_native_only(True))
    try:
        worker.start()
        worker.join(1)
        assert not worker.is_alive()
        assert delivered == []

        adapter.set_native_only(False)
        assert delivered == [(False, threading.get_ident())]
        QCoreApplication.processEvents()
        assert all(value == (False, threading.get_ident()) for value in delivered)
    finally:
        adapter.close()
        worker.join(1)


@pytest.mark.parametrize("shutdown", ["prepare_shutdown", "close"])
def test_adapter_discards_queued_notification_after_shutdown(shutdown):
    adapter = QtAdbRuntime()
    delivered = []
    adapter.changed.connect(delivered.append)
    worker = threading.Thread(target=lambda: adapter.runtime.set_native_only(True))
    try:
        worker.start()
        worker.join(1)
        assert not worker.is_alive()
        getattr(adapter, shutdown)()
        QCoreApplication.processEvents()
        assert delivered == []
    finally:
        adapter.close()
        worker.join(1)


def test_adapter_recheck_explicitly_requests_automatic_reselection(monkeypatch):
    monkeypatch.setattr("adblab.presentation.qt_adb_runtime.resolve_adb_path", lambda: None)
    adapter = QtAdbRuntime()
    recheck = Mock(return_value=True)
    monkeypatch.setattr(adapter.runtime, "recheck", recheck)
    try:
        adapter.recheck()
        recheck.assert_called_once_with()
    finally:
        adapter.close()


def test_adapter_selection_mode_is_forwarded_without_touching_requests(monkeypatch):
    """执行模式切换只影响后续命令：透传给运行实例并刷新快照。"""

    monkeypatch.setattr("adblab.presentation.qt_adb_runtime.resolve_adb_path", lambda: None)
    adapter = QtAdbRuntime()
    published: list[object] = []
    adapter.changed.connect(published.append)
    try:
        adapter.set_selection_mode("native")
        assert adapter.runtime.selection_mode == "native"
        adapter.set_selection_mode("fast")
        assert adapter.runtime.selection_mode == "fast"
        adapter.set_selection_mode("auto")
        assert adapter.runtime.selection_mode == "auto"
        assert published
    finally:
        adapter.close()


def test_adapter_recheck_invalidates_path_caches_before_reselection(monkeypatch):
    """重新检测必须先清解析缓存，否则安装或移除 platform-tools 后仍用旧路径。"""

    calls: list[str] = []
    monkeypatch.setattr("adblab.presentation.qt_adb_runtime.resolve_adb_path", lambda: None)
    monkeypatch.setattr(
        "adblab.presentation.qt_adb_runtime.invalidate_adb_path_cache",
        lambda: calls.append("resolver"),
    )
    monkeypatch.setattr(
        "adblab.presentation.qt_adb_runtime.reset_adb_program_cache",
        lambda: calls.append("program"),
    )
    adapter = QtAdbRuntime()
    monkeypatch.setattr(adapter.runtime, "recheck", lambda: calls.append("recheck") or True)
    try:
        adapter.recheck()
        assert calls == ["resolver", "program", "recheck"]
    finally:
        adapter.close()


def test_main_frame_projects_initial_native_scope_without_selecting_manual_native(monkeypatch):
    monkeypatch.setattr("adblab.presentation.qt_adb_runtime.resolve_adb_path", lambda: None)
    frame = QWidget()
    frame._closing = False
    frame._always_on_top = False
    frame.set_always_on_top = Mock()
    frame.set_continuous_scan = Mock()
    frame.left_panel = SimpleNamespace(signals=SimpleNamespace(restart_adb_requested=Mock()))
    frame.recheck_adb_environment = Mock()
    frame.set_adb_native_only = lambda enabled: MainFrame.set_adb_native_only(frame, enabled)
    frame.set_adb_selection_mode = lambda mode: MainFrame.set_adb_selection_mode(frame, mode)
    frame._start_device_discovery = Mock()
    frame._log_adb_environment = Mock()
    frame._update_adb_environment = lambda snapshot: MainFrame._update_adb_environment(
        frame, snapshot,
    )
    frame._settings_page = SettingsPage(frame, frame)
    try:
        MainFrame._bootstrap_adb_async(frame)
        assert frame._settings_page.adb_check_card.mode() == "auto"
        # 无可用客户端时执行范围仍是原生，但模式保持自动、不伪装成用户手动选择。
        assert "设备列表：原生 ADB" in frame._settings_page.adb_check_card.contentLabel.text()
        assert frame._adb_environment.snapshot().selection_mode == "auto"
        assert not frame._adb_environment.snapshot().native_only
        QCoreApplication.processEvents()
        assert frame._adb_environment.runtime.wait(2)
        QCoreApplication.processEvents()
        frame._start_device_discovery.assert_called_once_with()
    finally:
        frame._adb_environment.close()
        frame.close()


def test_settings_unavailable_fast_choice_can_be_switched_to_manual_native(
    monkeypatch, qt_application,
):
    adapter = QtAdbRuntime()
    monkeypatch.setattr(adapter.runtime, "start", lambda **_kwargs: False)
    frame = SimpleNamespace(
        _always_on_top=False,
        set_always_on_top=Mock(),
        set_continuous_scan=Mock(),
        left_panel=SimpleNamespace(signals=SimpleNamespace(restart_adb_requested=Mock())),
        recheck_adb_environment=Mock(),
        set_adb_selection_mode=adapter.set_selection_mode,
    )
    page = SettingsPage(frame)
    adapter.changed.connect(page.update_adb_environment)
    modes = []
    page.adb_check_card.mode_requested.connect(modes.append)
    try:
        page.resize(900, 640)
        page.show()
        page.update_adb_environment(adapter.snapshot())
        assert page.adb_check_card.mode() == "auto"
        assert adapter.snapshot().selection_mode == "auto"

        fast = page.adb_check_card.mode_button("fast")
        page.ensureWidgetVisible(fast, 0, 0)
        wait_for_stable_geometry(qt_application, (page, page.adb_check_card, fast))
        assert fast.isVisibleTo(page)
        fast.click()
        qt_application.processEvents()
        assert adapter.snapshot().selection_mode == "fast"
        assert page.adb_check_card.mode() == "fast"
        assert "手动快速" in page.adb_check_card.contentLabel.text()
        # 手动快速但能力未验证时，界面必须写明实际仍走原生通道。
        assert "设备列表：原生 ADB" in page.adb_check_card.contentLabel.text()

        page.adb_check_card.mode_button("native").click()
        qt_application.processEvents()
        assert adapter.snapshot().selection_mode == "native"
        assert page.adb_check_card.mode() == "native"
        assert "手动原生" in page.adb_check_card.contentLabel.text()
        assert modes == ["fast", "native"]
    finally:
        adapter.close()
        page.close()


def test_fast_scan_runs_while_other_commands_are_busy(monkeypatch):
    runtime = Mock()
    runtime.can_scan_fast.return_value = True
    runtime.wait_for_device_check.return_value = None
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)
    monkeypatch.setattr(execution.CommandRunner, "active_count", lambda: 1)
    thread = _ScanThread()
    snapshots = []
    thread.devices_changed.connect(snapshots.append)
    run = Mock(return_value=execution.CommandResult(True, "List of devices attached\nfake\tdevice"))
    monkeypatch.setattr(execution.CommandRunner, "run", run)
    monkeypatch.setattr(thread, "_sleep_interruptibly", lambda _: True)
    native = Mock()
    monkeypatch.setattr("gui.main_frame.ProcessRunner", native)
    thread.run()
    assert snapshots == [["fake"]]
    assert run.call_args.args[0] == ["adb", "devices", "-l"]
    assert not run.call_args.kwargs["cancelled"]()
    thread.stop()
    assert run.call_args.kwargs["cancelled"]()
    native.assert_not_called()


@pytest.mark.parametrize("completion", ["ready", "native", "stop", "timeout", "close"])
def test_scan_waits_for_host_without_opening_another_native_client(monkeypatch, completion):
    for key in (
        "ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    runtime = AdbRuntime(lambda: "C:/test/adb.exe")
    runtime._path = "C:/test/adb.exe"
    runtime._checking = True
    waiting = threading.Event()
    original_wait = runtime._condition.wait

    def wait(timeout):
        waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(runtime._condition, "wait", wait)
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)
    monkeypatch.setattr(execution.CommandRunner, "active_count", lambda: 0)
    fast = Mock(return_value=execution.CommandResult(True, "List of devices attached"))
    monkeypatch.setattr(execution.CommandRunner, "run", fast)
    native = Mock(return_value="List of devices attached")
    monkeypatch.setattr("gui.main_frame.ProcessRunner", Mock())
    scan = _ScanThread()
    monkeypatch.setattr(scan, "_run_devices_scan", native)
    monkeypatch.setattr(scan, "_sleep_interruptibly", lambda _: True)
    if completion == "timeout":
        scan.SCAN_CALL_TIMEOUT_S = 0.05
    worker = threading.Thread(target=scan.run)
    try:
        worker.start()
        assert waiting.wait(1), "scanner started native devices before host verification"
        native.assert_not_called()
        fast.assert_not_called()
        if completion == "ready":
            with runtime._condition:
                runtime._host.available = True
                runtime._condition.notify_all()
        elif completion == "native":
            runtime.set_mode("native")
        elif completion == "stop":
            scan.stop()
        elif completion == "close":
            runtime.close()
        worker.join(1)
        assert not worker.is_alive()
        if completion == "ready":
            fast.assert_called_once()
            assert 0 < fast.call_args.kwargs["timeout"] <= scan.SCAN_CALL_TIMEOUT_S
            native.assert_not_called()
        elif completion == "native":
            native.assert_called_once()
            fast.assert_not_called()
        else:
            native.assert_not_called()
            fast.assert_not_called()
    finally:
        scan.stop()
        runtime.close()
        worker.join(1)


@pytest.mark.parametrize("wait_seconds", [12.0, 16.0])
def test_scan_admission_and_native_process_share_one_deadline(monkeypatch, wait_seconds):
    clock = [100.0]
    monkeypatch.setattr("gui.main_frame.time", SimpleNamespace(monotonic=lambda: clock[0]))
    runtime = Mock()
    runtime.can_scan_fast.return_value = False

    def wait_for_device_check(timeout, cancelled):
        assert timeout == 15
        assert not cancelled()
        clock[0] += wait_seconds
        return None

    runtime.wait_for_device_check.side_effect = wait_for_device_check
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)
    monkeypatch.setattr(execution.CommandRunner, "active_count", lambda: 0)
    proc = Mock()
    proc.poll.return_value = None
    runner = Mock()
    runner.start.return_value = proc
    monkeypatch.setattr("gui.main_frame.ProcessRunner", lambda: runner)
    scan = _ScanThread()
    monkeypatch.setattr(scan, "_sleep_interruptibly", lambda _: True)
    monkeypatch.setattr(scan, "msleep", lambda ms: clock.__setitem__(0, clock[0] + ms / 1000))
    scan.run()
    runtime.wait_for_device_check.assert_called_once()
    if wait_seconds < 15:
        runner.start.assert_called_once()
        runner.stop.assert_called_once_with("device_scan", timeout=2.0)
        assert clock[0] == pytest.approx(115, abs=0.11)
    else:
        runner.start.assert_not_called()


@pytest.mark.parametrize("busy", [False, True])
def test_scan_requests_recovery_before_busy_gate_or_failed_native_scan(monkeypatch, busy):
    runtime = Mock()
    runtime.can_scan_fast.return_value = False
    runtime.wait_for_device_check.return_value = None
    events = []
    runtime.request_device_check.side_effect = lambda: events.append("check")
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)

    def active_count():
        events.append("busy")
        return int(busy)

    monkeypatch.setattr(execution.CommandRunner, "active_count", active_count)
    thread = _ScanThread()

    def failed_scan(_runner, *, deadline):
        events.append("native")
        return None

    monkeypatch.setattr(thread, "_run_devices_scan", failed_scan)
    monkeypatch.setattr(thread, "_sleep_interruptibly", lambda _: True)
    states = []
    thread.discovery_state_changed.connect(states.append)
    thread.run()

    assert events == (["check", "busy"] if busy else ["check", "busy", "native"])
    assert states == ([] if busy else ["unavailable"])
    runtime.request_device_check.assert_called_once()


def test_socket_wait_is_actually_cancellable_and_closes_connection(monkeypatch):
    local, peer = socket.socketpair()
    stop, entered = threading.Event(), threading.Event()
    monkeypatch.setattr(adb_transport.socket, "create_connection", lambda *a, **k: local)
    result = []

    def worker():
        entered.set()
        result.append(
            adb_transport.capture("devices", [], serial=None, timeout=10, cancelled=stop.is_set)
        )

    thread = threading.Thread(target=worker)
    try:
        thread.start()
        assert entered.wait(1)
        peer.settimeout(1)
        assert peer.recv(1024)
        stop.set()
        thread.join(1)
        assert not thread.is_alive()
        assert result[0].kind == "cancelled"
        assert peer.recv(1) == b""
    finally:
        stop.set()
        local.close()
        peer.close()
        thread.join(1)


def test_adb_client_card_lists_only_configured_sources(qt_application):
    """未配置的来源不占位；配置之后同一张卡能动态补上该行。"""

    card = AdbClientSettingCard()
    try:
        card.set_candidates([AdbCandidate("bundled", "C:/bundle/adb.exe")])
        assert card.client_button("bundled") is not None
        assert card.client_button("env") is None

        card.set_candidates([
            AdbCandidate("bundled", "C:/bundle/adb.exe"),
            AdbCandidate("env", "C:/env/adb.exe"),
        ])
        assert card.client_button("env") is not None
    finally:
        card.close()


def test_adb_client_card_detection_finishes_and_unlocks_actions(qt_application):
    """回归：识别完成后必须退出忙态，标题回到当前选择且控件可用。"""

    card = AdbClientSettingCard()
    try:
        card.set_busy(True)
        assert "正在识别" in card.card.contentLabel.text()

        card.apply_probes([
            ClientProbe(
                "bundled", "C:/bundle/adb.exe", True, executable=True,
                version="1.0.41 (37.0.0)",
            ),
        ])

        assert card.card.contentLabel.text() == "自动选择"
        assert card.rescan_button().isEnabled()
        assert card.choose_button().isEnabled()
        assert card.client_button("bundled").isEnabled()

        # 忙态复位后必须可以再次识别，否则按钮变成一次性入口。
        card.set_busy(True)
        card.apply_probes([])
        assert card.rescan_button().isEnabled()
    finally:
        card.close()


def test_adb_client_card_detection_timeout_exits_busy(qt_application):
    """超时兜底：识别未回填也要退出忙态并提示可重试。"""

    card = AdbClientSettingCard()
    try:
        card.set_busy(True)
        card._on_detection_timeout()

        assert "识别超时" in card.card.contentLabel.text()
        assert card.rescan_button().isEnabled()
        assert card.choose_button().isEnabled()
    finally:
        card.close()


def test_adb_client_selection_applies_preference_and_rechecks(monkeypatch, qt_application):
    """选择候选客户端后写配置、清两层路径缓存并重新检测执行环境。"""

    calls = []
    for name in (
        "set_client_preference", "invalidate_adb_path_cache",
        "reset_adb_program_cache", "clear_client_probe_cache",
    ):
        monkeypatch.setattr(
            f"gui.pages.fluent_pages.{name}",
            lambda *_args, _name=name: calls.append(_name),
        )
    writes = []
    values = {"adb_client": "auto"}
    settings = SimpleNamespace(
        get=values.get,
        set=lambda key, value: (values.__setitem__(key, value), writes.append((key, value))),
    )
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    frame = SimpleNamespace(
        _always_on_top=False,
        set_always_on_top=Mock(),
        set_continuous_scan=Mock(),
        left_panel=SimpleNamespace(signals=SimpleNamespace(restart_adb_requested=Mock())),
        recheck_adb_environment=Mock(),
        set_adb_selection_mode=Mock(),
    )
    page = SettingsPage(frame)
    try:
        page._apply_adb_client("sdk_home")

        assert writes == [("adb_client", "sdk_home")]
        assert values["adb_client"] == "sdk_home"
        assert calls[0] == "set_client_preference"
        assert {
            "invalidate_adb_path_cache", "reset_adb_program_cache", "clear_client_probe_cache",
        } <= set(calls)
        frame.recheck_adb_environment.assert_called_once_with()
        assert page.adb_client_card.selection() == "sdk_home"
    finally:
        page.close()


def test_adb_client_card_keeps_unusable_candidates_with_reason(qt_application):
    """识别结果回填：可用项可选中并显示版本，不可用项保留并给出原因。"""

    card = AdbClientSettingCard()
    try:
        # 行按实际配置的来源生成，这里显式给出两个来源再回填识别结果。
        card.set_candidates([
            AdbCandidate("bundled", "C:/bundle/adb.exe"),
            AdbCandidate("env", "C:/env/adb.exe"),
        ])
        card.apply_probes([
            ClientProbe(
                "bundled", "C:/bundle/adb.exe", True, executable=True,
                version="1.0.41 (37.0.0)",
            ),
            ClientProbe("env", "C:/env/adb.exe", False, error=ERROR_MISSING),
        ])

        assert card.client_button("bundled").isEnabled()
        assert "1.0.41 (37.0.0)" in card.detail_text("bundled")
        assert not card.client_button("env").isEnabled()
        assert "未设置或文件不存在" in card.detail_text("env")
        # 未配置的来源直接不占位，不再出现"未设置"噪音行。
        assert card.client_button("PATH") is None
    finally:
        card.close()


def test_settings_reports_partial_acceleration_and_session_override():
    frame = SimpleNamespace(
        _always_on_top=False,
        set_always_on_top=Mock(),
        set_continuous_scan=Mock(),
        left_panel=SimpleNamespace(signals=SimpleNamespace(restart_adb_requested=Mock())),
        recheck_adb_environment=Mock(),
        set_adb_selection_mode=Mock(),
    )
    parent = QWidget()
    page = SettingsPage(frame, parent)
    try:
        page.update_adb_environment(RuntimeSnapshot(True, True, False, True, 2, 2))
        assert "2" in page.adb_check_card.contentLabel.text()
        assert not page.adb_check_card.button.isEnabled()
        page.update_adb_environment(RuntimeSnapshot(False, True, False, True, 2, 2))
        page.adb_check_card.button.click()
        frame.recheck_adb_environment.assert_called_once()
        page.adb_check_card.mode_button("native").click()
        frame.set_adb_selection_mode.assert_called_with("native")
        page.update_adb_environment(RuntimeSnapshot(False, True, True, False, 0, 2))
        assert "原生" in page.adb_check_card.contentLabel.text()
    finally:
        page.close()


def test_settings_auto_mode_keeps_auto_while_scope_follows_capability():
    """自动模式不因能力变化改写用户选择，只由状态行说明实际执行范围。"""

    frame = SimpleNamespace(
        _always_on_top=False,
        set_always_on_top=Mock(),
        set_continuous_scan=Mock(),
        left_panel=SimpleNamespace(signals=SimpleNamespace(restart_adb_requested=Mock())),
        recheck_adb_environment=Mock(),
        set_adb_selection_mode=Mock(),
    )
    parent = QWidget()
    page = SettingsPage(frame, parent)
    try:
        page.update_adb_environment(RuntimeSnapshot(False, True, False, False, 0, 2))
        assert page.adb_check_card.mode() == "auto"
        assert "设备列表：原生 ADB" in page.adb_check_card.contentLabel.text()

        page.update_adb_environment(RuntimeSnapshot(False, True, False, True, 1, 2))
        assert page.adb_check_card.mode() == "auto"
        assert "设备列表：快速直连" in page.adb_check_card.contentLabel.text()

        page.update_adb_environment(RuntimeSnapshot(False, False, False, False, 0, 2))
        assert page.adb_check_card.mode() == "auto"
        assert "设备列表：原生 ADB" in page.adb_check_card.contentLabel.text()

        frame.set_adb_selection_mode.assert_not_called()
        page.adb_check_card.mode_button("native").click()
        frame.set_adb_selection_mode.assert_called_once_with("native")
    finally:
        page.close()


@pytest.mark.parametrize(
    ("status", "checking", "available", "expected"),
    [
        ("idle", False, False, "等待"),
        ("checking", True, False, "检查"),
        ("starting_server", True, False, "正在启动本机 ADB 服务"),
        ("retrying", True, False, "恢复"),
        ("ready", False, True, "就绪"),
        ("missing_adb", False, False, "未找到 ADB"),
        ("custom_server", False, False, "自定义"),
        ("host_timeout", False, False, "响应超时"),
        ("host_unavailable", False, False, "服务不可用"),
        ("host_protocol", False, False, "协议"),
        ("host_transport", False, False, "通信异常"),
        ("shell_unavailable", False, True, "Shell 未通过验证"),
    ],
)
def test_settings_explains_detection_status(status, checking, available, expected):
    frame = SimpleNamespace(
        _always_on_top=False,
        set_always_on_top=Mock(),
        set_continuous_scan=Mock(),
        left_panel=SimpleNamespace(signals=SimpleNamespace(restart_adb_requested=Mock())),
        recheck_adb_environment=Mock(),
        set_adb_selection_mode=Mock(),
    )
    parent = QWidget()
    page = SettingsPage(frame, parent)
    snapshot = RuntimeSnapshot(
        checking=checking, available=available, native_only=False,
        fast_devices=False, fast_shell_devices=0, checked_devices=0,
        selection_mode="auto", status=status,
    )
    try:
        page.update_adb_environment(snapshot)
        content = page.adb_check_card.contentLabel.text()
        assert expected in content
        assert "自动选择" in content
        assert "原生 ADB" in content
        assert page.adb_check_card.button.isEnabled() is not checking
        frame.set_adb_selection_mode.assert_not_called()
    finally:
        page.close()


@pytest.mark.parametrize(
    ("mode", "native_only", "fast_devices", "fast_count", "label"),
    [("native", True, False, 0, "手动原生"), ("fast", False, True, 2, "手动快速")],
)
def test_settings_distinguishes_manual_mode_from_effective_scope(
    mode, native_only, fast_devices, fast_count, label,
):
    frame = SimpleNamespace(
        _always_on_top=False,
        set_always_on_top=Mock(),
        set_continuous_scan=Mock(),
        left_panel=SimpleNamespace(signals=SimpleNamespace(restart_adb_requested=Mock())),
        recheck_adb_environment=Mock(),
        set_adb_selection_mode=Mock(),
    )
    parent = QWidget()
    page = SettingsPage(frame, parent)
    snapshot = RuntimeSnapshot(
        checking=False, available=True, native_only=native_only,
        fast_devices=fast_devices, fast_shell_devices=fast_count, checked_devices=2,
        selection_mode=mode, status="ready",
    )
    try:
        page.update_adb_environment(snapshot)
        content = page.adb_check_card.contentLabel.text()
        assert label in content
        assert page.adb_check_card.mode() == mode
        if fast_devices:
            assert "Shell 2" in content
        else:
            assert "原生 ADB" in content
        frame.set_adb_selection_mode.assert_not_called()
    finally:
        page.close()


@pytest.mark.parametrize(
    ("language", "mode_label", "status", "reason"),
    [
        ("zh_CN", "自动选择", "host_unavailable", "服务不可用"),
        ("zh_HK", "自動選擇", "host_unavailable", "服務無法使用"),
        ("en_US", "Automatic selection", "host_unavailable", "service is unavailable"),
        ("zh_CN", "自动选择", "starting_server", "正在启动本机 ADB 服务"),
        ("zh_HK", "自動選擇", "starting_server", "正在啟動本機 ADB 服務"),
        ("en_US", "Automatic selection", "starting_server", "Starting the local ADB service"),
    ],
)
def test_settings_translated_runtime_status_fits_narrow_large_font_page(
    monkeypatch, qt_application, language, mode_label, status, reason,
):
    values = dict(DEFAULTS, ui_font_size=22, language=language)
    settings = SimpleNamespace(get=values.get)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()
    translators = install_translators(qt_application, language)
    frame = Mock()
    frame._always_on_top = False
    page = SettingsPage(frame)
    try:
        page.resize(420, 640)
        page.show()
        page.update_adb_environment(
            RuntimeSnapshot(status == "starting_server", False, False, False, 0, 0, status=status)
        )
        cards = (page.adb_check_card, page.adb_check_card)
        wait_for_stable_geometry(qt_application, (page, *cards))
        content = page.adb_check_card.contentLabel.text()
        assert mode_label in content
        assert reason in content
        assert page.adb_check_card.button.isEnabled() is (status != "starting_server")
        assert page.horizontalScrollBar().maximum() == 0
        # 执行模式卡在窄屏大字号下也必须保持展开按钮可达。
        expand_button = page.adb_check_card.card.expandButton
        page.ensureWidgetVisible(expand_button, 0, 0)
        qt_application.processEvents()
        assert page.adb_check_card.isVisibleTo(page)
        assert expand_button.isVisibleTo(page)
        for card, control in (
            (page.adb_check_card, page.adb_check_card.button),
        ):
            page.ensureWidgetVisible(control, 0, 0)
            qt_application.processEvents()
            assert card.isVisibleTo(page)
            assert control.isVisibleTo(page)
            for label in (card.titleLabel, card.contentLabel):
                assert label.height() >= label.heightForWidth(label.width())
            point = control.mapTo(card, QPoint())
            assert 0 <= point.x() and point.x() + control.width() <= card.width()
            assert 0 <= point.y() and point.y() + control.height() <= card.height()
        frame.set_adb_selection_mode.assert_not_called()
    finally:
        page.close()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()


@pytest.mark.parametrize("kind", ["timeout", "protocol"])
def test_fast_scan_failure_preserves_last_snapshot(monkeypatch, kind):
    runtime = Mock()
    runtime.can_scan_fast.return_value = True
    runtime.wait_for_device_check.return_value = None
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)
    results = iter(
        [
            execution.CommandResult(True, "List of devices attached\nfake\tdevice"),
            execution.CommandResult(False, error=kind),
        ]
    )
    monkeypatch.setattr(execution.CommandRunner, "run", lambda *a, **k: next(results))
    thread = _ScanThread()
    snapshots, states = [], []
    thread.devices_changed.connect(snapshots.append)
    thread.discovery_state_changed.connect(states.append)
    pauses = iter([False, True])
    monkeypatch.setattr(thread, "_sleep_interruptibly", lambda _: next(pauses))
    thread.run()
    assert snapshots == [["fake"]]
    assert states == ["unavailable"]


def test_superseded_scan_keeps_snapshot_and_state_and_waits_normally(monkeypatch):
    runtime = Mock()
    runtime.can_scan_fast.return_value = True
    runtime.wait_for_device_check.return_value = None
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)
    results = iter([
        execution.CommandResult(True, "List of devices attached\ncurrent\tdevice"),
        execution.CommandResult(False, stale=True),
        execution.CommandResult(True, "List of devices attached\ncurrent\tdevice"),
    ])
    run = Mock(side_effect=lambda *a, **k: next(results))
    monkeypatch.setattr(execution.CommandRunner, "run", run)
    thread = _ScanThread()
    snapshots, states = [], []
    thread.devices_changed.connect(snapshots.append)
    thread.discovery_state_changed.connect(states.append)
    pauses = Mock(side_effect=[False, False, True])
    monkeypatch.setattr(thread, "_sleep_interruptibly", pauses)
    thread.run()
    assert snapshots == [["current"]]
    assert states == []
    assert run.call_count == pauses.call_count == 3
