"""用原生接口替身验证 macOS 会话身份、坐标和无焦点定位。"""

import os
import sys
from types import SimpleNamespace

import pytest

from services.remote.window_tracking import WindowsWindowTracker


def nsrect(x, y, width, height):
    return SimpleNamespace(origin=SimpleNamespace(x=x, y=y),
                           size=SimpleNamespace(width=width, height=height))


class Screen:
    def __init__(self, frame, visible, scale):
        self._frame, self._visible, self._scale = frame, visible, scale

    def frame(self):
        return nsrect(*self._frame)

    def visibleFrame(self):
        return nsrect(*self._visible)

    def backingScaleFactor(self):
        return self._scale


class NativeWindow:
    def __init__(self):
        self.frames, self.levels, self.orders = [], [], []
        self.view = SimpleNamespace(pointer=88, subviews=lambda: [])

    def contentView(self):
        return self.view

    def setFrame_display_(self, frame, display):
        self.frames.append((frame, display))

    def setLevel_(self, level):
        self.levels.append(level)

    def orderWindow_relativeTo_(self, place, number):
        self.orders.append((place, number))


class Accessibility:
    kAXErrorSuccess = 0
    kAXErrorInvalidUIElement = -25202
    kAXErrorCannotComplete = -25204
    kAXErrorNoValue = -25212
    kAXErrorAttributeUnsupported = -25205
    kAXValueCGPointType, kAXValueCGSizeType = 1, 2

    def __init__(self):
        self.trusted = True
        self.data = {
            100: {"AXWindows": [21], "AXHidden": False, "AXFocusedWindow": 21},
            200: {"AXWindows": [22], "AXHidden": False, "AXFocusedWindow": 22},
            900: {"AXWindows": [23], "AXHidden": False},
            21: {"AXTitle": "other", "AXPosition": (100, 100), "AXSize": (400, 600),
                 "AXMinimized": False},
            22: {"AXTitle": "session-title", "AXPosition": (100, 100), "AXSize": (400, 600),
                 "AXMinimized": False},
            23: {"AXTitle": "session-title", "AXPosition": (0, 0), "AXSize": (400, 600)},
        }
        self.accessed, self.timeouts = [], []
        self.error = 0

    def AXIsProcessTrusted(self):
        return self.trusted

    def AXUIElementCreateApplication(self, pid):
        return pid

    def AXUIElementSetMessagingTimeout(self, element, timeout):
        self.timeouts.append((element, timeout))
        return 0

    def AXUIElementCopyAttributeValue(self, element, name, _out):
        self.accessed.append((element, name))
        if self.error:
            return self.error, None
        if element not in self.data:
            return self.kAXErrorInvalidUIElement, None
        value = self.data[element].get(name)
        return (0, value) if value is not None else (self.kAXErrorNoValue, None)

    def AXValueGetValue(self, value, kind, _out):
        a, b = value
        if kind == self.kAXValueCGPointType:
            return True, SimpleNamespace(x=a, y=b)
        return True, SimpleNamespace(width=a, height=b)


@pytest.fixture
def native(monkeypatch):
    from services.remote.windowing.macos import MacOSWindowApi

    ax = Accessibility()
    screens = [Screen((0, 0, 1200, 900), (0, 30, 1200, 846), 2)]
    tool = NativeWindow()
    appkit = SimpleNamespace(
        NSThread=SimpleNamespace(isMainThread=lambda: True),
        NSScreen=SimpleNamespace(screens=lambda: screens),
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(
            frontmostApplication=lambda: SimpleNamespace(processIdentifier=lambda: 200),
            runningApplications=lambda: [
                SimpleNamespace(processIdentifier=lambda pid=pid: pid) for pid in (100, 200, 900)
            ],
        )),
        NSApplication=SimpleNamespace(sharedApplication=lambda: SimpleNamespace(
            windows=lambda: [tool],
        )),
        NSMakeRect=lambda *args: args,
        NSWindowAbove=1,
    )
    quartz = SimpleNamespace(
        kCGWindowListOptionAll=0, kCGWindowListOptionIncludingWindow=8, kCGNullWindowID=0,
        CGWindowListCopyWindowInfo=lambda *_: [{
            "kCGWindowOwnerPID": 200, "kCGWindowNumber": 333, "kCGWindowLayer": 0,
            "kCGWindowBounds": dict(zip(
                ("X", "Y", "Width", "Height"),
                (*ax.data[22]["AXPosition"], *ax.data[22]["AXSize"]),
            )),
            "kCGWindowIsOnscreen": not (
                ax.data[22]["AXMinimized"] or ax.data[200]["AXHidden"]
            ),
        }],
    )
    monkeypatch.setattr("services.remote.windowing.macos._load_macos", lambda: (
        appkit, ax, quartz, SimpleNamespace(pyobjc_id=lambda view: view.pointer),
    ))
    monkeypatch.setattr("services.remote.windowing.macos.psutil.process_iter", lambda _: [
        SimpleNamespace(info={"pid": pid, "ppid": parent})
        for pid, parent in {100: 1, 150: 100, 200: 150, 900: 1}.items()
    ])
    return SimpleNamespace(api=MacOSWindowApi(100), ax=ax, screens=screens, tool=tool,
                           quartz=quartz)


