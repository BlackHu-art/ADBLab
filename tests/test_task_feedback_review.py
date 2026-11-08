"""评审发现的窗口、来源身份与停止手势竞态回归。"""

import sys
from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from gui.i18n import tr
from gui.session_tasks import SessionTaskRegistry, SessionTaskSnapshot
from tests.test_task_feedback import _result
from tests.test_task_feedback import task_feedback as task_feedback
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


class _Owner(QWidget):
    dispose_ready = Signal(object)

    def __init__(self, key="owner", *, kind="logcat"):
        super().__init__()
        self.snapshot = SessionTaskSnapshot(key, "earlier", kind, "running", True, True,
                                            ("设备 3 · 原目标",))
        self.requests = []

    def task_snapshot(self):
        return self.snapshot

    def request_task_stop(self, revision):
        self.requests.append(revision)
        return True

    def request_dispose(self, _reason):
        return False


def test_explicit_task_switch_retains_external_focus_origin(task_feedback, qt_application):
    coordinator, page, _manager, _view, _sources = task_feedback()
    window = coordinator.parent()
    origin = QPushButton("外部入口", window)
    origin.setGeometry(10, 10, 100, 32)
    origin.show()
    page.present_action_result(_result("A", state="succeeded"))
    page.present_action_result(_result("B", state="succeeded"))
    coordinator.open_request("A", origin=origin)
    coordinator.drawer.close_button.setFocus()
    assert coordinator.open_request("B")
    assert coordinator.drawer.selected_key == "action:B"
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_application.processEvents()
    coordinator.drawer.close_drawer(animated=False)
    assert origin.hasFocus()


@pytest.mark.parametrize("automatic", [False, True])
def test_window_escape_closes_without_drawer_focus_and_leaves_other_escape_usable(
    task_feedback, qt_application, automatic,
):
    coordinator, page, _manager, view, _sources = task_feedback()
    window = coordinator.parent()
    view["tasks"] = True
    page.show()
    page.present_action_result(_result(state="failed" if automatic else "succeeded"))
    focus = QApplication.focusWidget()
    if focus is not None:
        focus.clearFocus()
    if automatic:
        page.search_edit.setFocus()
        coordinator.open_request("fixture", automatic=True)
        assert page.search_edit.hasFocus()
    else:
        page.table.rows["action:fixture"].title.click()
    assert coordinator.drawer.opened
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert not coordinator.drawer.opened
    if not automatic:
        assert page.table.rows["action:fixture"].title.hasFocus()
    wait_until(qt_application, coordinator.drawer.isHidden)
    from PySide6.QtGui import QKeySequence, QShortcut
    other_escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), window)
    other_escape.setContext(Qt.ShortcutContext.WindowShortcut)
    received = []
    other_escape.activated.connect(lambda: received.append(True))
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert received == [True]


@pytest.mark.parametrize("source,available", [("remote", True), ("unregistered", False)])
def test_remote_source_alias_preserves_known_route_only(task_feedback, source, available):
    coordinator, page, _manager, view, requests = task_feedback()
    view["tasks"] = True
    result = _result(state="failed")
    page.present_action_result(replace(result, spec=replace(result.spec, section=source)))
    coordinator.open_request("fixture")
    row = page.detail_row("action:fixture")
    assert coordinator.drawer.source_label.text() == (tr("远程控制") if available else row.kind)
    assert requests == []
    if available:
        coordinator.drawer.source_requested.emit("action:fixture")
        assert requests == ["remote"]


@pytest.mark.parametrize("surface", ["table", "drawer"])
@pytest.mark.parametrize("gesture", ["mouse", "space"])
def test_stop_press_cannot_retarget_new_revision(task_feedback, qt_application, surface, gesture):
    owner = _Owner()
    registry = SessionTaskRegistry(lambda: (owner,))
    coordinator, page, _manager, view, _sources = task_feedback(registry)
    view["tasks"] = True
    page.show()
    coordinator._refresh_hidden_page()
    coordinator.open_entry("session:owner")
    coordinator.drawer.animation.setCurrentTime(coordinator.drawer.animation.duration())
    button = (page.table.rows["session:owner"].cancel if surface == "table"
              else coordinator.drawer.cancel_button)
    if surface == "table":
        coordinator.drawer.close_drawer(animated=False)
    button.setFocus()
    qt_application.processEvents()
    if gesture == "mouse":
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
    else:
        QTest.keyPress(button, Qt.Key.Key_Space)
    owner.snapshot = replace(owner.snapshot, revision="newer")
    coordinator._refresh_hidden_page()
    if gesture == "mouse":
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    else:
        QTest.keyRelease(button, Qt.Key.Key_Space)
    assert owner.requests == []
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert owner.requests == ["newer"]
    owner.snapshot = replace(owner.snapshot, revision="programmatic")
    coordinator._refresh_hidden_page()
    button.click()
    assert owner.requests == ["newer", "programmatic"]
    owner.close()


