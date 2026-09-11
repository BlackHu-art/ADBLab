"""更新检查的请求、终态、限流和 QObject 生命周期契约。"""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QAbstractAnimation, QIODevice, QSize, Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtTest import QSignalSpy, QTest
from qfluentwidgets import NavigationDisplayMode
from shiboken6 import isValid

from tests.test_app_update import release_payload
from tests.ui_geometry_helpers import wait_until


class Reply(QNetworkReply):
    """只替换网络传输，保留 Qt 信号、同步 abort 和延迟销毁行为。"""

    def __init__(self, request, parent):
        super().__init__(parent)
        self.setRequest(request)
        self.setUrl(request.url())
        self.open(QIODevice.OpenModeFlag.ReadOnly)
        self.data = bytearray()
        self.aborted = False

    def bytesAvailable(self):
        return len(self.data) + super().bytesAvailable()

    def readData(self, size):
        data = bytes(self.data[:size])
        del self.data[:size]
        return data

    def feed(self, data):
        self.data.extend(data)
        self.readyRead.emit()

    def complete(self, data=b"", status=200, error=None, headers=()):
        self.setAttribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute, status)
        for key, value in headers:
            self.setRawHeader(key, value)
        if error is not None:
            self.setError(error, "controlled transport failure")
        self.feed(data)
        self.setFinished(True)
        self.finished.emit()

    def abort(self):
        self.aborted = True
        self.setError(QNetworkReply.NetworkError.OperationCanceledError, "cancelled")
        self.setFinished(True)
        self.finished.emit()


class Manager(QNetworkAccessManager):
    def __init__(self):
        super().__init__()
        self.requests = []
        self.replies = []

    def createRequest(self, operation, request, outgoingData=None):
        self.requests.append(QNetworkRequest(request))
        reply = Reply(request, self)
        self.replies.append(reply)
        return reply


@pytest.fixture
def checker(qt_application):
    from adblab.presentation.qt_app_update import QtAppUpdate

    manager = Manager()
    instance = QtAppUpdate(manager=manager)
    updates = []
    instance.changed.connect(updates.append)
    yield instance, manager, updates
    instance.prepare_shutdown()
    instance.deleteLater()
    manager.deleteLater()
    wait_until(qt_application, lambda: not isValid(instance) and not isValid(manager))


def test_only_explicit_check_uses_public_api_and_merges_repeated_clicks(checker):
    instance, manager, _updates = checker
    assert manager.requests == []
    assert instance.snapshot.status == "idle"
    instance.check()
    instance.check()
    assert len(manager.requests) == 1
    request = manager.requests[0]
    assert request.url().toString() == "https://api.github.com/repos/BlackHu-art/ADBLab/releases/latest"
    assert not request.hasRawHeader("Authorization")
    assert request.rawHeader("User-Agent").startsWith(b"ADBLab/")
    assert request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute) == (
        QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
    )
    assert instance.snapshot.status == "checking"
    assert not instance.snapshot.can_check


@pytest.mark.parametrize("tag,status", [
    ("v999.0.0", "available"), ("v0.0.0", "ahead"),
])
def test_success_is_emitted_once_and_reply_released(checker, qt_application, tag, status):
    instance, manager, updates = checker
    instance.check()
    reply = manager.replies[-1]
    reply.complete(json.dumps(release_payload(tag)).encode())
    assert instance.snapshot.status == status
    assert instance.snapshot.release.version == tag[1:]
    assert instance.snapshot.checked_at is not None
    assert len([s for s in updates if s.status == status]) == 1
    assert not instance.snapshot.can_check
    instance.check()
    assert len(manager.requests) == 1
    wait_until(qt_application, lambda: not isValid(reply))


@pytest.mark.parametrize("status,error,body,expected", [
    (404, QNetworkReply.NetworkError.ContentNotFoundError, b"{}", "unavailable"),
    (403, QNetworkReply.NetworkError.ContentAccessDenied, b"{}", "unavailable"),
    (429, QNetworkReply.NetworkError.UnknownContentError, b"{}", "rate_limited"),
    (None, QNetworkReply.NetworkError.HostNotFoundError, b"", "network"),
    (None, QNetworkReply.NetworkError.SslHandshakeFailedError, b"", "tls"),
    (200, None, b"not json", "invalid_response"),
    (200, None, b"[]", "invalid_response"),
    (302, None, b"", "unavailable"),
])
def test_failures_never_report_current(checker, status, error, body, expected):
    instance, manager, updates = checker
    instance.check()
    manager.replies[-1].complete(body, status=status, error=error)
    assert instance.snapshot.status == "error"
    assert instance.snapshot.error == expected
    assert all(s.status != "current" for s in updates)


