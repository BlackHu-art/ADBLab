from __future__ import annotations

import ctypes
import os
import sys
import uuid
from ctypes import wintypes
from dataclasses import replace

import pytest

from services.remote.window_tracking import (
    NativeWindowSnapshot,
    WindowsWindowTracker,
    _Win32WindowApi,
)


def _snapshot(hwnd=21, pid=200, **changes):
    return replace(
        NativeWindowSnapshot(
            hwnd=hwnd,
            pid=pid,
            rect=(-1500, 60, 700, 900),
            work_area=(-1920, 0, 1920, 1040),
            visible=True,
            minimized=False,
            foreground=True,
            topmost=False,
            dpi=144,
        ),
        **changes,
    )


class FakeWindowApi:
    def __init__(self):
        self.parents = {100: 1, 150: 100, 200: 150, 900: 1}
        self.windows = {21: (200, "session-title")}
        self.snapshots = {21: _snapshot()}
        self.enumerations = 0
        self.placements = []

    def process_parents(self):
        self.enumerations += 1
        return self.parents

    def window_handles(self):
        return list(self.windows)

    def identity(self, hwnd):
        return self.windows.get(hwnd)

    def snapshot(self, hwnd):
        return self.snapshots.get(hwnd)

    def position_tool(self, tool_hwnd, owner, rect):
        self.placements.append((tool_hwnd, owner, rect))
        return True


def test_exact_title_requires_root_or_descendant_pid():
    api = FakeWindowApi()
    api.windows = {9: (900, "session-title"), 10: (200, "session-title-extra")}
    api.snapshots = {9: _snapshot(9, 900), 10: _snapshot(10)}
    tracker = WindowsWindowTracker(100, "session-title", api=api)

    assert tracker.snapshot() is None
    assert tracker.lost is False


@pytest.mark.parametrize("pid", [100, 150, 200])
def test_binds_root_and_nested_launcher_descendants(pid):
    api = FakeWindowApi()
    api.windows[21] = (pid, "session-title")
    api.snapshots[21] = _snapshot(pid=pid)
    tracker = WindowsWindowTracker(100, "session-title", api=api)

    snapshot = tracker.snapshot()

    assert snapshot is not None
    assert (snapshot.hwnd, snapshot.pid) == (21, pid)
    assert snapshot.rect == (-1500, 60, 700, 900)
    assert snapshot.work_area == (-1920, 0, 1920, 1040)
    assert snapshot.dpi == 144


def test_initial_window_discovery_is_throttled_but_can_retry():
    api = FakeWindowApi()
    api.windows.clear()
    now = [1.0]
    tracker = WindowsWindowTracker(100, "session-title", api=api, clock=lambda: now[0])

    assert tracker.snapshot() is None
    api.windows[21] = (200, "session-title")
    now[0] = 1.1
    assert tracker.snapshot() is None
    assert api.enumerations == 1
    now[0] = 1.3
    assert tracker.snapshot() is not None
    assert api.enumerations == 2


@pytest.mark.parametrize("replacement", [None, (900, "session-title"), (200, "other")])
def test_bound_window_loss_is_terminal_and_never_rebinds(replacement):
    api = FakeWindowApi()
    tracker = WindowsWindowTracker(100, "session-title", api=api)
    assert tracker.snapshot() is not None
    if replacement is None:
        api.windows.pop(21)
    else:
        api.windows[21] = replacement
    api.windows[22] = (200, "session-title")
    api.snapshots[22] = _snapshot(22)

    assert tracker.snapshot() is None
    assert tracker.lost is True
    api.windows[21] = (200, "session-title")
    assert tracker.snapshot() is None
    assert api.enumerations == 1


@pytest.mark.parametrize("state", [{"visible": False}, {"minimized": True}])
def test_hidden_or_minimized_window_remains_bound_with_truthful_state(state):
    api = FakeWindowApi()
    tracker = WindowsWindowTracker(100, "session-title", api=api)
    assert tracker.snapshot() is not None
    api.snapshots[21] = _snapshot(**state)

    snapshot = tracker.snapshot()

    assert snapshot == api.snapshots[21]
    assert tracker.lost is False
    assert api.enumerations == 1
    assert tracker.position_tool(88, snapshot, (-780, 60, 100, 600)) is False
    assert api.placements == []


def test_geometry_failure_does_not_rebind_or_discard_verified_identity():
    api = FakeWindowApi()
    tracker = WindowsWindowTracker(100, "session-title", api=api)
    assert tracker.snapshot() is not None
    api.snapshots[21] = None
    assert tracker.snapshot() is None
    assert tracker.lost is False
    api.snapshots[21] = _snapshot(rect=(120, 30, 500, 600))
    assert tracker.snapshot().rect == (120, 30, 500, 600)
    assert api.enumerations == 1


