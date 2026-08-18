"""协调本地 Qt 网格重排，并让每代布局在有界轮次内收敛。"""

from __future__ import annotations

import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from enum import Enum
from functools import partial
from typing import Protocol

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QWidget
from shiboken6 import isValid

from gui.widgets.responsive_layout import (
    GridMode,
    GridPlan,
    ItemMetric,
    LayoutContext,
    WidthPolicy,
    adaptive_layout_spacing,
    choose_grid_plan,
    validate_grid_modes,
)


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


class ResponsiveCoordinator:
    """合并外部布局事件，并在最多三次应用后锁定保守方案。"""

    MAX_APPLY_ROUNDS = 3
    MAX_CONTEXT_SYNC_ROUNDS = 3
    RESIZE_DEBOUNCE_MS = 40
    _DEBOUNCED_REASONS = frozenset(
        {
            ReflowReason.RESIZE,
            ReflowReason.SPLITTER,
            ReflowReason.SCREEN,
            ReflowReason.DPI,
        }
    )

    def __init__(self) -> None:
        self._target_refs: list[weakref.ReferenceType[ReflowTarget]] = []
        self._attachments: dict[int, _TopLevelAttachment] = {}
        self._generation = 0
        self._rounds = 0
        self._state = "idle"
        self._fallback_reason: str | None = None
        self._fallback_locked = False
        self._reasons: list[ReflowReason] = []
        self._pending_reasons: list[ReflowReason] = []
        self._plan_history: list[object] = []
        self._settling_history: list[object] = []
        self._context_sync_rounds = 0
        self._settling_barrier_fingerprint: object | None = None
        self._in_apply = False
        self._internal_layout_feedback: dict[int, int] = {}
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(self.RESIZE_DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._flush_debounced_generation)

    @property
    def diagnostics(self) -> ResponsiveDiagnostics:
        return ResponsiveDiagnostics(
            generation=self._generation,
            rounds=self._rounds,
            stable=self._state == "idle",
            fallback_reason=self._fallback_reason,
            reasons=tuple(self._reasons),
        )

    @property
    def target_count(self) -> int:
        self._purge_targets()
        return len(self._target_refs)

    @property
    def attached_top_level_count(self) -> int:
        for key, attachment in tuple(self._attachments.items()):
            top_level = attachment.top_level_ref()
            if top_level is None or not isValid(top_level):
                self._detach_top_level_key(key, remove_filter=False)
        return len(self._attachments)

    def register(self, target: ReflowTarget) -> None:
        self._purge_targets()
        if any(target_ref() is target for target_ref in self._target_refs):
            return
        coordinator_ref = weakref.ref(self)

        def forget_target(dead_ref: weakref.ReferenceType[ReflowTarget]) -> None:
            coordinator = coordinator_ref()
            if coordinator is not None:
                coordinator._target_refs = [
                    target_ref
                    for target_ref in coordinator._target_refs
                    if target_ref is not dead_ref and target_ref() is not None
                ]

        self._target_refs.append(weakref.ref(target, forget_target))

    def unregister(self, target: ReflowTarget) -> None:
        self._target_refs = [
            target_ref
            for target_ref in self._target_refs
            if target_ref() is not None and target_ref() is not target
        ]

    def request_reflow(self, reason: ReflowReason) -> None:
        reason = reason if isinstance(reason, ReflowReason) else ReflowReason(reason)
        if reason is ReflowReason.LAYOUT_REQUEST and (self._state == "settling" or self._in_apply):
            return
        if self._state == "idle":
            if reason in self._DEBOUNCED_REASONS:
                self._state = "debouncing"
                self._reasons = [reason]
                self._debounce_timer.start()
                return
            self._start_generation((reason,))
            return
        if self._state == "debouncing":
            self._append_reason(self._reasons, reason)
            if reason in self._DEBOUNCED_REASONS:
                self._debounce_timer.start()
            else:
                self._debounce_timer.stop()
                reasons = tuple(self._reasons)
                self._start_generation(reasons)
            return
        if self._state == "scheduled":
            self._append_reason(self._reasons, reason)
            return
        self._append_reason(self._pending_reasons, reason)

    def _flush_debounced_generation(self) -> None:
        """在连续 resize/splitter/screen 通知的尾沿提交一次最终几何。"""

        if self._state != "debouncing":
            return
        reasons = tuple(self._reasons)
        self._start_generation(reasons)

    def attach_top_level(self, top_level: QWidget) -> None:
        key = id(top_level)
        if key in self._attachments:
            return
        event_filter = _ResponsiveEventFilter(self, top_level, key)
        top_level.installEventFilter(event_filter)
        attachment = _TopLevelAttachment(weakref.ref(top_level), event_filter)
        self._attachments[key] = attachment
        coordinator_ref = weakref.ref(self)

        def detach_destroyed(*_args) -> None:
            coordinator = coordinator_ref()
            if coordinator is not None:
                coordinator._detach_top_level_key(key, remove_filter=False)

        attachment.destroyed_slot = detach_destroyed
        top_level.destroyed.connect(detach_destroyed)
        self._ensure_screen_signal(key, top_level)

    def detach_top_level(self, top_level: QWidget) -> None:
        self._detach_top_level_key(id(top_level), remove_filter=True)

    @staticmethod
    def _append_reason(reasons: list[ReflowReason], reason: ReflowReason) -> None:
        if reason not in reasons:
            reasons.append(reason)

    def _purge_targets(self) -> None:
        self._target_refs = [
            target_ref for target_ref in self._target_refs if target_ref() is not None
        ]

    def _live_targets(self) -> tuple[ReflowTarget, ...]:
        self._purge_targets()
        return tuple(
            target for target_ref in self._target_refs if (target := target_ref()) is not None
        )

    def _start_generation(self, reasons: Iterable[ReflowReason]) -> None:
        self._debounce_timer.stop()
        self._generation += 1
        self._rounds = 0
        self._state = "scheduled"
        self._fallback_reason = None
        self._fallback_locked = False
        self._reasons = []
        self._plan_history = []
        self._settling_history = []
        self._context_sync_rounds = 0
        self._settling_barrier_fingerprint = None
        for reason in reasons:
            self._append_reason(self._reasons, reason)
        self._schedule_round(self._generation)

    def _schedule_round(self, generation: int) -> None:
        callback = partial(_run_scheduled_round, weakref.ref(self), generation)
        QTimer.singleShot(0, callback)

    def _schedule_settling_verification(self, generation: int) -> None:
        """留出一次 Qt 布局/滚动条事件窗口后，在本代复核最终 viewport。"""

        callback = partial(_run_scheduled_round, weakref.ref(self), generation)
        QTimer.singleShot(1, callback)

    @staticmethod
    def _plan_fingerprint(plan) -> object:
        return getattr(plan, "fingerprint", plan)

    @classmethod
    def _plan_settling_fingerprint(cls, plan) -> object:
        return getattr(plan, "settling_fingerprint", cls._plan_fingerprint(plan))

    def _collect_candidates(self):
        candidates = []
        for target in self._live_targets():
            try:
                context = target.responsive_context()
                plan = target.responsive_plan(context)
            except RuntimeError:
                self.unregister(target)
                continue
            candidates.append((target, context, plan))
        return candidates

    def _batch_fingerprint(self, candidates) -> tuple[object, ...]:
        return tuple(
            (id(target), self._plan_fingerprint(plan)) for target, _context, plan in candidates
        )

    def _batch_settling_fingerprint(self, candidates) -> tuple[object, ...]:
        return tuple(
            (id(target), self._plan_settling_fingerprint(plan))
            for target, _context, plan in candidates
        )

    def _can_synchronize_candidates(self, candidates, fingerprint) -> bool:
        if not self._plan_history:
            return False
        previous = self._plan_history[-1]
        if len(previous) != len(fingerprint):
            return False
        for (target, _context, _plan), previous_item, current_item in zip(
            candidates,
            previous,
            fingerprint,
        ):
            if previous_item == current_item:
                continue
            if not callable(getattr(target, "synchronize_responsive_plan", None)):
                return False
        return True

    def _synchronize_candidates(self, candidates, fingerprint) -> None:
        previous = self._plan_history[-1]
        for (target, _context, plan), previous_item, current_item in zip(
            candidates,
            previous,
            fingerprint,
        ):
            if previous_item == current_item:
                continue
            synchronize = getattr(target, "synchronize_responsive_plan", None)
            if not callable(synchronize):
                continue
            try:
                synchronize(plan)
            except RuntimeError:
                self.unregister(target)

    def _run_round(self, generation: int) -> None:
        if generation != self._generation or self._state == "idle":
            return
        self._state = "settling"
        if self._fallback_locked:
            self._collect_candidates()
            self._finish_generation(generation)
            return

        candidates = self._collect_candidates()
        if not candidates:
            self._finish_generation(generation)
            return
        fingerprint = self._batch_fingerprint(candidates)
        settling_fingerprint = self._batch_settling_fingerprint(candidates)
        if self._plan_history and fingerprint == self._plan_history[-1]:
            requires_barrier = any(
                bool(getattr(target, "requires_settling_barrier", False))
                for target, _context, _plan in candidates
            )
            if requires_barrier and self._settling_barrier_fingerprint != fingerprint:
                self._settling_barrier_fingerprint = fingerprint
                self._schedule_settling_verification(generation)
                return
            self._finish_generation(generation)
            return
        self._settling_barrier_fingerprint = None

        fallback_reason = None
        if fingerprint in self._plan_history:
            fallback_reason = "oscillation"
        elif (
            self._settling_history
            and settling_fingerprint == self._settling_history[-1]
            and self._context_sync_rounds < self.MAX_CONTEXT_SYNC_ROUNDS
            and self._can_synchronize_candidates(candidates, fingerprint)
        ):
            # 网格重排会先改变各行高度，随后才让滚动条刷新 viewport。
            # 行高不参与水平决策，只同步已应用只读快照并留出一轮事件循环，
            # 不占用防振荡的真实应用轮次。
            self._synchronize_candidates(candidates, fingerprint)
            self._context_sync_rounds += 1
            self._plan_history.append(fingerprint)
            self._settling_history.append(settling_fingerprint)
            self._schedule_round(generation)
            return
        elif self._rounds + 1 >= self.MAX_APPLY_ROUNDS:
            fallback_reason = "round_limit"

        if fallback_reason is not None:
            previous_settling = dict(self._settling_history[-1]) if self._settling_history else {}
            fallback_candidates = []
            for target, context, plan in candidates:
                current_settling = self._plan_settling_fingerprint(plan)
                if previous_settling.get(id(target)) == current_settling:
                    # 同一协调器可能同时服务 Devices 和右侧多个功能行；某个目标
                    # 未收敛时，只让该目标进入保守模式，稳定目标保持当前布局。
                    fallback_plan = plan
                else:
                    fallback_plan = target.conservative_responsive_plan(context)
                fallback_candidates.append((target, fallback_plan))
            self._apply_candidates(fallback_candidates)
            self._rounds += 1
            self._fallback_reason = fallback_reason
            self._fallback_locked = True
            self._plan_history.append(
                tuple(
                    (id(target), self._plan_fingerprint(plan))
                    for target, plan in fallback_candidates
                )
            )
            self._schedule_round(generation)
            return

        self._apply_candidates([(target, plan) for target, _context, plan in candidates])
        self._rounds += 1
        self._context_sync_rounds = 0
        self._plan_history.append(fingerprint)
        self._settling_history.append(settling_fingerprint)
        self._schedule_round(generation)

    def _apply_candidates(self, candidates) -> None:
        self._in_apply = True
        try:
            for target, plan in candidates:
                try:
                    target.apply_responsive_plan(plan)
                except RuntimeError:
                    self.unregister(target)
        finally:
            self._in_apply = False

    def _finish_generation(self, generation: int) -> None:
        if generation != self._generation:
            return
        self._state = "idle"
        self._schedule_internal_layout_feedback_clear(generation)
        if not self._pending_reasons:
            return
        pending_reasons = tuple(self._pending_reasons)
        self._pending_reasons.clear()
        self._start_generation(pending_reasons)

    def _route_top_level_event(
        self,
        key: int,
        top_level: QWidget,
        event_type: QEvent.Type,
    ) -> None:
        if event_type in (QEvent.Type.Show, QEvent.Type.WinIdChange):
            self._ensure_screen_signal(key, top_level)
        if event_type == QEvent.Type.LayoutRequest and key in self._internal_layout_feedback:
            return
        reason = _EVENT_REASONS.get(event_type)
        if reason is not None:
            self.request_reflow(reason)

    def _mark_internal_layout_feedback(self, container: QWidget) -> None:
        if not self._in_apply:
            return
        candidates = (container, container.window())
        for candidate in candidates:
            key = id(candidate)
            if key in self._attachments:
                self._internal_layout_feedback[key] = self._generation

    def _schedule_internal_layout_feedback_clear(self, generation: int) -> None:
        for key, attachment in self._attachments.items():
            if self._internal_layout_feedback.get(key) != generation:
                continue
            QCoreApplication.postEvent(
                attachment.event_filter,
                _ClearInternalLayoutFeedbackEvent(generation),
                Qt.EventPriority.LowEventPriority.value,
            )

    def _clear_internal_layout_feedback(self, key: int, generation: int) -> None:
        if self._internal_layout_feedback.get(key) == generation:
            self._internal_layout_feedback.pop(key, None)

    def _ensure_screen_signal(self, key: int, top_level: QWidget) -> None:
        attachment = self._attachments.get(key)
        if attachment is None:
            return
        handle = top_level.windowHandle()
        current_handle = (
            attachment.screen_handle_ref() if attachment.screen_handle_ref is not None else None
        )
        if current_handle is handle and attachment.screen_slot is not None:
            return
        self._disconnect_screen_signal(attachment)
        if handle is None:
            return
        coordinator_ref = weakref.ref(self)

        def screen_changed(*_args) -> None:
            coordinator = coordinator_ref()
            if coordinator is not None and key in coordinator._attachments:
                coordinator.request_reflow(ReflowReason.SCREEN)

        handle.screenChanged.connect(screen_changed)
        attachment.screen_handle_ref = weakref.ref(handle)
        attachment.screen_slot = screen_changed

    @staticmethod
    def _disconnect_screen_signal(attachment: _TopLevelAttachment) -> None:
        handle = (
            attachment.screen_handle_ref() if attachment.screen_handle_ref is not None else None
        )
        if handle is not None and isValid(handle) and attachment.screen_slot is not None:
            try:
                handle.screenChanged.disconnect(attachment.screen_slot)
            except (RuntimeError, TypeError):
                pass
        attachment.screen_handle_ref = None
        attachment.screen_slot = None

    def _detach_top_level_key(self, key: int, *, remove_filter: bool) -> None:
        attachment = self._attachments.pop(key, None)
        if attachment is None:
            return
        self._internal_layout_feedback.pop(key, None)
        top_level = attachment.top_level_ref()
        if remove_filter and top_level is not None and isValid(top_level):
            top_level.removeEventFilter(attachment.event_filter)
            if attachment.destroyed_slot is not None:
                try:
                    top_level.destroyed.disconnect(attachment.destroyed_slot)
                except (RuntimeError, TypeError):
                    pass
        self._disconnect_screen_signal(attachment)


