"""安装版更新界面、异步准备及退出授权的直接契约。"""

import importlib
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QSignalSpy
from shiboken6 import isValid

from core.tasks.supervision import StopDisposition, TaskStopResult
from gui.features.about import AboutPanel
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def _release(status="available", *, asset=None):
    from datetime import datetime, timezone

    return SimpleNamespace(
        status=status, installer_asset=asset, can_check=True, error="",
        checked_at=datetime.now(timezone.utc),
        release=SimpleNamespace(version="999.0.0", published_at=datetime.now(timezone.utc),
                                url="https://github.com/BlackHu-art/ADBLab/releases/tag/v999.0.0"),
    )


def _download(status="idle", *, verified=None):
    return SimpleNamespace(status=status, received=50, total=100, error="", verified=verified)


def test_installer_card_is_opt_in_and_requires_fresh_asset(qt_application):
    panel = AboutPanel()
    try:
        assert hasattr(panel, "set_installer_enabled")
        assert panel.installer_card.isHidden()
        asset = object()
        panel.set_installer_enabled(True)
        panel.set_update_snapshot(_release(asset=asset))
        assert panel.installer_download_button.isEnabled()
        assert panel.release_button.isEnabled()
        requests = QSignalSpy(panel.installerDownloadRequested)
        panel.installer_download_button.click()
        assert requests.count() == 1
        for status in ("checking", "error", "current", "ahead"):
            panel.set_update_snapshot(_release(status, asset=asset))
            assert not panel.installer_download_button.isEnabled()
            assert not panel.installer_install_button.isEnabled()
        panel.set_update_snapshot(_release(asset=None))
        assert not panel.installer_download_button.isEnabled()
    finally:
        panel.close()
        panel.deleteLater()


def test_installer_progress_ready_and_handoff_preserve_focus(qt_application):
    panel = AboutPanel()
    try:
        assert hasattr(panel, "set_installer_enabled")
        asset = object()
        panel.set_installer_enabled(True)
        panel.set_update_snapshot(_release(asset=asset))
        panel.resize(620, 700)
        panel.show()
        panel.activateWindow()
        panel.installer_download_button.setFocus(Qt.FocusReason.TabFocusReason)
        wait_until(qt_application, panel.installer_download_button.hasFocus)
        panel.set_installer_snapshot(_download("downloading"))
        assert not panel.installer_download_button.isEnabled()
        assert panel.installer_cancel_button.isEnabled()
        assert "50%" in panel.installer_card.contentLabel.text()
        assert panel.installer_actions.hasFocus()
        verified = SimpleNamespace(asset=asset)
        panel.set_installer_snapshot(_download("ready", verified=verified))
        assert panel.installer_install_button.isEnabled()
        panel.set_handoff_state("preparing")
        assert not panel.installer_install_button.isEnabled()
        assert not panel.check_update_button.isEnabled()
        panel.set_handoff_state("error")
        assert panel.installer_install_button.isEnabled()
        assert panel.check_update_button.isEnabled()
        panel.set_update_snapshot(_release("checking", asset=asset))
        panel.set_installer_snapshot(_download("ready", verified=verified))
        assert not panel.installer_install_button.isEnabled()
    finally:
        panel.close()
        panel.deleteLater()


class Handoff:
    def __init__(self):
        self.prepared = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail = False
        self.abort_calls = 0
        self.results = []
        self.threads = []

    def prepare(self, _verified):
        self.threads.append(threading.get_ident())
        self.entered.set()
        self.release.wait(3)
        if self.fail:
            raise OSError("private location must not reach the UI")
        self.prepared = True

    def abort(self):
        self.abort_calls += 1
        self.prepared = False

    def reset_attempt(self):
        self.prepared = False

    def mark_shutdown_success(self, success):
        self.results.append(success)

    def has_pending_helper(self):
        return False

    def wait_pending_helper(self, timeout):
        return True


def _adapter(qt_application, owner):
    spec = importlib.util.find_spec("gui.adapters.installer_handoff")
    assert spec is not None, "缺少异步交接准备 owner"
    module = importlib.import_module("gui.adapters.installer_handoff")
    return module.QtInstallerHandoff(owner)