def test_deadline_aborts_request_and_late_finished_cannot_overwrite_result(
    checker, qt_application, monkeypatch,
):
    instance, manager, updates = checker
    monkeypatch.setattr(instance, "TIMEOUT_MS", 20)
    instance.check()
    reply = manager.replies[-1]
    # 保留包装对象直到断言后，避免测试本身在 DeferredDelete 后操作 reply。
    reply.deleteLater = lambda: None
    wait_until(qt_application, lambda: instance.snapshot.status == "error")
    assert reply.aborted
    assert instance.snapshot.error == "timeout"
    reply.complete(json.dumps(release_payload()).encode())
    assert instance.snapshot.error == "timeout"
    assert len([s for s in updates if s.status == "error"]) == 1
    QNetworkReply.deleteLater(reply)


def test_oversized_stream_is_aborted_before_finished(checker):
    instance, manager, _updates = checker
    instance.check()
    reply = manager.replies[-1]
    reply.feed(b"x" * (instance.MAX_RESPONSE_BYTES + 1))
    assert reply.aborted
    assert instance.snapshot.error == "invalid_response"


def test_rate_limit_uses_server_retry_after_instead_of_short_cooldown(checker, monkeypatch):
    instance, manager, _updates = checker
    clock = [100.0]
    monkeypatch.setattr("adblab.presentation.qt_app_update.time.monotonic", lambda: clock[0])
    instance.check()
    manager.replies[-1].complete(status=403, headers=(
        (b"X-RateLimit-Remaining", b"0"), (b"Retry-After", b"120"),
    ))
    assert instance.snapshot.error == "rate_limited"
    clock[0] += 60
    instance.check()
    assert len(manager.requests) == 1
    clock[0] += 61
    instance.check()
    assert len(manager.requests) == 2


def test_cooldown_reenables_check_and_failed_refresh_retains_previous_release(
    checker, qt_application, monkeypatch,
):
    instance, manager, _updates = checker
    monkeypatch.setattr(instance, "COOLDOWN_SECONDS", 0.02)
    instance.check()
    manager.replies[-1].complete(json.dumps(release_payload("v999.0.0")).encode())
    wait_until(qt_application, lambda: instance.snapshot.can_check)
    instance.check()
    manager.replies[-1].complete(b"bad response")
    assert instance.snapshot.status == "error"
    assert instance.snapshot.release.version == "999.0.0"


@pytest.mark.parametrize("next_result", ["current", "ahead", "network_error", "invalid_release"])
def test_about_download_requires_current_available_result_after_explicit_check(
    checker, qt_application, monkeypatch, next_result,
):
    """历史发布不能授权下载；检查冷却只限制检查，不改变已确认新版的下载准入。"""

    from gui.features.about import AboutPanel
    from utils.app_metadata import APP_VERSION

    instance, manager, _updates = checker
    monkeypatch.setattr(instance, "COOLDOWN_SECONDS", 0.02)
    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True,
    )
    panel = AboutPanel()
    panel.updateRequested.connect(instance.check)
    instance.changed.connect(panel.set_update_snapshot)
    panel.resize(1100, 600)
    panel.show()
    qt_application.processEvents()
    try:
        assert manager.requests == []
        assert instance.snapshot.status == "idle"
        QTest.mouseClick(panel.release_button, Qt.MouseButton.LeftButton)
        assert opened == []
        assert not panel.release_button.isEnabled()

        panel.check_update_button.click()
        assert len(manager.requests) == 1
        assert instance.snapshot.status == "checking"
        assert not panel.release_button.isEnabled()
        QTest.mouseClick(panel.release_button, Qt.MouseButton.LeftButton)
        assert opened == []

        payload = release_payload("v999.0.0")
        manager.replies[-1].complete(json.dumps(payload).encode())
        verified_release = instance.snapshot.release
        assert verified_release is not None
        assert instance.snapshot.status == "available"
        assert not instance.snapshot.can_check
        assert not panel.check_update_button.isEnabled()
        assert panel.release_button.isEnabled()
        QTest.mouseClick(panel.release_button, Qt.MouseButton.LeftButton)
        assert opened == [payload["html_url"]]

        wait_until(qt_application, lambda: instance.snapshot.can_check)
        assert panel.check_update_button.isEnabled()
        assert panel.release_button.isEnabled()
        panel.check_update_button.click()
        assert len(manager.requests) == 2
        assert instance.snapshot.status == "checking"
        assert instance.snapshot.release is verified_release
        assert not panel.release_button.isEnabled()
        QTest.mouseClick(panel.release_button, Qt.MouseButton.LeftButton)
        assert opened == [payload["html_url"]]

        reply = manager.replies[-1]
        if next_result in {"current", "ahead"}:
            tag = f"v{APP_VERSION}" if next_result == "current" else "v0.0.0"
            reply.complete(json.dumps(release_payload(tag)).encode())
            assert instance.snapshot.status == next_result
            assert instance.snapshot.release.version == tag.removeprefix("v")
        else:
            if next_result == "network_error":
                reply.complete(status=None, error=QNetworkReply.NetworkError.HostNotFoundError)
                assert instance.snapshot.error == "network"
            else:
                reply.complete(json.dumps(release_payload(
                    "v999.0.1", html_url="https://example.invalid/untrusted-download",
                )).encode())
                assert instance.snapshot.error == "invalid_response"
            assert instance.snapshot.status == "error"
            assert instance.snapshot.release is verified_release
        assert not instance.snapshot.can_check
        assert not panel.release_button.isEnabled()
        QTest.mouseClick(panel.release_button, Qt.MouseButton.LeftButton)
        assert opened == [payload["html_url"]]

        wait_until(qt_application, lambda: instance.snapshot.can_check)
        assert panel.check_update_button.isEnabled()
        assert not panel.release_button.isEnabled()
        QTest.mouseClick(panel.release_button, Qt.MouseButton.LeftButton)
        assert opened == [payload["html_url"]]
        assert len(manager.requests) == 2
    finally:
        instance.changed.disconnect(panel.set_update_snapshot)
        panel.close()
        panel.deleteLater()
        wait_until(qt_application, lambda: not isValid(panel))


