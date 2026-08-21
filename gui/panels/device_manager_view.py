"""提供 Devices 面板字体/样式应用、设备列表与下拉交互视图控制器。"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QListWidgetItem,
    QTableView,
)

from gui.panels.side_panel_signals import BlockSignals
from gui.styles import BaseStyles, FontRole
from gui.widgets.responsive_controller import ReflowReason
from models.device_store import DeviceStore


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
        view = self._frame.ip_entry.view()
        if view is not None:
            view.setFont(font)
            horizontal_header = getattr(view, "horizontalHeader", None)
            if callable(horizontal_header):
                horizontal_header().setFont(font)
        self._frame.panel._apply_completer_style(self._frame.ip_entry.completer())
        sync_heights = getattr(self._frame, "_sync_device_control_heights", None)
        update_minimums = getattr(self._frame, "_update_device_minimum_heights", None)
        if callable(sync_heights) and hasattr(self._frame, "_device_action_buttons"):
            sync_heights()
        if callable(update_minimums) and hasattr(self._frame, "_device_action_frame"):
            update_minimums()

    def _apply_device_list_style(self):
        self._frame.apply_fonts()
        self._frame.listbox_devices.setStyleSheet(BaseStyles.DEVICE_LIST_STYLE())

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

    def update_device_list(self, devices: list[str] = None):
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
                        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                        self._frame.listbox_devices.addItem(item)
                    item.setText(txt)
                    item.setData(Qt.UserRole, info)
                    item.setCheckState(Qt.Checked if ip_addr in prev else Qt.Unchecked)
                    item.setToolTip(txt)
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
            info = item.data(Qt.UserRole) if item else None
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
        tv.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)  # 品牌列占剩余空间
        tv.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)  # 型号列占剩余空间
        tv.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)  # IP 列适应内容
        tv.verticalHeader().setVisible(False)
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        tv.setSelectionMode(QAbstractItemView.SingleSelection)
        tv.setShowGrid(False)
        tv.horizontalHeader().setHighlightSections(False)
        tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tv.setFont(self._frame._font_mono)
        tv.horizontalHeader().setFont(self._frame._font_mono)
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
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            self._frame.panel._apply_completer_style(comp)
            self._frame.ip_entry.setCompleter(comp)
            self._frame._sync_address_popup_width()
        self._frame.ip_entry.setCurrentIndex(-1)
        self._frame.ip_entry.lineEdit().clear()
        self._frame.ip_entry.lineEdit().setPlaceholderText("Select or type IP : Port")
        self._frame.ip_entry.lineEdit().setAccessibleName("Device address")

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
        if not (item.flags() & Qt.ItemIsUserCheckable):
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
