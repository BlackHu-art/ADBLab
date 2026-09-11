"""ADB 运行实例的 Qt 延迟启动、扫描、展示和资源收口验证。"""

import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from adblab.presentation.qt_adb_runtime import QtAdbRuntime
from core import adb_transport
from core import exec as execution
from core.adb_runtime import RuntimeSnapshot
from core.settings_manager import DEFAULTS, AppSettings
from gui.i18n import install_translators
from gui.main_frame import MainFrame, _ScanThread
from gui.pages.fluent_pages import SettingsPage
from gui.styles import BaseStyles
from tests.ui_geometry_helpers import wait_for_stable_geometry


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
    frame._start_device_discovery = Mock()
    frame._log_adb_environment = Mock()
    frame._update_adb_environment = lambda snapshot: MainFrame._update_adb_environment(
        frame, snapshot,
    )
    frame._settings_page = SettingsPage(frame, frame)
    try:
        MainFrame._bootstrap_adb_async(frame)
        assert frame._settings_page.adb_native_card.isChecked()
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
        set_adb_native_only=adapter.set_native_only,
    )
    page = SettingsPage(frame)
    adapter.changed.connect(page.update_adb_environment)
    selections = []
    page.adb_native_card.checkedChanged.connect(selections.append)
    try:
        page.resize(900, 640)
        page.show()
        page.update_adb_environment(adapter.snapshot())
        assert page.adb_native_card.isChecked()
        assert adapter.snapshot().selection_mode == "auto"

        indicator = page.adb_native_card.switchButton.indicator
        page.ensureWidgetVisible(indicator, 0, 0)
        wait_for_stable_geometry(qt_application, (page, page.adb_native_card, indicator))
        assert indicator.isVisibleTo(page)
        QTest.mouseClick(indicator, Qt.MouseButton.LeftButton)
        qt_application.processEvents()
        assert adapter.snapshot().selection_mode == "fast"
        assert not page.adb_native_card.isChecked()
        assert page.adb_native_card.switchButton.label.text() == "关"
        assert "手动快速" in page.adb_check_card.contentLabel.text()
        assert "当前使用原生 ADB" in page.adb_check_card.contentLabel.text()

        page.ensureWidgetVisible(indicator, 0, 0)
        QTest.mouseClick(indicator, Qt.MouseButton.LeftButton)
        qt_application.processEvents()
        assert adapter.snapshot().selection_mode == "native"
        assert page.adb_native_card.isChecked()
        assert page.adb_native_card.switchButton.label.text() == "开"
        assert "手动原生" in page.adb_check_card.contentLabel.text()
        assert selections == [False, True]
    finally:
        adapter.close()
        page.close()


def test_fast_scan_runs_while_other_commands_are_busy(monkeypatch):
    runtime = Mock()
    runtime.can_scan_fast.return_value = True
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


@pytest.mark.parametrize("busy", [False, True])
def test_scan_requests_recovery_before_busy_gate_or_failed_native_scan(monkeypatch, busy):
    runtime = Mock()
    runtime.can_scan_fast.return_value = False
    events = []
    runtime.request_device_check.side_effect = lambda: events.append("check")
    monkeypatch.setattr("gui.main_frame.adb_runtime", lambda: runtime)

    def active_count():
        events.append("busy")
        return int(busy)

    monkeypatch.setattr(execution.CommandRunner, "active_count", active_count)
    thread = _ScanThread()

    def failed_scan(_runner):
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


def test_settings_reports_partial_acceleration_and_session_override():
    frame = SimpleNamespace(
        _always_on_top=False,
        set_always_on_top=Mock(),
        set_continuous_scan=Mock(),
        left_panel=SimpleNamespace(signals=SimpleNamespace(restart_adb_requested=Mock())),
        recheck_adb_environment=Mock(),
        set_adb_native_only=Mock(),
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
        page.adb_native_card.setChecked(True)
        frame.set_adb_native_only.assert_called_with(True)
        page.update_adb_environment(RuntimeSnapshot(False, True, True, False, 0, 2))
        assert "原生" in page.adb_check_card.contentLabel.text()
    finally:
        page.close()


def test_settings_auto_mode_follows_capability_changes_without_selecting_manual_policy():
    frame = SimpleNamespace(
        _always_on_top=False,
        set_always_on_top=Mock(),
        set_continuous_scan=Mock(),
        left_panel=SimpleNamespace(signals=SimpleNamespace(restart_adb_requested=Mock())),
        recheck_adb_environment=Mock(),
        set_adb_native_only=Mock(),
    )
    parent = QWidget()
    page = SettingsPage(frame, parent)
    try:
        page.update_adb_environment(RuntimeSnapshot(False, True, False, False, 0, 2))
        assert page.adb_native_card.isChecked()
        frame.set_adb_native_only.assert_not_called()

        page.update_adb_environment(RuntimeSnapshot(False, True, False, True, 1, 2))
        assert not page.adb_native_card.isChecked()
        frame.set_adb_native_only.assert_not_called()

        page.update_adb_environment(RuntimeSnapshot(False, False, False, False, 0, 2))
        assert page.adb_native_card.isChecked()
        frame.set_adb_native_only.assert_not_called()

        page.update_adb_environment(RuntimeSnapshot(False, True, False, True, 1, 2))
        assert not page.adb_native_card.isChecked()
        frame.set_adb_native_only.assert_not_called()

        page.adb_native_card.setChecked(True)
        frame.set_adb_native_only.assert_called_once_with(True)
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
        set_adb_native_only=Mock(),
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
        frame.set_adb_native_only.assert_not_called()
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
        set_adb_native_only=Mock(),
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
        assert page.adb_native_card.isChecked() is native_only
        if fast_devices:
            assert "Shell 2" in content
        else:
            assert "原生 ADB" in content
        frame.set_adb_native_only.assert_not_called()
    finally:
        page.close()


@pytest.mark.parametrize(
    ("language", "mode_label", "status", "reason", "on_text"),
    [
        ("zh_CN", "自动选择", "host_unavailable", "服务不可用", "开"),
        ("zh_HK", "自動選擇", "host_unavailable", "服務無法使用", "開"),
        ("en_US", "Automatic selection", "host_unavailable", "service is unavailable", "On"),
        ("zh_CN", "自动选择", "starting_server", "正在启动本机 ADB 服务", "开"),
        ("zh_HK", "自動選擇", "starting_server", "正在啟動本機 ADB 服務", "開"),
        ("en_US", "Automatic selection", "starting_server", "Starting the local ADB service", "On"),
    ],
)
def test_settings_translated_runtime_status_fits_narrow_large_font_page(
    monkeypatch, qt_application, language, mode_label, status, reason, on_text,
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
        cards = (page.adb_check_card, page.adb_native_card)
        wait_for_stable_geometry(qt_application, (page, *cards))
        content = page.adb_check_card.contentLabel.text()
        assert mode_label in content
        assert reason in content
        assert page.adb_check_card.button.isEnabled() is (status != "starting_server")
        assert page.adb_native_card.switchButton.label.text() == on_text
        assert page.horizontalScrollBar().maximum() == 0
        for card, control in (
            (page.adb_check_card, page.adb_check_card.button),
            (page.adb_native_card, page.adb_native_card.switchButton),
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
        frame.set_adb_native_only.assert_not_called()
    finally:
        page.close()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()


@pytest.mark.parametrize("kind", ["timeout", "protocol"])
def test_fast_scan_failure_preserves_last_snapshot(monkeypatch, kind):
    runtime = Mock()
    runtime.can_scan_fast.return_value = True
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
