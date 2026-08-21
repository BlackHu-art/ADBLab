"""响应式布局的基础类型、事件原因映射与内部事件过滤器。"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

from gui.widgets.responsive_layout import LayoutContext

if TYPE_CHECKING:
    from gui.widgets.responsive_coordinator import ResponsiveCoordinator


class ReflowReason(Enum):
    """能够触发新布局代次的 Qt 或应用级原因。"""

    RESIZE = "resize"
    LAYOUT_REQUEST = "layout_request"
    FONT = "font"
    THEME = "theme"
    SCREEN = "screen"
    DPI = "dpi"
    SPLITTER = "splitter"
    EXPLICIT = "explicit"


class ReflowTarget(Protocol):
    """协调器所需的最小布局目标接口。"""

    def responsive_context(self) -> LayoutContext: ...

    def responsive_plan(self, context: LayoutContext): ...

    def conservative_responsive_plan(self, context: LayoutContext): ...

    def apply_responsive_plan(self, plan) -> None: ...


@dataclass(frozen=True)
class ResponsiveDiagnostics:
    """当前或最近一代布局收敛状态的只读快照。"""

    generation: int = 0
    rounds: int = 0
    stable: bool = True
    fallback_reason: str | None = None
    reasons: tuple[ReflowReason, ...] = ()


@dataclass
class _TopLevelAttachment:
    top_level_ref: weakref.ReferenceType[QWidget]
    event_filter: QObject
    screen_handle_ref: weakref.ReferenceType[QObject] | None = None
    screen_slot: Callable[..., None] | None = None
    destroyed_slot: Callable[..., None] | None = None


_EVENT_REASONS = {
    QEvent.Type.Resize: ReflowReason.RESIZE,
    QEvent.Type.LayoutRequest: ReflowReason.LAYOUT_REQUEST,
    QEvent.Type.FontChange: ReflowReason.FONT,
    QEvent.Type.ApplicationFontChange: ReflowReason.FONT,
    QEvent.Type.ThemeChange: ReflowReason.THEME,
    QEvent.Type.ApplicationPaletteChange: ReflowReason.THEME,
    QEvent.Type.ScreenChangeInternal: ReflowReason.SCREEN,
    QEvent.Type.DevicePixelRatioChange: ReflowReason.DPI,
}
_CLEAR_INTERNAL_LAYOUT_FEEDBACK_EVENT = QEvent.Type(QEvent.registerEventType())


class _ClearInternalLayoutFeedbackEvent(QEvent):
    def __init__(self, generation: int):
        super().__init__(_CLEAR_INTERNAL_LAYOUT_FEEDBACK_EVENT)
        self.generation = generation


def _run_scheduled_round(
    coordinator_ref: weakref.ReferenceType[ResponsiveCoordinator],
    generation: int,
) -> None:
    coordinator = coordinator_ref()
    if coordinator is not None:
        coordinator._run_round(generation)


class _ResponsiveEventFilter(QObject):
    def __init__(self, coordinator: ResponsiveCoordinator, top_level: QWidget, key: int):
        super().__init__()
        self._coordinator_ref = weakref.ref(coordinator)
        self._top_level_ref = weakref.ref(top_level)
        self._key = key

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        top_level = self._top_level_ref()
        if top_level is not None and watched is top_level:
            coordinator = self._coordinator_ref()
            if coordinator is not None:
                coordinator._route_top_level_event(self._key, top_level, event.type())
        return False

    def event(self, event: QEvent) -> bool:
        if event.type() == _CLEAR_INTERNAL_LAYOUT_FEEDBACK_EVENT:
            coordinator = self._coordinator_ref()
            if coordinator is not None:
                coordinator._clear_internal_layout_feedback(self._key, event.generation)
            return True
        return super().event(event)
