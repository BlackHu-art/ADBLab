from __future__ import annotations

import gc
import weakref

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMargins, QSize, QTimer
from PySide6.QtGui import QFont, QWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGridLayout, QWidget
from shiboken6 import isValid

from gui.widgets import responsive_layout
from gui.widgets.responsive_controller import (
    ReflowReason,
    ResponsiveCoordinator,
    ResponsiveGridBinding,
)
from gui.widgets.responsive_layout import (
    GridMode,
    GridPlacement,
    ItemMetric,
    LayoutContext,
    WidthPolicy,
    choose_grid_plan,
    row_major_mode,
    span_tail_mode,
)
from tests.ui_geometry_helpers import wait_until


class FakeTarget:
    def __init__(self, candidates, conservative, *, after_apply=None):
        self.candidates = list(candidates)
        self.conservative = conservative
        self.after_apply = after_apply
        self.applied = []
        self.plan_calls = 0

    def responsive_context(self):
        return LayoutContext(320, 200, False, ("Sans", 12.0), 1)

    def responsive_plan(self, context):
        del context
        index = min(self.plan_calls, len(self.candidates) - 1)
        self.plan_calls += 1
        return self.candidates[index]

    def conservative_responsive_plan(self, context):
        del context
        return self.conservative

    def apply_responsive_plan(self, plan):
        self.applied.append(plan)
        if self.after_apply is not None:
            self.after_apply(len(self.applied))


class ResizeEchoTarget:
    """记录每代真实采用的最终宽度，模拟用户连续拖动顶层窗口。"""

    def __init__(self):
        self.width = 900
        self.applied = []

    def responsive_context(self):
        return LayoutContext(self.width, 200, False, ("Sans", 12.0), 1)

    def responsive_plan(self, context):
        return context.width

    def conservative_responsive_plan(self, context):
        return context.width

    def apply_responsive_plan(self, plan):
        self.applied.append(plan)


class MetricWidget(QWidget):
    def __init__(self, minimum_width: int, preferred_width: int, *, minimum: int = 0):
        super().__init__()
        self.minimum_hint_width = minimum_width
        self.preferred_hint_width = preferred_width
        self.setMinimumWidth(minimum)

    def minimumSizeHint(self):
        return QSize(self.minimum_hint_width, 20)

    def sizeHint(self):
        return QSize(self.preferred_hint_width, 24)


class RecordingBinding(ResponsiveGridBinding):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.applied_modes = []

    def apply_responsive_plan(self, plan):
        super().apply_responsive_plan(plan)
        self.applied_modes.append(plan.mode.name)


def test_span_tail_plan_uses_full_second_row_and_real_width():
    metrics = tuple(ItemMetric(80, 100, WidthPolicy.NATURAL) for _ in range(3))
    context = LayoutContext(210, 100, False, ("Sans", 12.0), 1)

    plan = choose_grid_plan(
        metrics,
        [
            span_tail_mode("three", 3, 0),
            span_tail_mode("two", 2, 1),
            row_major_mode("one", 1, 2),
        ],
        210,
        QMargins(0, 0, 0, 0),
        6,
        context.fingerprint,
    )

    assert plan.mode.name == "two"
    assert plan.placements[-1].column_span == 2
    assert plan.required_width == 166


def test_paired_modes_keep_every_label_next_to_its_field():
    """paired_mode 必须显式保证所有 label-field 在 3/2/1 组布局中相邻。"""

    paired_mode = getattr(responsive_layout, "paired_mode", None)
    assert callable(paired_mode), "paired_mode must be a public planner constructor"
    metrics = tuple(ItemMetric(30, 30, WidthPolicy.NATURAL) for _ in range(12))
    modes = (
        paired_mode("three", 3, 0),
        paired_mode("two", 2, 1),
        paired_mode("one", 1, 2),
    )

    for width, expected_name in ((220, "three"), (150, "two"), (70, "one")):
        plan = choose_grid_plan(metrics, modes, width, QMargins(), 4, (width,))
        assert plan.mode.name == expected_name
        positions = {placement.item_index: placement for placement in plan.placements}
        for label_index in range(0, len(metrics), 2):
            label = positions[label_index]
            field = positions[label_index + 1]
            assert label.row == field.row
            assert field.column == label.column + 1


