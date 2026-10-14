"""平台选择必须与实际 Qt 后端及显式 SDL 偏好一致。"""

from types import SimpleNamespace

import pytest

from services.remote import window_tracking
from tests.test_remote_window_tracking import FakeWindowApi


@pytest.mark.parametrize(
    "platform,qt_platform,sdl,expected",
    [
        ("linux", "xcb", {}, True),
        ("linux", "xcb", {"SDL_VIDEO_DRIVER": "x11"}, True),
        ("linux", "xcb", {"SDL_VIDEODRIVER": "x11"}, True),
        ("linux", "wayland", {}, False),
        ("linux", "offscreen", {}, False),
        ("linux", "xcb", {"SDL_VIDEO_DRIVER": "wayland"}, False),
        ("linux", "xcb", {"SDL_VIDEODRIVER": "wayland"}, False),
        ("darwin", "cocoa", {}, False),
        ("win32", "windows", {}, True),
    ],
)
def test_factory_binds_only_for_compatible_window_backends(
    monkeypatch, platform, qt_platform, sdl, expected,
):
    import sys

    monkeypatch.setattr(window_tracking, "sys", SimpleNamespace(platform=platform))
    for key in ("SDL_VIDEO_DRIVER", "SDL_VIDEODRIVER"):
        monkeypatch.delenv(key, raising=False)
    for key, value in sdl.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setitem(sys.modules, "services.remote.x11_window_tracking", SimpleNamespace(
        X11WindowApi=FakeWindowApi,
    ))
    monkeypatch.setattr(window_tracking, "_Win32WindowApi", FakeWindowApi)
    create = getattr(window_tracking, "create_window_tracker", None)
    assert callable(create), "工厂必须按实际窗口后端选择定位能力"
    tracker = create(100, "session-title", platform_name=qt_platform)
    try:
        assert tracker.supported is expected
        snapshot = tracker.snapshot()
        if expected:
            assert snapshot is not None and snapshot.pid == 200
            assert tracker.position_tool(88, snapshot, (50, 60, 56, 400))
        else:
            assert snapshot is None
    finally:
        tracker.close()


def test_unavailable_x11_connection_falls_back_without_hiding_controls(monkeypatch):
    import sys

    def unavailable():
        raise OSError("no display connection")

    monkeypatch.setattr(window_tracking, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.delenv("SDL_VIDEO_DRIVER", raising=False)
    monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)
    monkeypatch.setitem(sys.modules, "services.remote.x11_window_tracking", SimpleNamespace(
        X11WindowApi=unavailable,
    ))
    create = getattr(window_tracking, "create_window_tracker", None)
    assert callable(create)
    tracker = create(100, "session-title", platform_name="xcb")
    try:
        assert not tracker.supported
        assert tracker.snapshot() is None
    finally:
        tracker.close()


def test_qt_backend_candidates_do_not_assume_scrcpy_uses_x11(monkeypatch):
    import sys

    monkeypatch.setattr(window_tracking, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "wayland;xcb")
    monkeypatch.delenv("SDL_VIDEO_DRIVER", raising=False)
    monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)
    monkeypatch.setitem(sys.modules, "services.remote.x11_window_tracking", SimpleNamespace(
        X11WindowApi=FakeWindowApi,
    ))
    tracker = window_tracking.create_window_tracker(100, "session-title", platform_name="xcb")
    try:
        assert not tracker.supported
    finally:
        tracker.close()
