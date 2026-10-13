"""验证投屏侧栏的会话归属、窗口跟随与资源清理。"""

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QAbstractButton, QWidget

pytestmark = pytest.mark.ui


def test_dock_placement_prefers_right_then_left_and_clamps_negative_monitor():
    from gui.panels.remote_panel_dock import dock_geometry

    assert dock_geometry((100, 100, 400, 600), (0, 0, 1200, 900), (56, 340)) == (508, 112, 56, 340)
    assert dock_geometry((780, 100, 400, 600), (0, 0, 1200, 900), (56, 340)) == (716, 112, 56, 340)
    assert dock_geometry(
        (-1920, 0, 1920, 1080), (-1920, 0, 1920, 1040), (32, 80),
    ) == (-40, 12, 32, 80)


class Frame(QObject):
    def __init__(self):
        super().__init__()
        self._device_sessions = {}
        self._connected_remote_devices = frozenset({"a", "b"})
        self._closing = self._remote_input_closing = False
        self.calls, self.invalidated = [], []
        self._input_controller = SimpleNamespace(
            _send_session_keyevent=lambda session, key: self.calls.append((session, key)),
            _send_session_action=lambda session, action: self.calls.append((session, action)),
            _invalidate_session_input=lambda session: self.invalidated.append(session),
        )

    def _mirror_device_name(self, device):
        return "演示设备 " + device.upper()


class Tracker:
    supported = True
    lost = False

    def __init__(self, pid, title):
        self.pid, self.title = pid, title
        self.positions = []
        self.current = SimpleNamespace(
            hwnd=pid, pid=pid, rect=(100, 100, 400, 600),
            work_area=(0, 0, 1200, 900), visible=True, minimized=False,
            foreground=True, topmost=False, dpi=96,
            foreground_hwnd=pid,
        )

    def snapshot(self):
        return self.current

    def position_tool(self, hwnd, owner, rect):
        self.positions.append(rect)
        return True


class UnsupportedTracker:
    supported = False

    def __init__(self, _pid, _title):
        pass

    def snapshot(self):
        raise AssertionError("便携工具栏不能依赖不可用的原生窗口查询")

    def position_tool(self, *_args):
        raise AssertionError("便携工具栏不能使用原生窗口定位")


def session(device, pid=100):
    return SimpleNamespace(
        config=SimpleNamespace(device=device, no_window=False, window_title="mirror-" + device),
        process=SimpleNamespace(pid=pid, poll=lambda: None), state="ready", resource_owned=True,
        cancel_event=threading.Event(),
    )


def test_unsupported_platform_shows_each_session_toolbar_and_preserves_its_target(qt_application):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QToolButton

    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    first, second = session("a"), session("b", 200)
    frame._device_sessions = {"a": first, "b": second}
    frame.selected_devices = ["b"]
    dock = RemotePanelDock(frame, owner, tracker_factory=UnsupportedTracker)
    try:
        dock.sync()
        assert set(dock.entries) == {"a", "b"}
        for device, target in (("a", first), ("b", second)):
            toolbar = dock.entries[device].toolbar
            assert toolbar.isVisible()
            more = toolbar.findChild(QToolButton, "remoteToolbarMore")
            QTest.mouseClick(more, Qt.MouseButton.LeftButton)
            assert toolbar.popup_window.isVisible()
            assert toolbar.popup_window.window() is toolbar
            button = toolbar.findChild(QAbstractButton, "remoteToolbarCommand_HOME")
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            assert frame.calls[-1] == (target, "HOME")
        dock.sync()
        assert len(dock.entries) == 2
        assert len(frame.calls) == 2
        frame._connected_remote_devices = frozenset({"b"})
        dock.tick()
        first_toolbar = dock.entries["a"].toolbar
        assert not first_toolbar.popup_window.isVisible()
        assert not first_toolbar.findChild(QAbstractButton, "remoteToolbarCommand_HOME").isEnabled()
        first_toolbar.key_requested.emit("HOME")
        assert len(frame.calls) == 2
    finally:
        dock.close()
        owner.close()


