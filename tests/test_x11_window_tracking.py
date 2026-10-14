from __future__ import annotations

import ctypes
import importlib
import os
from types import SimpleNamespace

import pytest


def _module():
    name = "services.remote.x11_window_tracking"
    assert importlib.util.find_spec(name) is not None, "Linux X11 window tracking is unavailable"
    return importlib.import_module(name)


class _Function:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


class FakeX11:
    def __init__(self, module):
        self.module = module
        self.atoms = {}
        self.buffers = {}
        self.properties = {}
        self.windows = {1: (0, 0, 3840, 1080), 20: (100, 90, 400, 600), 30: (700, 90, 80, 600)}
        self.maps = {1: 2, 20: 2, 30: 2}
        self.handler = None
        self.original_errors = []
        self.original_handler = module._XErrorHandler(
            lambda display, error: (
                self.original_errors.append((display, error.contents.error_code)) or 0
            )
        )
        self.handler = ctypes.cast(self.original_handler, ctypes.c_void_p).value
        self.closed = []
        self.moves = []
        self.transients = []
        self.freed = []
        self.XOpenDisplay = _Function(lambda _name: 99)
        self.XCloseDisplay = _Function(lambda display: self.closed.append(display) or 0)
        self.XDefaultRootWindow = _Function(lambda _display: 1)
        self.XInternAtom = _Function(self.intern)
        self.XGetWindowProperty = _Function(self.get_property)
        self.XFree = _Function(self.free)
        self.XSetErrorHandler = _Function(self.set_handler)
        self.XSync = _Function(lambda *_args: 0)
        self.XGetWindowAttributes = _Function(self.attributes)
        self.XTranslateCoordinates = _Function(self.translate)
        self.XMoveResizeWindow = _Function(self.move)
        self.XSetTransientForHint = _Function(self.transient)
        self.set_property(1, "_NET_CLIENT_LIST", "WINDOW", 32, [20, 30])
        self.set_property(1, "_NET_CURRENT_DESKTOP", "CARDINAL", 32, [1])
        self.set_property(1, "_NET_WORKAREA", "CARDINAL", 32, [0, 0, 3840, 1080, 0, 30, 3840, 1050])
        self.set_property(1, "_NET_ACTIVE_WINDOW", "WINDOW", 32, [20])
        self.set_property(20, "_NET_WM_PID", "CARDINAL", 32, [200])
        self.set_property(20, "_NET_WM_NAME", "UTF8_STRING", 8, "精确 title".encode())
        self.set_property(20, "_NET_FRAME_EXTENTS", "CARDINAL", 32, [4, 4, 30, 4])
        self.set_property(20, "_NET_WM_DESKTOP", "CARDINAL", 32, [1])
        self.set_property(30, "_NET_WM_PID", "CARDINAL", 32, [os.getpid()])
        self.set_property(30, "_NET_WM_NAME", "UTF8_STRING", 8, b"tool")

    def intern(self, _display, name, _only_existing):
        name = name.decode()
        return self.atoms.setdefault(name, len(self.atoms) + 1)

    def set_property(self, hwnd, name, kind, format_, value, remaining=0):
        self.properties[hwnd, self.intern(99, name.encode(), 0)] = (
            self.intern(99, kind.encode(), 0),
            format_,
            value,
            remaining,
        )

    def emit_error(self, display=99, code=3):
        event = self.module._XErrorEvent()
        event.error_code = code
        self.module._XErrorHandler(self.handler)(display, ctypes.pointer(event))

    def get_property(
        self,
        _display,
        hwnd,
        atom,
        _offset,
        _length,
        _delete,
        _type,
        actual_type,
        actual_format,
        count,
        remaining,
        result,
    ):
        if hwnd not in self.windows:
            self.emit_error()
            return 1
        kind, format_, data, tail = self.properties.get((hwnd, atom), (0, 0, [], 0))
        actual_type._obj.value = kind
        actual_format._obj.value = format_
        count._obj.value = len(data)
        remaining._obj.value = tail
        if data:
            buffer = (
                (ctypes.c_ubyte * len(data))(*data)
                if format_ == 8
                else (ctypes.c_ulong * len(data))(*data)
            )
            address = ctypes.addressof(buffer)
            self.buffers[address] = buffer
            ctypes.cast(result, ctypes.POINTER(ctypes.c_void_p))[0] = address
        return 0

    def free(self, pointer):
        address = ctypes.cast(pointer, ctypes.c_void_p).value
        self.freed.append(address)
        self.buffers.pop(address, None)
        return 0

    def set_handler(self, handler):
        previous = self.handler
        self.handler = ctypes.cast(handler, ctypes.c_void_p).value if handler else None
        return previous

    def attributes(self, _display, hwnd, pointer):
        if hwnd not in self.windows:
            self.emit_error()
            return 0
        x, y, width, height = self.windows[hwnd]
        attributes = pointer._obj
        attributes.x, attributes.y = x, y
        attributes.width, attributes.height = width, height
        attributes.map_state = self.maps[hwnd]
        return 1

    def translate(self, _display, hwnd, _root, _x, _y, x, y, _child):
        x._obj.value, y._obj.value = self.windows[hwnd][:2]
        return 1

    def move(self, _display, hwnd, x, y, width, height):
        self.moves.append((hwnd, x, y, width, height))
        self.windows[hwnd] = (x, y, width, height)
        return 1

    def transient(self, _display, hwnd, owner):
        self.transients.append((hwnd, owner))
        self.set_property(hwnd, "WM_TRANSIENT_FOR", "WINDOW", 32, [owner])
        return 1


