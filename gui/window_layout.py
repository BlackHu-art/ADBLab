"""集中处理主窗口尺寸与当前屏幕工作区约束。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize

DEFAULT_WINDOW_SIZE = QSize(1250, 700)
MINIMUM_WINDOW_SIZE = QSize(860, 500)


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