def test_portable_toolbar_retires_on_exit_and_old_callbacks_cannot_target_replacement(
    qt_application,
):
    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    first = session("a")
    frame._device_sessions = {"a": first}
    dock = RemotePanelDock(frame, owner, tracker_factory=UnsupportedTracker)
    try:
        dock.sync()
        assert "a" in dock.entries
        old = dock.entries["a"].toolbar
        first.process.poll = lambda: 0
        dock.tick()
        assert not dock.entries
        assert not old.isVisible()
        assert not dock.timer.isActive()
        assert frame.invalidated == [first]
        replacement = session("a", 300)
        frame._device_sessions["a"] = replacement
        dock.sync()
        assert dock.entries["a"].toolbar is not old
        old.key_requested.emit("HOME")
        assert frame.calls == []
        dock.entries["a"].toolbar.key_requested.emit("HOME")
        assert frame.calls == [(replacement, "HOME")]
        dock.close()
        assert not dock.entries
        assert not dock.timer.isActive()
    finally:
        dock.close()
        owner.close()


def test_dock_lifecycle_keeps_target_and_hides_popup_on_minimize(qt_application):
    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    first, second = session("a"), session("b", 200)
    frame._device_sessions = {"a": first, "b": second}
    dock = RemotePanelDock(frame, owner, tracker_factory=Tracker)
    try:
        dock.sync()
        assert len(dock.entries) == 2
        entry = dock.entries["a"]
        dock.tick()
        entry.toolbar.key_requested.emit("HOME")
        assert frame.calls == [(first, "HOME")]
        entry.tracker.current.rect = (200, 180, 420, 620)
        dock.tick()
        assert entry.tracker.positions[-1][:2] == (628, 192)
        entry.tracker.current.minimized = True
        dock.tick()
        assert not entry.toolbar.isVisible()
        assert not entry.toolbar.popup_window.isVisible()
        entry.tracker.current.minimized = False
        dock.tick()
        assert entry.toolbar.isVisible()
        first.cancel_event.set()
        first.state = "stopping"
        dock.sync()
        assert "a" not in dock.entries
        assert first in frame.invalidated
        assert "b" in dock.entries
        dock.close()
        assert not dock.timer.isActive()
        assert not dock.entries
    finally:
        dock.close()
        owner.close()


def test_closed_window_cannot_rebind_or_send_to_replacement_session(qt_application):
    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    first = session("a")
    frame._device_sessions = {"a": first}
    dock = RemotePanelDock(frame, owner, tracker_factory=Tracker)
    try:
        dock.sync()
        entry = dock.entries["a"]
        entry.tracker.lost, entry.tracker.current = True, None
        dock.tick()
        dock.sync()
        assert not dock.entries
        entry.toolbar.key_requested.emit("HOME")
        assert not frame.calls
        replacement = session("a", 300)
        frame._device_sessions["a"] = replacement
        dock.sync()
        assert dock.entries["a"].session is replacement
        entry.toolbar.key_requested.emit("HOME")
        assert not frame.calls
    finally:
        dock.close()
        owner.close()


@pytest.mark.parametrize(
    "tracker_factory", (Tracker, UnsupportedTracker), ids=("native", "portable"),
)
def test_destroyed_view_revokes_session_and_destroys_timer_and_tools(
    qt_application, tracker_factory,
):
    from shiboken6 import delete, isValid

    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    original = session("a")
    frame._device_sessions = {"a": original}
    dock = RemotePanelDock(frame, owner, tracker_factory=tracker_factory)
    dock.sync()
    timer, toolbar = dock.timer, dock.entries["a"].toolbar
    delete(owner)
    assert frame.invalidated == [original]
    assert not isValid(timer)
    assert not isValid(toolbar)


def test_record_only_session_does_not_create_window_tracker(qt_application):
    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    original = session("a")
    original.config.no_window = True
    frame._device_sessions = {"a": original}
    calls = []
    dock = RemotePanelDock(frame, owner, tracker_factory=lambda *args: calls.append(args))
    try:
        dock.sync()
        assert not calls
        assert not dock.entries
        assert not dock.timer.isActive()
    finally:
        dock.close()
        owner.close()


