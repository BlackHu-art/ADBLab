"""提供设备连接、发现、选择和基础操作面板。"""

from __future__ import annotations

import weakref
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QStyle,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base_panel import BasePanel
from gui.panels.side_panel_signals import BlockSignals
from gui.styles import BaseStyles, FontRole
from gui.widgets.responsive_controller import ReflowReason, ResponsiveGridBinding
from gui.widgets.responsive_layout import (
    GridPlan,
    LayoutContext,
    WidthPolicy,
    row_major_mode,
)
from models.device_store import DeviceStore
from utils.adb_targets import normalize_adb_connect_target


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
            manager.device_widget,
            manager._device_actions_layout,
            manager._device_action_buttons,
            (WidthPolicy.NATURAL,) * len(manager._device_action_buttons),
            (
                row_major_mode("two", 2, 0, column_stretches=(1, 1)),
                row_major_mode("one", 1, 1, column_stretches=(1,)),
            ),
            manager.panel._responsive_coordinator,
            context_provider=manager._responsive_context,
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


class DeviceManager(BasePanel):
    """维护设备列表展示，并向统一信号层转发设备操作。"""

    def build_ui(self) -> QWidget:
        w = QWidget()
        self.device_widget = w
        w.setObjectName("deviceManager")
        w.setAttribute(Qt.WA_StyledBackground, True)
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)

        g_dev = self._g("Devices")
        self._device_group = g_dev
        g_dev.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        g_dev.setAccessibleName("Devices")
        gd_l = QVBoxLayout(g_dev)
        # 与分组标题保留固定净空；连接区形态保持固定，极限尺寸由局部滚动承接。
        gd_l.setContentsMargins(4, 9, 4, 4)
        # 连接区和设备主体是两个视觉分区；宽布局下 Connect 正好位于 Refresh
        # 上方，保留明确净空以免两个按钮边框黏连。
        gd_l.setSpacing(6)

        rc = QGridLayout()
        rc.setHorizontalSpacing(2)
        rc.setVerticalSpacing(0)
        rc.setContentsMargins(0, 0, 0, 0)
        self._connect_layout = rc
        self.ip_entry = self._combo_editable(font_role=FontRole.MONO)
        self.ip_entry.setAccessibleName("Device address")
        self.ip_entry.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.ip_entry.setMinimumWidth(0)
        self.ip_entry.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.ip_entry.installEventFilter(self)
        self._build_combo_view()
        self._refresh_device_combobox()
        self.ip_entry.currentIndexChanged.connect(self._on_ip_selected)
        self.ip_entry.editTextChanged.connect(self._on_ip_edited)
        self.btn_connect_devices = self._b(
            "Connect", "plug.svg", tooltip="Connect to the entered device addresses"
        )
        rc.addWidget(self.ip_entry, 0, 0)
        rc.addWidget(self.btn_connect_devices, 0, 1)
        rc.setColumnStretch(0, 3)
        rc.setColumnStretch(1, 1)
        gd_l.addLayout(rc)

        self.set_discovery_state("scanning")

        body_host = _ShrinkableDeviceBody()
        body_host.setObjectName("deviceBody")
        body_host.setMinimumWidth(0)
        body_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._device_body_host = body_host
        body = QGridLayout(body_host)
        body.setHorizontalSpacing(2)
        body.setVerticalSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)
        self._device_body_layout = body

        self.listbox_devices = _ShrinkableDeviceList()
        self.listbox_devices.setObjectName("deviceList")
        self.listbox_devices.setAccessibleName("Connected devices")
        self.listbox_devices.setAccessibleDescription(
            "Use the checkboxes to select one or more devices for an operation"
        )
        self.listbox_devices.setEditTriggers(QListWidget.NoEditTriggers)
        self.listbox_devices.setSelectionBehavior(QListWidget.SelectRows)
        # 设备操作以复选状态为唯一真源，关闭独立行选择以避免高亮与勾选含义冲突。
        self.listbox_devices.setSelectionMode(QListWidget.NoSelection)
        self.listbox_devices.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.listbox_devices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.listbox_devices.setMinimumWidth(0)
        self._apply_device_list_style()

        side = QFrame()
        sl = QGridLayout(side)
        # medium 状态下 Connect 与两列动作共用水平列宽，间距也必须一致。
        sl.setHorizontalSpacing(rc.horizontalSpacing())
        sl.setVerticalSpacing(2)
        sl.setContentsMargins(0, 0, 0, 0)
        self._device_actions_layout = sl
        self.btn_refresh = self._b(
            "Refresh", "arrows-clockwise.svg", tooltip="Scan for connected devices"
        )
        self.btn_info = self._b(
            "Device Info",
            "info.svg",
            tooltip="Show selected device details in the operation log",
        )
        self.btn_disconnect = self._b(
            "Disconnect", "link-break.svg", tooltip="Disconnect the selected devices"
        )
        self.btn_restart_dev = self._b(
            "Restart", "arrow-counter-clockwise.svg", tooltip="Restart the selected devices"
        )
        self.btn_restart_adb = self._b(
            "ADB Server", "arrow-u-up-left.svg", tooltip="Restart the local ADB server"
        )
        self.btn_restart_adb.setAccessibleDescription(
            "Restarts the local ADB server after confirmation"
        )
        self.btn_batch = self._b(
            "Batch Install", "stack-plus.svg", tooltip="Install APK files on selected devices"
        )
        self.btn_all = self._b(
            "Select All", "check-square.svg", tooltip="Select every listed device"
        )
        self.btn_none = self._b("Deselect All", "square.svg", tooltip="Clear the device selection")
        self._device_action_buttons = (
            self.btn_refresh,
            self.btn_info,
            self.btn_disconnect,
            self.btn_restart_dev,
            self.btn_restart_adb,
            self.btn_batch,
            self.btn_all,
            self.btn_none,
        )
        # 在协调器首轮执行前就建立稳定 QObject 归属，字体/主题刷新不会遗漏动作按钮。
        for row, button in enumerate(self._device_action_buttons):
            sl.addWidget(button, row, 0)
        self._device_action_frame = side
        side.setMinimumWidth(0)
        side.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        for button in self._device_action_buttons:
            button.setMinimumWidth(0)
        body.addWidget(self.listbox_devices, 0, 0)
        body.addWidget(side, 0, 1)
        body.setColumnStretch(0, 3)
        body.setColumnStretch(1, 1)
        self._device_layout_mode = None
        self._device_body_mode = None
        self._device_responsive_binding = _DeviceResponsiveBinding(self)
        self.action_binding = self._device_responsive_binding
        self._sync_device_control_heights()
        self._update_device_minimum_heights()
        self._update_action_states()
        gd_l.addWidget(body_host)
        lo.addWidget(g_dev)
        self.panel.request_responsive_reflow(ReflowReason.EXPLICIT)
        return w

    def apply_responsive_width(self, width: int) -> None:
        """兼容旧入口；实际宽度始终由 Devices 视觉根在规划轮次中读取。"""

        del width
        self.panel.request_responsive_reflow(ReflowReason.RESIZE)

    def _responsive_context(self, container: QWidget) -> LayoutContext:
        """提供 SidePanel 状态；binding 会用视觉根真实几何和字体覆盖本地字段。"""

        font = container.font()
        return LayoutContext(
            container.contentsRect().width(),
            container.contentsRect().height(),
            self.panel._restricted_width_mode,
            (font.family(), font.pointSizeF()),
            self.panel._responsive_style_generation,
        )

    def _action_viewport_width(
        self,
        context: LayoutContext,
        mode: str,
        body_mode: str,
    ) -> int:
        """优先读取真实动作 frame，首次换态时使用单调的保守估算。"""

        action_rect = self._device_action_frame.contentsRect()
        if (
            self._device_layout_mode == mode
            and self._device_body_mode == body_mode
            and action_rect.width() > 0
        ):
            return action_rect.width()
        spacing = max(0, self._device_body_layout.horizontalSpacing())
        body_width = max(1, context.width - self._device_horizontal_insets())
        if body_mode == "side_by_side":
            # QGridLayout 的 3:1 分配会把该舍入像素交给右侧动作列。
            action_width = max(1, (body_width - spacing + 1) // 4)
        else:
            action_width = body_width
        return max(1, action_width)

    def _device_horizontal_insets(self) -> int:
        """返回 Devices 根到动作 viewport 之间不参与内容分配的横向占位。"""

        root_layout_margins = self.device_widget.layout().contentsMargins()
        group_contents_margins = self._device_group.contentsMargins()
        group_layout_margins = self._device_group.layout().contentsMargins()
        body_layout_margins = self._device_body_layout.contentsMargins()
        return sum(
            (
                root_layout_margins.left(),
                root_layout_margins.right(),
                group_contents_margins.left(),
                group_contents_margins.right(),
                group_layout_margins.left(),
                group_layout_margins.right(),
                body_layout_margins.left(),
                body_layout_margins.right(),
            )
        )

    def _build_device_plan(
        self,
        binding: _DeviceResponsiveBinding,
        context: LayoutContext,
        *,
        conservative: bool,
    ) -> _DeviceCompositePlan:
        """从视觉根和动作 viewport 的真实度量生成单一 Devices 计划。"""

        small_limit, wide_limit = self._device_layout_limits()
        if context.width < small_limit:
            mode = "compact"
        elif context.width < wide_limit:
            mode = "medium"
        else:
            mode = "wide"

        def action_plan_for(body_mode: str, *, force_one_column: bool) -> tuple[int, GridPlan]:
            viewport_width = self._action_viewport_width(context, mode, body_mode)
            action_context = LayoutContext(
                viewport_width,
                # 动作网格只按宽度选列；真实高度由外层复合计划统一参与指纹。
                0,
                context.restricted_workspace,
                context.font_fingerprint,
                context.style_generation,
            )
            return viewport_width, binding.action_plan(
                action_context,
                force_one_column=force_one_column,
            )

        stacked_viewport_width, stacked_action_plan = action_plan_for(
            "stacked",
            force_one_column=mode == "wide",
        )
        stacked_height_limit = self._device_stacked_height_limit(mode, stacked_action_plan)
        # 高度不参与列/宿主决策：compact/medium 使用更省高的全宽网格，wide 才并排。
        body_mode = "side_by_side" if mode == "wide" else "stacked"
        if body_mode == "stacked":
            viewport_width = stacked_viewport_width
            action_plan = stacked_action_plan
        else:
            viewport_width, action_plan = action_plan_for(
                "side_by_side",
                force_one_column=True,
            )
        connect_viewport_width, connect_action_plan = (
            (stacked_viewport_width, stacked_action_plan)
            if mode == "medium"
            else (viewport_width, action_plan)
        )
        margins = connect_action_plan.margins
        usable_width = max(
            1,
            connect_viewport_width
            - margins[0]
            - margins[2]
            - connect_action_plan.spacing * max(0, connect_action_plan.mode.columns - 1),
        )
        connect_width = max(1, usable_width // connect_action_plan.mode.columns)
        body_minimum_height = self._device_body_minimum_height(action_plan, body_mode)
        return _DeviceCompositePlan(
            mode,
            body_mode,
            action_plan,
            connect_width,
            body_minimum_height,
            stacked_height_limit,
            context.fingerprint,
        )

    def _apply_device_plan(self, plan: _DeviceCompositePlan) -> None:
        """按复合计划同步移动连接、列表、滚动区和既有动作按钮。"""

        structure_fingerprint = (plan.mode, plan.body_mode)
        if getattr(self, "_device_structure_fingerprint", None) == structure_fingerprint:
            return

        connect_layout = self._connect_layout
        connect_layout.removeWidget(self.ip_entry)
        connect_layout.removeWidget(self.btn_connect_devices)
        for column in range(max(3, connect_layout.columnCount())):
            connect_layout.setColumnStretch(column, 0)
            connect_layout.setColumnMinimumWidth(column, 0)
        for row in range(max(3, connect_layout.rowCount())):
            connect_layout.setRowStretch(row, 0)
        self.btn_connect_devices.setMinimumWidth(0)
        self.btn_connect_devices.setMaximumWidth(16_777_215)
        if plan.mode == "compact":
            connect_layout.addWidget(self.ip_entry, 0, 0, 1, 2)
            connect_layout.addWidget(self.btn_connect_devices, 1, 0, 1, 2)
            connect_layout.setColumnStretch(0, 1)
            connect_layout.setColumnStretch(1, 1)
        elif plan.mode == "medium":
            # 中等宽度保留地址整行，Connect 与下方两列动作的右侧单元格对齐。
            connect_layout.addWidget(self.ip_entry, 0, 0, 1, 2)
            connect_layout.addWidget(
                self.btn_connect_devices,
                1,
                1,
                alignment=Qt.AlignmentFlag.AlignRight,
            )
            connect_layout.setColumnStretch(0, 1)
            connect_layout.setColumnStretch(1, 1)
        else:
            connect_layout.addWidget(self.ip_entry, 0, 0)
            connect_layout.addWidget(
                self.btn_connect_devices,
                0,
                1,
                alignment=Qt.AlignmentFlag.AlignRight,
            )
            connect_layout.setColumnStretch(0, 3)
            # 连接区与主体共享 3:1 列语义，避免两个网格分别计算导致列宽漂移。
            connect_layout.setColumnStretch(1, 1)

        body = self._device_body_layout
        body.removeWidget(self.listbox_devices)
        body.removeWidget(self._device_action_frame)
        for column in range(max(3, body.columnCount())):
            body.setColumnStretch(column, 0)
            body.setColumnMinimumWidth(column, 0)
        for row in range(max(3, body.rowCount())):
            body.setRowStretch(row, 0)
            body.setRowMinimumHeight(row, 0)

        if plan.body_mode == "stacked":
            body.addWidget(self.listbox_devices, 0, 0, 1, 2)
            body.addWidget(self._device_action_frame, 1, 0, 1, 2)
            body.setColumnStretch(0, 1)
            body.setColumnStretch(1, 1)
            body.setRowStretch(0, 1)
            body.setRowStretch(1, 0)
        else:
            body.addWidget(self.listbox_devices, 0, 0)
            body.addWidget(self._device_action_frame, 0, 1)
            body.setColumnStretch(0, 3)
            body.setColumnStretch(1, 1)
            body.setRowStretch(0, 1)
        self._device_structure_fingerprint = structure_fingerprint

    def _finish_device_plan(self, plan: _DeviceCompositePlan) -> None:
        """在动作网格应用后同步等宽约束、最小高度和弹窗宽度。"""

        self._device_layout_mode = plan.mode
        self._device_body_mode = plan.body_mode
        self._device_action_overflow_required = plan.action_plan.overflow_required
        self._device_actions_layout.setProperty(
            "deviceActionColumnCount",
            plan.action_plan.mode.columns,
        )
        # 空的末尾伸展行吸收宽布局多出的列表高度，避免 Qt 把余量均摊到
        # 固定高度按钮之间；真实按钮行仍严格使用计划中的 2/4/6px 间距。
        action_row_count = max(
            (placement.row + placement.row_span for placement in plan.action_plan.placements),
            default=0,
        )
        for row in range(max(self._device_actions_layout.rowCount(), action_row_count + 1)):
            self._device_actions_layout.setRowStretch(row, 0)
        self._device_actions_layout.setRowStretch(action_row_count, 1)
        if plan.mode in {"wide", "medium"}:
            self.btn_connect_devices.setMinimumWidth(plan.connect_width)
            self.btn_connect_devices.setMaximumWidth(plan.connect_width)

        spacing = plan.action_plan.spacing
        for layout in (self._connect_layout, self._device_body_layout):
            if layout.horizontalSpacing() != spacing:
                layout.setHorizontalSpacing(spacing)
            if layout.verticalSpacing() != spacing:
                layout.setVerticalSpacing(spacing)

        self._sync_device_control_heights()
        self._update_device_minimum_heights(plan.body_minimum_height)
        self._sync_address_popup_width()

    def device_list_minimum_height(self) -> int:
        """返回当前内容下可完整显示一行设备所需的列表高度。"""

        row_heights = tuple(
            self.listbox_devices.sizeHintForRow(row) for row in range(self.listbox_devices.count())
        )
        valid_row_heights = tuple(height for height in row_heights if height > 0)
        row_height = (
            max(valid_row_heights) if valid_row_heights else self._empty_device_row_height()
        )
        viewport_margins = self.listbox_devices.viewportMargins()
        height = (
            row_height
            + self.listbox_devices.frameWidth() * 2
            + viewport_margins.top()
            + viewport_margins.bottom()
        )
        if self._device_list_reserves_horizontal_scrollbar():
            height += self.listbox_devices.horizontalScrollBar().sizeHint().height()
        return height

    def _empty_device_row_height(self) -> int:
        """通过当前字体和样式估算带复选框设备项的一行完整高度。"""

        option = QStyleOptionViewItem()
        self.listbox_devices.initViewItemOption(option)
        option.features |= (
            QStyleOptionViewItem.ViewItemFeature.HasDisplay
            | QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        )
        option.checkState = Qt.CheckState.Unchecked
        indicator_height = self.listbox_devices.style().pixelMetric(
            QStyle.PixelMetric.PM_IndicatorHeight,
            option,
            self.listbox_devices,
        )
        content_height = max(
            self.listbox_devices.fontMetrics().height(),
            indicator_height,
        )
        styled_height = (
            self.listbox_devices.style()
            .sizeFromContents(
                QStyle.ContentsType.CT_ItemViewItem,
                option,
                QSize(0, content_height),
                self.listbox_devices,
            )
            .height()
        )
        return max(content_height, styled_height)

    def _device_list_reserves_horizontal_scrollbar(self) -> bool:
        """除明确禁用外，预留横向滚动条高度，避免内容出现时顶开 splitter。"""

        return self.listbox_devices.horizontalScrollBarPolicy() != Qt.ScrollBarAlwaysOff

    def _update_device_minimum_heights(
        self,
        body_minimum_height: int | None = None,
    ) -> None:
        """向祖先传播一行列表和全部动作行的真实安全高度。"""

        list_height = self.device_list_minimum_height()
        self.listbox_devices.setMinimumHeight(list_height)
        action_plan = getattr(
            getattr(self, "_device_responsive_binding", None),
            "applied_plan",
            None,
        )
        action_height = self._device_action_minimum_height(action_plan)
        self._device_action_frame.setMinimumHeight(action_height)
        if body_minimum_height is None:
            body_minimum_height = self._device_body_minimum_height(
                action_plan,
                self._device_body_mode or "side_by_side",
            )
        self._device_body_host.setMinimumHeight(body_minimum_height)
        if self._device_body_mode == "stacked":
            self._device_body_layout.setRowMinimumHeight(0, list_height)
            self._device_body_layout.setRowMinimumHeight(1, action_height)
        else:
            self._device_body_layout.setRowMinimumHeight(
                0,
                body_minimum_height,
            )
        self._device_body_host.updateGeometry()
        self._device_group.updateGeometry()
        self.device_widget.updateGeometry()

    def _device_action_minimum_height(self, action_plan: GridPlan | None) -> int:
        """返回完整显示动作网格全部行所需的真实高度。"""

        action_margins = self._device_actions_layout.contentsMargins()
        row_heights: dict[int, int] = {}
        if action_plan is not None:
            placements = tuple(
                (placement.item_index, placement.row) for placement in action_plan.placements
            )
        else:
            placements = []
            for index, button in enumerate(self._device_action_buttons):
                layout_index = self._device_actions_layout.indexOf(button)
                if layout_index < 0:
                    continue
                row, _column, _row_span, _column_span = self._device_actions_layout.getItemPosition(
                    layout_index
                )
                placements.append((index, row))
        for button_index, row in placements:
            button = self._device_action_buttons[button_index]
            height = max(
                button.minimumHeight(),
                button.sizeHint().height(),
                button.minimumSizeHint().height(),
            )
            row_heights[row] = max(row_heights.get(row, 0), height)
        spacing = max(0, self._device_actions_layout.verticalSpacing())
        return (
            sum(row_heights.values())
            + spacing * max(0, len(row_heights) - 1)
            + action_margins.top()
            + action_margins.bottom()
        )

    def _device_body_minimum_height(
        self,
        action_plan: GridPlan | None,
        body_mode: str,
    ) -> int:
        """返回当前主体形态完整显示列表和动作区所需高度。"""

        margins = self._device_body_layout.contentsMargins()
        list_height = self.device_list_minimum_height()
        action_height = self._device_action_minimum_height(action_plan)
        if body_mode == "stacked":
            content_height = (
                list_height + max(0, self._device_body_layout.verticalSpacing()) + action_height
            )
        else:
            content_height = max(list_height, action_height)
        return content_height + margins.top() + margins.bottom()

    def _device_stacked_height_limit(self, mode: str, action_plan: GridPlan) -> int:
        """按当前样式度量计算主体能够安全堆叠的精确高度边界。"""

        root_margins = self.device_widget.layout().contentsMargins()
        group_contents = self._device_group.contentsMargins()
        group_layout = self._device_group.layout()
        group_margins = group_layout.contentsMargins()
        connect_margins = self._connect_layout.contentsMargins()
        body_margins = self._device_body_layout.contentsMargins()
        connect_rows = 1 if mode == "wide" else 2
        control_height = max(
            self.ip_entry.minimumHeight(),
            self.btn_connect_devices.minimumHeight(),
        )
        connect_spacing = max(0, self._connect_layout.verticalSpacing())
        connect_height = (
            connect_margins.top()
            + connect_margins.bottom()
            + connect_rows * control_height
            + max(0, connect_rows - 1) * connect_spacing
        )
        return sum(
            (
                root_margins.top(),
                root_margins.bottom(),
                group_contents.top(),
                group_contents.bottom(),
                group_margins.top(),
                group_margins.bottom(),
                connect_height,
                max(0, group_layout.spacing()),
                body_margins.top(),
                body_margins.bottom(),
                self.device_list_minimum_height(),
                max(0, self._device_body_layout.verticalSpacing()),
                self._device_action_minimum_height(action_plan),
            )
        )

    def _sync_device_control_heights(self) -> None:
        """按当前字体统一连接区和设备动作控件的最小高度。"""

        controls = (
            self.ip_entry,
            self.btn_connect_devices,
            *self._device_action_buttons,
        )
        base_minimums = getattr(self, "_device_control_base_minimums", None)
        if base_minimums is None:
            base_minimums = tuple(control.minimumHeight() for control in controls)
            self._device_control_base_minimums = base_minimums
        target_height = max(
            max(
                control.sizeHint().height(),
                control.minimumSizeHint().height(),
                base_minimum,
            )
            for control, base_minimum in zip(controls, base_minimums)
        )
        for control in controls:
            control.setMinimumHeight(target_height)

    def _device_layout_limits(self) -> tuple[int, int]:
        """按 Qt 控件最小宽度和实际容器 inset 计算三态切换断点。"""

        action_widths = tuple(
            max(button.minimumWidth(), button.minimumSizeHint().width())
            for button in self._device_action_buttons
        )
        action_margins = self._device_actions_layout.contentsMargins()
        # 与 Task 2 一致，先用最紧凑档选择可容纳模式，避免上一计划的 spacing
        # 反向改变 compact/wide 断点并产生方向性迟滞。
        action_spacing = 2
        action_cell_width = max(action_widths, default=1)
        one_column_width = action_cell_width + action_margins.left() + action_margins.right()
        two_column_width = (
            action_cell_width * 2 + action_spacing + action_margins.left() + action_margins.right()
        )

        horizontal_insets = self._device_horizontal_insets()

        compact_limit = horizontal_insets + two_column_width
        body_spacing = 2
        # wide 主体采用 3:1 stretch；Qt 将除不尽的一个像素优先分给右列。
        wide_limit = horizontal_insets + body_spacing + one_column_width * 4 - 1
        return compact_limit, wide_limit

    def _sync_address_popup_width(self) -> None:
        """让设备地址下拉表格和补全弹窗保持与输入框相同的当前宽度。"""

        width = max(1, self.ip_entry.width())
        for popup in (
            self.ip_entry.view(),
            self.ip_entry.completer().popup() if self.ip_entry.completer() else None,
        ):
            if popup is None:
                continue
            popup.setMinimumWidth(width)
            popup.setMaximumWidth(width)
            popup.resize(width, popup.height())

    def eventFilter(self, watched, event):
        if watched is getattr(self, "ip_entry", None) and event.type() == QEvent.Type.Resize:
            self._sync_address_popup_width()
        return super().eventFilter(watched, event)

    # ── 样式 ────────────────────────────────────────────────────────────

    def apply_fonts(self) -> None:
        """刷新设备列表、下拉表格和补全弹窗使用的等宽字体。"""

        font = BaseStyles.font_for_role(FontRole.MONO)
        self.listbox_devices.setProperty("fontRole", FontRole.MONO.value)
        self.listbox_devices.setFont(font)
        for i in range(self.listbox_devices.count()):
            item = self.listbox_devices.item(i)
            if item:
                item.setFont(font)
        view = self.ip_entry.view()
        if view is not None:
            view.setFont(font)
            horizontal_header = getattr(view, "horizontalHeader", None)
            if callable(horizontal_header):
                horizontal_header().setFont(font)
        self.panel._apply_completer_style(self.ip_entry.completer())
        sync_heights = getattr(self, "_sync_device_control_heights", None)
        update_minimums = getattr(self, "_update_device_minimum_heights", None)
        if callable(sync_heights) and hasattr(self, "_device_action_buttons"):
            sync_heights()
        if callable(update_minimums) and hasattr(self, "_device_action_frame"):
            update_minimums()

    def _apply_device_list_style(self):
        self.apply_fonts()
        self.listbox_devices.setStyleSheet(BaseStyles.DEVICE_LIST_STYLE())

    # ── 设备列表 ────────────────────────────────────────────────────────

    def set_discovery_state(self, state: str) -> None:
        """在设备分组标题中紧凑显示发现状态。"""

        state = str(state or "empty").lower()
        device_list = getattr(self, "listbox_devices", None)
        device_count = device_list.count() if device_list is not None else 0
        descriptions = {
            "scanning": ("Scanning…", "ADB device discovery is in progress"),
            "empty": ("No devices", "No Android devices are currently connected"),
            "unavailable": (
                "ADB unavailable",
                "ADB is unavailable; check the executable and server, then refresh",
            ),
            "ready": (
                f"{device_count} connected",
                f"{device_count} connected Android device(s) are available",
            ),
        }
        if state not in descriptions:
            state = "empty"
        text, description = descriptions[state]
        self._discovery_state = state
        title = f"Devices · {text}"
        self._device_group.setTitle(title)
        self._device_group.setAccessibleName(title)
        self._device_group.setAccessibleDescription(description)
        self._device_group.setToolTip(description)

    def update_device_list(self, devices: list[str] = None):
        if devices is None:
            devices = []
        devices = list(dict.fromkeys(devices or []))
        prev = set(self.selected_devices)
        blocker = QSignalBlocker(self.listbox_devices)
        try:
            existing = self._device_items_by_ip()
            device_set = set(devices)
            for ip, item in list(existing.items()):
                if ip not in device_set:
                    row = self.listbox_devices.row(item)
                    if row >= 0:
                        self.listbox_devices.takeItem(row)
            if devices:
                # DeviceStore 可能仍在后台补全新设备信息，先显示占位行，避免刷新后列表短暂为空。
                infos = {
                    str(info.get("ip", "")): info
                    for info in DeviceStore.get_full_devices_info(devices)
                }
                for device in devices:
                    info = infos.get(device) or {
                        "Brand": "ADB",
                        "Model": "Detecting",
                        "Aversion": "",
                        "ip": device,
                    }
                    brand = str(info.get("Brand", ""))
                    model = str(info.get("Model", ""))
                    version = str(info.get("Aversion", ""))
                    ip_addr = str(info.get("ip", ""))
                    txt = f"{brand}  |  {model}  |  {version}  |  {ip_addr}"
                    item = existing.get(ip_addr)
                    if item is None:
                        item = QListWidgetItem()
                        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                        self.listbox_devices.addItem(item)
                    item.setText(txt)
                    item.setData(Qt.UserRole, info)
                    item.setCheckState(Qt.Checked if ip_addr in prev else Qt.Unchecked)
                    item.setToolTip(txt)
        finally:
            del blocker
        self.panel._connected_device_cache = devices
        self.set_discovery_state("ready" if devices else "empty")
        DeviceManager._update_action_states(self)
        # 项目增删会改变真实行高及横向滚动条占位，必须立即刷新 splitter 安全下限。
        self.listbox_devices.doItemsLayout()
        update_minimums = getattr(self, "_update_device_minimum_heights", None)
        if callable(update_minimums):
            update_minimums()
        request_reflow = getattr(self.panel, "request_responsive_reflow", None)
        if callable(request_reflow):
            request_reflow(ReflowReason.EXPLICIT)

    def _update_action_states(self) -> None:
        """根据已连接和已勾选设备统一更新操作按钮状态。"""

        if not hasattr(self, "listbox_devices"):
            return
        device_count = self.listbox_devices.count()
        selected_devices = self.selected_devices
        selected_count = len(selected_devices)
        has_devices = device_count > 0
        has_selection = selected_count > 0
        for button in filter(
            None,
            (
                getattr(self, "btn_info", None),
                getattr(self, "btn_disconnect", None),
                getattr(self, "btn_restart_dev", None),
                getattr(self, "btn_batch", None),
            ),
        ):
            button.setEnabled(has_selection)
            if has_selection:
                button.setToolTip(str(button.property("functionalToolTip") or ""))
            elif button is getattr(self, "btn_info", None):
                button.setToolTip(
                    "Select a device first; device information is shown in the operation log"
                )
            else:
                button.setToolTip("Select a device first")
        select_all = getattr(self, "btn_all", None)
        deselect_all = getattr(self, "btn_none", None)
        if select_all is not None:
            select_all.setEnabled(has_devices and selected_count < device_count)
        if deselect_all is not None:
            deselect_all.setEnabled(has_selection)
        selection_changed = getattr(self.panel, "selected_devices_changed", None)
        if selection_changed is not None:
            selection_changed.emit(selected_devices)

    def _device_items_by_ip(self) -> dict[str, QListWidgetItem]:
        items = {}
        for row in range(self.listbox_devices.count()):
            item = self.listbox_devices.item(row)
            info = item.data(Qt.UserRole) if item else None
            ip = info.get("ip", "") if isinstance(info, dict) else ""
            if ip:
                items[str(ip)] = item
        return items

    # ── 下拉设备列表 ────────────────────────────────────────────────────

    def _build_combo_view(self):
        model = QStandardItemModel(0, 3)
        model.setHorizontalHeaderLabels(["Brand", "Model", "IP"])
        self._device_model = model
        tv = QTableView()
        tv.setModel(model)
        tv.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)  # 品牌列占剩余空间
        tv.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)  # 型号列占剩余空间
        tv.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)  # IP 列适应内容
        tv.verticalHeader().setVisible(False)
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        tv.setSelectionMode(QAbstractItemView.SingleSelection)
        tv.setShowGrid(False)
        tv.horizontalHeader().setHighlightSections(False)
        tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tv.setFont(self._font_mono)
        tv.horizontalHeader().setFont(self._font_mono)
        tv.verticalHeader().setDefaultSectionSize(20)
        tv.setMaximumHeight(240)
        tv.setStyleSheet(
            "QTableView { border: none; }"
            "QHeaderView::section { padding: 2px 6px; font-weight: bold; }"
        )
        self.ip_entry.setModel(model)
        self.ip_entry.setModelColumn(2)
        self.ip_entry.setView(tv)

    def _refresh_device_combobox(self):
        if not hasattr(self, "ip_entry"):
            return
        devs = DeviceStore.get_basic_devices_info()
        cache_key = tuple((str(brand), str(model), str(ip)) for brand, model, ip in devs)
        if cache_key == getattr(self, "_device_combo_cache", None):
            return
        self._device_combo_cache = cache_key
        self._device_model.removeRows(0, self._device_model.rowCount())
        ip_list = []
        for brand, model, ip in devs:
            ip_list.append(ip)
            self._device_model.appendRow(
                [
                    QStandardItem(str(brand)),
                    QStandardItem(str(model)),
                    QStandardItem(str(ip)),
                ]
            )
        if ip_list:
            comp = QCompleter(ip_list, self)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            self.panel._apply_completer_style(comp)
            self.ip_entry.setCompleter(comp)
            self._sync_address_popup_width()
        self.ip_entry.setCurrentIndex(-1)
        self.ip_entry.lineEdit().clear()
        self.ip_entry.lineEdit().setPlaceholderText("Select or type IP : Port")
        self.ip_entry.lineEdit().setAccessibleName("Device address")

    def _on_ip_selected(self, i):
        if 0 <= i < self._device_model.rowCount():
            ip_item = self._device_model.item(i, 2)
            if ip_item:
                with BlockSignals(self.ip_entry):
                    self.ip_entry.setCurrentIndex(-1)
                    self.ip_entry.setCurrentText(ip_item.text())
                self.panel._user_selected_ip = True

    def _on_ip_edited(self, t):
        self.panel._current_ip = t.strip()

    def _on_device_double_click(self, item):
        if not (item.flags() & Qt.ItemIsUserCheckable):
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    # ── 选择状态 ────────────────────────────────────────────────────────

    @property
    def selected_devices(self) -> list[str]:
        selected = []
        for index in range(self.listbox_devices.count()):
            item = self.listbox_devices.item(index)
            if item is None or item.checkState() != Qt.Checked:
                continue
            info = item.data(Qt.UserRole)
            if isinstance(info, dict) and info.get("ip"):
                selected.append(str(info["ip"]))
        return selected

    @property
    def ip_address(self) -> str:
        t = self.ip_entry.currentText().strip()
        return t if (self.panel._user_selected_ip or t) else ""

    def update_current_package(self, device_ip: str, package_name: str):
        def _up():
            for i in range(self.listbox_devices.count()):
                item = self.listbox_devices.item(i)
                info = item.data(Qt.UserRole)
                if info and info.get("ip") == device_ip:
                    item.setText(f"{device_ip}  |  {package_name}")
                    apps_tab = getattr(self.panel, "_apps_tab", None)
                    if apps_tab:
                        apps_tab.add_package_to_history(package_name)
                    break

        QTimer.singleShot(0, _up)

    # ── 信号连接 ────────────────────────────────────────────────────────

    def _request_connect(self):
        target, error = normalize_adb_connect_target(self.ip_address)
        if error:
            self.signals.log_message.emit("WARNING", error)
            line_edit = self.ip_entry.lineEdit()
            if line_edit:
                line_edit.setFocus()
                line_edit.selectAll()
            return
        self.signals.connect_requested.emit(target)

    def _request_refresh(self):
        self.set_discovery_state("scanning")
        self.signals.refresh_devices_requested.emit()

    def connect_signals(self):
        LP = self.signals
        self.btn_connect_devices.clicked.connect(self._request_connect)
        line_edit = self.ip_entry.lineEdit()
        if line_edit:
            line_edit.returnPressed.connect(self._request_connect)
        self.btn_refresh.clicked.connect(self._request_refresh)
        self.btn_info.clicked.connect(lambda: LP.device_info_requested.emit(self.selected_devices))
        self.btn_disconnect.clicked.connect(
            lambda: LP.disconnect_requested.emit(self.selected_devices)
        )
        self.btn_restart_dev.clicked.connect(
            lambda: LP.restart_devices_requested.emit(self.selected_devices)
        )
        self.btn_restart_adb.clicked.connect(LP.restart_adb_requested.emit)
        self.btn_batch.clicked.connect(
            lambda: LP.batch_install_requested.emit(self.selected_devices)
        )
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_double_click)
        self.btn_all.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_none.clicked.connect(lambda: self._set_all_checked(False))
        self.listbox_devices.itemChanged.connect(lambda _item: self._update_action_states())

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        blocker = QSignalBlocker(self.listbox_devices)
        try:
            for i in range(self.listbox_devices.count()):
                self.listbox_devices.item(i).setCheckState(state)
        finally:
            del blocker
        self._update_action_states()