def test_shrinkable_binding_does_not_use_dynamic_preferred_width(qt_application):
    """SHRINKABLE 的布局度量不得随当前文本造成的 sizeHint 漂移。"""

    container = QWidget()
    layout = QGridLayout(container)
    widget = MetricWidget(42, 80)
    coordinator = ResponsiveCoordinator()
    binding = ResponsiveGridBinding(
        container,
        layout,
        (widget,),
        (WidthPolicy.SHRINKABLE,),
        (row_major_mode("one", 1, 0),),
        coordinator,
        context_provider=lambda _container: LayoutContext(240, 80, False, ("Sans", 12.0), 1),
    )
    container.resize(240, 80)
    first = binding.responsive_plan(binding.responsive_context())

    widget.preferred_hint_width = 900
    second = binding.responsive_plan(binding.responsive_context())

    assert first.metrics == second.metrics
    assert first.required_width == second.required_width
    container.close()


def test_plan_distributes_spanning_item_deficit_across_covered_columns():
    mode = GridMode(
        name="spanning",
        columns=2,
        conservatism_rank=0,
        placements=(
            GridPlacement(0, 0, 0),
            GridPlacement(1, 1, 0, column_span=2),
        ),
        column_stretches=(1, 1),
        row_stretches=(0, 0),
    )

    plan = choose_grid_plan(
        (
            ItemMetric(50, 50, WidthPolicy.NATURAL),
            ItemMetric(130, 130, WidthPolicy.NATURAL),
        ),
        [mode],
        130,
        QMargins(),
        6,
        ("context",),
    )

    assert plan.column_widths == (87, 37)
    assert plan.required_width == 130


@pytest.mark.parametrize(
    ("column_stretches", "minimum_width", "expected_widths"),
    [
        ((3, 1), 40, (30, 10)),
        ((3, 1), 41, (31, 10)),
        ((3, 0, 1), 41, (31, 0, 10)),
        ((0, 0), 5, (3, 2)),
    ],
)
def test_plan_distributes_span_deficit_by_positive_column_weights(
    column_stretches,
    minimum_width,
    expected_widths,
):
    mode = GridMode(
        name="weighted",
        columns=len(column_stretches),
        conservatism_rank=0,
        placements=(GridPlacement(0, 0, 0, column_span=len(column_stretches)),),
        column_stretches=column_stretches,
        row_stretches=(0,),
    )

    plan = choose_grid_plan(
        (ItemMetric(minimum_width, minimum_width, WidthPolicy.NATURAL),),
        (mode,),
        minimum_width,
        QMargins(),
        0,
        ("weighted",),
    )

    assert plan.column_widths == expected_widths


def test_plan_orders_modes_by_strict_conservatism_rank_and_fingerprints_all_inputs():
    metrics = tuple(ItemMetric(80, 100, WidthPolicy.NATURAL) for _ in range(3))
    modes = [span_tail_mode("two", 2, 0), row_major_mode("one", 1, 1)]

    first = choose_grid_plan(metrics, modes, 210, QMargins(1, 2, 3, 4), 6, ("first",))
    second = choose_grid_plan(metrics, modes, 210, QMargins(1, 2, 3, 4), 6, ("second",))

    assert first.mode.name == "two"
    assert first.fingerprint != second.fingerprint
    assert first.fingerprint == (
        ("first",),
        210,
        (1, 2, 3, 4),
        6,
        tuple(metric.fingerprint for metric in metrics),
        first.mode.fingerprint,
        tuple(placement.fingerprint for placement in first.placements),
        first.column_widths,
        first.column_stretches,
        first.row_stretches,
        first.overflow_required,
    )


