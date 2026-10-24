"""拥有设备选择与发现状态，为 Qt 适配层提供不依赖控件的值快照。"""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceContextSnapshot:
    """冻结一次设备状态；扫描中保留目标，各功能另行执行自己的准入规则。"""

    selected_devices: tuple[str, ...]
    connected_devices: tuple[str, ...]
    discovery_state: str


class DeviceContext:
    """由所属窗口主线程串行提交，不管理扫描、持久化或功能会话。

    发现列表保留最近成功扫描的顺序，展示列表保留存续行的顺序。保留勾选与有效操作目标
    分别查询，使发现失败可以暂时阻止新操作，而不丢失用户先前选择。
    """

    _DISCOVERY_STATES = frozenset({"scanning", "ready", "empty", "unavailable"})

    def __init__(self) -> None:
        self._connected_devices: tuple[str, ...] = ()
        self._display_devices: tuple[str, ...] = ()
        self._checked_devices: tuple[str, ...] = ()
        self._discovery_state = "scanning"
        self._manual_refresh_previous_state: str | None = None

    def snapshot(self) -> DeviceContextSnapshot:
        """返回不可变操作快照；不可用时保留在线缓存，只屏蔽有效目标。"""
        return DeviceContextSnapshot(
            selected_devices=(
                () if self._discovery_state == "unavailable" else self._checked_devices
            ),
            connected_devices=self._connected_devices,
            discovery_state=self._discovery_state,
        )

    @property
    def checked_devices(self) -> tuple[str, ...]:
        """返回稳定展示顺序中的原勾选，不应用发现状态的准入限制。"""
        return self._checked_devices

    @property
    def display_devices(self) -> tuple[str, ...]:
        """返回存续设备在前、新设备按发现顺序追加的展示顺序。"""
        return self._display_devices

    def replace_connected_devices(self, devices: Iterable[str]) -> None:
        """提交成功列表并移除离线勾选；不选择新设备，也不改变发现状态。"""
        connected = tuple(dict.fromkeys(devices))
        online = set(connected)
        previous = set(self._display_devices)
        self._connected_devices = connected
        self._display_devices = (
            tuple(device for device in self._display_devices if device in online)
            + tuple(device for device in connected if device not in previous)
        )
        self._checked_devices = tuple(
            device for device in self._checked_devices if device in online
        )

    def set_selected_devices(self, devices: Iterable[str]) -> None:
        """按成员关系选择当前设备，忽略未知目标，输出遵循稳定展示顺序。"""
        selected = set(devices)
        self._checked_devices = tuple(
            device for device in self._display_devices if device in selected
        )

    def set_discovery_state(self, state: str) -> bool:
        """提交发现状态，返回是否改变；新终态令旧刷新恢复信息失效。"""
        normalized = str(state or "empty").lower()
        if normalized not in self._DISCOVERY_STATES:
            normalized = "empty"
        changed = normalized != self._discovery_state
        self._discovery_state = normalized
        if normalized != "scanning":
            self._manual_refresh_previous_state = None
        return changed

    def begin_refresh(self) -> bool:
        """保存刷新前状态并进入扫描；扫描期间拒绝重复请求。"""
        if self._discovery_state == "scanning":
            return False
        self._manual_refresh_previous_state = self._discovery_state
        self.set_discovery_state("scanning")
        return True

    def restore_superseded_refresh(self) -> bool:
        """消费被取代刷新的恢复信息；新终态已经到达时不覆盖它。"""
        previous = self._manual_refresh_previous_state
        self._manual_refresh_previous_state = None
        if self._discovery_state == "scanning" and previous is not None:
            return self.set_discovery_state(previous)
        return False