def test_finalizing_and_stopped_session_use_real_action_semantics(task_feedback):
    owner = _Owner(kind="performance")
    registry = SessionTaskRegistry(lambda: (owner,))
    coordinator, page, _manager, _view, _sources = task_feedback(registry)
    coordinator._refresh_hidden_page()
    coordinator.open_entry("session:owner")
    row = page.table.rows["session:owner"]
    assert row.cancel.accessibleName() == tr("停止会话")
    owner.snapshot = replace(owner.snapshot, state="finalizing", stop_enabled=False)
    coordinator._refresh_hidden_page()
    assert page.navigation_snapshot().active_count == 1
    assert not page.detail_row("session:owner").cancelling
    assert coordinator.drawer.cancel_button.isHidden()
    owner.snapshot = replace(owner.snapshot, state="cancelled", resource_owned=False)
    coordinator._refresh_hidden_page()
    assert page.detail_row("session:owner").state == tr("已停止")
    owner.close()


def _session_button(task_feedback, qt_application, surface):
    owner = _Owner()
    registry = SessionTaskRegistry(lambda: (owner,))
    coordinator, page, _manager, view, _sources = task_feedback(registry)
    view["tasks"] = True
    page.show()
    coordinator._refresh_hidden_page()
    coordinator.open_entry("session:owner")
    coordinator.drawer.animation.setCurrentTime(coordinator.drawer.animation.duration())
    button = (page.table.rows["session:owner"].cancel if surface == "table"
              else coordinator.drawer.cancel_button)
    if surface == "table":
        coordinator.drawer.close_drawer(animated=False)
    button.setFocus()
    qt_application.processEvents()
    return owner, coordinator, button


def _move_while_pressed(button, point):
    event = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(point), QPointF(button.mapToGlobal(point)),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(button, event)


@pytest.mark.parametrize("surface", ["table", "drawer"])
@pytest.mark.parametrize("finish", ["reenter", "abandon"])
def test_physical_stop_drag_keeps_original_revision_until_release(
    task_feedback, qt_application, surface, finish,
):
    owner, coordinator, button = _session_button(task_feedback, qt_application, surface)
    QTest.mousePress(button, Qt.MouseButton.LeftButton)
    outside = QPoint(-8, -8)
    _move_while_pressed(button, outside)
    owner.snapshot = replace(owner.snapshot, revision="newer")
    coordinator._refresh_hidden_page()
    if finish == "reenter":
        _move_while_pressed(button, button.rect().center())
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    else:
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=outside)
    assert owner.requests == []
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert owner.requests == ["newer"]
    owner.close()


@pytest.mark.parametrize("surface", ["table", "drawer"])
def test_space_autorepeat_does_not_start_a_new_stop_gesture(
    task_feedback, qt_application, surface,
):
    owner, coordinator, button = _session_button(task_feedback, qt_application, surface)
    QTest.keyPress(button, Qt.Key.Key_Space)
    owner.snapshot = replace(owner.snapshot, revision="newer")
    coordinator._refresh_hidden_page()
    for kind in (QEvent.Type.KeyRelease, QEvent.Type.KeyPress):
        QApplication.sendEvent(button, QKeyEvent(
            kind, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ", True, 1,
        ))
    QTest.keyRelease(button, Qt.Key.Key_Space)
    assert owner.requests == []
    QTest.keyClick(button, Qt.Key.Key_Space)
    assert owner.requests == ["newer"]
    owner.close()


@pytest.mark.parametrize("surface", ["table", "drawer"])
def test_stopping_resource_retry_uses_owner_admission_in_both_buttons(
    task_feedback, qt_application, surface,
):
    owner, coordinator, button = _session_button(task_feedback, qt_application, surface)
    owner.snapshot = replace(owner.snapshot, state="stopping", stop_enabled=True)
    coordinator._refresh_hidden_page()
    assert button.isEnabled()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert owner.requests == ["earlier"]
    owner.snapshot = replace(owner.snapshot, stop_enabled=False)
    coordinator._refresh_hidden_page()
    assert not button.isEnabled()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert owner.requests == ["earlier"]
    assert coordinator.page.navigation_snapshot().active_count == 1
    owner.snapshot = replace(owner.snapshot, state="finalizing")
    coordinator._refresh_hidden_page()
    assert button.isHidden()
    assert coordinator.page.navigation_snapshot().active_count == 1
    owner.close()