def test_plan_reports_fit_and_minimum_column_overflow():
    metrics = tuple(ItemMetric(80, 100, WidthPolicy.NATURAL) for _ in range(3))
    modes = (
        row_major_mode("three", 3, 0),
        span_tail_mode("two", 2, 1),
        row_major_mode("one", 1, 2),
    )

    fitting = choose_grid_plan(metrics, modes, 166, QMargins(), 6, ("fit",))
    overflowing = choose_grid_plan(metrics, modes, 79, QMargins(), 6, ("overflow",))

    assert fitting.mode.name == "two"
    assert fitting.conservatism_rank == 1
    assert fitting.overflow_required is False
    assert fitting.fingerprint[-1] is False
    assert overflowing.mode.name == "one"
    assert overflowing.conservatism_rank == 2
    assert overflowing.required_width == 80
    assert overflowing.overflow_required is True
    assert overflowing.fingerprint[-1] is True


@pytest.mark.parametrize(
    ("modes", "message"),
    [
        ([], "modes"),
        (
            [
                GridMode(
                    "bad-stretch",
                    2,
                    0,
                    column_stretches=(1,),
                )
            ],
            "column_stretches",
        ),
        (
            [
                GridMode(
                    "out-of-bounds",
                    2,
                    0,
                    placements=(GridPlacement(0, 0, 1, column_span=2),),
                )
            ],
            "bounds",
        ),
        (
            [row_major_mode("first", 1, 0), row_major_mode("duplicate", 1, 0)],
            "conservatism_rank",
        ),
        (
            [row_major_mode("narrow", 1, 0), row_major_mode("wide", 2, 1)],
            "wide.*narrow",
        ),
        (
            [row_major_mode("wide", 2, 0), row_major_mode("narrow", 1, 2)],
            "conservatism_rank",
        ),
    ],
)
def test_plan_rejects_invalid_mode_definitions(modes, message):
    with pytest.raises(ValueError, match=message):
        choose_grid_plan(
            (ItemMetric(20, 30, WidthPolicy.NATURAL),),
            modes,
            100,
            QMargins(),
            0,
            ("context",),
        )


def test_binding_rejects_reversed_modes_before_context_provider_runs(qt_application):
    container = QWidget()
    layout = QGridLayout(container)
    widget = MetricWidget(40, 60)
    provider_calls = []

    with pytest.raises(ValueError, match="wide.*narrow"):
        ResponsiveGridBinding(
            container,
            layout,
            (widget,),
            (WidthPolicy.NATURAL,),
            (
                row_major_mode("narrow", 1, 0),
                row_major_mode("wide", 2, 1),
            ),
            ResponsiveCoordinator(),
            context_provider=lambda current: provider_calls.append(current),
        )

    assert provider_calls == []


def test_coordinator_coalesces_external_burst_and_forces_conservative_third_plan(
    qt_application,
):
    target = FakeTarget(candidates=["A", "B", "C"], conservative="D")
    coordinator = ResponsiveCoordinator()
    coordinator.register(target)

    coordinator.request_reflow(ReflowReason.RESIZE)
    coordinator.request_reflow(ReflowReason.FONT)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)

    assert target.applied == ["A", "B", "D"]
    assert coordinator.diagnostics.generation == 1
    assert coordinator.diagnostics.rounds == 3
    assert coordinator.diagnostics.fallback_reason == "round_limit"
    assert target.plan_calls == 4
    assert coordinator.diagnostics.reasons == (
        ReflowReason.RESIZE,
        ReflowReason.FONT,
    )


def test_coordinator_fallback_only_conservatizes_targets_that_are_still_changing(
    qt_application,
):
    """一个目标达到轮次上限时，不得把同批稳定目标一起降到最保守模式。"""

    unstable = FakeTarget(candidates=["A", "B", "C"], conservative="D")
    stable = FakeTarget(candidates=["S", "S", "S"], conservative="T")
    coordinator = ResponsiveCoordinator()
    coordinator.register(unstable)
    coordinator.register(stable)

    coordinator.request_reflow(ReflowReason.EXPLICIT)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)

    assert unstable.applied == ["A", "B", "D"]
    assert stable.applied == ["S", "S", "S"]
    assert "T" not in stable.applied
    assert coordinator.diagnostics.fallback_reason == "round_limit"


