"""提供 Devices 面板字体/样式应用、设备列表与下拉交互视图控制器。"""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidgetItem,
    QTableView,
    QWidget,
)
from qfluentwidgets import InfoBadge, InfoLevel

from gui.panels.side_panel_signals import BlockSignals
from gui.styles import BaseStyles, FontRole
from gui.widgets.responsive_controller import ReflowReason
from models.device_store import DeviceStore

# 连接卡片在 compact/medium 形态下的水平占位常量：左右各 1px 边框 + 8px 内边距。
# 布局控制器按该常量扣除 Connect 固定宽度，避免模式切换瞬间读取上一形态的实时
# contentsMargins 造成断点滞后（wide 形态卡片保持零占位，见 _connect_card_style）。
_CONNECT_CARD_BORDER = 1
_CONNECT_CARD_PADDING_H = 8

# 发现状态徽标按状态键映射主题 token；徽标文本只补充标题区视觉，
# set_discovery_state 的状态字符串与标题文本契约保持不变。
_DISCOVERY_BADGE_LEVELS = {
    "scanning": InfoLevel.INFOAMTION,
    "empty": InfoLevel.INFOAMTION,
    "unavailable": InfoLevel.ERROR,
    "ready": InfoLevel.SUCCESS,
}


class _DeviceCardRow(QWidget):
    """设备行卡片：信息文本 + 状态徽标；鼠标事件全部透传给列表原生处理。"""

    def __init__(
        self,
        text: str,
        badge_text: str,
        badge_kind: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("deviceCard")
        self.setProperty("cardHovered", "false")
        self._badge_kind = badge_kind
        # 行卡片对鼠标透明：勾选、双击、悬停全部由 QListWidget 原生路径处理。
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._info_label = QLabel(text, self)
        self._info_label.setObjectName("deviceCardText")
        self._badge = InfoBadge(self)
        self._badge.setText(badge_text)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        layout.addWidget(self._info_label, 1)
        layout.addWidget(self._badge, 0)
        self._sync_card_style()

    def set_device_text(self, text: str) -> None:
        """更新卡片信息文本（与条目文本保持同源）。"""

        self._info_label.setText(text)

    def set_badge(self, text: str, kind: str) -> None:
        """更新状态徽标文本与配色。"""

        self._badge.setText(text)
        self._badge_kind = kind
        self._sync_card_style()

    def _sync_card_style(self) -> None:
        """按当前主题重建行卡片与徽标样式。"""

        bs = BaseStyles
        self.setStyleSheet(
            f"QWidget#deviceCard {{ background-color: {bs.color('PANEL_BG')};"
            f" border-radius: {bs.RADIUS_SM}px; }}"
            f"QWidget#deviceCard[cardHovered=\"true\"] {{"
            f" background-color: {bs.color('BUTTON_HOVER')}; }}"
        )
        self._badge.setLevel(
            InfoLevel.SUCCESS if self._badge_kind == "ready" else InfoLevel.WARNING
        )


class DeviceManagerView:
    """组合进 DeviceManager 的视图控制器，通过 ``self._frame`` 访问面板。"""

    def __init__(self, frame):
        self._frame = frame

    def apply_fonts(self) -> None:
        """刷新设备列表、下拉表格和补全弹窗使用的等宽字体。"""

        font = BaseStyles.font_for_role(FontRole.MONO)
        self._frame.listbox_devices.setProperty("fontRole", FontRole.MONO.value)
        self._frame.listbox_devices.setFont(font)
        for i in range(self._frame.listbox_devices.count()):
            item = self._frame.listbox_devices.item(i)
            if item:
                item.setFont(font)
                card = self._frame.listbox_devices.itemWidget(item)
                if card is not None:
                    # 行卡片跟随列表等宽字体；字号变化后徽标几何同步重算。
                    card.setFont(font)
        view = self._frame.ip_entry.view()
        if view is not None:
            view.setFont(font)
            horizontal_header = getattr(view, "horizontalHeader", None)
            if callable(horizontal_header):
                cast(QHeaderView, horizontal_header()).setFont(font)
        self._frame.panel._apply_completer_style(self._frame.ip_entry.completer())
        sync_heights = getattr(self._frame, "_sync_device_control_heights", None)
        update_minimums = getattr(self._frame, "_update_device_minimum_heights", None)
        if callable(sync_heights) and hasattr(self._frame, "_device_action_buttons"):
            sync_heights()
        if callable(update_minimums) and hasattr(self._frame, "_device_action_frame"):
            update_minimums()
        self._sync_discovery_badge_geometry()

    def _apply_device_list_style(self):
        # 列表样式由 ScalableListWidget 自维护（随主题重建），这里只刷新字体与卡片。
        self._frame.apply_fonts()
        self._apply_device_card_styles()

    def _apply_device_card_styles(self) -> None:
        """刷新设备行卡片、连接卡片、动作区卡片与发现状态徽标的主题样式。"""

        frame = self._frame
        listbox = getattr(frame, "listbox_devices", None)
        if listbox is not None:
            for row in range(listbox.count()):
                item = listbox.item(row)
                card = listbox.itemWidget(item) if item is not None else None
                if card is not None and hasattr(card, "_sync_card_style"):
                    card._sync_card_style()
        connect_card = getattr(frame, "_connect_card", None)
        if connect_card is not None:
            connect_card.setStyleSheet(
                self._connect_card_style(getattr(frame, "_device_layout_mode", None))
            )
        action_frame = getattr(frame, "_device_action_frame", None)
        if action_frame is not None:
            action_frame.setStyleSheet(self._action_card_style())
        badge = getattr(frame, "_discovery_badge", None)
        if badge is not None and badge.text():
            badge.setLevel(
                _DISCOVERY_BADGE_LEVELS.get(
                    getattr(frame, "_discovery_badge_kind", "empty"), InfoLevel.INFOAMTION
                )
            )
            self._sync_discovery_badge_geometry()

    def _apply_connect_card_style(self, mode: str) -> None:
        """按响应式模式切换连接卡片样式；相同模式不重复抛光，避免额外布局代次。"""

        frame = self._frame
        card = getattr(frame, "_connect_card", None)
        if card is None or getattr(frame, "_connect_card_mode", None) == mode:
            return
        frame._connect_card_mode = mode
        card.setStyleSheet(self._connect_card_style(mode))

    def _connect_card_style(self, mode) -> str:
        """连接区卡片 QSS；wide 保持零几何占位以维持与主体列宽对齐契约。"""

        bs = BaseStyles
        if mode == "wide":
            return "QFrame#connectCard { background: transparent; border: none; }"
        return (
            f"QFrame#connectCard {{"
            f" background-color: {bs.color('INPUT_BG')};"
            f" border: {_CONNECT_CARD_BORDER}px solid {bs.color('BORDER_COLOR')};"
            f" border-radius: {bs.RADIUS_LG}px;"
            f" padding: 6px {_CONNECT_CARD_PADDING_H}px; }}"
        )

    def _action_card_style(self) -> str:
        """动作区卡片 QSS：零边框零内边距，不改变动作网格度量契约。"""

        bs = BaseStyles
        return (
            f"QFrame#deviceActionCard {{"
            f" background-color: {bs.color('INPUT_BG')};"
            f" border: none;"
            f" border-radius: {bs.RADIUS_LG}px; }}"
        )

    def _sync_discovery_badge_geometry(self) -> None:
        """把发现状态徽标对齐到分组标题净空带右上角（浮层，不参与布局）。"""

        frame = self._frame
        badge = getattr(frame, "_discovery_badge", None)
        group = getattr(frame, "_device_group", None)
        # 仅对真实 QLabel 徽标做几何对齐：测试用 Mock 桩不应进入尺寸数学。
        if not isinstance(badge, QLabel) or group is None or not badge.text():
            return
        hint = badge.sizeHint()
        title_margin = BaseStyles.group_box_title_margin()
        badge_height = max(6, min(max(1, hint.height()), max(6, title_margin - 2)))
        badge_width = max(1, hint.width())
        badge.setGeometry(
            max(0, group.width() - badge_width - 12),
            max(1, (title_margin - badge_height) // 2),
            badge_width,
            badge_height,
        )
        badge.raise_()

    def _sync_device_card(self, item: QListWidgetItem, txt: str, info: dict) -> None:
        """创建或更新行卡片；条目文本仍是数据、提示与滚动契约的单一真源。"""

        listbox = self._frame.listbox_devices
        placeholder = str(info.get("Brand", "")) == "ADB" and str(
            info.get("Model", "")
        ) == "Detecting"
        badge_kind = "detecting" if placeholder else "ready"
        badge_text = "Detecting" if placeholder else "Ready"
        card = listbox.itemWidget(item)
        if card is None:
            card = _DeviceCardRow(txt, badge_text, badge_kind)
            card.setProperty("fontRole", FontRole.MONO.value)
            card.setFont(BaseStyles.font_for_role(FontRole.MONO))
            listbox.setItemWidget(item, card)
        else:
            card.set_device_text(txt)
            card.set_badge(badge_text, badge_kind)
        self._apply_device_card_styles()

    def set_discovery_state(self, state: str) -> None:
        """在设备分组标题中紧凑显示发现状态。"""

        state = str(state or "empty").lower()
        device_list = getattr(self._frame, "listbox_devices", None)
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
        self._frame._discovery_state = state
        title = f"Devices · {text}"
        self._frame._device_group.setTitle(title)
        self._frame._device_group.setAccessibleName(title)
        self._frame._device_group.setAccessibleDescription(description)
        self._frame._device_group.setToolTip(description)
        # 徽标只补充标题区视觉；状态字符串、标题与可访问文本契约均保持不变。
        badge_labels = {
            "scanning": ("Scanning", "scanning"),
            "empty": ("Empty", "empty"),
            "unavailable": ("Unavailable", "unavailable"),
            "ready": ("Connected", "ready"),
        }
        badge_text, badge_kind = badge_labels[state]
        badge = getattr(self._frame, "_discovery_badge", None)
        if badge is not None:
            badge.setText(badge_text)
            self._frame._discovery_badge_kind = badge_kind
            badge.setLevel(_DISCOVERY_BADGE_LEVELS.get(badge_kind, InfoLevel.INFOAMTION))
            self._sync_discovery_badge_geometry()

    def update_device_list(self, devices: list[str] | None = None):
        if devices is None:
            devices = []
        devices = list(dict.fromkeys(devices or []))
        prev = set(self._frame.selected_devices)
        blocker = QSignalBlocker(self._frame.listbox_devices)
        try:
            existing = self._frame._device_items_by_ip()
            device_set = set(devices)
            for ip, item in list(existing.items()):
                if ip not in device_set:
                    row = self._frame.listbox_devices.row(item)
                    if row >= 0:
                        self._frame.listbox_devices.takeItem(row)
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
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        self._frame.listbox_devices.addItem(item)
                    item.setText(txt)
                    item.setData(Qt.ItemDataRole.UserRole, info)
                    item.setCheckState(
                        Qt.CheckState.Checked if ip_addr in prev else Qt.CheckState.Unchecked
                    )
                    item.setToolTip(txt)
                    self._sync_device_card(item, txt, info)
        finally:
            del blocker
        self._frame.panel._connected_device_cache = devices
        self._frame.set_discovery_state("ready" if devices else "empty")
        self._update_action_states()
        # 项目增删会改变真实行高及横向滚动条占位，必须立即刷新 splitter 安全下限。
        self._frame.listbox_devices.doItemsLayout()
        update_minimums = getattr(self._frame, "_update_device_minimum_heights", None)
        if callable(update_minimums):
            update_minimums()
        request_reflow = getattr(self._frame.panel, "request_responsive_reflow", None)
        if callable(request_reflow):
            request_reflow(ReflowReason.EXPLICIT)

    def _update_action_states(self) -> None:
        """根据已连接和已勾选设备统一更新操作按钮状态。"""

        if not hasattr(self._frame, "listbox_devices"):
            return
        device_count = self._frame.listbox_devices.count()
        selected_devices = self._frame.selected_devices
        selected_count = len(selected_devices)
        has_devices = device_count > 0
        has_selection = selected_count > 0
        for button in filter(
            None,
            (
                getattr(self._frame, "btn_info", None),
                getattr(self._frame, "btn_disconnect", None),
                getattr(self._frame, "btn_restart_dev", None),
                getattr(self._frame, "btn_batch", None),
            ),
        ):
            button.setEnabled(has_selection)
            if has_selection:
                button.setToolTip(str(button.property("functionalToolTip") or ""))
            elif button is getattr(self._frame, "btn_info", None):
                button.setToolTip(
                    "Select a device first; device information is shown in the operation log"
                )
            else:
                button.setToolTip("Select a device first")
        select_all = getattr(self._frame, "btn_all", None)
        deselect_all = getattr(self._frame, "btn_none", None)
        if select_all is not None:
            select_all.setEnabled(has_devices and selected_count < device_count)
        if deselect_all is not None:
            deselect_all.setEnabled(has_selection)
        selection_changed = getattr(self._frame.panel, "selected_devices_changed", None)
        if selection_changed is not None:
            selection_changed.emit(selected_devices)

    def _device_items_by_ip(self) -> dict[str, QListWidgetItem]:
        items = {}
        for row in range(self._frame.listbox_devices.count()):
            item = self._frame.listbox_devices.item(row)
            info = item.data(Qt.ItemDataRole.UserRole) if item else None
            ip = info.get("ip", "") if isinstance(info, dict) else ""
            if ip:
                items[str(ip)] = item
        return items

    def _build_combo_view(self):
        model = QStandardItemModel(0, 3)
        model.setHorizontalHeaderLabels(["Brand", "Model", "IP"])
        self._frame._device_model = model
        tv = QTableView()
        tv.setModel(model)
        tv.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )  # 品牌列占剩余空间
        tv.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )  # 型号列占剩余空间
        tv.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )  # IP 列适应内容
        tv.verticalHeader().setVisible(False)
        tv.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tv.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tv.setShowGrid(False)
        tv.horizontalHeader().setHighlightSections(False)
        tv.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tv.setFont(self._frame._font_mono)
        tv.horizontalHeader().setFont(self._frame._font_mono)
        tv.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        tv.verticalHeader().setDefaultSectionSize(20)
        tv.setMaximumHeight(240)
        tv.setStyleSheet(
            "QTableView { border: none; }"
            "QHeaderView::section { padding: 2px 6px; font-weight: bold; }"
        )
        self._frame.ip_entry.setModel(model)
        self._frame.ip_entry.setModelColumn(2)
        self._frame.ip_entry.setView(tv)

    def _refresh_device_combobox(self):
        from gui.panels import device_manager as _device_manager_module

        if not hasattr(self._frame, "ip_entry"):
            return
        devs = DeviceStore.get_basic_devices_info()
        cache_key = tuple((str(brand), str(model), str(ip)) for brand, model, ip in devs)
        if cache_key == getattr(self._frame, "_device_combo_cache", None):
            return
        self._frame._device_combo_cache = cache_key
        self._frame._device_model.removeRows(0, self._frame._device_model.rowCount())
        ip_list = []
        for brand, model, ip in devs:
            ip_list.append(ip)
            self._frame._device_model.appendRow(
                [
                    QStandardItem(str(brand)),
                    QStandardItem(str(model)),
                    QStandardItem(str(ip)),
                ]
            )
        if ip_list:
            comp = _device_manager_module.QCompleter(ip_list, self._frame)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            self._frame.panel._apply_completer_style(comp)
            self._frame.ip_entry.setCompleter(comp)
            self._frame._sync_address_popup_width()
        self._frame.ip_entry.setCurrentIndex(-1)
        line_edit = self._frame.ip_entry.lineEdit()
        assert line_edit is not None  # stub Optional 收窄
        line_edit.clear()
        line_edit.setPlaceholderText("Select or type IP : Port")
        line_edit.setAccessibleName("Device address")

    def _on_ip_selected(self, i):
        if 0 <= i < self._frame._device_model.rowCount():
            ip_item = self._frame._device_model.item(i, 2)
            if ip_item:
                with BlockSignals(self._frame.ip_entry):
                    self._frame.ip_entry.setCurrentIndex(-1)
                    self._frame.ip_entry.setCurrentText(ip_item.text())
                self._frame.panel._user_selected_ip = True

    def _on_ip_edited(self, t):
        self._frame.panel._current_ip = t.strip()

    def _on_device_double_click(self, item):
        if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
