"""验证 macOS 窗口事件只通知 GUI、按会话过滤并完整撤销原生资源。"""

from types import SimpleNamespace

import pytest


class NativeAX:
    kAXErrorSuccess = 0

    def __init__(self, failures=()):
        self.failures = failures
        self.added, self.removed = [], []
        self.callback = None

    def AXObserverCreate(self, pid, callback, _out):
        self.pid, self.callback = pid, callback
        return 0, "observer"

    def AXObserverGetRunLoopSource(self, observer):
        assert observer == "observer"
        return "source"

    def AXObserverAddNotification(self, observer, element, name, _context):
        if name in self.failures:
            return -25207
        self.added.append((element, name))
        return 0

    def AXObserverRemoveNotification(self, observer, element, name):
        self.removed.append((element, name))
        if self.callback is not None:
            self.callback(observer, element, name, None)
        return 0


@pytest.fixture
def runtime(monkeypatch):
    import services.remote.windowing.macos_events as events

    added, removed = [], []
    cf = SimpleNamespace(
        kCFRunLoopCommonModes="common", CFRunLoopGetMain=lambda: "main",
        CFRunLoopAddSource=lambda *args: added.append(args),
        CFRunLoopRemoveSource=lambda *args: removed.append(args),
    )
    objc = SimpleNamespace(callbackFor=lambda _function: lambda callback: callback)
    monkeypatch.setattr(events, "_load_runtime", lambda: (cf, objc))
    return events, added, removed


def test_macos_motion_notifications_only_notify_and_share_main_common_runloop(runtime):
    events, added, _ = runtime
    ax, changes = NativeAX(), []
    subscription = events.MacOSWindowSubscription(ax, 200, "application", "window",
                                                lambda: changes.append(True))
    assert subscription.active and ax.pid == 200
    assert added == [("main", "source", "common")]
    assert ("window", "AXMoved") in ax.added and ("window", "AXResized") in ax.added
    assert ("application", "AXApplicationHidden") in ax.added
    ax.callback("observer", "window", "AXMoved", None)
    assert changes == [True]
    ax.callback("observer", "other-window", "AXMoved", None)
    assert changes == [True]
    subscription.close()


def test_macos_close_removes_notifications_and_runloop_before_releasing_callback(runtime):
    events, _, removed = runtime
    ax, changes = NativeAX(), []
    subscription = events.MacOSWindowSubscription(ax, 200, "application", "window",
                                                lambda: changes.append(True))
    callback = ax.callback
    subscription.close()
    subscription.close()
    callback("observer", "window", "AXMoved", None)
    assert not subscription.active
    assert changes == []
    assert removed == [("main", "source", "common")]
    assert sorted(ax.removed) == sorted(ax.added)


@pytest.mark.parametrize("missing", ["AXMoved", "AXResized"])
def test_missing_macos_motion_events_releases_partial_registration_for_polling(runtime, missing):
    events, added, removed = runtime
    ax = NativeAX(failures={missing})
    with pytest.raises(OSError):
        events.MacOSWindowSubscription(ax, 200, "application", "window", lambda: None)
    assert added == [] and removed == []
    assert sorted(ax.removed) == sorted(ax.added)


def test_optional_macos_notification_failure_keeps_motion_events(runtime):
    events, _, _ = runtime
    ax = NativeAX(failures={"AXTitleChanged"})
    subscription = events.MacOSWindowSubscription(ax, 200, "application", "window", lambda: None)
    assert subscription.active
    subscription.close()


def test_macos_state_changes_require_identity_refresh_before_geometry(runtime):
    events, _, _ = runtime
    ax, changes = NativeAX(), []
    subscription = events.MacOSWindowSubscription(
        ax, 200, "application", "window", lambda: changes.append("refresh"),
        state_changed=lambda: changes.append("invalidate"),
    )
    ax.callback("observer", "window", "AXMoved", None)
    assert changes == ["refresh"]
    ax.callback("observer", "window", "AXTitleChanged", None)
    assert changes == ["refresh", "invalidate", "refresh"]
    subscription.close()
    ax.callback("observer", "window", "AXTitleChanged", None)
    assert changes == ["refresh", "invalidate", "refresh"]


def test_missing_macos_event_api_does_not_import_native_dependencies(monkeypatch):
    import services.remote.windowing.macos_events as events

    def unexpected_load():
        pytest.fail("无事件能力时不应加载原生依赖")

    monkeypatch.setattr(events, "_load_runtime", unexpected_load)
    with pytest.raises(OSError, match="事件不可用"):
        events.MacOSWindowSubscription(SimpleNamespace(), 200, "app", "window", lambda: None)
