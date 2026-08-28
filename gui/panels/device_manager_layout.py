"""提供 Devices 面板几何度量、三态断点与响应式布局应用控制器。"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QScrollArea, QStyle, QStyleOptionViewItem, QWidget

from gui.panels.device_manager_responsive import _DeviceCompositePlan, _DeviceResponsiveBinding
from gui.widgets.responsive_controller import ReflowReason
from gui.widgets.responsive_layout import GridPlan, LayoutContext


class DeviceManagerLayout:
    """组合进 DeviceManager 的布局控制器，通过 ``self._frame`` 访问面板。"""

    def __init__(self, frame):
        self._frame = frame

    def apply_responsive_width(self, width: int) -> None:
        """兼容旧入口；实际宽度始终由 Devices 视觉根在规划轮次中读取。"""

        del width
        self._frame.panel.request_responsive_reflow(ReflowReason.RESIZE)

    def _responsive_context(self, container: QWidget) -> LayoutContext:
        """提供 SidePanel 状态；binding 会用视觉根真实几何和字体覆盖本地字段。"""

        del container
        root = self._frame.device_widget
        font = root.font()
        return LayoutContext(
            root.contentsRect().width(),
            root.contentsRect().height(),
            self._frame.panel._restricted_width_mode,
            (font.family(), font.pointSizeF()),
            self._frame.panel._responsive_style_generation,
        )

    def _action_viewport_width(
        self,
        context: LayoutContext,
        mode: str,
        body_mode: str,
    ) -> int:
        """优先读取真实动作 viewport，首次换态时使用单调的保守估算。"""

        action_rect = self._frame._device_action_scroll.viewport().contentsRect()
        if (
            self._frame._device_layout_mode == mode
            and self._frame._device_body_mode == body_mode
            and action_rect.width() > 0
        ):
            return action_rect.width()
        spacing = max(0, self._frame._device_body_layout.horizontalSpacing())
        body_width = max(1, context.width - self._frame._device_horizontal_insets())
        if body_mode == "side_by_side":
            # QGridLayout 的 3:1 分配会把该舍入像素交给右侧动作列。
            action_width = max(1, (body_width - spacing + 1) // 4)
        else:
            action_width = body_width
        return max(1, action_width)

    def _device_horizontal_insets(self) -> int:
        """返回 Devices 根到动作 viewport 之间不参与内容分配的横向占位。"""

        root_layout_margins = self._frame.device_widget.layout().contentsMargins()
        group_contents_margins = self._frame._device_group.contentsMargins()
        group_layout_margins = self._frame._device_group.layout().contentsMargins()
        body_layout_margins = self._frame._device_body_layout.contentsMargins()
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

        small_limit, wide_limit = self._frame._device_layout_limits()
        if context.width < small_limit:
            mode = "compact"
        elif context.width < wide_limit:
            mode = "medium"
        else:
            mode = "wide"

        def action_plan_for(body_mode: str, *, force_one_column: bool) -> tuple[int, GridPlan]:
            viewport_width = self._frame._action_viewport_width(context, mode, body_mode)
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
        stacked_height_limit = self._frame._device_stacked_height_limit(mode, stacked_action_plan)
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
        connect_width = (
            max(1, connect_viewport_width - margins[0] - margins[2])
            if mode == "medium"
            else max(1, usable_width // connect_action_plan.mode.columns)
        )
        body_minimum_height = self._frame._device_body_minimum_height(action_plan, body_mode)
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
        if getattr(self._frame, "_device_structure_fingerprint", None) == structure_fingerprint:
            return

        connect_layout = self._frame._connect_layout
        connect_layout.removeWidget(self._frame.ip_entry)
        connect_layout.removeWidget(self._frame.btn_connect_devices)
        for column in range(max(3, connect_layout.columnCount())):
            connect_layout.setColumnStretch(column, 0)
            connect_layout.setColumnMinimumWidth(column, 0)
        for row in range(max(3, connect_layout.rowCount())):
            connect_layout.setRowStretch(row, 0)
        self._frame.btn_connect_devices.setMinimumWidth(0)
        self._frame.btn_connect_devices.setMaximumWidth(16_777_215)
        if plan.mode == "compact":
            connect_layout.addWidget(self._frame.ip_entry, 0, 0, 1, 2)
            connect_layout.addWidget(self._frame.btn_connect_devices, 1, 0, 1, 2)
            connect_layout.setColumnStretch(0, 1)
            connect_layout.setColumnStretch(1, 1)
        elif plan.mode == "medium":
            # 中等宽度保留地址与 Connect 各自整行，避免两列动作布局留下半行空白。
            connect_layout.addWidget(self._frame.ip_entry, 0, 0, 1, 2)
            connect_layout.addWidget(self._frame.btn_connect_devices, 1, 0, 1, 2)
            connect_layout.setColumnStretch(0, 1)
            connect_layout.setColumnStretch(1, 1)
        else:
            connect_layout.addWidget(self._frame.ip_entry, 0, 0)
            connect_layout.addWidget(
                self._frame.btn_connect_devices,
                0,
                1,
                alignment=Qt.AlignmentFlag.AlignRight,
            )
            connect_layout.setColumnStretch(0, 3)
            # 连接区与主体共享 3:1 列语义，避免两个网格分别计算导致列宽漂移。
            connect_layout.setColumnStretch(1, 1)

        body = self._frame._device_body_layout
        body.removeWidget(self._frame.listbox_devices)
        body.removeWidget(self._frame._device_action_scroll)
        for column in range(max(3, body.columnCount())):
            body.setColumnStretch(column, 0)
            body.setColumnMinimumWidth(column, 0)
        for row in range(max(3, body.rowCount())):
            body.setRowStretch(row, 0)
            body.setRowMinimumHeight(row, 0)

        if plan.body_mode == "stacked":
            body.addWidget(self._frame.listbox_devices, 0, 0, 1, 2)
            body.addWidget(self._frame._device_action_scroll, 1, 0, 1, 2)
            body.setColumnStretch(0, 1)
            body.setColumnStretch(1, 1)
            body.setRowStretch(0, 1)
            body.setRowStretch(1, 0)
        else:
            body.addWidget(self._frame.listbox_devices, 0, 0)
            body.addWidget(self._frame._device_action_scroll, 0, 1)
            body.setColumnStretch(0, 3)
            body.setColumnStretch(1, 1)
            body.setRowStretch(0, 1)
        self._frame._device_structure_fingerprint = structure_fingerprint

    def _finish_device_plan(self, plan: _DeviceCompositePlan) -> None:
        """在动作网格应用后同步等宽约束、最小高度和弹窗宽度。"""

        self._frame._device_layout_mode = plan.mode
        self._frame._device_body_mode = plan.body_mode
        self._frame._device_action_overflow_required = plan.action_plan.overflow_required
        self._frame._device_actions_layout.setProperty(
            "deviceActionColumnCount",
            plan.action_plan.mode.columns,
        )
        # 空的末尾伸展行吸收宽布局多出的列表高度，避免 Qt 把余量均摊到
        # 固定高度按钮之间；真实按钮行仍严格使用计划中的 2/4/6px 间距。
        action_row_count = max(
            (placement.row + placement.row_span for placement in plan.action_plan.placements),
            default=0,
        )
        for row in range(max(self._frame._device_actions_layout.rowCount(), action_row_count + 1)):
            self._frame._device_actions_layout.setRowStretch(row, 0)
        self._frame._device_actions_layout.setRowStretch(action_row_count, 1)
        if plan.mode in {"wide", "medium"}:
            self._frame.btn_connect_devices.setMinimumWidth(plan.connect_width)
            self._frame.btn_connect_devices.setMaximumWidth(plan.connect_width)

        spacing = plan.action_plan.spacing
        for layout in (self._frame._connect_layout, self._frame._device_body_layout):
            if layout.horizontalSpacing() != spacing:
                layout.setHorizontalSpacing(spacing)
            if layout.verticalSpacing() != spacing:
                layout.setVerticalSpacing(spacing)

        self._frame._sync_device_control_heights()
        self._frame._update_device_minimum_heights(plan.body_minimum_height)
        self._frame._sync_address_popup_width()

    def device_list_minimum_height(self) -> int:
        """返回当前内容下可完整显示一行设备所需的列表高度。"""

        row_heights = tuple(
            self._frame.listbox_devices.sizeHintForRow(row)
            for row in range(self._frame.listbox_devices.count())
        )
        valid_row_heights = tuple(height for height in row_heights if height > 0)
        row_height = (
            max(valid_row_heights) if valid_row_heights else self._frame._empty_device_row_height()
        )
        viewport_margins = self._frame.listbox_devices.viewportMargins()
        height = (
            row_height
            + self._frame.listbox_devices.frameWidth() * 2
            + viewport_margins.top()
            + viewport_margins.bottom()
        )
        if self._frame._device_list_reserves_horizontal_scrollbar():
            height += self._frame.listbox_devices.horizontalScrollBar().sizeHint().height()
        return height

    def _empty_device_row_height(self) -> int:
        """通过当前字体和样式估算带复选框设备项的一行完整高度。"""

        option = QStyleOptionViewItem()
        self._frame.listbox_devices.initViewItemOption(option)
        cast(Any, option).features |= (
            QStyleOptionViewItem.ViewItemFeature.HasDisplay
            | QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        )
        cast(Any, option).checkState = Qt.CheckState.Unchecked
        indicator_height = self._frame.listbox_devices.style().pixelMetric(
            QStyle.PixelMetric.PM_IndicatorHeight,
            option,
            self._frame.listbox_devices,
        )
        content_height = max(
            self._frame.listbox_devices.fontMetrics().height(),
            indicator_height,
        )
        styled_height = (
            self._frame.listbox_devices.style()
            .sizeFromContents(
                QStyle.ContentsType.CT_ItemViewItem,
                option,
                QSize(0, content_height),
                self._frame.listbox_devices,
            )
            .height()
        )
        return max(content_height, styled_height)

    def _device_list_reserves_horizontal_scrollbar(self) -> bool:
        """除明确禁用外，预留横向滚动条高度，避免内容出现时顶开 splitter。"""

        return (
            self._frame.listbox_devices.horizontalScrollBarPolicy()
            != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

    def _update_device_minimum_heights(
        self,
        body_minimum_height: int | None = None,
    ) -> None:
        """向祖先传播一行列表和全部动作行的真实安全高度。"""

        list_height = self._frame.device_list_minimum_height()
        self._frame.listbox_devices.setMinimumHeight(list_height)
        action_plan = getattr(
            getattr(self._frame, "_device_responsive_binding", None),
            "applied_plan",
            None,
        )
        action_height = self._frame._device_action_minimum_height(action_plan)
        self._frame._device_action_frame.setMinimumHeight(action_height)
        action_host_height = action_height
        if action_plan is not None and action_plan.overflow_required:
            action_host_height += (
                self._frame._device_action_scroll.horizontalScrollBar().sizeHint().height()
            )
        self._frame._device_action_scroll.setMinimumHeight(action_host_height)
        if body_minimum_height is None:
            body_minimum_height = self._frame._device_body_minimum_height(
                action_plan,
                self._frame._device_body_mode or "side_by_side",
            )
        self._frame._device_body_host.setMinimumHeight(body_minimum_height)
        if self._frame._device_body_mode == "stacked":
            self._frame._device_body_layout.setRowMinimumHeight(0, list_height)
            self._frame._device_body_layout.setRowMinimumHeight(1, action_host_height)
        else:
            self._frame._device_body_layout.setRowMinimumHeight(
                0,
                body_minimum_height,
            )
        root = self._frame.device_widget
        root_layout = root.layout()
        if root_layout is not None:
            root_layout.invalidate()
            root_layout.activate()
            root_height = max(
                0,
                root_layout.minimumSize().height(),
                root.minimumSizeHint().height(),
            )
            if root.minimumHeight() != root_height:
                root.setMinimumHeight(root_height)
            viewport = root.parentWidget()
            scroll = viewport.parentWidget() if viewport is not None else None
            if isinstance(scroll, QScrollArea) and scroll.objectName() == "deviceScrollArea":
                preserve_height = bool(scroll.property("preserveDeviceContentHeight"))
                scroll_height = root_height if preserve_height else 0
                if scroll.minimumHeight() != scroll_height:
                    scroll.setMinimumHeight(scroll_height)
        self._frame._device_body_host.updateGeometry()
        self._frame._device_group.updateGeometry()
        self._frame.device_widget.updateGeometry()

    def _device_action_minimum_height(self, action_plan: GridPlan | None) -> int:
        """返回完整显示动作网格全部行所需的真实高度。"""

        action_margins = self._frame._device_actions_layout.contentsMargins()
        row_heights: dict[int, int] = {}
        if action_plan is not None:
            placements = tuple(
                (placement.item_index, placement.row) for placement in action_plan.placements
            )
        else:
            placements = []
            for index, button in enumerate(self._frame._device_action_buttons):
                layout_index = self._frame._device_actions_layout.indexOf(button)
                if layout_index < 0:
                    continue
                row, _column, _row_span, _column_span = (
                    self._frame._device_actions_layout.getItemPosition(layout_index)
                )
                placements.append((index, row))
        for button_index, row in placements:
            button = self._frame._device_action_buttons[button_index]
            height = max(
                button.minimumHeight(),
                button.sizeHint().height(),
                button.minimumSizeHint().height(),
            )
            row_heights[row] = max(row_heights.get(row, 0), height)
        spacing = max(0, self._frame._device_actions_layout.verticalSpacing())
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

        margins = self._frame._device_body_layout.contentsMargins()
        list_height = self._frame.device_list_minimum_height()
        action_height = self._frame._device_action_minimum_height(action_plan)
        if action_plan is not None and action_plan.overflow_required:
            action_height += (
                self._frame._device_action_scroll.horizontalScrollBar().sizeHint().height()
            )
        if body_mode == "stacked":
            content_height = (
                list_height
                + max(0, self._frame._device_body_layout.verticalSpacing())
                + action_height
            )
        else:
            content_height = max(list_height, action_height)
        return content_height + margins.top() + margins.bottom()

    def _device_stacked_height_limit(self, mode: str, action_plan: GridPlan) -> int:
        """按当前样式度量计算主体能够安全堆叠的精确高度边界。"""

        root_margins = self._frame.device_widget.layout().contentsMargins()
        group_contents = self._frame._device_group.contentsMargins()
        group_layout = self._frame._device_group.layout()
        group_margins = group_layout.contentsMargins()
        connect_margins = self._frame._connect_layout.contentsMargins()
        body_margins = self._frame._device_body_layout.contentsMargins()
        connect_rows = 1 if mode == "wide" else 2
        control_height = max(
            self._frame.ip_entry.minimumHeight(),
            self._frame.btn_connect_devices.minimumHeight(),
        )
        connect_spacing = max(0, self._frame._connect_layout.verticalSpacing())
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
                self._frame.device_list_minimum_height(),
                max(0, self._frame._device_body_layout.verticalSpacing()),
                self._frame._device_action_minimum_height(action_plan),
            )
        )

    def _sync_device_control_heights(self) -> None:
        """按当前字体统一连接区和设备动作控件的最小高度。"""

        controls = (
            self._frame.ip_entry,
            self._frame.btn_connect_devices,
            *self._frame._device_action_buttons,
        )
        base_minimums = getattr(self._frame, "_device_control_base_minimums", None)
        if base_minimums is None:
            base_minimums = tuple(control.minimumHeight() for control in controls)
            self._frame._device_control_base_minimums = base_minimums
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
            for button in self._frame._device_action_buttons
        )
        action_margins = self._frame._device_actions_layout.contentsMargins()
        # 与 Task 2 一致，先用最紧凑档选择可容纳模式，避免上一计划的 spacing
        # 反向改变 compact/wide 断点并产生方向性迟滞。
        action_spacing = 2
        action_cell_width = max(action_widths, default=1)
        one_column_width = action_cell_width + action_margins.left() + action_margins.right()
        two_column_width = (
            action_cell_width * 2 + action_spacing + action_margins.left() + action_margins.right()
        )

        horizontal_insets = self._frame._device_horizontal_insets()

        compact_limit = horizontal_insets + two_column_width
        body_spacing = 2
        # wide 主体采用 3:1 stretch；Qt 将除不尽的一个像素优先分给右列。
        wide_limit = horizontal_insets + body_spacing + one_column_width * 4 - 1
        return compact_limit, wide_limit

    def _sync_address_popup_width(self) -> None:
        """让设备地址下拉表格和补全弹窗保持与输入框相同的当前宽度。"""

        width = max(1, self._frame.ip_entry.width())
        completer = self._frame.ip_entry.completer()
        for popup in (
            self._frame.ip_entry.view(),
            completer.popup() if completer is not None else None,
        ):
            if popup is None:
                continue
            popup.setMinimumWidth(width)
            popup.setMaximumWidth(width)
            popup.resize(width, popup.height())