def test_resize_drag_coalesces_interleaved_events_and_applies_only_final_width(
    qt_application,
):
    """真实拖动会在 resize 之间处理事件，仍只能在尾沿提交一次最终布局。"""

    target = ResizeEchoTarget()
    coordinator = ResponsiveCoordinator()
    coordinator.register(target)

    for width in (880, 840, 800, 760):
        target.width = width
        coordinator.request_reflow(ReflowReason.RESIZE)
        qt_application.processEvents()
        QTest.qWait(5)

    wait_until(
        qt_application,
        lambda: coordinator.diagnostics.stable and coordinator.diagnostics.generation >= 1,
    )

    assert coordinator.diagnostics.generation == 1
    assert target.applied == [760]


def test_coordinator_fallback_locks_a_to_b_to_a_oscillation(qt_application):
    target = FakeTarget(candidates=["A", "B", "A"], conservative="D")
    coordinator = ResponsiveCoordinator()
    coordinator.register(target)

    coordinator.request_reflow(ReflowReason.EXPLICIT)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)

    assert target.applied == ["A", "B", "D"]
    assert coordinator.diagnostics.rounds == 3
    assert coordinator.diagnostics.fallback_reason == "oscillation"
    assert target.plan_calls == 4


def test_external_reasons_during_settling_create_one_followup_generation(qt_application):
    coordinator = ResponsiveCoordinator()

    def request_burst(apply_count):
        if apply_count == 1:
            coordinator.request_reflow(ReflowReason.RESIZE)
            coordinator.request_reflow(ReflowReason.FONT)

    target = FakeTarget(candidates=["A"], conservative="D", after_apply=request_burst)
    coordinator.register(target)

    coordinator.request_reflow(ReflowReason.EXPLICIT)
    wait_until(
        qt_application,
        lambda: coordinator.diagnostics.stable and coordinator.diagnostics.generation == 2,
    )

    assert target.applied == ["A", "A"]
    assert coordinator.diagnostics.generation == 2
    assert coordinator.diagnostics.reasons == (
        ReflowReason.RESIZE,
        ReflowReason.FONT,
    )


def test_internal_layout_request_during_settling_does_not_create_generation(qt_application):
    coordinator = ResponsiveCoordinator()

    def request_layout(apply_count):
        if apply_count == 1:
            coordinator.request_reflow(ReflowReason.LAYOUT_REQUEST)

    target = FakeTarget(candidates=["A"], conservative="D", after_apply=request_layout)
    coordinator.register(target)

    coordinator.request_reflow(ReflowReason.RESIZE)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)

    assert coordinator.diagnostics.generation == 1
    assert target.applied == ["A"]


def test_real_binding_queued_layout_request_does_not_start_extra_generation(qt_application):
    container = QWidget()
    container.resize(200, 100)
    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    widgets = tuple(MetricWidget(40, 60) for _index in range(3))
    provider_calls = []
    coordinator = ResponsiveCoordinator()
    binding = RecordingBinding(
        container,
        layout,
        widgets,
        (WidthPolicy.NATURAL,) * 3,
        (span_tail_mode("two", 2, 0), row_major_mode("one", 1, 1)),
        coordinator,
        context_provider=lambda current: (
            provider_calls.append(current)
            or LayoutContext(current.width(), current.height(), False, ("Sans", 12.0), 1)
        ),
    )
    container.show()
    wait_until(qt_application, container.isVisible)
    coordinator.attach_top_level(container)
    initial_generation = coordinator.diagnostics.generation

    coordinator.request_reflow(ReflowReason.EXPLICIT)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    drained = []
    QTimer.singleShot(0, lambda: drained.append(True))
    wait_until(qt_application, lambda: bool(drained) and coordinator.diagnostics.stable)

    assert coordinator.diagnostics.generation == initial_generation + 1
    assert coordinator.diagnostics.rounds == 1
    assert binding.applied_modes == ["two"]
    assert len(provider_calls) == 2


