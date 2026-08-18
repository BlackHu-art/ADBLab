"""提供不依赖界面的 Remote 按键与手势坐标映射。"""

from collections.abc import Sequence

DimensionsInput = Sequence[str | int] | None
DEFAULT_DIMENSIONS = (1080, 1920)

KEYCODES: dict[str, str] = {
    "HOME": "3",
    "BACK": "4",
    "POWER": "26",
    "RECENTS": "187",
    "MENU": "82",
    "VOL_UP": "24",
    "VOL_DOWN": "25",
    "DPAD_UP": "19",
    "DPAD_DOWN": "20",
    "DPAD_LEFT": "21",
    "DPAD_RIGHT": "22",
    "DPAD_CENTER": "23",
    "ENTER": "66",
    "DEL": "67",
    "APP_SWITCH": "187",
    "NOTIFICATION": "83",
    "SETTINGS": "176",
    "CAMERA": "27",
    "SEARCH": "84",
    "MEDIA_PLAY": "85",
    "MEDIA_NEXT": "87",
    "MEDIA_PREV": "88",
    "CH_UP": "166",
    "CH_DOWN": "167",
}


def parse_dimensions(dimensions: DimensionsInput) -> tuple[int, int] | None:
    """把设备尺寸转换为整数宽高，无效输入返回 None。"""
    if not dimensions or len(dimensions) < 2:
        return None
    try:
        return int(dimensions[0]), int(dimensions[1])
    except (TypeError, ValueError):
        return None


def _dimensions_or_default(dimensions: DimensionsInput) -> tuple[int, int]:
    # ADB 尺寸查询失败时仍保持手势按钮可用，使用常见竖屏分辨率兜底。
    return parse_dimensions(dimensions) or DEFAULT_DIMENSIONS


def notification_swipe(dimensions: DimensionsInput, expand: bool) -> tuple[int, int, int, int]:
    """根据屏幕尺寸生成展开或收起通知栏的滑动坐标。"""
    width, height = _dimensions_or_default(dimensions)
    x = max(1, width // 2)
    if expand:
        return x, 0, x, max(1, height - 1)
    return x, max(1, height - 1), x, 0


def directional_swipe(
    dimensions: DimensionsInput,
    direction: str,
) -> tuple[int, int, int, int]:
    """根据屏幕尺寸和方向生成位于安全边距内的滑动坐标。"""
    width, height = _dimensions_or_default(dimensions)
    center_x = max(1, width // 2)
    center_y = max(1, height // 2)
    margin_x = max(10, width // 10)
    margin_y = max(10, height // 10)

    match direction.lower():
        case "up":
            return center_x, height - margin_y, center_x, margin_y
        case "down":
            return center_x, margin_y, center_x, height - margin_y
        case "left":
            return width - margin_x, center_y, margin_x, center_y
        case "right":
            return margin_x, center_y, width - margin_x, center_y
        case _:
            raise ValueError(f"Unknown swipe direction: {direction}")
