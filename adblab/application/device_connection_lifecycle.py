"""定义设备连接的窗口生命周期契约，不加载 Qt 或配对服务。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from services.adb_pairing import PairingOutcome


class WirelessHistoryGuard(Protocol):
    """已受理历史的动态许可；GUI 和执行器均可读取，不拥有后台资源。"""

    def is_current(self) -> bool:
        """复核当前身份与关闭状态，不做 I/O 或调用 Qt 方法；不撤销已开始的写入。"""
        ...


class DeviceConnectionLifecycle(Protocol):
    """GUI 线程同步调用的连接生命周期边界；异常保留给原调用链处理。"""

    def capture_wireless_history(self, outcome: PairingOutcome) -> WirelessHistoryGuard | None:
        """拒绝未核实结果时返回 None；接纳后仍须在历史任务的各检查点复核 guard。"""
        ...

    def invalidate_wireless_pairing(self, reason: str) -> None:
        """提交重启前撤销旧配对资格；回调失败不得继续提交重启。"""
        ...

    def note_adb_server_restarted(self) -> None:
        """重启成功后通知当前连接环境；刷新调度与用户反馈仍由 Controller 负责。"""
        ...
