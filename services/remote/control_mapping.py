"""提供不依赖界面的 Remote 按键与手势坐标映射。"""

import re
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
    "ENTER": "66",
    "DEL": "67",
    "SETTINGS": "176",
    "CAMERA": "27",
    "SEARCH": "84",
    "MEDIA_PLAY": "85",
    "MEDIA_NEXT": "87",
    "MEDIA_PREV": "88",
}


def parse_input_viewport_dimensions(output: str) -> tuple[int, int] | None:
    """提取默认显示的当前逻辑区域；忽略无效、休眠和非默认显示。

    原生 dumpsys input 以 displayId 判断有效性；兼容 Java 的显式 valid 字段。
    未知、冲突或带偏移的区域不降级成自然尺寸，避免在错误坐标位置注入手势。
    """
    if not isinstance(output, str):
        return None
    dimensions: set[tuple[int, int]] = set()
    for viewport in re.finditer(
        r"\bViewport (?:INTERNAL|EXTERNAL|VIRTUAL):\s*(?P<native>[^\r\n]*)"
        r"|\bDisplayViewport\{(?P<java>[^{}]*)\}",
        output,
    ):
        java = viewport.group("java")
        fields = java if java is not None else viewport.group("native")
        if re.search(r"\bdisplayId\s*=\s*0\s*(?:,|$)", fields) is None:
            continue
        valid = re.search(r"\bvalid\s*=\s*(\w+)", fields)
        if (java is not None and valid is None) or (valid and valid.group(1) != "true"):
            continue
        active = re.search(r"\bisActive\s*=\s*([^,}]+)", fields)
        if active is not None and active.group(1).strip() not in ("true", "[1]"):
            continue
        frame = re.search(
            r"\blogicalFrame\s*=\s*\[\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\s*\]",
            fields,
        ) or re.search(
            r"\blogicalFrame\s*=\s*Rect\(\s*(-?\d+),\s*(-?\d+)\s*-\s*(-?\d+),\s*(-?\d+)\s*\)",
            fields,
        )
        if frame is None:
            continue
        left, top, right, bottom = (int(value) for value in frame.groups())
        if left == 0 and top == 0 and right > 0 and bottom > 0:
            dimensions.add((right, bottom))
    return dimensions.pop() if len(dimensions) == 1 else None


def parse_dimensions(dimensions: DimensionsInput) -> tuple[int, int] | None:
    """把设备尺寸转换为整数宽高，无效输入返回 None。"""
    if not dimensions or len(dimensions) < 2:
        return None
    try:
        return int(dimensions[0]), int(dimensions[1])
    except (TypeError, ValueError):
        return None


def _dimensions_or_default(dimensions: DimensionsInput) -> tuple[int, int]:
    # 纯坐标映射保留默认尺寸契约；执行层必须先确认当前逻辑区域有效。
    return parse_dimensions(dimensions) or DEFAULT_DIMENSIONS


def notification_swipe(dimensions: DimensionsInput, expand: bool) -> tuple[int, int, int, int]:
    """根据屏幕尺寸生成展开或收起通知栏的滑动坐标。"""
    width, height = _dimensions_or_default(dimensions)
    x = width // 2
    if expand:
        return x, 0, x, height - 1
    return x, height - 1, x, 0


def directional_swipe(
    dimensions: DimensionsInput,
    direction: str,
) -> tuple[int, int, int, int]:
    """根据屏幕尺寸和方向生成位于安全边距内的滑动坐标。"""
    width, height = _dimensions_or_default(dimensions)
    center_x = width // 2
    center_y = height // 2
    # 极小但有效的虚拟区域也必须落在边界内，常规屏幕保留原有 10% 边距。
    margin_x = min(max(10, width // 10), (width - 1) // 2)
    margin_y = min(max(10, height // 10), (height - 1) // 2)
    far_x = min(width - 1, width - margin_x)
    far_y = min(height - 1, height - margin_y)

    match direction.lower():
        case "up":
            return center_x, far_y, center_x, margin_y
        case "down":
            return center_x, margin_y, center_x, far_y
        case "left":
            return far_x, center_y, margin_x, center_y
        case "right":
            return margin_x, center_y, far_x, center_y
        case _:
            raise ValueError(f"Unknown swipe direction: {direction}")