class ResponsiveGridBinding:
    """把真实 QWidget 度量连接到纯规划器和有界协调器。"""

    def __init__(
        self,
        container: QWidget,
        layout: QGridLayout,
        widgets: Iterable[QWidget],
        policies: Iterable[WidthPolicy],
        modes: Iterable[GridMode],
        coordinator: ResponsiveCoordinator,
        *,
        context_provider: Callable[[QWidget], LayoutContext],
        explicit_minimums: Iterable[int] = (),
        use_provided_geometry: bool = False,
        adaptive_spacing: bool = False,
    ) -> None:
        widget_items = tuple(widgets)
        policy_items = tuple(policies)
        mode_items = tuple(modes)
        explicit_items = tuple(explicit_minimums)
        if len(widget_items) != len(policy_items):
            raise ValueError("policies must match widgets")
        mode_items = validate_grid_modes(mode_items)
        if explicit_items and len(explicit_items) != len(widget_items):
            raise ValueError("explicit_minimums must match widgets")
        if any(policy is WidthPolicy.EXPLICIT for policy in policy_items) and not explicit_items:
            raise ValueError("EXPLICIT policies require explicit_minimums")

        self._container_ref = weakref.ref(container)
        self._layout_ref = weakref.ref(layout)
        self._widget_refs = tuple(weakref.ref(widget) for widget in widget_items)
        self._policies = policy_items
        self._modes = mode_items
        self._coordinator_ref = weakref.ref(coordinator)
        try:
            self._context_provider_ref: weakref.WeakMethod | None = weakref.WeakMethod(
                context_provider
            )
        except TypeError:
            self._context_provider_ref = None
            self._context_provider = context_provider
        else:
            self._context_provider = None
        self._explicit_minimums = explicit_items
        self._use_provided_geometry = bool(use_provided_geometry)
        self._adaptive_spacing = bool(adaptive_spacing)
        self._initial_minimum_width = container.minimumWidth()
        self._initial_maximum_width = container.maximumWidth()
        self._applied_plan: GridPlan | None = None
        self._destroyed = False
        container.destroyed.connect(self._on_container_destroyed)
        coordinator.register(self)

    @property
    def applied_plan(self) -> GridPlan | None:
        return self._applied_plan

    @property
    def requires_settling_barrier(self) -> bool:
        """外部 viewport 几何需要等待滚动条显隐后再完成当前代。"""

        return self._use_provided_geometry

    def widgets(self) -> tuple[QWidget, ...]:
        if self._destroyed:
            return ()
        return tuple(
            widget
            for widget_ref in self._widget_refs
            if (widget := widget_ref()) is not None and isValid(widget)
        )

    def responsive_context(self) -> LayoutContext:
        container = self._live_container()
        provider = self._resolve_context_provider()
        provided = provider(container)
        if not isinstance(provided, LayoutContext):
            raise TypeError("context_provider must return LayoutContext")
        rect = container.contentsRect()
        width = provided.width if self._use_provided_geometry else rect.width()
        height = provided.height if self._use_provided_geometry else rect.height()
        font = container.font()
        font_fingerprint = (
            font.family(),
            font.styleName(),
            font.pointSizeF(),
            font.pixelSize(),
            int(font.weight()),
            font.italic(),
            font.stretch(),
            font.fixedPitch(),
            font.kerning(),
            font.toString(),
        )
        return LayoutContext(
            width,
            height,
            provided.restricted_workspace,
            font_fingerprint,
            provided.style_generation,
        )

    def _resolve_context_provider(self) -> Callable[[QWidget], LayoutContext]:
        if self._context_provider_ref is None:
            assert self._context_provider is not None
            return self._context_provider
        provider = self._context_provider_ref()
        if provider is None:
            raise RuntimeError("responsive context provider owner has been destroyed")
        owner = getattr(provider, "__self__", None)
        if isinstance(owner, QObject) and not isValid(owner):
            raise RuntimeError("responsive context provider owner has been destroyed")
        return provider

    def responsive_plan(self, context: LayoutContext) -> GridPlan:
        return self._plan_for_modes(context, self._modes)

    def conservative_responsive_plan(self, context: LayoutContext) -> GridPlan:
        conservative_mode = self._modes[-1]
        rebased_mode = replace(conservative_mode, conservatism_rank=0)
        plan = self._plan_for_modes(context, (rebased_mode,))
        return replace(plan, mode=conservative_mode)

    def apply_responsive_plan(self, plan: GridPlan) -> None:
        layout = self._live_layout()
        widgets = self._live_widgets_exact()
        current = self._applied_plan
        if (
            current is not None
            and current.fingerprint == plan.fingerprint
            and layout.horizontalSpacing() == plan.spacing
            and layout.verticalSpacing() == plan.spacing
        ):
            return
        if layout.horizontalSpacing() != plan.spacing:
            layout.setHorizontalSpacing(plan.spacing)
        if layout.verticalSpacing() != plan.spacing:
            layout.setVerticalSpacing(plan.spacing)
        structure = (
            plan.mode.fingerprint,
            tuple(placement.fingerprint for placement in plan.placements),
            plan.column_widths,
            plan.column_stretches,
            plan.row_stretches,
        )
        current_structure = (
            (
                current.mode.fingerprint,
                tuple(placement.fingerprint for placement in current.placements),
                current.column_widths,
                current.column_stretches,
                current.row_stretches,
            )
            if current is not None
            else None
        )
        if structure != current_structure:
            previous_columns = max(
                int(layout.property("responsiveColumnCount") or 0),
                layout.columnCount(),
            )
            previous_rows = max(
                int(layout.property("responsiveRowCount") or 0),
                layout.rowCount(),
            )
            while layout.count():
                layout.takeAt(0)
            for placement in plan.placements:
                layout.addWidget(
                    widgets[placement.item_index],
                    placement.row,
                    placement.column,
                    placement.row_span,
                    placement.column_span,
                )
            for column in range(max(previous_columns, plan.mode.columns)):
                stretch = plan.column_stretches[column] if column < plan.mode.columns else 0
                layout.setColumnStretch(column, stretch)
                minimum_width = plan.column_widths[column] if column < plan.mode.columns else 0
                layout.setColumnMinimumWidth(column, minimum_width)
            for row in range(max(previous_rows, len(plan.row_stretches))):
                stretch = plan.row_stretches[row] if row < len(plan.row_stretches) else 0
                layout.setRowStretch(row, stretch)
            layout.setProperty("responsiveColumnCount", plan.mode.columns)
            layout.setProperty("responsiveRowCount", len(plan.row_stretches))
        container = self._live_container()
        if self._use_provided_geometry:
            # 外部 viewport 作为规划宽度时，每行必须独立落实该宽度。共享滚动内容
            # 可以由某个溢出行撑宽，但不得把其他未溢出网格的 stretch 列一并摊宽。
            container.setMaximumWidth(self._initial_maximum_width)
            container.setMinimumWidth(self._initial_minimum_width)
            if plan.overflow_required:
                row_width = min(
                    self._initial_maximum_width,
                    max(self._initial_minimum_width, plan.required_width),
                )
                container.setMinimumWidth(row_width)
                container.setMaximumWidth(row_width)
            else:
                container.setMaximumWidth(
                    min(
                        self._initial_maximum_width,
                        max(self._initial_minimum_width, plan.available_width),
                    )
                )
        container.setProperty(
            "responsiveOverflowWidth",
            plan.required_width if plan.overflow_required else 0,
        )
        container.updateGeometry()
        if (parent := container.parentWidget()) is not None:
            parent.updateGeometry()
        self._applied_plan = plan
        coordinator = self._coordinator_ref()
        if coordinator is not None:
            coordinator._mark_internal_layout_feedback(self._live_container())

    def synchronize_responsive_plan(self, plan: GridPlan) -> None:
        """只同步不影响水平决策的最新上下文，不重复搬移或调整控件。"""

        self._live_container()
        self._live_widgets_exact()
        current = self._applied_plan
        if current is None or current.settling_fingerprint != plan.settling_fingerprint:
            raise RuntimeError("responsive plan cannot be synchronized before it is applied")
        self._applied_plan = plan

    def _live_container(self) -> QWidget:
        container = self._container_ref()
        if self._destroyed or container is None or not isValid(container):
            raise RuntimeError("responsive container has been destroyed")
        return container

    def _live_layout(self) -> QGridLayout:
        layout = self._layout_ref()
        if self._destroyed or layout is None or not isValid(layout):
            raise RuntimeError("responsive layout has been destroyed")
        return layout

    def _live_widgets_exact(self) -> tuple[QWidget, ...]:
        widgets = self.widgets()
        if len(widgets) != len(self._widget_refs):
            raise RuntimeError("responsive widget has been destroyed")
        return widgets

    def _measure_widgets(self) -> tuple[ItemMetric, ...]:
        widgets = self._live_widgets_exact()
        metrics = []
        for index, (widget, policy) in enumerate(zip(widgets, self._policies)):
            minimum_width = max(0, widget.minimumWidth())
            if policy is WidthPolicy.NATURAL:
                minimum_width = max(minimum_width, widget.minimumSizeHint().width())
                preferred_width = max(minimum_width, widget.sizeHint().width())
            elif policy is WidthPolicy.SHRINKABLE:
                # 可收缩字段的当前文本会改变 sizeHint；仅采用稳定的最小尺寸提示作为
                # 偏好宽度，并保留控件显式 minimumWidth 作为布局下限。
                preferred_width = max(minimum_width, widget.minimumSizeHint().width())
            elif policy is WidthPolicy.WRAPPING:
                # 可换行文案同样不以当前文本的自然宽度驱动断点。
                preferred_width = max(minimum_width, widget.minimumSizeHint().width())
            elif policy is WidthPolicy.EXPLICIT:
                minimum_width = max(0, int(self._explicit_minimums[index]))
                preferred_width = max(minimum_width, widget.sizeHint().width())
            else:
                preferred_width = max(minimum_width, widget.sizeHint().width())
            metrics.append(ItemMetric(minimum_width, preferred_width, policy))
        return tuple(metrics)

    def _plan_for_modes(
        self,
        context: LayoutContext,
        modes: tuple[GridMode, ...],
    ) -> GridPlan:
        layout = self._live_layout()
        metrics = self._measure_widgets()
        spacing = layout.horizontalSpacing()
        if spacing < 0:
            spacing = layout.spacing()
        if spacing < 0:
            spacing = 0
        if self._adaptive_spacing:
            spacing = 2
            provisional = choose_grid_plan(
                metrics,
                modes,
                context.width,
                layout.contentsMargins(),
                spacing,
                context.fingerprint,
            )
            gap_count = max(0, provisional.mode.columns - 1)
            minimum_width = max(0, provisional.required_width - spacing * gap_count)
            font_height = max(
                (widget.fontMetrics().height() for widget in self._live_widgets_exact()),
                default=self._live_container().fontMetrics().height(),
            )
            spacing = adaptive_layout_spacing(
                context.width,
                minimum_width,
                font_height,
                gap_count,
            )
        return choose_grid_plan(
            metrics,
            modes,
            context.width,
            layout.contentsMargins(),
            spacing,
            context.fingerprint,
        )

    def _on_container_destroyed(self, *_args) -> None:
        self._destroyed = True
        coordinator = self._coordinator_ref()
        if coordinator is not None:
            coordinator.unregister(self)
