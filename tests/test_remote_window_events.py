from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

import pytest

from services.remote import window_tracking


class FakeNativeFunction:
    def __init__(self, call):
        self.call = call
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.call(*args)


class FakeUser32:
    def __init__(self, *, fail_at=0):
        self.registered = []
        self.removed = []
        self.callbacks = []
        self.fail_at = fail_at
        self.SetWinEventHook = FakeNativeFunction(self._set_hook)
        self.UnhookWinEvent = FakeNativeFunction(self._unhook)

    def _set_hook(self, event_min, event_max, module, callback, pid, thread, flags):
        handle = 0x100000000 + len(self.registered) + 1
        self.registered.append((handle, event_min, event_max, module, pid, thread, flags))
        self.callbacks.append(callback)
        if len(self.registered) == self.fail_at:
            return 0
        return handle

    def _unhook(self, handle):
        self.removed.append(handle)
        return True

    def emit(self, event, hwnd=21, object_id=0, child_id=0):
        for registration, callback in zip(self.registered, self.callbacks):
            handle, event_min, event_max, _module, _pid, _thread, _flags = registration
            if event_min <= event <= event_max:
                callback(handle, event, hwnd, object_id, child_id, 99, 1234)


def _subscribe(monkeypatch, user, callback):
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    api = object.__new__(window_tracking._Win32WindowApi)
    api._user32 = user
    subscribe = getattr(api, "subscribe_changes", None)
    assert callable(subscribe), "Win32 后端应提供可释放的窗口变化订阅"
    return subscribe(21, 200, callback)


def test_native_events_scope_process_and_preserve_pointer_width(monkeypatch):
    user = FakeUser32()
    changes = []
    subscription = _subscribe(monkeypatch, user, lambda: changes.append(True))

    assert subscription.active
    assert len(user.registered) == 3
    for _handle, event_min, event_max, module, pid, thread, flags in user.registered:
        assert module is None
        assert thread == 0
        assert flags == 0  # WINEVENT_OUTOFCONTEXT
        if event_min == 3:
            assert event_max == 3
            assert pid == 0
        else:
            assert pid == 200
    assert user.SetWinEventHook.restype is wintypes.HANDLE
    assert user.UnhookWinEvent.argtypes == [wintypes.HANDLE]
    native_callback = user.callbacks[0]
    assert native_callback._argtypes_[0] is wintypes.HANDLE
    assert native_callback._argtypes_[2] is wintypes.HWND

    user.emit(0x800B)
    assert changes == [True]
    subscription.close()
    subscription.close()
    assert not subscription.active
    assert sorted(user.removed) == [0x100000001, 0x100000002, 0x100000003]
    user.emit(0x800B)
    user.emit(3, hwnd=999)
    assert changes == [True]


@pytest.mark.parametrize(
    "event", [0x8001, 0x8002, 0x8003, 0x8004, 0x800A, 0x800B, 0x800C, 0x16, 0x17],
)
def test_native_owner_change_events_only_notify_for_exact_window(monkeypatch, event):
    user = FakeUser32()
    changes = []
    subscription = _subscribe(monkeypatch, user, lambda: changes.append(True))
    user.emit(event, hwnd=22)
    user.emit(event, object_id=-4)
    user.emit(event, child_id=1)
    assert changes == []
    user.emit(event)
    assert changes == [True]
    subscription.close()


def test_global_foreground_event_notifies_on_other_process_window(monkeypatch):
    user = FakeUser32()
    changes = []
    subscription = _subscribe(monkeypatch, user, lambda: changes.append(True))
    user.emit(3, hwnd=999)
    assert changes == [True]
    user.emit(0x8005)
    assert changes == [True]
    subscription.close()


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_partial_registration_failure_releases_hooks_and_disables_notifications(
    monkeypatch, fail_at,
):
    user = FakeUser32(fail_at=fail_at)
    changes = []
    subscription = _subscribe(monkeypatch, user, lambda: changes.append(True))
    assert not subscription.active
    assert len(user.registered) == fail_at
    assert len(user.removed) == fail_at - 1
    user.emit(0x800B)
    user.emit(3, hwnd=999)
    assert changes == []
    subscription.close()
    assert len(user.removed) == fail_at - 1


@pytest.mark.parametrize("missing", ["SetWinEventHook", "UnhookWinEvent"])
def test_missing_native_event_functions_allow_polling_fallback(monkeypatch, missing):
    user = FakeUser32()
    delattr(user, missing)
    subscription = _subscribe(monkeypatch, user, lambda: pytest.fail("不应收到事件"))
    assert subscription is None


def test_unhook_failure_disables_callback_and_can_retry(monkeypatch, caplog):
    user = FakeUser32()
    changes = []
    subscription = _subscribe(monkeypatch, user, lambda: changes.append(True))
    user.UnhookWinEvent.call = lambda _handle: False
    subscription.close()
    assert not subscription.active
    user.emit(0x800B)
    assert changes == []
    assert "事件" in caplog.text

    user.UnhookWinEvent.call = user._unhook
    subscription.close()
    assert len(user.removed) == 3


def test_close_drops_reentrant_events_during_unhook(monkeypatch):
    user = FakeUser32()
    changes = []
    subscription = _subscribe(monkeypatch, user, lambda: changes.append(True))

    def unhook(handle):
        user.emit(0x800B)
        return user._unhook(handle)

    user.UnhookWinEvent.call = unhook
    subscription.close()
    assert changes == []
    assert len(user.removed) == 3


def test_wrong_thread_close_defers_native_release_until_owner_thread(monkeypatch, caplog):
    user = FakeUser32()
    changes = []
    subscription = _subscribe(monkeypatch, user, lambda: changes.append(True))
    worker = threading.Thread(target=subscription.close)
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert not subscription.active
    assert user.removed == []
    assert "安装线程" in caplog.text
    user.emit(0x800B)
    assert changes == []

    subscription.close()
    assert len(user.removed) == 3
