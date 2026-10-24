"""定义窗口状态和基础、可选事件能力的共享契约。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

PhysicalRect = tuple[int, int, int, int]


@dataclass(frozen=True)
class NativeWindowSnapshot:
    """窗口状态；矩形统一为桌面物理像素的 x、y、宽、高。"""

    hwnd: int
    pid: int
    rect: PhysicalRect
    work_area: PhysicalRect
    visible: bool
    minimized: bool
    foreground: bool
    topmost: bool
    dpi: int = 96
    foreground_hwnd: int = 0


class _WindowApi(Protocol):
    """隔离原生读取和定位，使身份决策不依赖 GUI 或外部命令。"""

    def process_parents(self) -> dict[int, int]: ...
    def window_handles(self) -> list[int]: ...
    def identity(self, hwnd: int) -> tuple[int, str] | None: ...
    def snapshot(self, hwnd: int) -> NativeWindowSnapshot | None: ...
    def position_tool(
        self, tool_hwnd: int, owner: NativeWindowSnapshot, rect: PhysicalRect
    ) -> bool: ...


class _WindowSubscription(Protocol):
    """可选事件能力；订阅和释放必须在调用方的同一消息循环线程完成。"""

    @property
    def active(self) -> bool: ...
    def close(self) -> None: ...


@runtime_checkable
class _EventWindowApi(Protocol):
    """独立可选事件协议，基础窗口后端无须实现。"""

    def subscribe_changes(
        self, hwnd: int, pid: int, callback: Callable[[], None],
    ) -> _WindowSubscription | None: ...
