"""提供 Devices 面板字体/样式应用、设备列表与下拉交互视图控制器。"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QSignalBlocker, QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidgetItem,
    QStyle,
    QStyleOptionViewItem,
    QWidget,
)
from qfluentwidgets import BodyLabel, InfoBadge, InfoLevel

from gui.panels.side_panel_signals import BlockSignals
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role
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
        self._content = QWidget(self)
        self._content.setObjectName("deviceCardContent")
        self._content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._info_label = apply_label_role(BodyLabel(text, self._content), FontRole.MONO)
        self._info_label.setObjectName("deviceCardText")
        self._info_label.setToolTip(text)
        self._info_label.setAccessibleDescription(text)
        self._badge = InfoBadge(self._content)
        self._badge.setText(badge_text)
        content_layout = QHBoxLayout(self._content)
        content_layout.setContentsMargins(4, 0, 4, 0)
        content_layout.setSpacing(6)
        content_layout.addWidget(self._info_label, 1)
        content_layout.addWidget(self._badge, 0)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(32, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self._content)
        self._sync_card_style()

    def set_check_indicator_gutter(self, width: int) -> None:
        """为列表原生勾选指示器保留透明且可点击的区域。"""

        margins = self._layout.contentsMargins()
        self._layout.setContentsMargins(max(0, int(width)), margins.top(), 0, margins.bottom())

    def set_device_text(self, text: str) -> None:
        """更新卡片信息文本（与条目文本保持同源）。"""

        self._info_label.setText(text)
        self._info_label.setToolTip(text)
        self._info_label.setAccessibleDescription(text)

    def set_badge(self, text: str, kind: str) -> None:
        """更新状态徽标文本与配色。"""

        self._badge.setText(text)
        self._badge_kind = kind
        self._sync_card_style()

    def _sync_card_style(self) -> None:
        """按当前主题重建行卡片与徽标样式。"""

        bs = BaseStyles
        self.setStyleSheet(
            "QWidget#deviceCard { background: transparent; }"
            f"QWidget#deviceCardContent {{ background-color: {bs.color('PANEL_BG')};"
            f" border-radius: {bs.RADIUS_SM}px; }}"
            f'QWidget#deviceCard[cardHovered="true"] QWidget#deviceCardContent {{'
            f" background-color: {bs.color('BUTTON_HOVER')}; }}"
        )
        self._badge.setLevel(
            InfoLevel.SUCCESS if self._badge_kind == "ready" else InfoLevel.WARNING
        )

    def sizeHint(self) -> QSize:
        """设备长文本不反向撑宽列表，仅保留当前行高。"""

        return QSize(0, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        """设备行允许水平收缩，完整信息由条目数据与提示保留。"""

        return QSize(0, super().minimumSizeHint().height())


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
        self._frame.ip_entry.setFont(font)
        sync_heights = getattr(self._frame, "_sync_device_control_heights", None)
        update_minimums = getattr(self._frame, "_update_device_minimum_heights", None)
        if callable(sync_heights) and hasattr(self._frame, "_device_action_buttons"):
            sync_heights()
        if callable(update_minimums) and hasattr(self._frame, "_device_action_frame"):
            update_minimums()
        self._sync_discovery_badge_geometry()

    def _apply_device_list_style(self):
        # 列表样式由 qfluentwidgets ListWidget 自维护，这里只刷新字体与设备卡片。
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
                if item is not None and card is not None and hasattr(card, "_sync_card_style"):
                    card._sync_card_style()
                    self._sync_device_card_indicator_gutter(item, card)
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
        """状态徽标由 HeaderCardWidget.headerLayout 自动管理。"""

        badge = getattr(self._frame, "_discovery_badge", None)
        if badge is not None:
            badge.updateGeometry()

    def _sync_device_card(self, item: QListWidgetItem, txt: str, info: dict) -> None:
        """创建或更新行卡片；条目文本仍是数据、提示与滚动契约的单一真源。"""

        listbox = self._frame.listbox_devices
        placeholder = (
            str(info.get("Brand", "")) == "ADB" and str(info.get("Model", "")) == "Detecting"
        )
        badge_kind = "detecting" if placeholder else "ready"
        badge_text = "检测中" if placeholder else "就绪"
        card = listbox.itemWidget(item)
        if card is None:
            card = _DeviceCardRow(txt, badge_text, badge_kind)
            card.setProperty("fontRole", FontRole.MONO.value)
            card.setFont(BaseStyles.font_for_role(FontRole.MONO))
            listbox.setItemWidget(item, card)
        else:
            card.set_device_text(txt)
            card.set_badge(badge_text, badge_kind)
        self._sync_device_card_indicator_gutter(item, card)
        self._apply_device_card_styles()

    def _sync_device_card_indicator_gutter(
        self,
        item: QListWidgetItem,
        card: _DeviceCardRow,
    ) -> None:
        """让不透明卡片内容从原生勾选框右侧开始绘制。"""

        listbox = self._frame.listbox_devices
        option = QStyleOptionViewItem()
        listbox.initViewItemOption(option)
        # PySide6 类型桩未公开这些 ViewItem 字段，运行时由 Qt 提供。
        runtime_option = cast(Any, option)
        runtime_option.rect = listbox.visualItemRect(item)
        runtime_option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        runtime_option.checkState = item.checkState()
        check_rect = listbox.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            option,
            listbox,
        )
        card_left = card.geometry().left()
        gutter = max(32, check_rect.right() - card_left + 4)
        card.set_check_indicator_gutter(gutter)

    def set_discovery_state(self, state: str) -> None:
        """在设备分组标题中紧凑显示发现状态。"""

        state = str(state or "empty").lower()
        device_list = getattr(self._frame, "listbox_devices", None)
        device_count = device_list.count() if device_list is not None else 0
        descriptions = {
            "scanning": ("扫描中…", "正在扫描 Android 设备"),
            "empty": ("无设备", "当前没有已连接的 Android 设备"),
            "unavailable": (
                "ADB 不可用",
                "ADB 当前不可用，请检查程序和服务后刷新",
            ),
            "ready": (
                f"已连接 {device_count} 台",
                f"当前有 {device_count} 台 Android 设备可用",
            ),
        }
        if state not in descriptions:
            state = "empty"
        text, description = descriptions[state]
        title = "设备与连接"
        self._frame._device_group.setTitle(title)
        self._frame._device_group.setAccessibleName(f"{title}: {text}")
        self._frame._device_group.setAccessibleDescription(description)
        self._frame._device_group.setToolTip(description)
        # 徽标只补充标题区视觉；状态字符串、标题与可访问文本契约均保持不变。
        badge_labels = {
            "scanning": ("扫描中", "scanning"),
            "empty": ("无设备", "empty"),
            "unavailable": ("不可用", "unavailable"),
            "ready": ("已连接", "ready"),
        }
        badge_text, badge_kind = badge_labels[state]
        badge = getattr(self._frame, "_discovery_badge", None)
        if badge is not None:
            badge.setText(badge_text)
            self._frame._discovery_badge_kind = badge_kind
            badge.setLevel(_DISCOVERY_BADGE_LEVELS.get(badge_kind, InfoLevel.INFOAMTION))
            self._sync_discovery_badge_geometry()
        refresh_button = getattr(self._frame, "btn_refresh", None)
        if refresh_button is not None:
            scanning = state == "scanning"
            refresh_button.setEnabled(not scanning)
            tooltip = (
                "正在扫描已连接的 Android 设备"
                if scanning
                else str(refresh_button.property("functionalToolTip") or "扫描已连接设备")
            )
            refresh_button.setToolTip(tooltip)
            refresh_button.setAccessibleDescription(tooltip)

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
                button.setToolTip("请先选择设备；设备信息会显示在操作日志中")
            else:
                button.setToolTip("请先选择设备")
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
        """配置参考组件自己的弹出菜单，不再注入原生表格模型。"""

        self._frame.ip_entry.setMaxVisibleItems(8)
        self._frame.ip_entry.setPlaceholderText("选择或输入 IP:端口")

    def _refresh_device_combobox(self):
        if not hasattr(self._frame, "ip_entry"):
            return
        devs = DeviceStore.get_basic_devices_info()
        cache_key = tuple((str(brand), str(model), str(ip)) for brand, model, ip in devs)
        if cache_key == getattr(self._frame, "_device_combo_cache", None):
            return
        self._frame._device_combo_cache = cache_key
        combo = self._frame.ip_entry
        current_text = combo.currentText()
        cursor_position = combo.cursorPosition()
        with BlockSignals(combo):
            while combo.count():
                combo.removeItem(combo.count() - 1)
            for brand, model, ip in devs:
                label = " · ".join(part for part in (str(brand), str(model), str(ip)) if part)
                combo.addItem(label, userData=str(ip))
            combo.setCurrentIndex(-1)
            combo.setText(current_text)
            combo.setCursorPosition(min(cursor_position, len(current_text)))
        combo.setPlaceholderText("选择或输入 IP:端口")
        combo.setAccessibleName("设备地址")

    def _on_ip_selected(self, i):
        combo = self._frame.ip_entry
        if 0 <= i < combo.count():
            ip = str(combo.itemData(i) or "").strip()
            if ip:
                with BlockSignals(combo):
                    combo.setCurrentIndex(-1)
                    combo.setText(ip)
                self._frame.panel._user_selected_ip = True

    def _on_device_double_click(self, item):
        if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