def test_close_aborts_synchronously_and_suppresses_all_late_ui_updates(checker):
    instance, manager, updates = checker
    instance.check()
    reply = manager.replies[-1]
    before = len(updates)
    instance.prepare_shutdown()
    instance.prepare_shutdown()
    assert reply.aborted
    reply.complete(json.dumps(release_payload()).encode())
    instance.check()
    assert len(updates) == before
    assert len(manager.requests) == 1


def test_application_close_preparation_stops_update_request(checker):
    from gui.close_controller import CloseController

    instance, manager, updates = checker
    frame = SimpleNamespace(
        _app_update=instance, _initial_refresh_timer=QTimer(), _scan_refresh_timer=QTimer(),
        _scan_thread=None, left_panel=SimpleNamespace(),
    )
    instance.check()
    before = len(updates)
    CloseController(frame)._prepare_ui_for_shutdown()
    assert manager.replies[-1].aborted
    assert len(updates) == before


def test_secondary_rate_limit_respects_retry_after(checker):
    instance, manager, _updates = checker
    instance.check()
    manager.replies[-1].complete(status=403, headers=((b"Retry-After", b"120"),))
    assert instance.snapshot.error == "rate_limited"


def test_main_window_wires_settings_to_manual_check_without_startup_request(
    qt_application, monkeypatch,
):
    from adblab.presentation.qt_app_update import QtAppUpdate
    from core.settings_manager import DEFAULTS, AppSettings
    from models.device_store import DeviceStore
    from tests.test_main_window_layout import _MainFrameSettings, build_main_frame

    manager = Manager()
    settings = _MainFrameSettings()
    settings.values.update(DEFAULTS, continuous_device_scan=False)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda _devices: [])
    monkeypatch.setattr(
        "gui.main_frame.QtAppUpdate", lambda parent: QtAppUpdate(parent, manager=manager),
    )
    window = build_main_frame(settings=settings)
    try:
        window.show()
        window.navigationInterface.widget("settingsPage").click()
        page = window._settings_page
        wait_until(qt_application, lambda: page.isVisible())
        about = page.about_panel
        assert manager.requests == []
        page.ensureWidgetVisible(about.check_update_button, 0, 0)
        about.check_update_button.click()
        assert len(manager.requests) == 1
        assert not about.check_update_button.isEnabled()
        window.navigationInterface.widget("homePage").click()
        manager.replies[-1].complete(json.dumps(release_payload("v999.0.0")).encode())
        window.navigationInterface.widget("settingsPage").click()
        assert "999.0.0" in about.project_card.contentLabel.text()
        assert len(manager.requests) == 1
    finally:
        window._app_update.prepare_shutdown()
        window._unbind_window_screen()
        window._close_ready = True
        window.close()
        window.deleteLater()
        manager.deleteLater()
        wait_until(qt_application, lambda: not isValid(window) and not isValid(manager))