@pytest.mark.parametrize("boundary", ["tab", "hide", "disable", "deactivate"])
def test_cancelled_keyboard_gesture_cannot_stop_previous_owner_on_new_ax_click(
    task_feedback, qt_application, boundary,
):
    owner_a, owner_b = _Owner("a"), _Owner("b")
    registry = SessionTaskRegistry(lambda: (owner_a, owner_b))
    coordinator, _page, _manager, _view, _sources = task_feedback(registry)
    window = coordinator.parent()
    coordinator._refresh_hidden_page()
    coordinator.open_entry("session:a")
    drawer = coordinator.drawer
    drawer.animation.setCurrentTime(drawer.animation.duration())
    button = drawer.cancel_button
    button.setFocus()
    wait_until(qt_application, button.hasFocus)
    QTest.keyPress(button, Qt.Key.Key_Space)
    assert button.isDown()
    other = None
    try:
        if boundary == "tab":
            QTest.keyClick(button, Qt.Key.Key_Tab)
        elif boundary == "hide":
            button.hide()
        elif boundary == "disable":
            button.setEnabled(False)
        else:
            other = QWidget()
            target = QPushButton("另一个窗口", other)
            other.show()
            other.activateWindow()
            target.setFocus()
            wait_until(qt_application, lambda: QApplication.activeWindow() is other)
        focus = QApplication.focusWidget()
        assert focus is not button
        assert not button.isDown()
        QTest.keyRelease(focus or window, Qt.Key.Key_Space)
        if other is not None:
            other.close()
            window.activateWindow()
            wait_until(qt_application, lambda: QApplication.activeWindow() is window)
        assert coordinator.open_entry("session:b")
        assert drawer.selected_key == "session:b"
        assert button.isVisible() and button.isEnabled()
        button.click()
        assert owner_a.requests == []
        assert owner_b.requests == ["earlier"]
    finally:
        if other is not None:
            other.close()
        owner_a.close()
        owner_b.close()


@pytest.mark.parametrize("surface", ["table", "drawer"])
def test_mouse_gesture_keeps_identity_when_focus_changes_while_pressed(
    task_feedback, qt_application, surface,
):
    owner, coordinator, button = _session_button(task_feedback, qt_application, surface)
    target = QPushButton("外部焦点", coordinator.parent())
    target.show()
    QTest.mousePress(button, Qt.MouseButton.LeftButton)
    target.setFocus()
    assert not button.hasFocus()
    _move_while_pressed(button, QPoint(-8, -8))
    owner.snapshot = replace(owner.snapshot, revision="newer")
    coordinator._refresh_hidden_page()
    _move_while_pressed(button, button.rect().center())
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    assert owner.requests == []
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert owner.requests == ["newer"]
    owner.close()


def test_native_minimized_snapshots_consume_success_without_running_presentation(
    task_feedback, qt_application,
):
    coordinator, page, _manager, _view, _sources = task_feedback()
    window = coordinator.parent()
    cocoa = QApplication.platformName() == "cocoa"
    page.present_action_result(_result())
    window.showMinimized()
    # Cocoa 先发布 Qt 状态，再完成原生映射；过早 showNormal 会收到晚到的最小化事件。
    # offscreen 不模拟原生曝光变化，仍按相同窗口状态验收全部业务门控。
    wait_until(qt_application, lambda: (
        window.isMinimized() and (
            not cocoa or window.windowHandle() is not None
            and not window.windowHandle().isExposed()
        )
    ))
    assert window.isMinimized()
    page.present_action_result(_result(state="succeeded"))
    button = coordinator.navigation_button
    assert not button._presentation_enabled
    assert not button._animation_timer.isActive()
    assert not button._success_timer.isActive()
    window.showNormal()
    wait_until(qt_application, lambda: (
        window.isVisible() and not window.isMinimized() and button.isVisible()
        and (not cocoa or window.windowHandle() is not None and window.windowHandle().isExposed())
    ))
    assert button._presentation_enabled
    assert not button._success_visible
    assert not button._success_timer.isActive()
    page.present_action_result(_result("active-again"))
    assert page.navigation_snapshot().active_count == 1
    assert button._animation_timer.isActive(), {
        "minimized": window.isMinimized(),
        "window_visible": window.isVisible(),
        "button_visible": button.isVisible(),
        "presentation_enabled": button._presentation_enabled,
        "exposed": window.windowHandle().isExposed(),
        "snapshot": button._snapshot,
    }


@pytest.fixture
def native_frame(qt_application, monkeypatch):
    if sys.platform == "darwin":
        assert QApplication.platformName() == "cocoa", "macOS MainFrame 必须使用 Cocoa"
    from tests.test_main_window_layout import build_main_frame
    from tests.ui_lifecycle_helpers import cleanup_ui_windows
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    frame = build_main_frame()
    frame.show()
    qt_application.processEvents()
    try:
        yield frame
    finally:
        assert not cleanup_ui_windows((frame,), cleanup_records={})


