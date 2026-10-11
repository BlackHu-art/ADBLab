"""响应式计划缓存只复用相同水平输入，不缓存真实控件度量。"""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QWidget

from gui.widgets import responsive_binding
from gui.widgets.responsive_binding import ResponsiveGridBinding
from gui.widgets.responsive_coordinator import ResponsiveCoordinator
from gui.widgets.responsive_layout import LayoutContext, WidthPolicy, row_major_mode

pytestmark = pytest.mark.ui


class _MetricWidget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.minimum_hint_width = 40
        self.preferred_hint_width = 70
        self.measurements = 0

    def minimumSizeHint(self):
        self.measurements += 1
        return QSize(self.minimum_hint_width, 24)

    def sizeHint(self):
        self.measurements += 1
        return QSize(self.preferred_hint_width, 24)


@pytest.fixture
def cached_binding(qt_application, monkeypatch):
    roots = []
    planner = Mock(wraps=responsive_binding.choose_grid_plan)
    monkeypatch.setattr(responsive_binding, "choose_grid_plan", planner)

    def build(*, adaptive=False):
        container = QWidget()
        roots.append(container)
        layout = QGridLayout(container)
        layout.setContentsMargins(3, 4, 5, 6)
        layout.setHorizontalSpacing(6)
        widgets = (_MetricWidget(container), _MetricWidget(container))
        coordinator = ResponsiveCoordinator()
        context = LayoutContext(240, 100, False, ("Sans", 12.0), 1)
        binding = ResponsiveGridBinding(
            container, layout, widgets, (WidthPolicy.NATURAL,) * 2,
            (row_major_mode("two", 2, 0), row_major_mode("one", 1, 1)),
            coordinator, context_provider=lambda _container: context,
            adaptive_spacing=adaptive,
        )
        return binding, layout, widgets, context, planner

    yield build
    for root in roots:
        root.close()
        root.deleteLater()


@pytest.mark.parametrize("adaptive,initial_calls", [(False, 1), (True, 2)])
def test_identical_and_height_only_inputs_reuse_plan_but_remeasure_widgets(
    cached_binding, adaptive, initial_calls,
):
    binding, _layout, widgets, context, planner = cached_binding(adaptive=adaptive)
    first = binding.responsive_plan(context)
    measurements = sum(widget.measurements for widget in widgets)

    same = binding.responsive_plan(context)
    taller = binding.responsive_plan(replace(context, height=320))

    assert planner.call_count == initial_calls
    assert same == first
    assert taller.context_fingerprint == replace(context, height=320).fingerprint
    assert taller.settling_fingerprint == first.settling_fingerprint
    assert sum(widget.measurements for widget in widgets) > measurements


@pytest.mark.parametrize("changes", [
    {"width": 80},
    {"restricted_workspace": True},
    {"font_fingerprint": ("Other font", 18.0)},
    {"style_generation": 2},
])
def test_context_changes_invalidate_cached_plan(cached_binding, changes):
    binding, _layout, _widgets, context, planner = cached_binding()
    binding.responsive_plan(context)
    updated = replace(context, **changes)

    plan = binding.responsive_plan(updated)

    assert planner.call_count == 2
    assert plan.context_fingerprint == updated.fingerprint
    assert plan.available_width == updated.width


@pytest.mark.parametrize("change", ["minimum_hint", "preferred_hint", "explicit_minimum"])
def test_current_widget_metrics_invalidate_plan_without_context_change(cached_binding, change):
    binding, _layout, widgets, context, planner = cached_binding()
    before = binding.responsive_plan(context)
    if change == "minimum_hint":
        widgets[0].minimum_hint_width = 90
    elif change == "preferred_hint":
        widgets[0].preferred_hint_width = 120
    else:
        widgets[0].setMinimumWidth(100)

    after = binding.responsive_plan(context)

    assert planner.call_count == 2
    assert after.metrics != before.metrics


@pytest.mark.parametrize("change", ["horizontal_margin", "vertical_margin", "spacing"])
def test_layout_margins_and_spacing_invalidate_plan(cached_binding, change):
    binding, layout, _widgets, context, planner = cached_binding()
    before = binding.responsive_plan(context)
    if change == "horizontal_margin":
        layout.setContentsMargins(11, 4, 5, 6)
    elif change == "vertical_margin":
        layout.setContentsMargins(3, 12, 5, 6)
    else:
        layout.setHorizontalSpacing(11)

    after = binding.responsive_plan(context)

    assert planner.call_count == 2
    if change == "spacing":
        assert after.spacing == 11
    else:
        assert after.margins != before.margins


def test_adaptive_spacing_uses_fresh_widget_font_height(cached_binding):
    binding, _layout, widgets, context, planner = cached_binding(adaptive=True)
    narrow = replace(context, width=100)
    for widget in widgets:
        widget.setFont(QFont("Sans", 8))
    before = binding.responsive_plan(narrow)
    for widget in widgets:
        widget.setFont(QFont("Sans", 32))

    after = binding.responsive_plan(narrow)

    assert planner.call_count == 4
    assert after.metrics == before.metrics
    assert after.spacing < before.spacing


def test_normal_and_conservative_plans_keep_only_latest_inputs(cached_binding):
    binding, _layout, _widgets, context, planner = cached_binding()
    binding.responsive_plan(context)
    conservative = binding.conservative_responsive_plan(context)
    binding.responsive_plan(context)
    binding.conservative_responsive_plan(context)
    assert planner.call_count == 2
    assert conservative.mode.name == "one"
    assert conservative.mode.conservatism_rank == 1

    for width in range(241, 251):
        current = replace(context, width=width)
        binding.responsive_plan(current)
        binding.conservative_responsive_plan(current)
    previous_calls = planner.call_count
    binding.responsive_plan(context)
    binding.conservative_responsive_plan(context)
    assert planner.call_count == previous_calls + 2


def test_changed_modes_are_not_reused_from_same_cache_slot(cached_binding):
    binding, _layout, _widgets, context, planner = cached_binding()
    first_modes = (row_major_mode("first", 1, 0),)
    changed_modes = (row_major_mode("changed", 1, 0, column_stretches=(2,)),)
    binding._plan_for_modes(context, first_modes)
    binding._plan_for_modes(context, first_modes)
    assert planner.call_count == 1

    changed = binding._plan_for_modes(context, changed_modes)
    assert planner.call_count == 2
    assert changed.mode == changed_modes[0]
