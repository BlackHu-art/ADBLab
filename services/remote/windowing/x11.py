"""以独立 X11 连接读取镜像窗口，供原生 X11 与 XWayland 侧栏复用。"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from services.remote.windowing.contracts import NativeWindowSnapshot, PhysicalRect

_ERROR_LOCK = threading.RLock()
_Display = ctypes.c_void_p
_Window = ctypes.c_ulong
_Atom = ctypes.c_ulong
_BytePointer = ctypes.POINTER(ctypes.c_ubyte)


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("border_width", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p),
        ("root", _Window),
        ("class_", ctypes.c_int),
        ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int),
        ("screen", ctypes.c_void_p),
    ]


class _XErrorEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("display", _Display),
        ("resourceid", ctypes.c_ulong),
        ("serial", ctypes.c_ulong),
        ("error_code", ctypes.c_ubyte),
        ("request_code", ctypes.c_ubyte),
        ("minor_code", ctypes.c_ubyte),
    ]


_XErrorHandler = ctypes.CFUNCTYPE(ctypes.c_int, _Display, ctypes.POINTER(_XErrorEvent))


class _XMonitorInfo(ctypes.Structure):
    _fields_ = [
        ("name", _Atom),
        ("primary", ctypes.c_int),
        ("automatic", ctypes.c_int),
        ("noutput", ctypes.c_int),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("mwidth", ctypes.c_int),
        ("mheight", ctypes.c_int),
        ("outputs", ctypes.POINTER(ctypes.c_ulong)),
    ]


def _load_x11() -> ctypes.CDLL:
    """只加载系统已有库；缺失时由工厂选择便携工具栏。"""
    library = ctypes.util.find_library("X11")
    if not library:
        raise OSError("X11 窗口能力不可用")
    return ctypes.CDLL(library)


def _load_xrandr() -> ctypes.CDLL | None:
    """可选监视器查询不增加依赖，旧服务器仍可使用根窗口工作区。"""
    library = ctypes.util.find_library("Xrandr")
    if not library:
        return None
    try:
        api = ctypes.CDLL(library)
        api.XRRQueryVersion.argtypes = [
            _Display,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        api.XRRQueryVersion.restype = ctypes.c_int
        api.XRRGetMonitors.argtypes = [
            _Display,
            _Window,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        api.XRRGetMonitors.restype = ctypes.POINTER(_XMonitorInfo)
        api.XRRFreeMonitors.argtypes = [ctypes.POINTER(_XMonitorInfo)]
        api.XRRFreeMonitors.restype = None
        return api
    except (OSError, AttributeError):
        return None


class X11WindowApi:
    """调用方在 GUI 线程拥有连接；关闭幂等，查询不读取进程命令或激活窗口。"""

    def __init__(self, *, proc_root: Path = Path("/proc")):
        self._x11 = _load_x11()
        self._proc_root = proc_root
        self._atoms: dict[str, int] = {}
        self._declare_functions()
        self._display = self._x11.XOpenDisplay(None)
        if not self._display:
            raise OSError("无法连接 X11 显示服务")
        try:
            self._root = int(self._x11.XDefaultRootWindow(self._display))
            self._randr = _load_xrandr()
            if self._randr is not None:
                try:
                    with self._checked():
                        major, minor = ctypes.c_int(), ctypes.c_int()
                        available = self._randr.XRRQueryVersion(
                            self._display, ctypes.byref(major), ctypes.byref(minor)
                        )
                        if not available or (major.value, minor.value) < (1, 5):
                            self._randr = None
                except OSError:
                    self._randr = None
        except BaseException:
            # 构造未完成时调用方拿不到实例，连接仍必须由本边界释放后重抛。
            self.close()
            raise

    def _declare_functions(self) -> None:
        api = self._x11
        api.XOpenDisplay.argtypes = [ctypes.c_char_p]
        api.XOpenDisplay.restype = _Display
        api.XCloseDisplay.argtypes = [_Display]
        api.XCloseDisplay.restype = ctypes.c_int
        api.XDefaultRootWindow.argtypes = [_Display]
        api.XDefaultRootWindow.restype = _Window
        api.XInternAtom.argtypes = [_Display, ctypes.c_char_p, ctypes.c_int]
        api.XInternAtom.restype = _Atom
        api.XGetWindowProperty.argtypes = [
            _Display,
            _Window,
            _Atom,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_int,
            _Atom,
            ctypes.POINTER(_Atom),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(_BytePointer),
        ]
        api.XGetWindowProperty.restype = ctypes.c_int
        api.XFree.argtypes = [ctypes.c_void_p]
        api.XFree.restype = ctypes.c_int
        api.XSetErrorHandler.argtypes = [ctypes.c_void_p]
        api.XSetErrorHandler.restype = ctypes.c_void_p
        api.XSync.argtypes = [_Display, ctypes.c_int]
        api.XSync.restype = ctypes.c_int
        api.XGetWindowAttributes.argtypes = [_Display, _Window, ctypes.POINTER(_XWindowAttributes)]
        api.XGetWindowAttributes.restype = ctypes.c_int
        api.XTranslateCoordinates.argtypes = [
            _Display,
            _Window,
            _Window,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(_Window),
        ]
        api.XTranslateCoordinates.restype = ctypes.c_int
        api.XMoveResizeWindow.argtypes = [
            _Display,
            _Window,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        api.XMoveResizeWindow.restype = ctypes.c_int
        api.XSetTransientForHint.argtypes = [_Display, _Window, _Window]
        api.XSetTransientForHint.restype = ctypes.c_int

    @contextmanager
    def _checked(self) -> Iterator[None]:
        """只拦截本连接本轮请求；同步收口后立即恢复进程原有错误处理器。"""
        with _ERROR_LOCK:
            if not self._display:
                raise OSError("X11 连接已关闭")
            errors: list[int] = []
            previous = 0

            def handle_error(display, event):
                if display == self._display:
                    errors.append(int(event.contents.error_code))
                    return 0
                # Qt 等其他连接仍遵循原错误处理语义，不能全局吞错。
                return _XErrorHandler(previous)(display, event)

            callback = _XErrorHandler(handle_error)
            # Xlib 返回旧处理器时会把默认 NULL 转为 _XDefaultError 的有效地址。
            previous = self._x11.XSetErrorHandler(callback)
            try:
                yield
            finally:
                # 异常中断时也排空已发请求，避免 BadWindow 在恢复后触发默认退出。
                try:
                    self._x11.XSync(self._display, 0)
                finally:
                    self._x11.XSetErrorHandler(previous)
                if errors:
                    raise OSError("X11 窗口请求失效")

    def close(self) -> None:
        """只释放本实例连接；调用方须先停轮询，重复关闭无副作用。"""
        with _ERROR_LOCK:
            if self._display:
                self._x11.XCloseDisplay(self._display)
                self._display = None

    def process_parents(self) -> dict[int, int]:
        """仅解析 stat 的 PID/PPID；进程退出、权限变化和损坏行均略过。"""
        parents: dict[int, int] = {}
        try:
            entries = list(self._proc_root.iterdir())
        except OSError:
            return parents
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            try:
                stat = (entry / "stat").read_text(encoding="utf-8")
                # comm 可含空格和右括号，只有最后一个右括号后才是 state/PPID。
                prefix, separator, suffix = stat.rpartition(")")
                fields = suffix.split()
                pid = int(prefix.split(" (", 1)[0])
                if separator and pid == int(entry.name) and len(fields) >= 2:
                    parents[pid] = int(fields[1])
            except (OSError, UnicodeError, ValueError):
                continue
        return parents

    def _atom(self, name: str) -> int:
        if name not in self._atoms:
            self._atoms[name] = int(self._x11.XInternAtom(self._display, name.encode("ascii"), 0))
        return self._atoms[name]

    def _property(self, hwnd: int, name: str, kind: str, format_: int) -> bytes | list[int] | None:
        """有界读取完整属性，Xlib 的 32 位值按宿主 unsigned long 布局释放。"""
        actual_type, actual_format = _Atom(), ctypes.c_int()
        count, remaining = ctypes.c_ulong(), ctypes.c_ulong()
        data = _BytePointer()
        result = self._x11.XGetWindowProperty(
            self._display,
            hwnd,
            self._atom(name),
            0,
            16384,
            0,
            self._atom(kind),
            ctypes.byref(actual_type),
            ctypes.byref(actual_format),
            ctypes.byref(count),
            ctypes.byref(remaining),
            ctypes.byref(data),
        )
        try:
            if (
                result != 0
                or actual_type.value != self._atom(kind)
                or actual_format.value != format_
                or remaining.value
            ):
                return None
            if not data:
                return b"" if format_ == 8 else []
            if format_ == 8:
                return ctypes.string_at(data, count.value)
            values = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
            return [int(values[index]) & 0xFFFFFFFF for index in range(count.value)]
        finally:
            if data:
                self._x11.XFree(data)

    def _numbers(self, hwnd: int, name: str, kind: str = "CARDINAL") -> list[int]:
        value = self._property(hwnd, name, kind, 32)
        return value if isinstance(value, list) else []

    def window_handles(self) -> list[int]:
        """读取窗口管理器的顶层客户列表，不递归探查其他应用子窗口。"""
        try:
            with self._checked():
                return self._numbers(self._root, "_NET_CLIENT_LIST", "WINDOW")
        except OSError:
            return []

    def _identity(self, hwnd: int) -> tuple[int, str] | None:
        pids = self._numbers(hwnd, "_NET_WM_PID")
        if len(pids) != 1 or pids[0] <= 0:
            return None
        title = self._property(hwnd, "_NET_WM_NAME", "UTF8_STRING", 8)
        if not isinstance(title, bytes):
            return None
        try:
            return pids[0], title.decode("utf-8")
        except UnicodeError:
            return None

    def identity(self, hwnd: int) -> tuple[int, str] | None:
        """只接受完整 UTF-8 标题和单一 PID，窗口销毁时返回无身份。"""
        if hwnd <= 0:
            return None
        try:
            with self._checked():
                return self._identity(hwnd)
        except OSError:
            return None

    def _attributes(self, hwnd: int) -> _XWindowAttributes:
        attributes = _XWindowAttributes()
        if not self._x11.XGetWindowAttributes(self._display, hwnd, ctypes.byref(attributes)):
            raise OSError("X11 窗口几何不可用")
        return attributes

    def _monitor_rects(self) -> list[PhysicalRect]:
        if self._randr is None:
            return []
        count = ctypes.c_int()
        monitors = self._randr.XRRGetMonitors(self._display, self._root, 1, ctypes.byref(count))
        if not monitors:
            return []
        try:
            return [
                (monitor.x, monitor.y, monitor.width, monitor.height)
                for monitor in (monitors[index] for index in range(count.value))
                if monitor.width > 0 and monitor.height > 0
            ]
        finally:
            self._randr.XRRFreeMonitors(monitors)

    def _work_area(self, rect: PhysicalRect, desktop: int) -> PhysicalRect:
        root = self._attributes(self._root)
        area = (0, 0, root.width, root.height)
        workareas = self._numbers(self._root, "_NET_WORKAREA")
        offset = desktop * 4
        if offset + 4 <= len(workareas):
            x, y, width, height = workareas[offset : offset + 4]
            if width > 0 and height > 0:
                area = (ctypes.c_int32(x).value, ctypes.c_int32(y).value, width, height)
        monitors = self._monitor_rects()
        if not monitors:
            return area

        def overlap(monitor: PhysicalRect) -> int:
            return max(
                0, min(rect[0] + rect[2], monitor[0] + monitor[2]) - max(rect[0], monitor[0])
            ) * max(0, min(rect[1] + rect[3], monitor[1] + monitor[3]) - max(rect[1], monitor[1]))

        monitor = max(monitors, key=overlap)
        x, y = max(area[0], monitor[0]), max(area[1], monitor[1])
        width = min(area[0] + area[2], monitor[0] + monitor[2]) - x
        height = min(area[1] + area[3], monitor[1] + monitor[3]) - y
        return (x, y, width, height) if width > 0 and height > 0 else monitor

    def snapshot(self, hwnd: int) -> NativeWindowSnapshot | None:
        """返回根窗口像素坐标和装饰外框；隐藏/最小化仍保留已验证身份。"""
        if hwnd <= 0:
            return None
        try:
            with self._checked():
                identity = self._identity(hwnd)
                if identity is None:
                    return None
                attributes = self._attributes(hwnd)
                x, y, child = ctypes.c_int(), ctypes.c_int(), _Window()
                if not self._x11.XTranslateCoordinates(
                    self._display,
                    hwnd,
                    self._root,
                    0,
                    0,
                    ctypes.byref(x),
                    ctypes.byref(y),
                    ctypes.byref(child),
                ):
                    return None
                extents = self._numbers(hwnd, "_NET_FRAME_EXTENTS")
                left, right, top, bottom = (
                    extents if len(extents) == 4 else [attributes.border_width] * 4
                )
                rect = (
                    x.value - left,
                    y.value - top,
                    attributes.width + left + right,
                    attributes.height + top + bottom,
                )
                states = self._numbers(hwnd, "_NET_WM_STATE", "ATOM")
                wm_state = self._numbers(hwnd, "WM_STATE", "WM_STATE")
                minimized = self._atom("_NET_WM_STATE_HIDDEN") in states or bool(
                    wm_state and wm_state[0] == 3
                )
                desktop = self._numbers(self._root, "_NET_CURRENT_DESKTOP")
                current_desktop = desktop[0] if desktop else 0
                window_desktop = self._numbers(hwnd, "_NET_WM_DESKTOP")
                on_desktop = not window_desktop or window_desktop[0] in (
                    current_desktop,
                    0xFFFFFFFF,
                )
                active = self._numbers(self._root, "_NET_ACTIVE_WINDOW", "WINDOW")
                foreground_hwnd = active[0] if active else 0
                return NativeWindowSnapshot(
                    hwnd=hwnd,
                    pid=identity[0],
                    rect=rect,
                    work_area=self._work_area(rect, current_desktop),
                    visible=attributes.map_state == 2 and on_desktop and not minimized,
                    minimized=minimized,
                    foreground=foreground_hwnd == hwnd,
                    topmost=self._atom("_NET_WM_STATE_ABOVE") in states,
                    foreground_hwnd=foreground_hwnd,
                )
        except OSError:
            return None

    def position_tool(
        self, tool_hwnd: int, owner: NativeWindowSnapshot, rect: PhysicalRect
    ) -> bool:
        """只移动本进程工具窗；瞬态归属维持相对层级，不激活或移动镜像。"""
        x, y, width, height = rect
        if (
            tool_hwnd <= 0
            or tool_hwnd == owner.hwnd
            or not (0 < width <= 65535 and 0 < height <= 65535)
        ):
            return False
        if not (-32768 <= x <= 32767 and -32768 <= y <= 32767):
            return False
        try:
            with self._checked():
                tool_identity = self._identity(tool_hwnd)
                owner_identity = self._identity(owner.hwnd)
                if tool_identity is None or tool_identity[0] != os.getpid():
                    return False
                if owner_identity is None or owner_identity[0] != owner.pid:
                    return False
                transient = self._numbers(tool_hwnd, "WM_TRANSIENT_FOR", "WINDOW")
                if transient != [owner.hwnd]:
                    self._x11.XSetTransientForHint(self._display, tool_hwnd, owner.hwnd)
                return bool(
                    self._x11.XMoveResizeWindow(self._display, tool_hwnd, x, y, width, height)
                )
        except OSError:
            return False
