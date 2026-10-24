"""封装窗口连接生命周期访问，保留既有准入与通知时机，不创建 Qt 资源。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from adblab.application.device_connection_lifecycle import WirelessHistoryGuard

if TYPE_CHECKING:
    from services.adb_pairing import PairingOutcome


@dataclass(frozen=True)
class _WindowWirelessHistoryGuard:
    """保留原历史闭包的强引用，只读取 Python 身份、代次和窗口关闭标量。"""

    owner_provider: Callable[[], object | None]
    owner: object
    pairing: object
    revision: int

    def is_current(self) -> bool:
        """后台不重复调用 GUI 准入；普通取消不扩大为已受理历史的撤销。"""
        return bool(
            self.owner_provider() is self.owner
            and not getattr(self.owner, "_closing", False)
            and getattr(self.owner, "_adb_pairing", None) is self.pairing
            and getattr(self.pairing, "context_revision", None) == self.revision
        )


class QtDeviceConnectionLifecycle:
    """将连接事件转发到当前窗口，允许构造后绑定或更换 owner。

    provider 在 GUI 和执行器中均可能读取，只能返回 Python 对象引用，不能访问控件。
    本对象不拥有 QObject、线程或关闭流程；通知异常沿原调用栈传播。
    """

    def __init__(self, owner_provider: Callable[[], object | None]) -> None:
        """仅保存提供者，构造时不解析 owner，也不创建配对协调器。"""
        self._owner_provider = owner_provider

    def capture_wireless_history(self, outcome: PairingOutcome) -> WirelessHistoryGuard | None:
        """在 GUI 线程沿用原窗口准入，返回可供后台反复读取的动态 guard。"""
        owner = self._owner_provider()
        pairing = getattr(owner, "_adb_pairing", None)
        accepts = getattr(pairing, "accepts_outcome", None)
        if (
            getattr(owner, "_closing", False)
            or not callable(accepts)
            or not accepts(outcome)
        ):
            return None
        return _WindowWirelessHistoryGuard(
            self._owner_provider, owner, pairing, outcome.context_revision,
        )

    def invalidate_wireless_pairing(self, reason: str) -> None:
        """GUI 线程转发失效原因；缺失窗口回调时保留无操作兼容行为。"""
        invalidate = getattr(self._owner_provider(), "invalidate_wireless_pairing", None)
        if callable(invalidate):
            invalidate(reason)

    def note_adb_server_restarted(self) -> None:
        """GUI 线程通知当前窗口；关闭细则由原窗口方法维护，不追加统一过滤。"""
        notify = getattr(self._owner_provider(), "note_adb_server_restarted", None)
        if callable(notify):
            notify()
