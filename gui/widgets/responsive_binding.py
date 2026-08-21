"""把真实 QWidget 度量连接到纯规划器和有界协调器的网格绑定。"""

from __future__ import annotations

import weakref
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
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

if TYPE_CHECKING:
    from gui.widgets.responsive_coordinator import ResponsiveCoordinator


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