@pytest.mark.parametrize("width", [1000, 1280])
@pytest.mark.parametrize("activate", ["mouse", "space"])
def test_update_check_keeps_focus_and_theme_independent(
    qt_application, monkeypatch, width, activate,
):
    """检查入口禁用时焦点留在更新卡片，不能跳到侧栏后误操作主题。"""

    from adblab.presentation.qt_app_update import QtAppUpdate
    from core.settings_manager import DEFAULTS, AppSettings
    from gui.styles import BaseStyles
    from models.device_store import DeviceStore
    from tests.test_main_window_layout import (
        _FakeScreen,
        _FakeScreenAdapter,
        _MainFrameSettings,
        build_main_frame,
    )

    manager = Manager()
    settings = _MainFrameSettings()
    settings.values.update(
        DEFAULTS, continuous_device_scan=False, window_width=width, window_height=840,
        mica_enabled=False,
    )
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda _devices: [])
    monkeypatch.setattr(
        "gui.main_frame.QtAppUpdate", lambda parent: QtAppUpdate(parent, manager=manager),
    )
    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True,
    )
    window = build_main_frame(
        settings=settings,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("update-test", QSize(1920, 1080))),
    )
    monkeypatch.setattr(window._app_update, "COOLDOWN_SECONDS", 0.02)
    try:
        window.show()
        window.activateWindow()
        window.navigationInterface.widget("settingsPage").click()
        page = window._settings_page
        panel = window.navigationInterface.panel
        expected_mode = (
            NavigationDisplayMode.COMPACT if width < 1120 else NavigationDisplayMode.EXPAND
        )
        wait_until(
            qt_application,
            lambda: page.isVisible() and panel.displayMode == expected_mode
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )
        about = page.about_panel
        theme_button = window._theme_navigation_widget
        assert theme_button.isCompacted == (width < 1120)
        theme_calls = QSignalSpy(theme_button.clicked)
        original_theme = BaseStyles.current_theme()
        page.ensureWidgetVisible(about.check_update_button, 0, 0)
        about.check_update_button.setFocus(Qt.FocusReason.TabFocusReason)
        wait_until(qt_application, about.check_update_button.hasFocus)
        if activate == "mouse":
            QTest.mouseClick(about.check_update_button, Qt.MouseButton.LeftButton)
        else:
            QTest.keyClick(about.check_update_button, Qt.Key.Key_Space)
        qt_application.processEvents()
        assert len(manager.requests) == 1
        assert not about.check_update_button.isEnabled()
        assert BaseStyles.current_theme() == original_theme
        assert theme_calls.count() == 0
        focus = qt_application.focusWidget()
        assert focus is not None and about.isAncestorOf(focus), (
            type(focus).__name__, focus.objectName() if focus else "",
        )
        for key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            QTest.keyClick(focus, key)
        assert len(manager.requests) == 1
        assert BaseStyles.current_theme() == original_theme
        assert theme_calls.count() == 0
        assert opened == []

        payload = release_payload("v999.0.0")
        manager.replies[-1].complete(json.dumps(payload).encode())
        assert qt_application.focusWidget() is focus
        assert about.release_button.isEnabled()
        QTest.mouseClick(about.release_button, Qt.MouseButton.LeftButton)
        assert opened == [payload["html_url"]]
        assert BaseStyles.current_theme() == original_theme
        assert theme_calls.count() == 0

        # 下载入口有焦点时重查也必须承接焦点，防止旧版下载准入撤销后跳到侧栏。
        wait_until(qt_application, lambda: window._app_update.snapshot.can_check)
        about.release_button.setFocus(Qt.FocusReason.TabFocusReason)
        window._app_update.check()
        assert not about.release_button.isEnabled()
        assert qt_application.focusWidget() is focus

        # 后台结果只更新状态，不能从用户随后选中的其他控件抢回焦点。
        theme_target = theme_button if theme_button.isCompacted else theme_button.switch.indicator
        theme_target.setFocus(Qt.FocusReason.TabFocusReason)
        manager.replies[-1].complete(b"bad response")
        assert theme_target.hasFocus()
        assert BaseStyles.current_theme() == original_theme
        assert theme_calls.count() == 0
    finally:
        window._app_update.prepare_shutdown()
        window._unbind_window_screen()
        window._close_ready = True
        window.close()
        window.deleteLater()
        manager.deleteLater()
        wait_until(qt_application, lambda: not isValid(window) and not isValid(manager))
