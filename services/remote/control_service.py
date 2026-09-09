"""封装不依赖界面的 Remote 设备控制操作。"""

from collections.abc import Callable
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

    def get_dimensions(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, int] | None:
        """读取缓存或可取消的设备尺寸；关闭后不再启动查询。"""
        if cancelled is not None and cancelled():
            return None
        # wm size 是同步 ADB 命令；缓存可避免连续点击手势按钮时卡住 UI。
        cached = self._dimensions_cache.get(device_id)
        now = monotonic()
        if cached and now - cached[1] <= self.dimension_ttl_seconds:
            return cached[0]

        dimensions = (
            self.adb.get_dimensions(device_id=device_id)
            if cancelled is None
            else self.adb.get_dimensions(device_id=device_id, cancelled=cancelled)
        )
        parsed = self.remember_dimensions(device_id, dimensions)
        if parsed:
            return parsed

        return cached[0] if cached else None

    def send_keyevent(
        self, device_id: str, key_name: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """把逻辑按键名转换为 Android keyevent 并发送到指定设备。"""
        code = KEYCODES.get(key_name)
        if code is None:
            # 只接受显式数字 keycode，其余一律拒绝，避免未校验字符串进入设备 shell。
            if not (isinstance(key_name, str) and key_name.isascii() and key_name.isdigit()):
                return None
            code = key_name
        return self._shell_input(f"keyevent {code}", device_id, cancelled)

    def perform_action(
        self, device_id: str, action: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """按 UI 动作分发，尺寸查询与后续写操作共用同一取消信号。"""
        action_spec = REMOTE_ACTIONS.get(action)
        if not action_spec:
            raise ValueError(f"Unknown remote action: {action}")
        method_name, args = action_spec
        return getattr(self, method_name)(device_id, *args, cancelled=cancelled)

    def _shell_input(self, command: str, device_id: str, cancelled: Callable[[], bool] | None):
        """将取消信号交给输入执行边界，结果不触发服务层重试。"""
        if cancelled is None:
            return self.adb.shell_input(command, device_id=device_id)
        return self.adb.shell_input(command, device_id=device_id, cancelled=cancelled)

    def _shell(self, command: str, device_id: str, cancelled: Callable[[], bool] | None):
        """保留原 Shell 结果；多步动作逐次经过同一取消检查。"""
        if cancelled is None:
            return self.adb.shell(command, device_id=device_id)
        return self.adb.shell(command, device_id=device_id, cancelled=cancelled)

    def swipe(
        self,
        device_id: str,
        x1: int | float,
        y1: int | float,
        x2: int | float,
        y2: int | float,
        duration_ms: int | None = None,
        *,
        cancelled: Callable[[], bool] | None = None,
    ):
        """构造并发送 Android input swipe 命令。"""
        parts = [int(x1), int(y1), int(x2), int(y2)]
        if duration_ms is not None:
            parts.append(int(duration_ms))
        return self._shell_input(
            "swipe " + " ".join(str(part) for part in parts),
            device_id, cancelled,
        )

    def directional_swipe(
        self, device_id: str, direction: str, duration_ms: int = 300,
        *, cancelled: Callable[[], bool] | None = None,
    ):
        """尺寸查询与方向手势共用取消信号，查询取消后不发送输入。"""
        coords = directional_swipe(self.get_dimensions(device_id, cancelled=cancelled), direction)
        return self.swipe(device_id, *coords, duration_ms=duration_ms, cancelled=cancelled)

    def expand_notifications(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """在尺寸查询和展开通知栏之间保留取消边界。"""
        coords = notification_swipe(
            self.get_dimensions(device_id, cancelled=cancelled), expand=True,
        )
        return self.swipe(device_id, *coords, duration_ms=300, cancelled=cancelled)

    def collapse_notifications(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """在尺寸查询和收起通知栏之间保留取消边界。"""
        coords = notification_swipe(
            self.get_dimensions(device_id, cancelled=cancelled), expand=False,
        )
        return self.swipe(device_id, *coords, duration_ms=300, cancelled=cancelled)

    def rotate_portrait(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """可取消地设置竖屏，不撤销已经完成的设置。"""
        return self._set_rotation(device_id, 0, cancelled=cancelled)

    def rotate_landscape(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """可取消地设置横屏，不撤销已经完成的设置。"""
        return self._set_rotation(device_id, 1, cancelled=cancelled)

    def reset_rotation(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """清除尺寸缓存并可取消地恢复自动旋转。"""
        self.clear_dimensions(device_id)
        return self._shell("settings put system accelerometer_rotation 1", device_id, cancelled)

    def _set_rotation(
        self, device_id: str, rotation: int, *, cancelled: Callable[[], bool] | None = None,
    ):
        """关闭自动旋转并写入方向；兼容设置键沿用同一取消边界。"""
        self.clear_dimensions(device_id)
        prerequisite = self._shell(
            "settings put system accelerometer_rotation 0", device_id, cancelled,
        )
        if not getattr(prerequisite, "success", True):
            return prerequisite
        result = self._shell(
            f"settings put system user_rotation {rotation}",
            device_id, cancelled,
        )
        if getattr(result, "success", True):
            return result

        return self._shell(
            f"settings put system rotation {rotation}",
            device_id, cancelled,
        )