def test_prepare_is_async_nonduplicating_and_ready_after_thread_exit(qt_application):
    owner = Handoff()
    adapter = _adapter(qt_application, owner)
    ready = QSignalSpy(adapter.ready)
    try:
        assert adapter.start(object())
        assert owner.entered.wait(1)
        assert not adapter.start(object())
        assert ready.count() == 0
        assert adapter.is_running()
        owner.release.set()
        wait_until(qt_application, lambda: ready.count() == 1)
        assert not adapter.is_running()
        assert owner.threads != [threading.get_ident()]
        adapter.prepare_shutdown(preserve_prepared=True)
        assert owner.abort_calls == 0
        assert adapter.wait(0)
    finally:
        owner.release.set()
        adapter.prepare_shutdown()
        assert adapter.wait(3)
        adapter.deleteLater()


def test_prepare_failure_allows_retry_and_shutdown_waits_late_prepare(qt_application):
    owner = Handoff()
    owner.fail = True
    adapter = _adapter(qt_application, owner)
    states = []
    adapter.changed.connect(states.append)
    ready = QSignalSpy(adapter.ready)
    try:
        owner.release.set()
        assert adapter.start(object())
        wait_until(qt_application, lambda: "error" in states)
        assert owner.abort_calls == 0
        owner.fail = False
        owner.entered.clear()
        owner.release.clear()
        assert adapter.start(object())
        assert owner.entered.wait(1)
        adapter.prepare_shutdown()
        assert not adapter.wait(0)
        before = list(states)
        owner.release.set()
        assert adapter.wait(3)
        qt_application.processEvents()
        assert states == before
        assert ready.count() == 0
        assert not owner.prepared
        assert not adapter.start(object())
    finally:
        owner.release.set()
        adapter.prepare_shutdown()
        assert adapter.wait(3)
        adapter.deleteLater()


def test_preparing_signal_shutdown_retains_started_thread(qt_application):
    owner = Handoff()
    adapter = _adapter(qt_application, owner)
    observations = []

    def close_during_publication(state):
        if state == "preparing":
            observations.append(adapter.is_running())
            adapter.prepare_shutdown()

    adapter.changed.connect(close_during_publication)
    try:
        assert adapter.start(object())
        assert observations == [True]
        assert not adapter.wait(0)
        owner.release.set()
        assert adapter.wait(3)
        assert not owner.prepared
        assert not adapter._poll.isActive()
    finally:
        owner.release.set()
        adapter.prepare_shutdown()
        assert adapter.wait(3)
        adapter.deleteLater()


def test_preparing_signal_cannot_start_second_attempt(qt_application):
    owner = Handoff()
    owner.release.set()
    adapter = _adapter(qt_application, owner)
    repeats = []
    adapter.changed.connect(
        lambda state: repeats.append(adapter.start(object())) if state == "preparing" else None,
    )
    try:
        assert adapter.start(object())
        assert repeats == [False]
        wait_until(qt_application, lambda: not adapter._poll.isActive())
        assert len(owner.threads) == 1
    finally:
        adapter.prepare_shutdown()
        assert adapter.wait(3)
        adapter.deleteLater()


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_helper_stays_supervised_after_prepare_thread_exit(
    qt_application, tmp_path, monkeypatch, cancelled,
):
    from core import installer_handoff as module
    from tests.test_installer_handoff import fake_handoff_attempt

    owner, verified, process = fake_handoff_attempt(tmp_path, monkeypatch)
    entered, released = threading.Event(), threading.Event()

    def read(*args, **kwargs):
        entered.set()
        assert released.wait(3)
        if cancelled:
            raise InterruptedError("controlled cancellation")
        return b"INVALID"

    monkeypatch.setattr(module, "read_pipe_line", read)
    adapter = _adapter(qt_application, owner)
    states = []
    adapter.changed.connect(states.append)
    ready = QSignalSpy(adapter.ready)
    try:
        assert adapter.start(verified)
        assert entered.wait(1)
        if cancelled:
            adapter.cancel()
            adapter.cancel()
        released.set()
        wait_until(qt_application, lambda: ("cancelled" if cancelled else "error") in states)
        assert adapter.is_running()
        assert not adapter.start(verified)
        assert not adapter.wait(0)
        assert process.wait_calls == [5], "GUI polling must never wait for the helper"
        from gui.close_controller import CloseController
        from tests.test_phase2_mainframe_shutdown_gate import _frame

        frame = _frame(lambda: None)
        frame._installer_handoff = adapter
        CloseController(frame)._register_application_shutdown_tasks()
        supervisor = frame.task_supervisor.supervisor
        assert any(
            item.kind == "installer_handoff_prepare" and item.running
            for item in supervisor.active_snapshot()
        )
        adapter.prepare_shutdown(preserve_prepared=True)
        assert not adapter.wait(0.01)
        assert adapter.is_running()
        assert owner._process is process
        process.returncode = 1
        assert adapter.wait(0)
        assert not adapter.is_running()
        assert process.stdout.closed
        assert any(
            item.kind == "installer_handoff_prepare" and not item.running
            for item in supervisor.active_snapshot()
        )
        qt_application.processEvents()
        assert ready.count() == 0
    finally:
        released.set()
        process.returncode = 1
        adapter.prepare_shutdown()
        assert adapter.wait(3)
        adapter.deleteLater()