def test_macos_binds_exact_title_only_within_started_process_tree(native):
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    snapshot = tracker.snapshot()
    assert snapshot is not None and snapshot.pid == 200
    assert snapshot.foreground
    assert snapshot.foreground_hwnd == snapshot.hwnd
    assert (900, "AXWindows") not in native.ax.accessed
    assert all(0 < timeout <= 0.05 for _, timeout in native.ax.timeouts)
    assert {100, 200, 21, 22} <= {element for element, _ in native.ax.timeouts}


def test_macos_snapshot_tracks_move_resize_minimize_hide_and_restore(native):
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    first = tracker.snapshot()
    assert first.rect == (200, 200, 800, 1200)
    assert first.work_area == (0, 48, 2400, 1692)
    assert first.dpi == 192
    native.ax.data[22].update(AXPosition=(300, 200), AXSize=(500, 400), AXMinimized=True)
    snapshot = tracker.snapshot()
    assert snapshot.hwnd == first.hwnd
    assert snapshot.rect == (600, 400, 1000, 800) and snapshot.minimized
    native.ax.data[22]["AXMinimized"] = False
    native.ax.data[200]["AXHidden"] = True
    assert not tracker.snapshot().visible
    native.ax.data[200]["AXHidden"] = False
    assert tracker.snapshot().visible and not tracker.snapshot().minimized


def test_macos_negative_secondary_display_uses_its_scale_and_work_area(native):
    native.screens.append(Screen((-1600, -100, 1600, 1000), (-1600, -100, 1600, 976), 1))
    native.ax.data[22]["AXPosition"] = (-1400, 120)
    snapshot = WindowsWindowTracker(100, "session-title", api=native.api).snapshot()
    assert snapshot.rect == (-1400, 120, 400, 600)
    assert snapshot.work_area == (-1600, 24, 1600, 976)
    assert snapshot.dpi == 96


def test_macos_bound_window_uses_targeted_cg_query_while_moving(native, monkeypatch):
    queries = []
    original = native.quartz.CGWindowListCopyWindowInfo

    def query(option, number):
        queries.append((option, number))
        return original(option, number)

    monkeypatch.setattr(native.quartz, "CGWindowListCopyWindowInfo", query)
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    assert tracker.snapshot() is not None
    native.ax.data[22]["AXPosition"] = (200, 200)
    assert tracker.snapshot().rect[:2] == (400, 400)
    assert queries == [(0, 0), (8, 333)]


def test_macos_cached_window_number_cannot_order_relative_to_foreign_pid(native, monkeypatch):
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    assert tracker.snapshot() is not None
    monkeypatch.setattr(native.quartz, "CGWindowListCopyWindowInfo", lambda *_: [{
        "kCGWindowOwnerPID": 900, "kCGWindowNumber": 333, "kCGWindowLayer": 10,
        "kCGWindowIsOnscreen": True,
    }])
    snapshot = tracker.snapshot()
    assert not snapshot.topmost
    assert tracker.position_tool(88, snapshot, (1000, 200, 112, 680))
    assert native.tool.orders[-1] == (1, 0)
    assert native.tool.levels[-1] == 0


def test_macos_places_only_owned_view_without_activating_mirror(native):
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    snapshot = tracker.snapshot()
    assert not tracker.position_tool(999, snapshot, (1016, 224, 112, 680))
    assert native.tool.frames == []
    assert tracker.position_tool(88, snapshot, (1016, 224, 112, 680))
    assert native.tool.frames[-1] == ((508, 448, 56, 340), True)
    assert native.tool.orders[-1] == (1, 333)
    assert native.tool.levels[-1] == 0


def test_macos_query_timeout_does_not_rebind_or_destroy_identity(native):
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    first = tracker.snapshot()
    native.ax.error = native.ax.kAXErrorCannotComplete
    assert tracker.snapshot() is None and not tracker.lost
    native.ax.error = 0
    assert tracker.snapshot().hwnd == first.hwnd


def test_macos_timeout_configuration_failure_never_queries_unbounded_window(native, monkeypatch):
    original = native.ax.AXUIElementSetMessagingTimeout
    monkeypatch.setattr(native.ax, "AXUIElementSetMessagingTimeout", lambda element, timeout: (
        native.ax.kAXErrorCannotComplete if element == 22 else original(element, timeout)
    ))
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    assert tracker.snapshot() is None and not tracker.lost
    assert all(element != 22 for element, _ in native.ax.accessed)