def test_real_binding_forces_third_round_fallback_and_one_readonly_verify(qt_application):
    container = QWidget()
    container.resize(200, 100)
    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    widgets = tuple(MetricWidget(40, 60) for _index in range(3))
    style_generations = []

    def changing_context(current):
        style_generation = len(style_generations) + 1
        style_generations.append(style_generation)
        return LayoutContext(
            current.width(), current.height(), False, ("Sans", 12.0), style_generation
        )

    coordinator = ResponsiveCoordinator()
    binding = RecordingBinding(
        container,
        layout,
        widgets,
        (WidthPolicy.NATURAL,) * 3,
        (span_tail_mode("two", 2, 0), row_major_mode("one", 1, 1)),
        coordinator,
        context_provider=changing_context,
    )
    container.show()
    wait_until(qt_application, container.isVisible)
    coordinator.attach_top_level(container)

    coordinator.request_reflow(ReflowReason.EXPLICIT)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    drained = []
    QTimer.singleShot(0, lambda: drained.append(True))
    wait_until(qt_application, lambda: bool(drained) and coordinator.diagnostics.stable)

    assert coordinator.diagnostics.generation == 1
    assert coordinator.diagnostics.rounds == 3
    assert coordinator.diagnostics.fallback_reason == "round_limit"
    assert binding.applied_modes == ["two", "two", "one"]
    assert style_generations == [1, 2, 3, 4]
    assert binding.applied_plan.mode.name == "one"


def test_height_only_settling_snapshot_does_not_consume_an_apply_round(qt_application):
    """行高反馈只同步只读快照，后续真实宽度变化仍可在本代正常应用。"""

    container = QWidget()
    container.resize(200, 100)
    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    widgets = tuple(MetricWidget(40, 60) for _index in range(3))
    contexts = [(200, 100), (200, 120), (220, 120), (220, 120)]
    context_calls = []

    def settling_context(_current):
        index = min(len(context_calls), len(contexts) - 1)
        width, height = contexts[index]
        context_calls.append((width, height))
        return LayoutContext(width, height, False, ("Sans", 12.0), 1)

    coordinator = ResponsiveCoordinator()
    binding = RecordingBinding(
        container,
        layout,
        widgets,
        (WidthPolicy.NATURAL,) * 3,
        (span_tail_mode("two", 2, 0), row_major_mode("one", 1, 1)),
        coordinator,
        context_provider=settling_context,
        use_provided_geometry=True,
    )

    coordinator.request_reflow(ReflowReason.RESIZE)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)

    assert coordinator.diagnostics.rounds == 2
    assert coordinator.diagnostics.fallback_reason is None
    assert binding.applied_modes == ["two", "two"]
    assert context_calls == [*contexts, (220, 120)]
    assert binding.applied_plan is not None
    assert binding.applied_plan.available_width == 220
    assert binding.applied_plan.context_fingerprint[1] == 120


@pytest.mark.parametrize("deleted_object", ["container", "widget"])
def test_real_binding_scheduled_round_does_not_access_deleted_qobject(
    qt_application,
    deleted_object,
):
    metric_accesses = []

    class AccessRecordingWidget(MetricWidget):
        def minimumSizeHint(self):
            metric_accesses.append("minimum")
            return super().minimumSizeHint()

        def sizeHint(self):
            metric_accesses.append("preferred")
            return super().sizeHint()

    container = QWidget()
    layout = QGridLayout(container)
    widget = AccessRecordingWidget(40, 60)
    coordinator = ResponsiveCoordinator()
    binding = ResponsiveGridBinding(
        container,
        layout,
        (widget,),
        (WidthPolicy.NATURAL,),
        (row_major_mode("one", 1, 0),),
        coordinator,
        context_provider=lambda current: LayoutContext(
            current.width(), current.height(), False, ("Sans", 12.0), 1
        ),
    )
    assert binding.widgets() == (widget,)

    coordinator.request_reflow(ReflowReason.EXPLICIT)
    victim = container if deleted_object == "container" else widget
    victim.deleteLater()
    QCoreApplication.sendPostedEvents(victim, QEvent.Type.DeferredDelete)
    assert not isValid(victim)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)

    assert metric_accesses == []
    assert coordinator.target_count == 0
    assert coordinator.diagnostics.rounds == 0