def test_ready_helper_is_preserved_without_wait_until_explicit_abort(
    qt_application, tmp_path, monkeypatch,
):
    from tests.test_installer_handoff import fake_handoff_attempt

    owner, verified, process = fake_handoff_attempt(tmp_path, monkeypatch, answer=b"READY")
    adapter = _adapter(qt_application, owner)
    ready = QSignalSpy(adapter.ready)
    try:
        assert adapter.start(verified)
        wait_until(qt_application, lambda: ready.count() == 1)
        assert not adapter.is_running()
        adapter.prepare_shutdown(preserve_prepared=True)
        assert adapter.wait(0.01)
        assert process.wait_calls == []
        assert owner.prepared
        assert process.stdin is not None and not process.stdin.closed
        owner.mark_shutdown_success(True)
        # COMMIT 的单次发送与根入口顺序由 core 直接测试覆盖。
        owner.abort()
        assert adapter.is_running()
        process.returncode = 0
        assert adapter.wait(0)
    finally:
        process.returncode = 0
        adapter.prepare_shutdown()
        assert adapter.wait(3)
        adapter.deleteLater()


@pytest.mark.parametrize("case", [
    "success", "ordinary", "not_prepared", "preparation", "historical_residual",
    "residual", "forced", "error_type", "failed", "timed_out", "no_finalizer",
])
def test_handoff_requires_explicit_successful_shutdown(qt_application, monkeypatch, case):
    from gui.close_controller import CloseController

    owner = Handoff()
    owner.prepared = case != "not_prepared"
    result = TaskStopResult("app-finalizer", "app", StopDisposition.GRACEFUL)
    results = ()
    if case in {"forced", "failed", "timed_out", "error_type"}:
        disposition = StopDisposition.GRACEFUL if case == "error_type" else StopDisposition(case)
        results = (TaskStopResult(
            "task", "app", disposition, "OSError" if case == "error_type" else "",
        ),)
    frame = SimpleNamespace(
        _handoff=owner, _installer_close_requested=case != "ordinary",
        _shutdown_had_residual=case == "historical_residual", _shutdown_results=results,
        _shutdown_preparation_failures=(object(),) if case == "preparation" else (),
        _close_started=True, _close_ready=False, _shutdown_owner_id="app", close=Mock(),
        setWindowTitle=Mock(), log_service=Mock(), findChildren=Mock(return_value=[]),
    )
    monkeypatch.setattr("gui.close_controller.QTimer.singleShot", lambda _delay, cb: cb())
    CloseController(frame)._on_application_finalized(
        None if case == "no_finalizer" else result,
        (object(),) if case == "residual" else (),
    )
    assert owner.results == [case == "success"]
    assert frame._close_ready
    frame.close.assert_called_once()
    if case != "success":
        assert owner.abort_calls == 1


def test_close_registers_installer_threads_and_preserves_only_confirmed_handoff(qt_application):
    from gui.close_controller import CloseController
    from tests.test_phase2_mainframe_shutdown_gate import _frame

    frame = _frame(lambda: None)
    frame._handoff = Handoff()
    frame._installer_close_requested = False
    frame._installer_update = Mock()
    frame._installer_handoff = Mock()
    close = CloseController(frame)
    close._register_application_shutdown_tasks()
    kinds = {item.kind for item in frame.task_supervisor.supervisor.active_snapshot()}
    assert {"installer_download", "installer_handoff_prepare"} <= kinds
    close._prepare_ui_for_shutdown()
    frame._installer_update.prepare_shutdown.assert_called_once()
    frame._installer_handoff.prepare_shutdown.assert_called_once_with(preserve_prepared=False)


