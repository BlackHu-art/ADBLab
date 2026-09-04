"""提供可测试的响应式网格规划与兼容重排辅助函数。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from PySide6.QtCore import QMargins
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QSizePolicy, QWidget

Fingerprint: TypeAlias = tuple[object, ...]
RESPONSIVE_AUTO_MINIMUM_EM_PROPERTY = "responsiveAutoMinimumEm"
RESPONSIVE_MINIMUM_TEXT_PROPERTY = "responsiveMinimumText"
RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY = "responsiveSizeHintMinimum"


class WidthPolicy(Enum):
    """描述控件在网格规划中的最小宽度来源。"""

    NATURAL = "natural"
    SHRINKABLE = "shrinkable"
    WRAPPING = "wrapping"
    EXPLICIT = "explicit"


@dataclass(frozen=True)
class ItemMetric:
    """一次布局轮次中单个控件的只读宽度度量。"""

    minimum_width: int
    preferred_width: int
    width_policy: WidthPolicy

    def __post_init__(self) -> None:
        minimum = max(0, int(self.minimum_width))
        preferred = max(minimum, int(self.preferred_width))
        object.__setattr__(self, "minimum_width", minimum)
        object.__setattr__(self, "preferred_width", preferred)
        if not isinstance(self.width_policy, WidthPolicy):
            object.__setattr__(self, "width_policy", WidthPolicy(self.width_policy))

    @property
    def fingerprint(self) -> Fingerprint:
        return (self.minimum_width, self.preferred_width, self.width_policy.value)

    @property
    def policy(self) -> WidthPolicy:
        return self.width_policy


@dataclass(frozen=True)
class GridPlacement:
    """把一个度量项放入网格中的位置。"""

    item_index: int
    row: int
    column: int
    row_span: int = 1
    column_span: int = 1

    @property
    def fingerprint(self) -> Fingerprint:
        return (
            self.item_index,
            self.row,
            self.column,
            self.row_span,
            self.column_span,
        )

    @property
    def index(self) -> int:
        return self.item_index


@dataclass(frozen=True)
class GridMode:
    """候选网格模式；rank 越大越保守。"""

    name: str
    columns: int
    conservatism_rank: int
    placements: tuple[GridPlacement, ...] | None = None
    column_stretches: tuple[int, ...] = ()
    row_stretches: tuple[int, ...] = ()
    span_tail: bool = False
    paired: bool = False
    equal_column_groups: tuple[tuple[int, ...], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", int(self.columns))
        object.__setattr__(self, "conservatism_rank", int(self.conservatism_rank))
        if self.placements is not None:
            object.__setattr__(self, "placements", tuple(self.placements))
        object.__setattr__(
            self,
            "column_stretches",
            tuple(max(0, int(value)) for value in self.column_stretches),
        )
        object.__setattr__(
            self,
            "equal_column_groups",
            tuple(
                tuple(int(column) for column in group)
                for group in self.equal_column_groups
            ),
        )
        object.__setattr__(
            self,
            "row_stretches",
            tuple(max(0, int(value)) for value in self.row_stretches),
        )

    @property
    def fingerprint(self) -> Fingerprint:
        placements = (
            None
            if self.placements is None
            else tuple(placement.fingerprint for placement in self.placements)
        )
        return (
            self.name,
            self.columns,
            self.conservatism_rank,
            placements,
            self.column_stretches,
            self.equal_column_groups,
            self.row_stretches,
            self.span_tail,
            self.paired,
        )

    @property
    def column_count(self) -> int:
        return self.columns


@dataclass(frozen=True)
class GridPlan:
    """对某次上下文和控件度量作出的完整网格决定。"""

    mode: GridMode
    placements: tuple[GridPlacement, ...]
    column_widths: tuple[int, ...]
    column_stretches: tuple[int, ...]
    row_stretches: tuple[int, ...]
    required_width: int
    available_width: int
    margins: tuple[int, int, int, int]
    spacing: int
    context_fingerprint: Fingerprint
    metrics: tuple[ItemMetric, ...]
    overflow_required: bool

    @property
    def conservatism_rank(self) -> int:
        return self.mode.conservatism_rank

    @property
    def fingerprint(self) -> Fingerprint:
        return (
            self.context_fingerprint,
            self.available_width,
            self.margins,
            self.spacing,
            tuple(metric.fingerprint for metric in self.metrics),
            self.mode.fingerprint,
            tuple(placement.fingerprint for placement in self.placements),
            self.column_widths,
            self.column_stretches,
            self.row_stretches,
            self.overflow_required,
        )

    @property
    def settling_fingerprint(self) -> Fingerprint:
        """返回忽略行高反馈、但保留全部水平布局与样式输入的应用指纹。"""

        context = self.context_fingerprint
        if len(context) == 5 and isinstance(context[0], int) and isinstance(context[1], int):
            context = (context[0], *context[2:])
        return (
            context,
            self.available_width,
            self.margins,
            self.spacing,
            tuple(metric.fingerprint for metric in self.metrics),
            self.mode.fingerprint,
            tuple(placement.fingerprint for placement in self.placements),
            self.column_widths,
            self.column_stretches,
            self.row_stretches,
            self.overflow_required,
        )


@dataclass(frozen=True)
class LayoutContext:
    """一轮规划使用的本地几何、字体与外部样式代次。"""

    width: int
    height: int
    restricted_workspace: bool
    font_fingerprint: Fingerprint
    style_generation: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "width", max(0, int(self.width)))
        object.__setattr__(self, "height", max(0, int(self.height)))
        object.__setattr__(self, "restricted_workspace", bool(self.restricted_workspace))
        object.__setattr__(self, "font_fingerprint", tuple(self.font_fingerprint))
        object.__setattr__(self, "style_generation", int(self.style_generation))

    @property
    def available_width(self) -> int:
        return self.width

    @property
    def available_height(self) -> int:
        return self.height

    @property
    def fingerprint(self) -> Fingerprint:
        return (
            self.width,
            self.height,
            self.restricted_workspace,
            self.font_fingerprint,
            self.style_generation,
        )


def adaptive_layout_spacing(
    available_width: int,
    minimum_width: int,
    font_height: int,
    gap_count: int,
) -> int:
    """把每行的水平余量映射为稳定的 2/4/6 像素间距档位。"""

    gaps = max(0, int(gap_count))
    if gaps == 0:
        return 2
    slack = max(0, int(available_width) - max(0, int(minimum_width)))
    band_step = max(4, (max(0, int(font_height)) + 3) // 4)
    if slack >= gaps * band_step * 2:
        return 6
    if slack >= gaps * band_step:
        return 4
    return 2


def row_major_mode(
    name: str,
    columns: int,
    conservatism_rank: int,
    *,
    column_stretches: Iterable[int] = (),
    row_stretches: Iterable[int] = (),
) -> GridMode:
    """创建按行顺序放置控件的候选模式。"""

    return GridMode(
        name=name,
        columns=columns,
        conservatism_rank=conservatism_rank,
        column_stretches=tuple(column_stretches),
        row_stretches=tuple(row_stretches),
    )


def span_tail_mode(
    name: str,
    columns: int,
    conservatism_rank: int,
    *,
    column_stretches: Iterable[int] = (),
    row_stretches: Iterable[int] = (),
) -> GridMode:
    """创建让最后一个不足整行的行占满全部列的候选模式。"""

    return GridMode(
        name=name,
        columns=columns,
        conservatism_rank=conservatism_rank,
        column_stretches=tuple(column_stretches),
        row_stretches=tuple(row_stretches),
        span_tail=True,
    )


def paired_mode(
    name: str,
    group_columns: int,
    conservatism_rank: int,
    *,
    label_stretch: int = 0,
    field_stretch: int = 1,
    row_stretches: Iterable[int] = (),
) -> GridMode:
    """创建标签与字段相邻的候选模式，每行容纳指定数量的语义组。"""

    group_columns = int(group_columns)
    if group_columns < 1:
        raise ValueError("group_columns must be positive")
    column_stretches = tuple(
        stretch
        for _group in range(group_columns)
        for stretch in (max(0, int(label_stretch)), max(0, int(field_stretch)))
    )
    return GridMode(
        name=name,
        columns=group_columns * 2,
        conservatism_rank=conservatism_rank,
        column_stretches=column_stretches,
        row_stretches=tuple(row_stretches),
        paired=True,
    )


def _generated_placements(item_count: int, mode: GridMode) -> tuple[GridPlacement, ...]:
    if not mode.span_tail or item_count == 0 or item_count % mode.columns == 0:
        return tuple(
            GridPlacement(index, *divmod(index, mode.columns)) for index in range(item_count)
        )

    tail_count = item_count % mode.columns
    full_count = item_count - tail_count
    placements = [GridPlacement(index, *divmod(index, mode.columns)) for index in range(full_count)]
    tail_row = full_count // mode.columns
    base_span, extra = divmod(mode.columns, tail_count)
    column = 0
    for tail_index in range(tail_count):
        span = base_span + (1 if tail_index < extra else 0)
        placements.append(
            GridPlacement(full_count + tail_index, tail_row, column, column_span=span)
        )
        column += span
    return tuple(placements)


def _validated_mode(
    mode: GridMode,
    item_count: int,
) -> tuple[
    tuple[GridPlacement, ...],
    tuple[int, ...],
    tuple[tuple[int, ...], ...],
    tuple[int, ...],
]:
    if mode.columns < 1:
        raise ValueError("mode columns must be positive")
    if mode.column_stretches and len(mode.column_stretches) != mode.columns:
        raise ValueError("column_stretches must match mode columns")
    column_stretches = mode.column_stretches or (1,) * mode.columns
    linked_columns: set[int] = set()
    for group in mode.equal_column_groups:
        if len(group) < 2 or any(column < 0 or column >= mode.columns for column in group):
            raise ValueError("equal_column_groups must contain valid column groups")
        if len(set(group)) != len(group) or linked_columns.intersection(group):
            raise ValueError("equal_column_groups must not repeat columns")
        if len({column_stretches[column] for column in group}) != 1:
            raise ValueError("equal_column_groups must use matching column_stretches")
        linked_columns.update(group)
    if mode.paired and (mode.columns % 2 or item_count % 2):
        raise ValueError("paired modes require complete label-field pairs")

    placements = (
        _generated_placements(item_count, mode) if mode.placements is None else mode.placements
    )
    if len(placements) != item_count:
        raise ValueError("placements must contain every item exactly once")

    seen_items: set[int] = set()
    occupied_cells: set[tuple[int, int]] = set()
    row_count = 0
    for placement in placements:
        if (
            placement.item_index < 0
            or placement.item_index >= item_count
            or placement.row < 0
            or placement.column < 0
            or placement.row_span < 1
            or placement.column_span < 1
            or placement.column + placement.column_span > mode.columns
        ):
            raise ValueError("placement is outside mode bounds")
        if placement.item_index in seen_items:
            raise ValueError("placements must contain every item exactly once")
        seen_items.add(placement.item_index)
        for row in range(placement.row, placement.row + placement.row_span):
            for column in range(placement.column, placement.column + placement.column_span):
                cell = (row, column)
                if cell in occupied_cells:
                    raise ValueError("placements must not overlap")
                occupied_cells.add(cell)
        row_count = max(row_count, placement.row + placement.row_span)

    if seen_items != set(range(item_count)):
        raise ValueError("placements must contain every item exactly once")
    if mode.paired:
        positions = {placement.item_index: placement for placement in placements}
        for label_index in range(0, item_count, 2):
            label = positions[label_index]
            field = positions[label_index + 1]
            if (
                label.row != field.row
                or label.row_span != field.row_span
                or label.column_span != 1
                or field.column_span != 1
                or field.column != label.column + 1
            ):
                raise ValueError("paired modes must keep each label next to its field")
    if mode.row_stretches and len(mode.row_stretches) != row_count:
        raise ValueError("row_stretches must match mode rows")
    row_stretches = mode.row_stretches or (0,) * row_count
    return placements, column_stretches, mode.equal_column_groups, row_stretches


def _required_column_widths(
    metrics: tuple[ItemMetric, ...],
    placements: tuple[GridPlacement, ...],
    columns: int,
    spacing: int,
    column_stretches: tuple[int, ...],
    equal_column_groups: tuple[tuple[int, ...], ...],
) -> tuple[int, ...]:
    widths = [0] * columns
    for placement in placements:
        if placement.column_span == 1:
            widths[placement.column] = max(
                widths[placement.column],
                metrics[placement.item_index].minimum_width,
            )

    for placement in placements:
        if placement.column_span == 1:
            continue
        covered_columns = range(placement.column, placement.column + placement.column_span)
        current_width = sum(widths[column] for column in covered_columns)
        current_width += spacing * (placement.column_span - 1)
        deficit = max(0, metrics[placement.item_index].minimum_width - current_width)
        if not deficit:
            continue
        covered_columns = tuple(covered_columns)
        weights = tuple(column_stretches[column] for column in covered_columns)
        if not any(weights):
            weights = (1,) * placement.column_span
        total_weight = sum(weights)
        allocations = [deficit * weight // total_weight for weight in weights]
        remainder = deficit - sum(allocations)
        remainder_order = sorted(
            range(placement.column_span),
            key=lambda offset: (-(deficit * weights[offset] % total_weight), offset),
        )
        for offset in remainder_order[:remainder]:
            allocations[offset] += 1
        for offset, column in enumerate(covered_columns):
            widths[column] += allocations[offset]
    for group in equal_column_groups:
        shared_width = max(widths[column] for column in group)
        for column in group:
            widths[column] = shared_width
    return tuple(widths)


def validate_grid_modes(modes: Iterable[GridMode]) -> tuple[GridMode, ...]:
    """验证候选严格按宽到窄排列，且 rank 从零逐级递增。"""

    mode_items = tuple(modes)
    if not mode_items:
        raise ValueError("modes must not be empty")
    for expected_rank, mode in enumerate(mode_items):
        if mode.conservatism_rank != expected_rank:
            raise ValueError("conservatism_rank must start at 0 and increase by 1")
    if any(
        wider.columns <= narrower.columns for wider, narrower in zip(mode_items, mode_items[1:])
    ):
        raise ValueError("modes must be ordered from wide to narrow")
    return mode_items


def choose_grid_plan(
    metrics: Iterable[ItemMetric],
    modes: Iterable[GridMode],
    available_width: int,
    margins: QMargins,
    spacing: int,
    context_fingerprint: Iterable[object],
) -> GridPlan:
    """选择能够放入真实可用宽度的最不保守网格模式。"""

    metric_items = tuple(metrics)
    mode_items = validate_grid_modes(modes)

    spacing = int(spacing)
    if spacing < 0:
        raise ValueError("spacing must not be negative")
    width = max(0, int(available_width))
    margin_values = (margins.left(), margins.top(), margins.right(), margins.bottom())
    context_values = tuple(context_fingerprint)
    plans: list[GridPlan] = []
    for mode in mode_items:
        placements, column_stretches, equal_column_groups, row_stretches = _validated_mode(
            mode,
            len(metric_items),
        )
        column_widths = _required_column_widths(
            metric_items,
            placements,
            mode.columns,
            spacing,
            column_stretches,
            equal_column_groups,
        )
        required_width = (
            margin_values[0]
            + margin_values[2]
            + sum(column_widths)
            + spacing * max(0, mode.columns - 1)
        )
        plans.append(
            GridPlan(
                mode=mode,
                placements=placements,
                column_widths=column_widths,
                column_stretches=column_stretches,
                row_stretches=row_stretches,
                required_width=required_width,
                available_width=width,
                margins=margin_values,
                spacing=spacing,
                context_fingerprint=context_values,
                metrics=metric_items,
                overflow_required=required_width > width,
            )
        )
    return next((plan for plan in plans if plan.required_width <= width), plans[-1])


def prepare_responsive_content(root: QWidget) -> None:
    """让滚动页中的按钮可收缩，并允许长说明在窄宽度换行。"""

    for button in root.findChildren(QPushButton):
        button.setMinimumWidth(0)
        policy = button.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        button.setSizePolicy(policy)
    for label in root.findChildren(QLabel):
        if len(label.text().strip()) < 24:
            continue
        if int(label.property(RESPONSIVE_AUTO_MINIMUM_EM_PROPERTY) or 0) > 0:
            continue
        label.setMinimumWidth(0)
        label.setWordWrap(True)


def reflow_widgets(
    layout: QGridLayout,
    widgets: Iterable[QWidget],
    columns: int,
    *,
    column_stretch: int = 1,
    widget_stretches: Iterable[int] | None = None,
) -> None:
    """在不重建控件和信号连接的前提下重新排列网格控件。"""

    items = tuple(widgets)
    stretches = (
        tuple(max(0, int(value)) for value in widget_stretches)
        if widget_stretches is not None
        else tuple(max(0, int(column_stretch)) for _item in items)
    )
    if len(stretches) != len(items):
        raise ValueError("widget_stretches must match widgets")
    columns = max(1, int(columns))
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
    for index, widget in enumerate(items):
        row, column = divmod(index, columns)
        layout.addWidget(widget, row, column)
    for column in range(max(previous_columns, columns)):
        if column >= columns:
            stretch = 0
        else:
            stretch = max(
                (stretches[index] for index in range(column, len(items), columns)),
                default=0,
            )
        layout.setColumnStretch(column, stretch)
    rows = (len(items) + columns - 1) // columns
    for row in range(max(previous_rows, rows)):
        layout.setRowStretch(row, 0)
    layout.setProperty("responsiveColumnCount", columns)
    layout.setProperty("responsiveRowCount", rows)