def test_binding_rebuilds_context_and_remeasures_every_round(qt_application):
    container = QWidget()
    container.resize(260, 120)
    font = QFont("Arial", 13)
    font.setWeight(QFont.Weight.Bold)
    font.setItalic(True)
    font.setStretch(110)
    container.setFont(font)
    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    widgets = (
        MetricWidget(80, 100),
        MetricWidget(70, 90, minimum=15),
        MetricWidget(60, 120, minimum=10),
        MetricWidget(65, 85),
    )
    policies = (
        WidthPolicy.NATURAL,
        WidthPolicy.SHRINKABLE,
        WidthPolicy.WRAPPING,
        WidthPolicy.EXPLICIT,
    )
    dynamic = {"restricted": False, "style": 3}
    provider_containers = []

    def context_provider(current_container):
        provider_containers.append(current_container)
        return LayoutContext(
            999,
            999,
            dynamic["restricted"],
            ("provider-font-is-not-authoritative",),
            dynamic["style"],
        )

    coordinator = ResponsiveCoordinator()
    binding = ResponsiveGridBinding(
        container,
        layout,
        widgets,
        policies,
        [
            row_major_mode("four", 4, 0),
            span_tail_mode("two", 2, 1),
            row_major_mode("one", 1, 2),
        ],
        coordinator,
        context_provider=context_provider,
        explicit_minimums=(0, 0, 0, 55),
    )

    first_context = binding.responsive_context()
    first_plan = binding.responsive_plan(first_context)
    assert first_context.width == container.contentsRect().width()
    assert first_context.height == container.contentsRect().height()
    assert first_context.restricted_workspace is False
    assert first_context.style_generation == 3
    assert len(first_context.font_fingerprint) >= 6
    assert first_plan.context_fingerprint == first_context.fingerprint
    assert tuple(metric.minimum_width for metric in first_plan.metrics) == (80, 15, 10, 55)
    assert tuple(metric.width_policy for metric in first_plan.metrics) == policies

    container.resize(220, 140)
    container.setFont(QFont("Courier New", 15))
    widgets[0].minimum_hint_width = 95
    dynamic.update(restricted=True, style=4)
    second_context = binding.responsive_context()
    second_plan = binding.responsive_plan(second_context)
    assert provider_containers == [container, container]
    assert second_context.fingerprint != first_context.fingerprint
    assert second_context.restricted_workspace is True
    assert second_context.style_generation == 4
    assert second_plan.metrics[0].minimum_width == 95
    assert second_plan.fingerprint != first_plan.fingerprint


def test_binding_applies_complete_plan_and_exposes_conservative_snapshot(qt_application):
    container = QWidget()
    container.resize(240, 120)
    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.setColumnStretch(4, 9)
    layout.setColumnMinimumWidth(4, 77)
    layout.setRowStretch(3, 8)
    widgets = tuple(MetricWidget(60, 80) for _index in range(3))
    coordinator = ResponsiveCoordinator()
    binding = ResponsiveGridBinding(
        container,
        layout,
        widgets,
        (WidthPolicy.NATURAL,) * 3,
        [span_tail_mode("two", 2, 0), row_major_mode("one", 1, 1)],
        coordinator,
        context_provider=lambda current: LayoutContext(
            current.width(), current.height(), False, ("ignored",), 1
        ),
    )

    context = binding.responsive_context()
    plan = binding.responsive_plan(context)
    conservative = binding.conservative_responsive_plan(context)
    binding.apply_responsive_plan(plan)

    assert binding.applied_plan == plan
    assert binding.widgets() == widgets
    assert conservative.mode.name == "one"
    assert tuple(layout.itemAt(index).widget() for index in range(layout.count())) == widgets
    assert layout.getItemPosition(2) == (1, 0, 1, 2)
    assert [layout.columnStretch(index) for index in range(5)] == [1, 1, 0, 0, 0]
    assert [layout.columnMinimumWidth(index) for index in range(5)] == [60, 60, 0, 0, 0]
    assert [layout.rowStretch(index) for index in range(4)] == [0, 0, 0, 0]
    with pytest.raises(AttributeError):
        binding.applied_plan = conservative


