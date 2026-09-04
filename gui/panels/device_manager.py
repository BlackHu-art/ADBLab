"""提供设备连接、发现、选择和基础操作面板。"""

from __future__ import annotations

import weakref
from typing import cast

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import InfoBadge

from gui.panels.base_panel import BasePanel
from gui.panels.device_manager_layout import DeviceManagerLayout
from gui.panels.device_manager_responsive import (
    _DeviceResponsiveBinding,
    _ShrinkableActionScroll,
    _ShrinkableDeviceBody,
    _ShrinkableDeviceList,
)
from gui.panels.device_manager_view import DeviceManagerView, _DeviceCardRow
from gui.styles import FontRole
from gui.widgets.responsive_controller import ReflowReason
from models.device_store import DeviceStore  # noqa: F401  供测试通过本模块命名空间补丁。
from utils.adb_targets import normalize_adb_connect_target


def _resolve_device_controller(frame, attr, controller_cls):
    """返回 frame 上已实例化的控制器，或为静态调用与测试桩按需新建。"""

    controller = getattr(frame, attr, None)
    if isinstance(controller, controller_cls):
        return controller
    return controller_cls(frame)


class DeviceManager(BasePanel):
    """维护设备列表展示，并向统一信号层转发设备操作。"""

    def __init__(self, panel, parent=None):
        super().__init__(panel, parent)
        self._layout_controller = DeviceManagerLayout(self)
        self._view_controller = DeviceManagerView(self)

    def build_ui(self) -> QWidget:
        w = QWidget()
        self.device_widget = w
        w.setObjectName("deviceManager")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        # 给短屏滚动到底后的最后一行动作保留稳定净空，避免 Qt 在
        # 响应式高度收敛期间因像素取整把按钮边缘留在 viewport 外。
        lo.setContentsMargins(0, 0, 0, 8)

        g_dev = self._g("设备与连接")
        self._device_group = g_dev
        g_dev.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        g_dev.setAccessibleName("设备与连接")
        # HeaderCardWidget 公开 headerLayout，状态徽标直接进入参考组件标题区。
        self._discovery_badge = InfoBadge(g_dev.headerView)
        self._discovery_badge.setProperty("fontRole", FontRole.UI.value)
        self._discovery_badge_kind = "empty"
        g_dev.headerLayout.addStretch(1)
        g_dev.headerLayout.addWidget(self._discovery_badge)
        gd_l = g_dev.viewLayout
        # 与分组标题保留固定净空；连接区形态保持固定，极限尺寸由局部滚动承接。
        gd_l.setContentsMargins(12, 12, 12, 14)
        # 连接区和设备主体是两个视觉分区；宽布局下 Connect 正好位于 Refresh
        # 上方，保留明确净空以免两个按钮边框黏连。
        gd_l.setSpacing(10)

        rc = QGridLayout()
        rc.setHorizontalSpacing(2)
        rc.setVerticalSpacing(0)
        rc.setContentsMargins(0, 0, 0, 0)
        self._connect_layout = rc
        self.ip_entry = self._combo_editable(font_role=FontRole.MONO)
        self.ip_entry.setAccessibleName("设备地址")
        self.ip_entry.setMinimumWidth(0)
        self.ip_entry.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._build_combo_view()
        self._refresh_device_combobox()
        self.ip_entry.currentIndexChanged.connect(self._on_ip_selected)
        self.ip_entry.textChanged.connect(self._on_ip_edited)
        self.btn_connect_devices = self._b(
            "连接",
            "plug.svg",
            variant="accent",
            tooltip="连接输入的设备地址",
        )
        rc.addWidget(self.ip_entry, 0, 0)
        rc.addWidget(self.btn_connect_devices, 0, 1)
        rc.setColumnStretch(0, 3)
        rc.setColumnStretch(1, 1)
        # 连接区卡片：仅视觉包壳，ip_entry / btn_connect_devices 与网格结构不变。
        connect_card = QFrame()
        connect_card.setObjectName("connectCard")
        card_lo = QVBoxLayout(connect_card)
        card_lo.setContentsMargins(0, 0, 0, 0)
        card_lo.setSpacing(0)
        card_lo.addLayout(rc)
        gd_l.addWidget(connect_card)
        self._connect_card = connect_card

        body_host = _ShrinkableDeviceBody()
        body_host.setObjectName("deviceBody")
        body_host.setMinimumWidth(0)
        body_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._device_body_host = body_host
        body = QGridLayout(body_host)
        body.setHorizontalSpacing(2)
        body.setVerticalSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)
        self._device_body_layout = body

        self.listbox_devices = _ShrinkableDeviceList()
        self.listbox_devices.setObjectName("deviceList")
        self.listbox_devices.setAccessibleName("已连接设备")
        self.listbox_devices.setAccessibleDescription(
            "使用复选框选择一台或多台设备执行操作"
        )
        self.listbox_devices.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.listbox_devices.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # 设备操作以复选状态为唯一真源，关闭独立行选择以避免高亮与勾选含义冲突。
        self.listbox_devices.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.listbox_devices.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.listbox_devices.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.listbox_devices.setMinimumWidth(0)
        self._apply_device_list_style()

        side = QFrame()
        side.setObjectName("deviceActionCard")
        sl = QGridLayout(side)
        # medium 状态下 Connect 与两列动作共用水平列宽，间距也必须一致。
        sl.setHorizontalSpacing(rc.horizontalSpacing())
        sl.setVerticalSpacing(2)
        sl.setContentsMargins(0, 0, 0, 0)
        self._device_actions_layout = sl
        self.btn_refresh = self._b(
            "刷新", "arrows-clockwise.svg", tooltip="扫描已连接设备"
        )
        self.btn_info = self._b(
            "设备信息",
            "info.svg",
            tooltip="在操作日志中显示所选设备详情",
        )
        self.btn_disconnect = self._b(
            "断开连接",
            "link-break.svg",
            variant="danger",
            tooltip="断开所选设备",
        )
        self.btn_restart_dev = self._b(
            "重启设备", "arrow-counter-clockwise.svg", tooltip="重启所选设备"
        )
        self.btn_restart_adb = self._b(
            "重启 ADB", "arrow-u-up-left.svg", tooltip="重启本机 ADB 服务"
        )
        self.btn_restart_adb.setAccessibleDescription(
            "确认后重启本机 ADB 服务"
        )
        self.btn_batch = self._b(
            "批量安装", "stack-plus.svg", tooltip="向所选设备安装 APK 文件"
        )
        self.btn_all = self._b(
            "全选", "check-square.svg", tooltip="选择列表中的全部设备"
        )
        self.btn_none = self._b("取消全选", "square.svg", tooltip="清除设备选择")
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
        side.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        for button in self._device_action_buttons:
            button.setMinimumWidth(0)

        action_scroll = _ShrinkableActionScroll()
        action_scroll.setObjectName("deviceActionScroll")
        action_scroll.setAccessibleName("设备操作")
        action_scroll.setFrameShape(QFrame.Shape.NoFrame)
        action_scroll.setWidgetResizable(True)
        action_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        action_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        action_scroll.setMinimumSize(0, 0)
        action_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        action_scroll.setWidget(side)
        self._device_action_scroll = action_scroll
        body.addWidget(self.listbox_devices, 0, 0)
        body.addWidget(action_scroll, 0, 1)
        body.setColumnStretch(0, 3)
        body.setColumnStretch(1, 1)
        self._device_layout_mode = None
        self._device_body_mode = None
        self._device_responsive_binding = _DeviceResponsiveBinding(self)
        self.action_binding = self._device_responsive_binding
        self._sync_device_control_heights()
        self._update_device_minimum_heights()
        initial_state = str(
            getattr(self.panel, "_device_discovery_state", "scanning") or "scanning"
        ).lower()
        if initial_state not in {"scanning", "empty", "unavailable", "ready"}:
            initial_state = "scanning"
        self.set_discovery_state(initial_state)
        self._update_action_states()
        self._apply_device_card_styles()
        gd_l.addWidget(body_host)
        lo.addWidget(g_dev)
        self.panel.request_responsive_reflow(ReflowReason.EXPLICIT)
        return w

    # ── 布局控制器委托 wrapper ─────────────────────────────────────────

    def apply_responsive_width(self, width: int) -> None:
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        ).apply_responsive_width(width)

    def _responsive_context(self, container):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._responsive_context(container)

    def _action_viewport_width(self, context, mode, body_mode):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._action_viewport_width(context, mode, body_mode)

    def _device_horizontal_insets(self):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._device_horizontal_insets()

    def _build_device_plan(self, binding, context, *, conservative):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._build_device_plan(binding, context, conservative=conservative)

    def _apply_device_plan(self, plan):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._apply_device_plan(plan)

    def _finish_device_plan(self, plan):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._finish_device_plan(plan)

    def device_list_minimum_height(self):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        ).device_list_minimum_height()

    def _empty_device_row_height(self):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._empty_device_row_height()

    def _device_list_reserves_horizontal_scrollbar(self):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._device_list_reserves_horizontal_scrollbar()

    def _update_device_minimum_heights(self, body_minimum_height=None):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._update_device_minimum_heights(body_minimum_height)

    def _device_action_minimum_height(self, action_plan):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._device_action_minimum_height(action_plan)

    def _device_body_minimum_height(self, action_plan, body_mode):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._device_body_minimum_height(action_plan, body_mode)

    def _device_stacked_height_limit(self, mode, action_plan):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._device_stacked_height_limit(mode, action_plan)

    def _sync_device_control_heights(self):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._sync_device_control_heights()

    def _device_layout_limits(self):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._device_layout_limits()

    def _sync_address_popup_width(self):
        return _resolve_device_controller(
            self, "_layout_controller", DeviceManagerLayout
        )._sync_address_popup_width()

    # ── 视图控制器委托 wrapper ─────────────────────────────────────────

    def apply_fonts(self):
        return _resolve_device_controller(self, "_view_controller", DeviceManagerView).apply_fonts()

    def _apply_device_list_style(self):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._apply_device_list_style()

    def _apply_device_card_styles(self):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._apply_device_card_styles()

    def _apply_connect_card_style(self, mode):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._apply_connect_card_style(mode)

    def _sync_discovery_badge_geometry(self):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._sync_discovery_badge_geometry()

    def set_discovery_state(self, state):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        ).set_discovery_state(state)

    def update_device_list(self, devices=None):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        ).update_device_list(devices)

    def _update_action_states(self):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._update_action_states()

    def _device_items_by_ip(self):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._device_items_by_ip()

    def _build_combo_view(self):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._build_combo_view()

    def _refresh_device_combobox(self):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._refresh_device_combobox()

    def _on_ip_selected(self, i):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._on_ip_selected(i)

    def _on_ip_edited(self, t):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._on_ip_edited(t)

    def _on_device_double_click(self, item):
        return _resolve_device_controller(
            self, "_view_controller", DeviceManagerView
        )._on_device_double_click(item)

    # ── 选择状态 ────────────────────────────────────────────────────────

    @property
    def selected_devices(self) -> list[str]:
        selected = []
        for index in range(self.listbox_devices.count()):
            item = self.listbox_devices.item(index)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            info = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(info, dict) and info.get("ip"):
                selected.append(str(info["ip"]))
        return selected

    @property
    def ip_address(self) -> str:
        t = self.ip_entry.currentText().strip()
        return t if (self.panel._user_selected_ip or t) else ""

    def update_current_package(self, device_ip: str, package_name: str):
        frame_ref = weakref.ref(self)

        def _up():
            frame = frame_ref()
            if frame is None:
                return
            for i in range(frame.listbox_devices.count()):
                item = frame.listbox_devices.item(i)
                info = item.data(Qt.ItemDataRole.UserRole)
                if info and info.get("ip") == device_ip:
                    text = f"{device_ip}  |  {package_name}"
                    item.setText(text)
                    card = frame.listbox_devices.itemWidget(item)
                    if card is not None:
                        # 行卡片文本与条目文本保持同源显示。
                        cast(_DeviceCardRow, card).set_device_text(text)
                    apps_tab = getattr(frame.panel, "_apps_tab", None)
                    if apps_tab:
                        apps_tab.add_package_to_history(package_name)
                    break

        QTimer.singleShot(0, _up)

    # ── 信号连接 ────────────────────────────────────────────────────────

    def _request_connect(self):
        target, error = normalize_adb_connect_target(self.ip_address)
        if error:
            self.signals.log_message.emit("WARNING", error)
            self.ip_entry.setFocus()
            self.ip_entry.selectAll()
            return
        self.signals.connect_requested.emit(target)

    def _request_refresh(self):
        request_refresh = getattr(self.panel, "request_device_refresh", None)
        if callable(request_refresh):
            request_refresh()
            return
        # 仅供最小测试替身兼容；生产路径始终由 SidePanel 提交共享状态。
        if not self.btn_refresh.isEnabled():
            return
        self.set_discovery_state("scanning")
        self.signals.refresh_devices_requested.emit()

    def connect_signals(self):
        LP = self.signals
        self.btn_connect_devices.clicked.connect(self._request_connect)
        self.ip_entry.returnPressed.connect(self._request_connect)
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
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        blocker = QSignalBlocker(self.listbox_devices)
        try:
            for i in range(self.listbox_devices.count()):
                item = self.listbox_devices.item(i)
                assert item is not None  # stub Optional 收窄
                item.setCheckState(state)
        finally:
            del blocker
        self._update_action_states()
