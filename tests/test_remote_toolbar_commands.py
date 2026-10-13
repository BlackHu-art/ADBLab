"""从侧栏真实点击验证固定会话队列到设备命令边界，不连接真实设备。"""

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QScrollArea, QToolButton, QWidget

from core.exec import CommandResult
from gui.panels.remote_panel_dock import RemotePanelDock
from gui.panels.remote_panel_input import RemotePanelInput
from services.remote.control_service import RemoteControlService
from tests.test_remote_dock import Frame, Tracker, session
from tests.test_remote_session_input import QueuedExecutor

pytestmark = pytest.mark.ui


EXPECTED_COMMANDS = (
    ("BACK", (("input", "keyevent 4"),)),
    ("HOME", (("input", "keyevent 3"),)),
    ("RECENTS", (("input", "keyevent 187"),)),
    ("VOL_UP", (("input", "keyevent 24"),)),
    ("VOL_DOWN", (("input", "keyevent 25"),)),
    ("POWER", (("input", "keyevent 26"),)),
    ("rotate_portrait", (
        ("shell", "settings put system accelerometer_rotation 0"),
        ("shell", "settings put system user_rotation 0"),
    )),
    ("rotate_landscape", (
        ("shell", "settings put system accelerometer_rotation 0"),
        ("shell", "settings put system user_rotation 1"),
    )),
    ("notif_expand", (("input", "swipe 540 0 540 1919 300"),)),
    ("notif_collapse", (("input", "swipe 540 1919 540 0 300"),)),
    ("swipe_up", (("input", "swipe 540 1728 540 192 300"),)),
    ("swipe_down", (("input", "swipe 540 192 540 1728 300"),)),
    ("swipe_left", (("input", "swipe 972 960 108 960 300"),)),
    ("swipe_right", (("input", "swipe 108 960 972 960 300"),)),
    ("MENU", (("input", "keyevent 82"),)),
    ("ENTER", (("input", "keyevent 66"),)),
    ("DEL", (("input", "keyevent 67"),)),
    ("SETTINGS", (("shell", "am start -a android.settings.SETTINGS 2>&1"),)),
    ("CAMERA", (("input", "keyevent 27"),)),
    ("SEARCH", (("input", "keyevent 84"),)),
    ("MEDIA_PREV", (("input", "keyevent 88"),)),
    ("MEDIA_PLAY", (("input", "keyevent 85"),)),
    ("MEDIA_NEXT", (("input", "keyevent 87"),)),
)


LANDSCAPE_COMMANDS = {
    "notif_expand": (("input", "swipe 960 0 960 1079 300"),),
    "notif_collapse": (("input", "swipe 960 1079 960 0 300"),),
    "swipe_up": (("input", "swipe 960 972 960 108 300"),),
    "swipe_down": (("input", "swipe 960 108 960 972 300"),),
    "swipe_left": (("input", "swipe 1728 540 192 540 300"),),
    "swipe_right": (("input", "swipe 192 540 1728 540 300"),),
}


class CommandRecorder:
    def __init__(self):
        self.commands = []

    def get_dimensions(self, *, device_id, cancelled):
        assert device_id in {"a", "b"} and not cancelled()
        return 1080, 1920

    def shell_input(self, command, *, device_id, cancelled):
        assert not cancelled()
        self.commands.append((device_id, "input", command))
        return True

    def shell(self, command, *, device_id, cancelled):
        assert not cancelled()
        if command == "dumpsys input":
            width, height = (1080, 1920) if device_id == "a" else (1920, 1080)
            return CommandResult(success=True, output=(
                f"Viewport INTERNAL: displayId=0, uniqueId=fixture, port=0, orientation=0, "
                f"logicalFrame=[0, 0, {width}, {height}], physicalFrame=[0, 0, 1080, 1920], "
                "deviceSize=[1080, 1920], isActive=[1]"
            ))
        self.commands.append((device_id, "shell", command))
        return CommandResult(success=True)


@pytest.mark.parametrize(("code", "expected"), EXPECTED_COMMANDS, ids=[
    code for code, _ in EXPECTED_COMMANDS
])
def test_each_toolbar_button_reaches_its_device_command_after_selection_change(
    qt_application, code, expected,
):
    owner, frame = QWidget(), Frame()
    frame._device_sessions = {"a": session("a"), "b": session("b", 200)}
    frame._remote_executor = executor = QueuedExecutor()
    frame._remote_control = RemoteControlService(bridge := CommandRecorder())
    lifecycle_lock = threading.Lock()
    frame._shutdown_lifecycle_lock = lambda: lifecycle_lock
    frame._remote_queue_status_requested = SimpleNamespace(emit=lambda *_: None)
    frame._log = lambda *_: None
    frame._input_controller = controller = RemotePanelInput(frame)
    for name in (
        "_mark_remote_submitted", "_mark_remote_completed", "_emit_remote_queue_status",
        "_remote_input_succeeded",
    ):
        setattr(frame, name, getattr(controller, name))
    dock = RemotePanelDock(frame, owner, tracker_factory=Tracker)
    try:
        dock.sync()
        for device in ("a", "b"):
            toolbar = dock.entries[device].toolbar
            more = toolbar.findChild(QToolButton, "remoteToolbarMore")
            QTest.mouseClick(more, Qt.MouseButton.LeftButton)
            qt_application.processEvents()
            popup = toolbar.popup_window
            button = toolbar.findChild(QAbstractButton, f"remoteToolbarCommand_{code}")
            assert button is not None
            if button.window() is popup:
                popup.findChild(QScrollArea).ensureWidgetVisible(button)
                qt_application.processEvents()
            before = len(bridge.commands)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            assert len(bridge.commands) == before, "设备命令须进入队列而非阻塞鼠标事件"
            frame.selected_devices = ["b" if device == "a" else "a"]
            frame._device_admission_revision = getattr(frame, "_device_admission_revision", 0) + 1
            executor.drain()
            device_expected = LANDSCAPE_COMMANDS.get(code, expected) if device == "b" else expected
            assert bridge.commands[before:] == [
                (device, kind, command) for kind, command in device_expected
            ]
            assert popup.isVisible()
            QTest.mouseClick(more, Qt.MouseButton.LeftButton)
        assert frame._remote_sent == frame._remote_submitted == frame._remote_completed == 2
        assert getattr(frame, "_remote_failed", 0) == 0
    finally:
        dock.close()
        owner.close()