def test_binding_column_minimums_match_weighted_plan_geometry_and_clear_when_narrowed(
    qt_application,
):
    container = QWidget()
    container.resize(200, 100)
    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    first = MetricWidget(0, 0)
    second = MetricWidget(0, 0)
    spanning = MetricWidget(80, 80)
    binding = ResponsiveGridBinding(
        container,
        layout,
        (first, second, spanning),
        (WidthPolicy.SHRINKABLE, WidthPolicy.SHRINKABLE, WidthPolicy.NATURAL),
        (
            GridMode(
                "weighted-two",
                2,
                0,
                placements=(
                    GridPlacement(0, 0, 0),
                    GridPlacement(1, 0, 1),
                    GridPlacement(2, 1, 0, column_span=2),
                ),
                column_stretches=(3, 1),
                row_stretches=(0, 0),
            ),
            row_major_mode("one", 1, 1),
        ),
        ResponsiveCoordinator(),
        context_provider=lambda current: LayoutContext(
            current.width(), current.height(), False, ("Sans", 12.0), 1
        ),
    )

    wide_plan = binding.responsive_plan(binding.responsive_context())
    binding.apply_responsive_plan(wide_plan)
    container.show()
    wait_until(qt_application, lambda: first.width() > second.width())
    assert wide_plan.column_widths == (60, 20)
    assert [layout.columnMinimumWidth(index) for index in range(2)] == [60, 20]
    assert first.width() > second.width()

    narrow_plan = binding.conservative_responsive_plan(binding.responsive_context())
    binding.apply_responsive_plan(narrow_plan)
    assert narrow_plan.mode.name == "one"
    assert layout.columnMinimumWidth(0) == 80
    assert layout.columnMinimumWidth(1) == 0


def test_binding_unregisters_when_container_is_destroyed(qt_application):
    container = QWidget()
    layout = QGridLayout(container)
    widget = MetricWidget(40, 60)
    binding = ResponsiveGridBinding(
        container,
        layout,
        (widget,),
        (WidthPolicy.NATURAL,),
        (row_major_mode("one", 1, 0),),
        coordinator := ResponsiveCoordinator(),
        context_provider=lambda current: LayoutContext(
            current.width(), current.height(), False, ("Sans", 12.0), 1
        ),
    )
    assert coordinator.target_count == 1
    assert binding.widgets() == (widget,)

    container.show()
    container.deleteLater()
    wait_until(qt_application, lambda: coordinator.target_count == 0)

    assert binding.widgets() == ()


def test_bound_context_provider_owner_is_weak_and_not_called_after_pending_delete(
    qt_application,
):
    provider_calls = []

    class ContextOwner(QWidget):
        def provide_context(self, current):
            provider_calls.append(current)
            self.objectName()
            return LayoutContext(current.width(), current.height(), False, ("Sans", 12.0), 1)

    owner = ContextOwner()
    owner_ref = weakref.ref(owner)
    container = QWidget()
    layout = QGridLayout(container)
    widget = MetricWidget(40, 60)
    coordinator = ResponsiveCoordinator()
    binding = ResponsiveGridBinding(
        container,
        layout,
        (widget,),
        (WidthPolicy.NATURAL,),
        (row_major_mode("one", 1, 0),),
        coordinator,
        context_provider=owner.provide_context,
    )
    assert binding.widgets() == (widget,)

    coordinator.request_reflow(ReflowReason.EXPLICIT)
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(owner, QEvent.Type.DeferredDelete)
    assert not isValid(owner)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)

    assert provider_calls == []
    assert coordinator.target_count == 0
    del owner
    gc.collect()
    assert owner_ref() is None


