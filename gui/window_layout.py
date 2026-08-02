"""集中处理主窗口尺寸和左右分栏比例的校验与换算。"""

from __future__ import annotations

from PySide6.QtCore import QSize

DEFAULT_WINDOW_SIZE = QSize(1120, 640)
MINIMUM_WINDOW_SIZE = QSize(860, 500)
DEFAULT_PANEL_RATIO = 0.40
MINIMUM_PANEL_RATIO = 0.20
MAXIMUM_PANEL_RATIO = 0.70


def _coerce_int(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return int(fallback)
    return parsed


def normalize_window_size(
    width,
    height,
    *,
    available_size: QSize | None = None,
    minimum_size: QSize = MINIMUM_WINDOW_SIZE,
    default_size: QSize = DEFAULT_WINDOW_SIZE,
) -> QSize:
    """把配置尺寸限制在最小值和当前屏幕可用范围内。"""

    normalized_width = max(minimum_size.width(), _coerce_int(width, default_size.width()))
    normalized_height = max(minimum_size.height(), _coerce_int(height, default_size.height()))
    if available_size is not None and available_size.isValid():
        maximum_width = max(minimum_size.width(), available_size.width())
        maximum_height = max(minimum_size.height(), available_size.height())
        normalized_width = min(normalized_width, maximum_width)
        normalized_height = min(normalized_height, maximum_height)
    return QSize(normalized_width, normalized_height)


def normalize_panel_ratio(value, *, fallback: float = DEFAULT_PANEL_RATIO) -> float:
    """返回安全的左栏比例，异常值回退到默认比例。"""

    try:
        ratio = float(value)
    except (TypeError, ValueError, OverflowError):
        ratio = float(fallback)
    if ratio <= 0 or ratio >= 1:
        ratio = float(fallback)
    return min(MAXIMUM_PANEL_RATIO, max(MINIMUM_PANEL_RATIO, ratio))


def ratio_from_sizes(left_width: int, right_width: int) -> float:
    """根据分栏实际宽度计算并校验左栏比例。"""

    left_width = max(0, _coerce_int(left_width, 0))
    right_width = max(0, _coerce_int(right_width, 0))
    total = left_width + right_width
    if total <= 0:
        return DEFAULT_PANEL_RATIO
    return normalize_panel_ratio(left_width / total)


def split_sizes_for_ratio(total_width: int, ratio: float) -> tuple[int, int]:
    """按比例拆分可用宽度并保证两个结果均为非负整数。"""

    total_width = max(0, int(total_width))
    ratio = normalize_panel_ratio(ratio)
    left_width = int(round(total_width * ratio))
    return left_width, max(0, total_width - left_width)