def test_macos_closed_window_cannot_rebind_same_title_and_close_releases_references(native):
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    assert tracker.snapshot() is not None
    del native.ax.data[22]
    assert tracker.snapshot() is None and tracker.lost
    native.ax.data[22] = {"AXTitle": "session-title"}
    assert tracker.snapshot() is None
    tracker.close()
    tracker.close()
    assert native.api.window_handles() == []


def test_macos_requires_existing_permission_to_verify_window_titles(monkeypatch):
    from services.remote.windowing.macos import MacOSWindowApi

    ax = Accessibility()
    ax.trusted = False
    monkeypatch.setattr("services.remote.windowing.macos._load_macos", lambda: (
        SimpleNamespace(NSThread=SimpleNamespace(isMainThread=lambda: True)), ax,
        SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: False), None,
    ))
    with pytest.raises(OSError, match="辅助功能"):
        MacOSWindowApi(os.getpid())


def test_macos_metadata_only_binds_verified_title_and_process(native, monkeypatch):
    from services.remote.windowing.macos import MacOSWindowApi

    native.ax.trusted = False
    window = dict(native.quartz.CGWindowListCopyWindowInfo(0, 0)[0])
    foreign = dict(window, kCGWindowNumber=444, kCGWindowOwnerPID=900,
                   kCGWindowName="session-title")
    rows = [foreign, window]
    monkeypatch.setattr(native.quartz, "CGPreflightScreenCaptureAccess", lambda: True,
                        raising=False)
    monkeypatch.setattr(native.quartz, "CGWindowListCopyWindowInfo", lambda *_: rows)
    monkeypatch.setattr(native.quartz, "CGWindowListCreateDescriptionFromArray",
                        lambda numbers: [r for r in rows if r["kCGWindowNumber"] in numbers],
                        raising=False)
    now = [0.0]
    tracker = WindowsWindowTracker(100, "session-title", api=MacOSWindowApi(100),
                                   clock=lambda: now[0])
    try:
        assert tracker.snapshot() is None   # 标题被遮蔽，同名的无关进程也不能授权输入。
        window["kCGWindowName"] = "other"
        now[0] += 1
        assert tracker.snapshot() is None
        window["kCGWindowName"] = "session-title"
        now[0] += 1
        snapshot = tracker.snapshot()
        assert snapshot is not None and snapshot.pid == 200
        assert tracker.position_tool(88, snapshot, (1016, 224, 112, 680))
        assert native.tool.orders[-1] == (1, 333)
        window["kCGWindowOwnerPID"] = 900
        assert tracker.snapshot() is None and tracker.lost
        assert not tracker.position_tool(88, snapshot, (1016, 224, 112, 680))
        assert native.ax.accessed == []
    finally:
        tracker.close()


def test_macos_verified_window_subscribes_native_motion_and_releases_late_events(
    native, monkeypatch,
):
    subscriptions = []

    class Subscription:
        def __init__(self, ax, pid, application, window, callback, **_kwargs):
            assert ax is native.ax
            assert (pid, application, window) == (200, 200, 22)
            self.active = True
            self.callback = callback
            self.closes = 0
            subscriptions.append(self)

        def close(self):
            self.active = False
            self.closes += 1

    monkeypatch.setitem(sys.modules, "services.remote.windowing.macos_events", SimpleNamespace(
        MacOSWindowSubscription=Subscription,
    ))
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    changes = []
    tracker.set_change_callback(lambda: changes.append(True))
    assert not tracker.event_tracking
    assert tracker.snapshot() is not None
    assert tracker.event_tracking
    subscriptions[0].callback()
    assert changes == [True]
    tracker.close()
    subscriptions[0].callback()
    assert changes == [True]
    assert subscriptions[0].closes == 1


def test_macos_motion_snapshot_reads_only_verified_cg_geometry(native, monkeypatch):
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    first = tracker.snapshot()
    data = native.quartz.CGWindowListCopyWindowInfo(0, 0)[0]
    data["kCGWindowBounds"].update(X=200, Y=180, Width=420, Height=500)
    monkeypatch.setattr(native.quartz, "CGWindowListCopyWindowInfo", lambda *_: [data])
    native.ax.accessed.clear()
    moved = native.api.motion_snapshot(first.hwnd, first.pid)
    assert moved.rect == (400, 360, 840, 1000)
    assert moved.visible and moved.dpi == 192
    assert native.ax.accessed == []
    assert native.api.motion_snapshot(first.hwnd, 900) is None


def test_macos_motion_state_change_requires_complete_identity_refresh(native):
    tracker = WindowsWindowTracker(100, "session-title", api=native.api)
    first = tracker.snapshot()
    native.api._windows[first.hwnd].needs_verification = True
    assert native.api.motion_snapshot(first.hwnd, first.pid) is None
    native.ax.data[22]["AXTitle"] = "replacement"
    assert tracker.snapshot() is None and tracker.lost
