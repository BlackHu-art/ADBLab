"""合并外部布局事件并在有界应用轮次内收敛的响应式协调器。"""

from __future__ import annotations

import weakref
from collections.abc import Iterable
from functools import partial

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from gui.widgets.responsive_primitives import (
    _EVENT_REASONS,
    ReflowReason,
    ReflowTarget,
    ResponsiveDiagnostics,
    _ClearInternalLayoutFeedbackEvent,
    _ResponsiveEventFilter,
    _run_scheduled_round,
    _TopLevelAttachment,
)


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
