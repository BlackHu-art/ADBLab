"""提供 Devices 面板的响应式复合计划与自收缩控件层。"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QListWidget, QScrollArea, QWidget

from gui.widgets.responsive_controller import ResponsiveGridBinding
from gui.widgets.responsive_layout import (
    GridPlan,
    LayoutContext,
    WidthPolicy,
    row_major_mode,
)

if TYPE_CHECKING:
    from gui.panels.device_manager import DeviceManager


@dataclass(frozen=True)
class _DeviceCompositePlan:
    """同时约束连接行、设备主体和动作按钮网格的复合计划。"""

    mode: str
    body_mode: str
    action_plan: GridPlan
    connect_width: int
    body_minimum_height: int
    stacked_height_limit: int
    context_fingerprint: tuple[object, ...]

    @property
    def fingerprint(self) -> tuple[object, ...]:
        return (
            self.context_fingerprint,
            self.mode,
            self.body_mode,
            self.action_plan.fingerprint,
            self.connect_width,
            self.body_minimum_height,
            self.stacked_height_limit,
        )

    @property
    def settling_fingerprint(self) -> tuple[object, ...]:
        """忽略外层高度反馈，但保留全部布局决定和水平输入。"""

        context = self.context_fingerprint
        if len(context) == 5 and isinstance(context[0], int) and isinstance(context[1], int):
            context = (context[0], *context[2:])
        return (
            context,
            self.mode,
            self.body_mode,
            self.action_plan.settling_fingerprint,
            self.connect_width,
            self.body_minimum_height,
            self.stacked_height_limit,
        )


class _DeviceResponsiveBinding(ResponsiveGridBinding):
    """把动作网格纳入 Devices 三态复合计划的单一协调目标。"""

    def __init__(self, manager: DeviceManager) -> None:
        self._manager_ref = weakref.ref(manager)
        super().__init__(
            manager._device_action_frame,
            manager._device_actions_layout,
            manager._device_action_buttons,
            (WidthPolicy.NATURAL,) * len(manager._device_action_buttons),
            (
                row_major_mode("two", 2, 0, column_stretches=(1, 1)),
                row_major_mode("one", 1, 1, column_stretches=(1,)),
            ),
            manager.panel._responsive_coordinator,
            context_provider=manager._responsive_context,
            use_provided_geometry=True,
            adaptive_spacing=True,
        )

    def _manager(self) -> DeviceManager:
        manager = self._manager_ref()
        if manager is None:
            raise RuntimeError("device manager has been destroyed")
        return manager

    def action_plan(self, context: LayoutContext, *, force_one_column: bool) -> GridPlan:
        """按动作 viewport 规划按钮列，并允许复合计划锁定单列。"""

        if force_one_column:
            return ResponsiveGridBinding.conservative_responsive_plan(self, context)
        return ResponsiveGridBinding.responsive_plan(self, context)

    def responsive_plan(self, context: LayoutContext) -> _DeviceCompositePlan:
        return self._manager()._build_device_plan(self, context, conservative=False)

    def conservative_responsive_plan(self, context: LayoutContext) -> _DeviceCompositePlan:
        return self._manager()._build_device_plan(self, context, conservative=True)

    def apply_responsive_plan(self, plan: _DeviceCompositePlan) -> None:
        manager = self._manager()
        manager._apply_device_plan(plan)
        ResponsiveGridBinding.apply_responsive_plan(self, plan.action_plan)
        manager._finish_device_plan(plan)

    def synchronize_responsive_plan(self, plan: _DeviceCompositePlan) -> None:
        """只同步高度反馈后的动作计划快照，不重复搬移 Devices 控件。"""

        self._manager()
        ResponsiveGridBinding.synchronize_responsive_plan(self, plan.action_plan)


class _ShrinkableDeviceList(QListWidget):
    """只向布局声明一行的安全高度，剩余空间仍可由伸展因子分配。"""

    def sizeHint(self) -> QSize:
        return QSize(0, max(0, self.minimumHeight()))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, max(0, self.minimumHeight()))


class _ShrinkableDeviceBody(QWidget):
    """只向外层传播当前计划的一行安全高度，内部仍可按计划堆叠。"""

    def minimumSizeHint(self) -> QSize:
        return QSize(0, max(0, self.minimumHeight()))


class _ShrinkableActionScroll(QScrollArea):
    """只传播动作区安全高度，横向不足由自身滚动条承接。"""

    def sizeHint(self) -> QSize:
        return QSize(0, max(0, self.minimumHeight()))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, max(0, self.minimumHeight()))