@pytest.mark.parametrize(
    ("event_type", "reason"),
    [
        (QEvent.Type.Resize, ReflowReason.RESIZE),
        (QEvent.Type.LayoutRequest, ReflowReason.LAYOUT_REQUEST),
        (QEvent.Type.FontChange, ReflowReason.FONT),
        (QEvent.Type.ThemeChange, ReflowReason.THEME),
        (QEvent.Type.ScreenChangeInternal, ReflowReason.SCREEN),
        (QEvent.Type.DevicePixelRatioChange, ReflowReason.DPI),
    ],
)
def test_coordinator_attach_top_level_routes_responsive_events(
    qt_application,
    event_type,
    reason,
):
    window = QWidget()
    target = FakeTarget(candidates=["A"], conservative="D")
    coordinator = ResponsiveCoordinator()
    coordinator.register(target)
    coordinator.attach_top_level(window)
    expected_generation = coordinator.diagnostics.generation + 1

    QCoreApplication.sendEvent(window, QEvent(event_type))
    wait_until(
        qt_application,
        lambda: coordinator.diagnostics.stable
        and coordinator.diagnostics.generation == expected_generation,
    )

    assert coordinator.diagnostics.reasons == (reason,)
    assert coordinator.attached_top_level_count == 1
    window.show()
    window.deleteLater()
    wait_until(qt_application, lambda: coordinator.attached_top_level_count == 0)


def test_coordinator_attaches_real_window_handle_screen_signal_after_show(qt_application):
    window = QWidget()
    target = FakeTarget(candidates=["A"], conservative="D")
    coordinator = ResponsiveCoordinator()
    coordinator.register(target)
    coordinator.attach_top_level(window)

    window.show()
    wait_until(qt_application, lambda: window.windowHandle() is not None)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    generation = coordinator.diagnostics.generation
    handle = window.windowHandle()
    handle.screenChanged.emit(handle.screen())
    wait_until(
        qt_application,
        lambda: coordinator.diagnostics.stable
        and coordinator.diagnostics.generation == generation + 1,
    )

    assert coordinator.diagnostics.reasons == (ReflowReason.SCREEN,)


def test_coordinator_rebinds_screen_signal_when_window_handle_changes(qt_application):
    class SwappableHandleWidget(QWidget):
        def __init__(self, handle):
            self.current_handle = handle
            super().__init__()

        def windowHandle(self):
            return self.current_handle

    first_handle = QWindow()
    second_handle = QWindow()
    window = SwappableHandleWidget(first_handle)
    target = FakeTarget(candidates=["A"], conservative="D")
    coordinator = ResponsiveCoordinator()
    coordinator.register(target)
    coordinator.attach_top_level(window)

    first_handle.screenChanged.emit(first_handle.screen())
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    generation = coordinator.diagnostics.generation
    window.current_handle = second_handle
    QCoreApplication.sendEvent(window, QEvent(QEvent.Type.WinIdChange))

    first_handle.screenChanged.emit(first_handle.screen())
    assert coordinator.diagnostics.generation == generation
    second_handle.screenChanged.emit(second_handle.screen())
    wait_until(
        qt_application,
        lambda: coordinator.diagnostics.stable
        and coordinator.diagnostics.generation == generation + 1,
    )
    assert coordinator.diagnostics.reasons == (ReflowReason.SCREEN,)


def test_coordinator_detach_reattach_keeps_one_destroyed_cleanup(qt_application):
    class RecordingCoordinator(ResponsiveCoordinator):
        def __init__(self):
            super().__init__()
            self.detach_calls = []

        def _detach_top_level_key(self, key, *, remove_filter):
            self.detach_calls.append((key, remove_filter))
            return super()._detach_top_level_key(key, remove_filter=remove_filter)

    window = QWidget()
    window.show()
    wait_until(qt_application, lambda: window.windowHandle() is not None)
    coordinator = RecordingCoordinator()
    for _index in range(3):
        coordinator.attach_top_level(window)
        coordinator.detach_top_level(window)
    coordinator.attach_top_level(window)
    coordinator.detach_calls.clear()

    window.deleteLater()
    wait_until(qt_application, lambda: coordinator.attached_top_level_count == 0)

    assert coordinator.detach_calls == [(id(window), False)]