def test_more_dismisses_on_foreground_change_but_opens_for_background_target(qt_application):
    from PySide6.QtWidgets import QToolButton

    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    frame._device_sessions = {"a": session("a")}
    dock = RemotePanelDock(frame, owner, tracker_factory=Tracker)
    try:
        dock.sync()
        entry = dock.entries["a"]
        entry.tracker.current.foreground = False
        entry.tracker.current.foreground_hwnd = 700
        dock.tick()
        entry.toolbar.findChild(QToolButton, "remoteToolbarMore").click()
        dock.tick()
        assert entry.toolbar.popup_window.isVisible()
        entry.tracker.current.foreground_hwnd = 800
        dock.tick()
        assert not entry.toolbar.popup_window.isVisible()
    finally:
        dock.close()
        owner.close()


@pytest.mark.parametrize("code", ["rotate_portrait", "MEDIA_PLAY"])
def test_more_mouse_click_delivers_to_its_session_across_tracking_tick(qt_application, code):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractButton, QScrollArea, QToolButton

    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    first, second = session("a"), session("b", 200)
    frame._device_sessions = {"a": first, "b": second}
    frame.selected_devices = ["b"]
    dock = RemotePanelDock(frame, owner, tracker_factory=Tracker)
    try:
        dock.sync()
        for device, expected in (("a", first), ("b", second)):
            toolbar = dock.entries[device].toolbar
            more = toolbar.findChild(QToolButton, "remoteToolbarMore")
            QTest.mouseClick(more, Qt.MouseButton.LeftButton)
            qt_application.processEvents()
            popup = toolbar.popup_window
            button = popup.findChild(QAbstractButton, f"remoteToolbarCommand_{code}")
            popup.findChild(QScrollArea).ensureWidgetVisible(button)
            qt_application.processEvents()
            for _ in range(2):
                before = len(frame.calls)
                QTest.mousePress(button, Qt.MouseButton.LeftButton)
                dock.tick()
                assert popup.isVisible(), "面板内部按下不能被当成外部点击提前收起"
                assert len(frame.calls) == before
                QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
                dock.tick()
                assert frame.calls[before:] == [(expected, code)]
                assert popup.isVisible(), "执行操作后应保留面板以便连续控制同一设备"
                assert more.isChecked()
            QTest.mouseClick(more, Qt.MouseButton.LeftButton)
            assert not popup.isVisible()
            assert not more.isChecked()
        assert frame.calls == [(first, code), (first, code), (second, code), (second, code)]
    finally:
        dock.close()
        owner.close()


def test_main_form_omits_standalone_controller_button_and_entry_section(
    qt_application, monkeypatch, isolated_app_settings,
):
    from gui.i18n import tr
    from tests.test_responsive_panels import _close_feature_panel, _show_feature_panel

    panel, remote, _scroll, content = _show_feature_panel(
        "remote", 780, 12, qt_application, monkeypatch,
    )
    try:
        assert not any(button.text() == tr("打开独立遥控器")
                       for button in content.findChildren(QAbstractButton))
        assert content.findChild(QWidget, "remoteControllerEntry") is None
        assert not remote._standalone_remote.isVisible()
        assert len(remote._remote_control_buttons) == 23
        assert all(button.window() is remote._standalone_remote
                   for button in remote._remote_control_buttons)
        assert remote.maxsize.isVisibleTo(content)
    finally:
        _close_feature_panel(panel)


def test_controller_resize_alone_reflows_without_resizing_main_page(
    qt_application, monkeypatch, isolated_app_settings,
):
    from tests.test_responsive_panels import _close_feature_panel, _show_feature_panel
    from tests.ui_geometry_helpers import wait_until

    panel, remote, _scroll, _content = _show_feature_panel(
        "remote", 780, 12, qt_application, monkeypatch,
    )
    try:
        window = remote._standalone_remote
        window.show()
        qt_application.processEvents()
        window.resize(1100, 500)
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        initial_columns = remote._remote_navigation_binding.applied_plan.mode.columns
        window.resize(270, 500)
        wait_until(qt_application, lambda: (
            remote._remote_navigation_binding.applied_plan.mode.columns < initial_columns
        ))
        assert remote._remote_navigation_binding.applied_plan.mode.columns < initial_columns
    finally:
        _close_feature_panel(panel)
