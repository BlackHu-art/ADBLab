"""会话工具栏固定目标与现有广播队列的准入边界。"""

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from core.exec import CommandResult
from gui.panels.remote_panel_input import RemotePanelInput
from services.remote.control_service import RemoteControlService


class QueuedExecutor:
    def __init__(self):
        self.pending = []

    def submit(self, task):
        future = Future()
        self.pending.append((task, future))
        return future

    def drain(self):
        while self.pending:
            task, future = self.pending.pop(0)
            future.set_result(task())


class RecordingBridge:
    def __init__(self):
        self.commands = []
        self.before_input = None

    def get_dimensions(self, *, device_id, cancelled):
        return (1080, 1920)

    def shell(self, command, *, device_id, cancelled):
        assert command == "dumpsys input"
        if cancelled():
            return CommandResult(success=False, error="Cancelled")
        return CommandResult(success=True, output=(
            "Viewport INTERNAL: displayId=0, orientation=0, "
            "logicalFrame=[0, 0, 1080, 1920], isActive=[1]"
        ))

    def shell_input(self, command, *, device_id, cancelled):
        if self.before_input is not None:
            self.before_input(cancelled)
        if cancelled():
            return False
        self.commands.append((device_id, command))
        return True


def session(device="device-a", state="ready"):
    return SimpleNamespace(
        config=SimpleNamespace(device=device), state=state,
        resource_owned=True, cancel_event=threading.Event(),
    )


@pytest.fixture
def inputs():
    bridge = RecordingBridge()
    executor = QueuedExecutor()
    current = session()
    lifecycle = threading.Lock()
    frame = SimpleNamespace(
        selected_devices=["device-a"], _device_sessions={"device-a": current},
        _connected_remote_devices=None, _device_admission_revision=0,
        _remote_control=RemoteControlService(bridge), _remote_executor=executor,
        _closing=False, _remote_input_closing=False,
        _shutdown_lifecycle_lock=lambda: lifecycle,
        _remote_queue_status_requested=SimpleNamespace(emit=lambda *_: None),
        _log=lambda *_: None, futures=[],
    )
    controller = RemotePanelInput(frame)
    frame._can_operate_device = lambda: bool(frame.selected_devices) and not frame._closing
    frame._track_remote_future = frame.futures.append
    for name in (
        "_mark_remote_submitted", "_mark_remote_completed", "_emit_remote_queue_status",
        "_remote_input_succeeded", "_submit_remote_input",
    ):
        setattr(frame, name, getattr(controller, name))
    return controller, frame, current, executor, bridge


@pytest.mark.parametrize("selected", [[], ["device-b"]])
def test_queued_session_input_retains_target_after_selection_changes(inputs, selected):
    controller, frame, current, executor, bridge = inputs
    controller._send_session_keyevent(current, "HOME")
    frame.selected_devices = selected
    frame._device_admission_revision += 1

    executor.drain()

    assert bridge.commands == [("device-a", "keyevent 3")]
    assert frame._remote_sent == 1
    assert len(frame.futures) == 1 and frame.futures[0].done()


@pytest.mark.parametrize("state", ["connecting", "ready", "running"])
def test_session_action_accepts_deselected_connected_target(inputs, state):
    controller, frame, current, executor, bridge = inputs
    current.state = state
    controller._set_connected_devices(["device-a", "device-b"])
    frame.selected_devices = ["device-b"]

    controller._send_session_action(current, "swipe_up")
    executor.drain()

    assert bridge.commands == [("device-a", "swipe 540 1728 540 192 300")]


def test_replacement_invalidates_old_queue_and_rejects_old_toolbar(inputs):
    controller, frame, old, executor, bridge = inputs
    controller._send_session_keyevent(old, "HOME")
    controller._invalidate_session_input(old)
    frame._device_sessions["device-a"] = replacement = session()
    controller._send_session_keyevent(old, "BACK")
    controller._send_session_keyevent(replacement, "RECENTS")
    executor.drain()

    assert bridge.commands == [("device-a", "keyevent 187")]
    assert frame._remote_submitted == 2
    assert frame._remote_failed == 1


def test_disconnect_revokes_old_queue_even_after_reconnect(inputs):
    controller, frame, current, executor, bridge = inputs
    controller._set_connected_devices(["device-a"])
    controller._send_session_keyevent(current, "HOME")
    controller._set_connected_devices([])
    controller._send_session_keyevent(current, "BACK")
    controller._set_connected_devices(["device-a"])
    controller._send_session_keyevent(current, "RECENTS")
    executor.drain()

    assert bridge.commands == [("device-a", "keyevent 187")]
    assert frame._remote_submitted == 2
    assert frame._remote_failed == 1


@pytest.mark.parametrize("state", ["preparing", "stopping", "stopped", "failed"])
def test_inactive_session_cannot_submit_input(inputs, state):
    controller, frame, current, executor, bridge = inputs
    current.state = state

    controller._send_session_keyevent(current, "HOME")
    executor.drain()

    assert bridge.commands == []
    assert frame.futures == []


@pytest.mark.parametrize("reason", ["released", "cancelled", "closing"])
def test_unavailable_session_cannot_submit_input(inputs, reason):
    controller, frame, current, executor, bridge = inputs
    if reason == "released":
        current.resource_owned = False
    elif reason == "cancelled":
        current.cancel_event.set()
    else:
        frame._remote_input_closing = True

    controller._send_session_keyevent(current, "HOME")
    executor.drain()

    assert bridge.commands == []
    assert frame.futures == []


@pytest.mark.parametrize("reason", ["stop", "shutdown", "offline"])
def test_inflight_session_input_observes_cancellation(inputs, reason):
    controller, frame, current, _, bridge = inputs
    entered, released = threading.Event(), threading.Event()
    observed = []

    def wait_for_cancel(cancelled):
        entered.set()
        observed.append((released.wait(2), cancelled()))

    bridge.before_input = wait_for_cancel
    with ThreadPoolExecutor(max_workers=1) as executor:
        frame._remote_executor = executor
        controller._send_session_action(current, "swipe_up")
        try:
            assert entered.wait(2)
            if reason == "stop":
                current.cancel_event.set()
                controller._invalidate_session_input(current)
            elif reason == "offline":
                controller._set_connected_devices([])
            else:
                frame._remote_input_closing = True
        finally:
            released.set()
        frame.futures[0].result(2)

    assert observed == [(True, True)]
    assert bridge.commands == []
    assert frame._remote_failed == 1


def test_session_stop_event_revokes_queued_input(inputs):
    controller, frame, current, executor, bridge = inputs
    controller._send_session_keyevent(current, "HOME")
    current.cancel_event.set()
    executor.drain()

    assert bridge.commands == []
    assert frame._remote_failed == 1


def test_broadcast_keeps_selection_revision_cancellation(inputs):
    controller, frame, current, executor, bridge = inputs
    frame.selected_devices = ["device-a", "device-b"]
    controller._send_keyevent("HOME")
    controller._send_session_keyevent(current, "BACK")
    frame.selected_devices = ["device-b"]
    frame._device_admission_revision += 1
    executor.drain()

    assert bridge.commands == [("device-a", "keyevent 4")]
    assert frame._remote_failed == 2
    controller._send_keyevent("HOME")
    executor.drain()
    assert bridge.commands[-1] == ("device-b", "keyevent 3")
