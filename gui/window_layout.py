"""集中处理主窗口尺寸和左右分栏比例的校验与换算。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize

DEFAULT_WINDOW_SIZE = QSize(1120, 640)
MINIMUM_WINDOW_SIZE = QSize(860, 500)
DEFAULT_PANEL_RATIO = 0.40
DEFAULT_DEVICE_LOG_RATIO = 0.60
MINIMUM_PANEL_RATIO = 0.20
MAXIMUM_PANEL_RATIO = 0.70


@dataclass(frozen=True)
class WorkspaceConstraints:
    """保留用户首选尺寸，并描述当前屏幕实际可采用的窗口约束。"""

    available_size: QSize
    preferred_window_size: QSize
    effective_window_size: QSize
    minimum_window_size: QSize
    restricted: bool

    def __post_init__(self) -> None:
        for name in (
            "available_size",
            "preferred_window_size",
            "effective_window_size",
            "minimum_window_size",
        ):
            object.__setattr__(self, name, QSize(getattr(self, name)))


def _coerce_int(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return int(fallback)
    return parsed


def minimum_window_size_for_available(
    available_size: QSize | None,
    *,
    design_minimum: QSize = MINIMUM_WINDOW_SIZE,
    allow_vertical_overflow: bool = False,
) -> QSize:
    """在受限工作区中把窗口最小值降到屏幕真实可用尺寸。"""

    if available_size is None or not available_size.isValid():
        return QSize(design_minimum)
    return QSize(
        min(design_minimum.width(), available_size.width()),
        (
            design_minimum.height()
            if allow_vertical_overflow
            else min(design_minimum.height(), available_size.height())
        ),
    )


def normalize_window_size(
    width,
    height,
    *,
    available_size: QSize | None = None,
    minimum_size: QSize = MINIMUM_WINDOW_SIZE,
    default_size: QSize = DEFAULT_WINDOW_SIZE,
    allow_vertical_overflow: bool = False,
) -> QSize:
    """把配置尺寸限制在最小值和当前屏幕可用范围内。"""

    effective_minimum = minimum_window_size_for_available(
        available_size,
        design_minimum=minimum_size,
        allow_vertical_overflow=allow_vertical_overflow,
    )
    normalized_width = max(
        effective_minimum.width(),
        _coerce_int(width, default_size.width()),
    )
    normalized_height = max(
        effective_minimum.height(),
        _coerce_int(height, default_size.height()),
    )
    if available_size is not None and available_size.isValid():
        normalized_width = min(normalized_width, available_size.width())
        normalized_height = max(
            effective_minimum.height(),
            min(normalized_height, available_size.height()),
        )
    return QSize(normalized_width, normalized_height)


def compute_workspace_constraints(
    available_size: QSize | None,
    preferred_window_size: QSize,
    *,
    design_minimum: QSize = MINIMUM_WINDOW_SIZE,
    allow_vertical_overflow: bool = False,
) -> WorkspaceConstraints:
    """计算当前屏幕的有效尺寸，不把临时裁剪写回用户首选尺寸。"""

    available = QSize(available_size) if available_size is not None else QSize()
    preferred = QSize(preferred_window_size)
    if not preferred.isValid():
        preferred = QSize(DEFAULT_WINDOW_SIZE)
    minimum = minimum_window_size_for_available(
        available if available.isValid() else None,
        design_minimum=design_minimum,
        allow_vertical_overflow=allow_vertical_overflow,
    )
    effective = normalize_window_size(
        preferred.width(),
        preferred.height(),
        available_size=available if available.isValid() else None,
        minimum_size=design_minimum,
        default_size=preferred,
        allow_vertical_overflow=allow_vertical_overflow,
    )
    return WorkspaceConstraints(
        available_size=available,
        preferred_window_size=preferred,
        effective_window_size=effective,
        minimum_window_size=minimum,
        restricted=(
            available.isValid()
            and (
                available.width() < design_minimum.width()
                or available.height() < design_minimum.height()
            )
        ),
    )


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


def split_sizes_for_constraints(
    total_width: int,
    ratio: float,
    *,
    left_minimum: int,
    right_minimum: int,
) -> tuple[int, int]:
    """按比例拆分宽度，并以当前两个面板的真实最小宽度为边界。"""

    total_width = max(0, _coerce_int(total_width, 0))
    left_minimum = max(0, _coerce_int(left_minimum, 0))
    right_minimum = max(0, _coerce_int(right_minimum, 0))
    minimum_total = left_minimum + right_minimum
    if total_width <= 0:
        return 0, 0
    if minimum_total > total_width:
        if minimum_total <= 0:
            return split_sizes_for_ratio(total_width, ratio)
        left_width = int(round(total_width * left_minimum / minimum_total))
        return left_width, total_width - left_width

    requested_left, _requested_right = split_sizes_for_ratio(total_width, ratio)
    left_width = min(total_width - right_minimum, max(left_minimum, requested_left))
    return left_width, total_width - left_width