@pytest.mark.parametrize("confirmed", [False, True])
def test_mainframe_only_prepares_after_confirmation_and_closes_after_ready(
    qt_application, confirmed,
):
    from gui.main_frame import MainFrame

    assert hasattr(MainFrame, "_request_installer_install")
    asset = object()
    verified = SimpleNamespace(asset=asset)
    owner = Handoff()
    frame = SimpleNamespace(
        _closing=False, _installer_confirmation_pending=False, _installer_close_requested=False,
        _handoff=owner, _installer_handoff=Mock(),
        _installer_update=SimpleNamespace(snapshot=_download("ready", verified=verified)),
        _app_update=SimpleNamespace(snapshot=_release(asset=asset)),
        _settings_page=SimpleNamespace(about_panel=Mock()),
        _confirm_installer_exit=Mock(return_value=confirmed), close=Mock(),
    )
    frame._installer_handoff.is_running.return_value = False
    MainFrame._request_installer_install(frame)
    frame.close.assert_not_called()
    if not confirmed:
        frame._installer_handoff.start.assert_not_called()
        return
    frame._installer_handoff.start.assert_called_once_with(verified)
    owner.prepared = True
    MainFrame._on_installer_handoff_ready(frame)
    assert frame._installer_close_requested
    frame.close.assert_called_once()


def test_mainframe_stale_release_never_closes_after_helper_ready(qt_application):
    from gui.main_frame import MainFrame

    assert hasattr(MainFrame, "_on_installer_handoff_ready")
    old_asset = object()
    frame = SimpleNamespace(
        _closing=False, _installer_close_requested=False, _installer_requested_asset=old_asset,
        _handoff=SimpleNamespace(prepared=True), _installer_handoff=Mock(),
        _installer_update=SimpleNamespace(snapshot=_download(
            "ready", verified=SimpleNamespace(asset=old_asset),
        )),
        _app_update=SimpleNamespace(snapshot=_release("error", asset=old_asset)),
        _settings_page=SimpleNamespace(about_panel=Mock()), close=Mock(),
    )
    MainFrame._on_installer_handoff_ready(frame)
    frame.close.assert_not_called()
    frame._installer_handoff.cancel.assert_called_once()


@pytest.mark.parametrize("change", ["checking", "error", "closing"])
def test_install_confirmation_rechecks_nested_event_loop_changes(qt_application, change):
    from gui.main_frame import MainFrame

    asset = object()
    verified = SimpleNamespace(asset=asset)
    frame = SimpleNamespace(
        _closing=False, _installer_confirmation_pending=False, _installer_close_requested=False,
        _handoff=Handoff(), _installer_handoff=Mock(),
        _installer_update=SimpleNamespace(snapshot=_download("ready", verified=verified)),
        _app_update=SimpleNamespace(snapshot=_release(asset=asset)),
    )
    frame._installer_handoff.is_running.return_value = False

    def confirm():
        if change == "closing":
            frame._closing = True
        else:
            frame._app_update.snapshot = _release(change, asset=asset)
        return True

    frame._confirm_installer_exit = confirm
    MainFrame._request_installer_install(frame)
    frame._installer_handoff.start.assert_not_called()


@pytest.mark.parametrize("status", ["checking", "error"])
def test_new_release_check_revokes_preparing_installer(qt_application, status):
    from gui.main_frame import MainFrame

    asset = object()
    update = _release(status, asset=asset)
    frame = SimpleNamespace(
        _closing=False, _installer_requested_asset=asset, _installer_update=Mock(),
        _installer_handoff=Mock(), _settings_page=SimpleNamespace(about_panel=Mock()),
    )
    MainFrame._on_installer_release_changed(frame, update)
    assert frame._installer_requested_asset is None
    frame._installer_handoff.cancel.assert_called_once()
    frame._installer_update.set_release.assert_called_once_with(update)


def test_other_ui_cleanup_failure_cannot_skip_installer_cancellation(qt_application):
    from gui.close_controller import CloseController
    from tests.test_phase2_mainframe_shutdown_gate import _frame

    frame = _frame(lambda: None)
    frame._installer_update = Mock()
    frame._installer_handoff = Mock()
    frame._settings_page = SimpleNamespace(prepare_shutdown=Mock(side_effect=ValueError("broken")))
    with pytest.raises(ValueError):
        CloseController(frame)._prepare_ui_for_shutdown()
    frame._installer_update.prepare_shutdown.assert_called_once()
    frame._installer_handoff.prepare_shutdown.assert_called_once_with(preserve_prepared=False)


