"""按本次进程归属跟踪 scrcpy 窗口，并提供无焦点的原生侧栏定位。"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable

from services.remote.windowing.contracts import (
    NativeWindowSnapshot as NativeWindowSnapshot,
)
from services.remote.windowing.contracts import (
    PhysicalRect as PhysicalRect,
)
from services.remote.windowing.contracts import (
    _EventWindowApi as _EventWindowApi,
)
from services.remote.windowing.contracts import (
    _WindowApi as _WindowApi,
)
from services.remote.windowing.contracts import (
    _WindowSubscription as _WindowSubscription,
)
from services.remote.windowing.win32 import _Win32WindowApi as _Win32WindowApi

_LOGGER = logging.getLogger(__name__)


class WindowsWindowTracker:
    """复用原生 API 绑定启动进程及其后代窗口；失效后永久结束，调用方负责关闭。"""

    def __init__(
        self,
        root_pid: int,
        title: str,
        *,
        api: _WindowApi | None = None,
        clock: Callable[[], float] = time.monotonic,
        discovery_interval_seconds: float = 0.25,
    ):
        self._root_pid = root_pid
        self._title = title
        self._api = api
        if api is None and sys.platform == "win32":
            self._api = _Win32WindowApi()
        self._clock = clock
        self._discovery_interval = max(0.05, discovery_interval_seconds)
        self._next_discovery = float("-inf")
        self._bound: tuple[int, int] | None = None
        self._lost = False
        self._change_callback: Callable[[], None] | None = None
        self._event_subscription: _WindowSubscription | None = None
        self._event_generation = 0

    @property
    def supported(self) -> bool:
        """当前平台是否具有原生窗口能力。"""
        return self._api is not None

    @property
    def lost(self) -> bool:
        """已绑定身份是否失效；首次窗口尚未出现不属于失效。"""
        return self._lost

    @property
    def event_tracking(self) -> bool:
        """是否已订阅绑定窗口的变化；为假时调用方继续使用轮询兜底。"""
        return self._event_subscription is not None and self._event_subscription.active

    def set_change_callback(self, callback: Callable[[], None] | None) -> None:
        """在 GUI 消息循环线程设置变更通知；通知只标记待刷新，不能同步定位。

        首次身份绑定前保留通知，绑定后才订阅原生事件。取消、替换和关闭会作废旧
        通知；无事件能力的后端继续按原有 snapshot 接口工作。
        """
        if callback is self._change_callback or self._lost:
            return
        self._stop_event_tracking()
        self._change_callback = callback
        self._start_event_tracking()

    def _start_event_tracking(self) -> None:
        bound = self._bound
        if bound is None or self._change_callback is None or self._lost:
            return
        api = self._api
        if not isinstance(api, _EventWindowApi):
            return
        generation = self._event_generation

        def changed() -> None:
            if self._lost or generation != self._event_generation or bound != self._bound:
                return
            callback = self._change_callback
            if callback is not None:
                callback()

        try:
            subscription = api.subscribe_changes(*bound, changed)
            if subscription is not None:
                if subscription.active:
                    self._event_subscription = subscription
                else:
                    subscription.close()
        except OSError:
            _LOGGER.debug("订阅投屏窗口事件失败，继续轮询", exc_info=True)

    def _stop_event_tracking(self) -> None:
        """先作废通知再释放，防止释放期间重入或已排队的回调继续影响侧栏。"""
        self._event_generation += 1
        subscription, self._event_subscription = self._event_subscription, None
        if subscription is not None:
            subscription.close()

    def _mark_lost(self) -> None:
        self._lost = True
        self._change_callback = None
        self._stop_event_tracking()

    def close(self) -> None:
        """会话结束时撤销绑定并释放自有原生连接；重复关闭不重复释放。"""
        self._mark_lost()
        api, self._api = self._api, None
        self._bound = None
        close = getattr(api, "close", None)
        if callable(close):
            try:
                close()
            except OSError:
                _LOGGER.debug("关闭投屏窗口连接失败", exc_info=True)

    def snapshot(self) -> NativeWindowSnapshot | None:
        """同步读取一次状态，不等待窗口出现；初始发现节流且不启动外部命令。"""
        api = self._api
        if api is None or self._lost or self._root_pid <= 0 or not self._title:
            return None
        try:
            if self._bound is None:
                now = self._clock()
                if now < self._next_discovery:
                    return None
                self._next_discovery = now + self._discovery_interval
                parents = api.process_parents()
                for hwnd in api.window_handles():
                    identity = api.identity(hwnd)
                    if identity is None or identity[1] != self._title:
                        continue
                    if not self._belongs_to_session(identity[0], parents):
                        continue
                    snapshot = api.snapshot(hwnd)
                    if snapshot is not None and snapshot.pid == identity[0]:
                        if api.identity(hwnd) == identity:
                            self._bound = (hwnd, identity[0])
                            self._start_event_tracking()
                            return snapshot
                return None
            hwnd, pid = self._bound
            if api.identity(hwnd) != (pid, self._title):
                self._mark_lost()
                return None
            snapshot = api.snapshot(hwnd)
            # 几何查询可能短暂失败；仅身份变化才终止，避免把最小化当成退出。
            if api.identity(hwnd) != (pid, self._title):
                self._mark_lost()
                return None
            if snapshot is None or snapshot.pid != pid:
                return None
            return snapshot
        except OSError:
            _LOGGER.debug("读取投屏窗口状态失败", exc_info=True)
            return None

    def position_tool(
        self, tool_hwnd: int, owner: NativeWindowSnapshot, rect: PhysicalRect
    ) -> bool:
        """仅定位本跟踪实例的侧栏；不显示、激活或改变 scrcpy 本身的位置。"""
        api = self._api
        if api is None or self._lost or self._bound != (owner.hwnd, owner.pid):
            return False
        if tool_hwnd <= 0 or rect[2] <= 0 or rect[3] <= 0:
            return False
        current = self.snapshot()
        if current is None or not current.visible or current.minimized:
            return False
        try:
            return api.position_tool(tool_hwnd, current, rect)
        except OSError:
            _LOGGER.debug("定位投屏侧栏失败", exc_info=True)
            return False

    def _belongs_to_session(self, pid: int, parents: dict[int, int]) -> bool:
        """沿一次进程快照回溯，兼容冻结入口和 venv 的多级启动进程。"""
        visited: set[int] = set()
        while pid > 0 and pid not in visited:
            if pid == self._root_pid:
                return True
            visited.add(pid)
            pid = parents.get(pid, 0)
        return False


def create_window_tracker(
    root_pid: int, title: str, *, platform_name: str,
) -> WindowsWindowTracker:
    """仅为能定位工具窗及镜像的后端创建跟踪器；其余交给便携工具栏。

    GUI 提供已经创建的 Qt 后端名称，不能仅凭 Wayland 会话中也存在 DISPLAY 就使用
    X11 句柄。显式 SDL 非 x11 选择保留，原生连接由返回的跟踪器负责关闭。
    """
    api = None
    if sys.platform == "linux" and platform_name == "xcb":
        from utils.gui_platform import sdl_allows_x11

        if sdl_allows_x11(os.environ) and ";" not in os.environ.get("QT_QPA_PLATFORM", ""):
            from services.remote.x11_window_tracking import X11WindowApi

            try:
                api = X11WindowApi()
            except OSError:
                _LOGGER.debug("X11 窗口跟随不可用，使用便携工具栏", exc_info=True)
    return WindowsWindowTracker(root_pid, title, api=api)