@pytest.fixture
def native(monkeypatch, tmp_path):
    module = _module()
    library = FakeX11(module)
    monkeypatch.setattr(module, "_load_x11", lambda: library)
    monkeypatch.setattr(module, "_load_xrandr", lambda: None)
    api = module.X11WindowApi(proc_root=tmp_path)
    yield SimpleNamespace(api=api, library=library, module=module, proc_root=tmp_path)
    api.close()


def test_process_ancestry_reads_only_stat_and_handles_parentheses(native):
    for pid, content in [
        (10, "10 (launcher ) name) S 1 0 0"),
        (20, "20 (mirror) R 10 0 0"),
        (30, "bad"),
    ]:
        directory = native.proc_root / str(pid)
        directory.mkdir()
        (directory / "stat").write_text(content)
    assert native.api.process_parents() == {10: 1, 20: 10}


def test_exact_utf8_identity_requires_pid_and_complete_title(native):
    assert native.api.identity(20) == (200, "精确 title")
    native.library.set_property(20, "_NET_WM_NAME", "UTF8_STRING", 8, b"partial", remaining=10)
    assert native.api.identity(20) is None
    native.library.set_property(20, "_NET_WM_NAME", "UTF8_STRING", 8, b"title")
    native.library.set_property(20, "_NET_WM_PID", "STRING", 8, b"200")
    assert native.api.identity(20) is None
    assert not native.library.buffers


def test_snapshot_reports_frame_workarea_foreground_and_native_pixels(native):
    snapshot = native.api.snapshot(20)
    assert snapshot is not None
    assert snapshot.rect == (96, 60, 408, 634)
    assert snapshot.work_area == (0, 30, 3840, 1050)
    assert snapshot.foreground and snapshot.foreground_hwnd == 20
    assert snapshot.visible and not snapshot.minimized and not snapshot.topmost
    assert native.api.window_handles() == [20, 30]


@pytest.mark.parametrize("kind", ["hidden", "iconic", "unmapped", "other_desktop"])
def test_snapshot_preserves_hidden_and_minimized_identity(native, kind):
    if kind == "hidden":
        hidden = native.library.intern(99, b"_NET_WM_STATE_HIDDEN", 0)
        native.library.set_property(20, "_NET_WM_STATE", "ATOM", 32, [hidden])
    elif kind == "iconic":
        native.library.set_property(20, "WM_STATE", "WM_STATE", 32, [3, 0])
    elif kind == "unmapped":
        native.library.maps[20] = 0
    else:
        native.library.set_property(20, "_NET_WM_DESKTOP", "CARDINAL", 32, [0])
    snapshot = native.api.snapshot(20)
    assert snapshot is not None and snapshot.pid == 200
    assert snapshot.visible is False
    assert snapshot.minimized is (kind in {"hidden", "iconic"})


def test_monitor_workarea_uses_owner_monitor_intersection(native, monkeypatch):
    monkeypatch.setattr(
        native.api, "_monitor_rects", lambda: [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
    )
    native.library.windows[20] = (2200, 100, 400, 600)
    assert native.api.snapshot(20).work_area == (1920, 30, 1920, 1050)


def test_position_changes_only_owned_tool_and_never_owner_geometry(native):
    owner = native.api.snapshot(20)
    assert native.api.position_tool(30, owner, (520, 60, 80, 500))
    assert native.library.moves == [(30, 520, 60, 80, 500)]
    assert native.library.transients == [(30, 20)]
    assert native.library.windows[20] == (100, 90, 400, 600)
    assert native.api.position_tool(30, owner, (530, 60, 80, 500))
    assert native.library.transients == [(30, 20)]
    native.library.set_property(30, "_NET_WM_PID", "CARDINAL", 32, [1234])
    assert not native.api.position_tool(30, owner, (550, 60, 80, 500))
    assert len(native.library.moves) == 2


def test_position_rejects_owner_replacement_self_and_invalid_geometry(native):
    owner = native.api.snapshot(20)
    assert not native.api.position_tool(20, owner, (0, 0, 80, 500))
    assert not native.api.position_tool(30, owner, (0, 0, 0, 500))
    native.library.set_property(20, "_NET_WM_PID", "CARDINAL", 32, [201])
    assert not native.api.position_tool(30, owner, (0, 0, 80, 500))
    assert not native.library.moves


def test_destroyed_window_is_recoverable_and_original_error_handler_is_restored(native):
    previous = native.library.handler
    del native.library.windows[20]
    assert native.api.identity(20) is None
    assert native.api.snapshot(20) is None
    assert native.library.handler == previous
    assert native.library.original_errors == []
    assert native.api.identity(30) == (os.getpid(), "tool")
    with native.api._checked():
        native.library.emit_error(display=101, code=8)
    assert native.library.original_errors == [(101, 8)]
    assert native.library.handler == previous


def test_close_is_idempotent_and_queries_stop_using_connection(native):
    native.api.close()
    native.api.close()
    assert native.library.closed == [99]
    assert native.api.identity(20) is None
    assert native.api.snapshot(20) is None
    assert native.api.window_handles() == []


def test_async_badwindow_after_move_is_failure_and_handler_is_restored(native, monkeypatch):
    owner = native.api.snapshot(20)
    previous = native.library.handler
    monkeypatch.setattr(
        native.library, "XSync", _Function(lambda *_args: native.library.emit_error() or 0)
    )
    assert not native.api.position_tool(30, owner, (520, 60, 80, 500))
    assert native.library.handler == previous
    assert native.library.original_errors == []


def test_constructor_failure_releases_opened_connection(native, monkeypatch):
    native.api.close()
    native.library.closed.clear()

    def unavailable():
        raise OSError("simulated loader failure")

    monkeypatch.setattr(native.module, "_load_xrandr", unavailable)
    with pytest.raises(OSError, match="simulated loader failure"):
        native.module.X11WindowApi()
    assert native.library.closed == [99]