def test_installed_window_wires_explicit_download_prepare_and_real_close(
    qt_application, monkeypatch, isolated_settings_client_detection,
):
    from core.settings_manager import DEFAULTS, AppSettings
    from gui.main_frame import MainFrame
    from tests.test_main_window_layout import _MainFrameSettings, build_main_frame

    class Downloader(QObject):
        changed = Signal(object)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.snapshot = _download()
            self.requests = []
            self.stopped = False

        def set_release(self, snapshot):
            self.release = snapshot

        def start(self, asset):
            assert self.release.installer_asset is asset
            self.requests.append(asset)
            self.snapshot = _download("ready", verified=SimpleNamespace(asset=asset))
            self.changed.emit(self.snapshot)
            return True

        def cancel(self):
            self.stopped = True

        prepare_shutdown = cancel

        def wait(self, _timeout):
            return True

        def is_running(self):
            return False

    owner = Handoff()
    owner.release.set()
    settings = _MainFrameSettings()
    settings.values.update(DEFAULTS, continuous_device_scan=False)
    settings.close = Mock(return_value=True)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr("gui.adapters.installer_update.QtInstallerUpdate", Downloader)
    original_init = MainFrame.__init__

    def installed_init(self, **kwargs):
        original_init(self, handoff=owner, **kwargs)

    monkeypatch.setattr(MainFrame, "__init__", installed_init)
    window = build_main_frame(settings=settings)
    actual_close = window.close
    try:
        about = window._settings_page.about_panel
        assert not about.installer_card.isHidden()
        assert window._installer_update.requests == []
        asset = object()
        window._app_update.snapshot = _release(asset=asset)
        window._app_update.changed.emit(window._app_update.snapshot)
        about.installer_download_button.click()
        assert window._installer_update.requests == [asset]
        assert about.installer_install_button.isEnabled()
        monkeypatch.setattr(window, "_confirm_installer_exit", lambda: True)
        request_close = Mock()
        window.close = request_close
        about.installer_install_button.click()
        wait_until(qt_application, lambda: request_close.call_count == 1)
        assert window._installer_close_requested
        assert owner.prepared
        assert owner.results == []
        window.close = actual_close
        actual_close()
        wait_until(qt_application, lambda: window._close_ready)
        assert window._installer_update.stopped
        assert owner.results == [False, True]
        settings.close.assert_called_once()
    finally:
        window.close = actual_close
        owner.release.set()
        if not window._close_started:
            window._installer_close_requested = False
            actual_close()
        wait_until(qt_application, lambda: window._close_ready)
        window.deleteLater()
        wait_until(qt_application, lambda: not isValid(window))


def test_install_confirmation_respects_large_text_and_parent_bounds(qt_application, monkeypatch):
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QWidget

    from gui.main_frame import MainFrame, MessageBox
    from gui.styles import BaseStyles

    parent = QWidget()
    parent.resize(720, 640)
    parent.adb_controller = SimpleNamespace(operation_manager=SimpleNamespace(
        active_snapshot=lambda: (SimpleNamespace(kind="monkey"),),
    ))
    monkeypatch.setattr(
        BaseStyles, "font_for_role", classmethod(lambda _cls, _role: QFont("Arial", 22)),
    )
    observations = []

    def inspect_dialog(dialog):
        dialog.show()
        qt_application.processEvents()
        observations.append((
            dialog.contentLabel.font().pointSizeF(),
            dialog.widget.width(),
            dialog.contentLabel.fontMetrics().boundingRect(
                dialog.contentLabel.rect(), Qt.TextFlag.TextWordWrap, dialog.contentLabel.text(),
            ).height() <= dialog.contentLabel.height(),
            dialog.cancelButton.hasFocus(),
        ))
        dialog.hide()
        return 0

    monkeypatch.setattr(MessageBox, "exec", inspect_dialog)
    parent.show()
    try:
        assert not MainFrame._confirm_installer_exit(parent)
        assert observations[0][0] == 22
        assert observations[0][1] <= parent.width() - 32
        assert all(observations[0][2:])
    finally:
        parent.close()
        parent.deleteLater()