def test_foreground_identity_changes_are_reported_without_rebinding():
    api = FakeWindowApi()
    api.snapshots[21] = _snapshot(foreground_hwnd=21)
    tracker = WindowsWindowTracker(100, "session-title", api=api)
    assert tracker.snapshot().foreground_hwnd == 21

    api.snapshots[21] = _snapshot(foreground=False, foreground_hwnd=88)
    first_other = tracker.snapshot()
    assert first_other.foreground is False
    assert first_other.foreground_hwnd == 88
    api.snapshots[21] = _snapshot(foreground=False, foreground_hwnd=89)
    second_other = tracker.snapshot()
    assert second_other.foreground is False
    assert second_other.foreground_hwnd == 89
    assert api.enumerations == 1


def test_placing_tool_uses_physical_coordinates_and_rejects_stale_owner():
    api = FakeWindowApi()
    tracker = WindowsWindowTracker(100, "session-title", api=api)
    owner = tracker.snapshot()
    assert owner is not None

    assert tracker.position_tool(88, owner, (-780, 60, 100, 600)) is True
    assert api.placements == [(88, owner, (-780, 60, 100, 600))]
    api.windows[21] = (900, "session-title")
    assert tracker.position_tool(88, owner, (-780, 60, 100, 600)) is False
    assert len(api.placements) == 1
    assert tracker.lost is True


def test_unsupported_platform_never_loads_windows_api(monkeypatch):
    monkeypatch.setattr("services.remote.window_tracking.sys.platform", "linux")
    tracker = WindowsWindowTracker(100, "session-title")
    assert tracker.supported is False
    assert tracker.snapshot() is None
    assert tracker.position_tool(88, _snapshot(), (0, 0, 10, 10)) is False


def test_cyclic_or_disconnected_process_tree_is_rejected():
    api = FakeWindowApi()
    api.parents = {100: 1, 150: 200, 200: 150}
    tracker = WindowsWindowTracker(100, "session-title", api=api)
    assert tracker.snapshot() is None


def test_identity_change_during_snapshot_cannot_bind_unrelated_window():
    api = FakeWindowApi()

    def read_then_reuse(hwnd):
        api.windows[hwnd] = (900, "session-title")
        return _snapshot(hwnd)

    api.snapshot = read_then_reuse
    tracker = WindowsWindowTracker(100, "session-title", api=api)
    assert tracker.snapshot() is None
    assert tracker.lost is False


def test_transient_native_enumeration_error_remains_retryable():
    api = FakeWindowApi()
    now = [0.0]
    first = [True]

    def parents():
        if first[0]:
            first[0] = False
            raise OSError("snapshot unavailable")
        return api.parents

    api.process_parents = parents
    tracker = WindowsWindowTracker(100, "session-title", api=api, clock=lambda: now[0])
    assert tracker.snapshot() is None
    now[0] = 1.0
    assert tracker.snapshot() is not None
    assert tracker.lost is False


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "win32", reason="原生 Win32 验证需要 Windows")
def test_native_hidden_windows_keep_physical_geometry_and_owned_stacking():
    api = _Win32WindowApi()
    user = api._user32
    user.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user.CreateWindowExW.restype = wintypes.HWND
    user.DestroyWindow.argtypes = [wintypes.HWND]
    user.DestroyWindow.restype = wintypes.BOOL
    title = f"ADBLab-window-test-{uuid.uuid4().hex}"
    windows = []

    try:
        with api._physical_coordinates():
            for caption in (title, "ADBLab-hidden-test-tool"):
                hwnd = user.CreateWindowExW(
                    0x08000080, "STATIC", caption, 0x80000000,
                    120, 80, 400, 600, None, None, None, None,
                )
                assert hwnd
                windows.append(hwnd)
        owner_hwnd, tool_hwnd = windows
        tracker = WindowsWindowTracker(os.getpid(), title)
        owner = tracker.snapshot()
        assert owner is not None
        assert owner.hwnd == owner_hwnd
        assert owner.rect == (120, 80, 400, 600)
        assert owner.visible is False
        assert os.getpid() in api.process_parents()

        assert api.position_tool(tool_hwnd, owner, (-250, 60, 100, 400))
        tool = api.snapshot(tool_hwnd)
        assert tool is not None
        assert tool.rect == (-250, 60, 100, 400)
        assert tool.topmost is False
        assert tool.visible is False
        assert api._get_window_long(tool_hwnd, -8) == owner_hwnd

        assert user.SetWindowPos(owner_hwnd, -1, 0, 0, 0, 0, 0x0013)
        topmost_owner = api.snapshot(owner_hwnd)
        assert topmost_owner is not None and topmost_owner.topmost
        assert api.position_tool(tool_hwnd, topmost_owner, (525, 80, 100, 400))
        topmost_tool = api.snapshot(tool_hwnd)
        assert topmost_tool is not None and topmost_tool.topmost

        assert user.SetWindowPos(owner_hwnd, -2, 0, 0, 0, 0, 0x0013)
        normal_owner = api.snapshot(owner_hwnd)
        assert normal_owner is not None and not normal_owner.topmost
        assert api.position_tool(tool_hwnd, normal_owner, (525, 80, 100, 400))
        normal_tool = api.snapshot(tool_hwnd)
        assert normal_tool is not None and not normal_tool.topmost
    finally:
        for hwnd in reversed(windows):
            if user.IsWindow(hwnd):
                assert user.DestroyWindow(hwnd)
