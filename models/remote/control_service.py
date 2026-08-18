"""封装不依赖界面的 Remote 设备控制操作。"""

from time import monotonic

from core.adb_bridge import ADBBridge

from .control_mapping import (
    KEYCODES,
    DimensionsInput,
    directional_swipe,
    notification_swipe,
    parse_dimensions,
)

DEFAULT_DIMENSION_TTL_SECONDS = 30.0
REMOTE_ACTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "swipe_up": ("directional_swipe", ("up",)),
    "swipe_down": ("directional_swipe", ("down",)),
    "swipe_left": ("directional_swipe", ("left",)),
    "swipe_right": ("directional_swipe", ("right",)),
    "notif_expand": ("expand_notifications", ()),
    "notif_collapse": ("collapse_notifications", ()),
    "rotate_portrait": ("rotate_portrait", ()),
    "rotate_landscape": ("rotate_landscape", ()),
    "rotate_reset": ("reset_rotation", ()),
}


class RemoteControlService:
    """提供与 RemotePanel 解耦的设备控制原语。"""

    def __init__(
        self,
        adb: ADBBridge | None = None,
        dimension_ttl_seconds: float = DEFAULT_DIMENSION_TTL_SECONDS,
    ):
        self.adb = adb or ADBBridge()
        self.dimension_ttl_seconds = dimension_ttl_seconds
        self._dimensions_cache: dict[str, tuple[tuple[int, int], float]] = {}

    def remember_dimensions(
        self, device_id: str, dimensions: DimensionsInput
    ) -> tuple[int, int] | None:
        parsed = parse_dimensions(dimensions)
        if not parsed:
            return None
        self._dimensions_cache[device_id] = (parsed, monotonic())
        return parsed

    def clear_dimensions(self, device_id: str | None = None):
        if device_id is None:
            self._dimensions_cache.clear()
            return
        self._dimensions_cache.pop(device_id, None)

    def get_dimensions(self, device_id: str) -> tuple[int, int] | None:
        # wm size 是同步 ADB 命令；缓存可避免连续点击手势按钮时卡住 UI。
        cached = self._dimensions_cache.get(device_id)
        now = monotonic()
        if cached and now - cached[1] <= self.dimension_ttl_seconds:
            return cached[0]

        dimensions = self.adb.get_dimensions(device_id=device_id)
        parsed = self.remember_dimensions(device_id, dimensions)
        if parsed:
            return parsed

        return cached[0] if cached else None

    def send_keyevent(self, device_id: str, key_name: str):
        """把逻辑按键名转换为 Android keyevent 并发送到指定设备。"""
        code = KEYCODES.get(key_name, key_name)
        if not code:
            return None
        return self.adb.shell_input(f"keyevent {code}", device_id=device_id)

    def perform_action(self, device_id: str, action: str):
        """按 UI 动作名分发到遥控能力，避免面板层保存底层方法映射。"""
        action_spec = REMOTE_ACTIONS.get(action)
        if not action_spec:
            raise ValueError(f"Unknown remote action: {action}")
        method_name, args = action_spec
        return getattr(self, method_name)(device_id, *args)

    def swipe(
        self,
        device_id: str,
        x1: int | float,
        y1: int | float,
        x2: int | float,
        y2: int | float,
        duration_ms: int | None = None,
    ):
        """构造并发送 Android input swipe 命令。"""
        parts = [int(x1), int(y1), int(x2), int(y2)]
        if duration_ms is not None:
            parts.append(int(duration_ms))
        return self.adb.shell_input(
            "swipe " + " ".join(str(part) for part in parts),
            device_id=device_id,
        )

    def directional_swipe(self, device_id: str, direction: str, duration_ms: int = 300):
        coords = directional_swipe(self.get_dimensions(device_id), direction)
        return self.swipe(device_id, *coords, duration_ms=duration_ms)

    def expand_notifications(self, device_id: str):
        coords = notification_swipe(self.get_dimensions(device_id), expand=True)
        return self.swipe(device_id, *coords, duration_ms=300)

    def collapse_notifications(self, device_id: str):
        coords = notification_swipe(self.get_dimensions(device_id), expand=False)
        return self.swipe(device_id, *coords, duration_ms=300)

    def rotate_portrait(self, device_id: str):
        return self._set_rotation(device_id, 0)

    def rotate_landscape(self, device_id: str):
        return self._set_rotation(device_id, 1)

    def reset_rotation(self, device_id: str):
        self.clear_dimensions(device_id)
        return self.adb.shell("settings put system accelerometer_rotation 1", device_id=device_id)

    def _set_rotation(self, device_id: str, rotation: int):
        """关闭自动旋转并写入方向；主键失败时回退兼容设置键。"""
        self.clear_dimensions(device_id)
        self.adb.shell("settings put system accelerometer_rotation 0", device_id=device_id)
        result = self.adb.shell(
            f"settings put system user_rotation {rotation}",
            device_id=device_id,
        )
        if getattr(result, "success", True):
            return result

        return self.adb.shell(
            f"settings put system rotation {rotation}",
            device_id=device_id,
        )
