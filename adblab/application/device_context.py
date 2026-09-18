"""提供当前设备选择和发现状态的不可变值快照，不拥有设备状态。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceContextSnapshot:
    """从设备协调器读取一次状态；扫描中保留选择，操作准入仍要求 ready。"""

    selected_devices: tuple[str, ...]
    connected_devices: tuple[str, ...]
    discovery_state: str
