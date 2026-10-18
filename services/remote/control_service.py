"""封装不依赖界面的 Remote 设备控制操作。"""

import re
from collections.abc import Callable
from time import monotonic

from core.adb_bridge import ADBBridge

from .control_mapping import (
    KEYCODES,
    DimensionsInput,
    directional_swipe,
    notification_swipe,
    parse_dimensions,
    parse_input_viewport_dimensions,
)

DEFAULT_DIMENSION_TTL_SECONDS = 30.0
_INTENT_FAILURE = re.compile(
    r"^\s*(?:Error(?:\s+type\s+\d+|:)|Exception(?:\s|:)"
    r"|[\w.$]*Exception\b|Permission Denial:|Status:\s*(?:timeout|failed|error)\b)",
    re.IGNORECASE | re.MULTILINE,
)
REMOTE_ACTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "power_long_press": ("long_press_power", ()),
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
        # 该缓存保留启动预检提供的自然尺寸；输入坐标另查当前逻辑区域。
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

    def _get_input_dimensions(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, int] | None:
        """在输入工作线程查询当前区域；旋转可由外部改变，不能复用自然尺寸缓存。"""
        if cancelled is not None and cancelled():
            return None
        result = self._shell("dumpsys input", device_id, cancelled)
        if (cancelled is not None and cancelled()) or not result.success:
            return None
        return parse_input_viewport_dimensions(result.output)

    def send_keyevent(
        self, device_id: str, key_name: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """发送逻辑按键；设置入口显式打开系统设置，避免 ROM 将设置键用于其他动作。

        SETTINGS 在命令成功但输出含 Intent 错误时返回 False，其余按键返回 ADB 结果对象；
        未知且非十进制 keycode 返回 None。调用方必须同时兼容布尔与结果对象。
        """
        if key_name == "SETTINGS":
            # 与系统 Intent 入口保持相同失败语义：am 可能输出错误但返回零退出码。
            result = self._shell("am start -a android.settings.SETTINGS 2>&1", device_id, cancelled)
            if result.success and _INTENT_FAILURE.search(result.output):
                return False
            return result
        code = KEYCODES.get(key_name)
        if code is None:
            # 只接受显式数字 keycode，其余一律拒绝，避免未校验字符串进入设备 shell。
            if not (isinstance(key_name, str) and key_name.isascii() and key_name.isdigit()):
                return None
            code = key_name
        return self._shell_input(f"keyevent {code}", device_id, cancelled)

    def long_press_power(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """发送一次系统电源长按事件；由设备策略决定响应，不模拟硬件强制关机。"""
        return self._shell_input("keyevent --longpress 26", device_id, cancelled)

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
        dimensions = self._get_input_dimensions(device_id, cancelled=cancelled)
        if dimensions is None:
            return False
        coords = directional_swipe(dimensions, direction)
        return self.swipe(device_id, *coords, duration_ms=duration_ms, cancelled=cancelled)

    def expand_notifications(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """在尺寸查询和展开通知栏之间保留取消边界。"""
        dimensions = self._get_input_dimensions(device_id, cancelled=cancelled)
        if dimensions is None:
            return False
        coords = notification_swipe(dimensions, expand=True)
        return self.swipe(device_id, *coords, duration_ms=300, cancelled=cancelled)

    def collapse_notifications(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """在尺寸查询和收起通知栏之间保留取消边界。"""
        dimensions = self._get_input_dimensions(device_id, cancelled=cancelled)
        if dimensions is None:
            return False
        coords = notification_swipe(dimensions, expand=False)
        return self.swipe(device_id, *coords, duration_ms=300, cancelled=cancelled)

    def rotate_portrait(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """按设备有效基础尺寸设置竖屏，不撤销已经完成的设置。"""
        return self._set_orientation(device_id, portrait=True, cancelled=cancelled)

    def rotate_landscape(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """按设备有效基础尺寸设置横屏，不撤销已经完成的设置。"""
        return self._set_orientation(device_id, portrait=False, cancelled=cancelled)

    def reset_rotation(
        self, device_id: str, *, cancelled: Callable[[], bool] | None = None,
    ):
        """清除尺寸缓存并可取消地恢复自动旋转。"""
        self.clear_dimensions(device_id)
        return self._shell("settings put system accelerometer_rotation 1", device_id, cancelled)

    def _set_orientation(
        self, device_id: str, *, portrait: bool, cancelled: Callable[[], bool] | None = None,
    ):
        """查询失败或方向不明确时拒绝写设置；基础尺寸不受当前旋转角度影响。"""
        if cancelled is not None and cancelled():
            return False
        # 绕过启动预检缓存：wm size 的有效覆盖尺寸可能已被其他工具修改。
        dimensions = (
            self.adb.get_dimensions(device_id=device_id)
            if cancelled is None
            else self.adb.get_dimensions(device_id=device_id, cancelled=cancelled)
        )
        if cancelled is not None and cancelled():
            return False
        parsed = parse_dimensions(dimensions)
        if parsed is None:
            return False
        width, height = parsed
        if width <= 0 or height <= 0 or width == height:
            return False
        rotation = int((height > width) != portrait)
        return self._set_rotation(device_id, rotation, cancelled=cancelled)

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