def _install_owner(frame, device, *, kind="logcat"):
    from gui.features.base import FeatureSessionKey
    host = frame._workspace_feature_hosts["system"]
    key = FeatureSessionKey(kind, device, 0)
    owner, _created = host.registry.get_or_create(
        key, lambda _key: _Owner(f"session:original-{device}", kind=kind),
    )
    host.stack.addWidget(owner)
    return host, key, owner


def test_native_hidden_disposal_preserves_foreground_task_then_front_route_dismisses(
    native_frame, qt_application,
):
    frame = native_frame
    host, key, owner = _install_owner(frame, "device-A")
    assert frame._open_workspace_feature("system", "logcat", device_id="device-A")
    host.registry.request_dispose(key)
    frame._on_nav_requested("tasks")
    frame._task_page.present_action_result(_result(state="succeeded"))
    frame._task_feedback.open_request("fixture")
    owner.dispose_ready.emit(key)
    qt_application.processEvents()
    assert frame._task_feedback.drawer.opened
    assert frame._task_page.selected_key == "action:fixture"
    frame._open_workspace_feature("apps", "overview")
    assert not frame._task_feedback.drawer.opened
    frame._task_feedback.open_request("fixture")
    frame._open_workspace_feature("apps", "overview")
    assert frame._task_feedback.drawer.opened
    frame._open_workspace_feature("apps", "packages")
    assert not frame._task_feedback.drawer.opened


@pytest.mark.parametrize("kind", ["logcat", "performance"])
def test_native_session_source_opens_original_existing_owner_and_never_replaces_removed(
    native_frame, qt_application, kind,
):
    frame = native_frame
    host, key_a, owner_a = _install_owner(frame, "device-A", kind=kind)
    _host, _key_b, owner_b = _install_owner(frame, "device-B", kind=kind)
    frame._open_workspace_feature("system", kind, device_id="device-B")
    frame._on_nav_requested("tasks")
    selection = tuple(frame.left_panel.selected_devices)
    coordinator = frame._task_feedback
    coordinator._refresh_hidden_page()
    before = host.registry.keys()
    task_key = "session:" + owner_a.snapshot.key
    coordinator.open_entry(task_key)
    coordinator.drawer.source_requested.emit(task_key)
    assert host.stack.currentWidget() is owner_a
    assert host.registry.keys() == before
    assert tuple(frame.left_panel.selected_devices) == selection
    frame._open_workspace_feature("system", kind, device_id="device-B")
    frame._on_nav_requested("tasks")
    coordinator.open_entry(task_key)
    host.registry.remove(key_a)
    coordinator.drawer.source_requested.emit(task_key)
    qt_application.processEvents()
    assert host.stack.currentWidget() is owner_b
    assert key_a not in host.registry.keys()
    assert len(host.registry.keys()) == 1
    assert tuple(frame.left_panel.selected_devices) == selection
    owner_a.deleteLater()


def test_native_remote_projection_keeps_global_labels_for_single_and_batch_after_offline(
    native_frame,
):
    from gui.panels.remote_panel_scrcpy import RemoteDeviceSession
    from services.remote.types import ScrcpyConfig
    frame = native_frame
    remote = frame.left_panel.remote_panel
    bar = frame._global_device_bar
    devices = ("fixture-first", "fixture-second", "fixture-third")
    bar.set_context([], devices, "ready")

    def member(device):
        config = ScrcpyConfig("", "", device, "1280", "60", "8M", "h264", "0", "0")
        return RemoteDeviceSession(config, state="ready", resource_owned=True)

    remote._device_sessions = {devices[2]: member(devices[2])}
    coordinator = frame._task_feedback
    try:
        coordinator._refresh_hidden_page()
        snapshot = remote.task_snapshot()
        key = "session:" + snapshot.key
        assert frame._task_page.detail_row(key).target == bar.device_label(devices[2])
        assert bar.device_label(devices[2]) == tr("设备 {number}").format(number=3)
        remote._device_sessions[devices[1]] = member(devices[1])
        coordinator._refresh_hidden_page()
        expected = " · ".join((bar.device_label(devices[2]), bar.device_label(devices[1])))
        assert frame._task_page.detail_row(key).target == expected
        bar.set_context([], [], "ready")
        remote.set_target_devices([])
        remote.set_connected_devices([])
        coordinator._refresh_hidden_page()
        assert frame._task_page.detail_row(key).target == expected
        frame._on_nav_requested("tasks")
        coordinator.open_entry(key)
        coordinator.drawer.source_requested.emit(key)
        assert frame._workspace_feature_hosts["devices"].current_feature == "remote"
        assert frame.left_panel.remote_panel is remote
        assert tuple(frame.left_panel.selected_devices) == ()
    finally:
        for session in remote._device_sessions.values():
            session.resource_owned = False
            session.state = "stopped"
