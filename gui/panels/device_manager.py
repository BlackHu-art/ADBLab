"""设备管理标签页 — 连接、设备列表、文字输入、截图、临时邮箱。"""

import unicodedata

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base_panel import BasePanel
from gui.panels.side_panel_signals import BlockSignals
from gui.styles.base_styles import BaseStyles
from models.adb_device import ADBDevice
from models.device_store import DeviceStore


class DeviceManager(BasePanel):
    """设备管理标签页。"""

    def build_ui(self) -> QWidget:
        w = QWidget()
        w.setObjectName("deviceManager")
        w.setAttribute(Qt.WA_StyledBackground, True)
        lo = QVBoxLayout(w)
        lo.setSpacing(3)
        lo.setContentsMargins(4, 4, 4, 4)

        # ── 设备管理 ──
        g_dev = self._g("Devices")
        gd_l = QVBoxLayout(g_dev)
        gd_l.setSpacing(2)

        # 连接行
        rc = QHBoxLayout()
        rc.setSpacing(4)
        self.ip_entry = self._combo()
        self.ip_entry.setEditable(True)
        self._build_column_view()
        self._refresh_device_combobox()
        self.ip_entry.currentIndexChanged.connect(self._on_ip_selected)
        self.ip_entry.editTextChanged.connect(self._on_ip_edited)
        self.btn_connect_devices = self._b("Connect", "Connect.svg")
        rc.addWidget(self.ip_entry, 3)
        rc.addWidget(self.btn_connect_devices, 1)
        gd_l.addLayout(rc)

        # 设备列表 + 右侧按钮
        body = QHBoxLayout()
        body.setSpacing(4)
        self.listbox_devices = QListWidget()
        self.listbox_devices.setObjectName("deviceList")
        self.listbox_devices.setFont(self._font_mono)
        self.listbox_devices.setEditTriggers(QListWidget.NoEditTriggers)
        self.listbox_devices.setSelectionBehavior(QListWidget.SelectRows)
        self.listbox_devices.setSelectionMode(QListWidget.MultiSelection)
        self.listbox_devices.setDragDropMode(QAbstractItemView.NoDragDrop)
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.listbox_devices.setSizePolicy(sp)
        self._apply_device_list_style()

        side = QFrame()
        sl = QVBoxLayout(side)
        sl.setSpacing(2)
        sl.setContentsMargins(0, 0, 0, 0)
        self.btn_refresh_devices = self._b("Refresh List", "Refresh.svg")
        self.btn_devices_Info = self._b("Device Info", "Info.svg")
        self.btn_disconnect_devices = self._b("Disconnect", "Disconnect.svg")
        self.btn_restart_devices = self._b("Restart Device", "Restart.svg")
        self.btn_restart_adb = self._b("Restart ADB", "Restore.svg", dc=True)
        self.btn_restart_adb.setToolTip("双击重启 ADB 服务")
        self.btn_batch_install = self._b("Batch Install APK", "Install_app.svg")
        self.btn_sel_all = self._qb("Select All")
        self.btn_sel_none = self._qb("Deselect All")
        for b in (
            self.btn_refresh_devices,
            self.btn_devices_Info,
            self.btn_disconnect_devices,
            self.btn_restart_devices,
            self.btn_restart_adb,
            self.btn_batch_install,
            self.btn_sel_all,
            self.btn_sel_none,
        ):
            sl.addWidget(b)
        sl.addStretch()
        body.addWidget(self.listbox_devices, 3)
        body.addWidget(side, 1)
        gd_l.addLayout(body)
        lo.addWidget(g_dev)
        return w

    def _apply_device_list_style(self):
        """设备列表统一样式。"""
        bs = BaseStyles
        self.listbox_devices.setStyleSheet(f"""QListWidget#deviceList{{
    background-color:{bs.color('INPUT_BG')};
    color:{bs.color('TEXT_PRIMARY')};
    border:1px solid {bs.color('BORDER_COLOR')};
    border-radius:{bs.RADIUS_MD}px;
    padding:2px;
    outline:none;
}}
QListWidget#deviceList::item{{
    padding:3px 6px;
    color:{bs.color('TEXT_PRIMARY')};
}}
QListWidget#deviceList::item:selected{{
    background-color:{bs.color('SELECTION_BG')};
    color:{bs.color('SELECTION_TEXT')};
}}
QListWidget#deviceList::item:hover{{
    background-color:{bs.color('BUTTON_HOVER')};
}}
QListWidget::indicator{{
    width:16px;height:16px;
}}
QListWidget::indicator:unchecked{{
    image:none;
    border:2px solid {bs.color('BORDER_COLOR')};
    border-radius:3px;
    background-color:{bs.color('INPUT_BG')};
}}
QListWidget::indicator:checked{{
    image:url(icons:Checkmark.svg);
    border:none;
}}""")

    # ── 设备列表操作 ──

    def update_device_list(self, devices: list[str] = None):
        """刷新设备列表，按品牌/型号/版本/IP 对齐显示。"""
        if devices is None:
            devices = ADBDevice.get_connected_devices_async()
        if not devices:
            return
        prev = set(self.selected_devices)
        self.listbox_devices.clear()
        self.panel._connected_device_cache = devices

        infos = DeviceStore.get_full_devices_info(devices)
        key_map = {"model": "Model", "brand": "Brand", "version": "Aversion", "ip": "ip"}
        ml = {"model": 0, "brand": 0, "version": 0, "ip": 0}
        for info in infos:
            for k in ml:
                ml[k] = max(ml[k], _display_width(str(info.get(key_map[k], "Unknown"))))
        for info in infos:
            mk = key_map
            m = _pad_str(str(info.get(mk["model"], "Unknown")), ml["model"])
            b = _pad_str(str(info.get(mk["brand"], "Unknown")), ml["brand"])
            v = _pad_str(str(info.get(mk["version"], "Unknown")), ml["version"])
            ip = _pad_str(str(info.get("ip", "")), ml["ip"])
            txt = f"  {m}  │  {b}  │  {v}  │  {ip}  "
            item = QListWidgetItem(txt)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if info.get("ip") in prev else Qt.Unchecked)
            item.setFont(self._font_mono)
            item.setData(Qt.UserRole, info)
            self.listbox_devices.addItem(item)

    def _build_column_view(self):
        """用 QTableView + QStandardItemModel 实现三列精准对齐下拉列表。"""
        model = QStandardItemModel(0, 3)
        model.setHorizontalHeaderLabels(["Brand", "Model", "IP"])
        self._device_model = model

        tv = QTableView()
        tv.setModel(model)
        tv.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tv.verticalHeader().setVisible(False)
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        tv.setSelectionMode(QAbstractItemView.SingleSelection)
        tv.setShowGrid(False)
        tv.horizontalHeader().setHighlightSections(False)
        tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tv.setFont(self._font_mono)
        tv.horizontalHeader().setFont(self._font_mono)
        tv.verticalHeader().setDefaultSectionSize(20)
        tv.setMinimumWidth(420)
        tv.setMaximumHeight(260)
        tv.setStyleSheet(
            "QTableView { border: none; }"
            "QHeaderView::section { padding: 2px 6px; font-weight: bold; }"
        )

        # 关键：把 model 同时设给 combo，这样选中行时 combo 能正确处理
        self.ip_entry.setModel(model)
        self.ip_entry.setModelColumn(2)
        self.ip_entry.setView(tv)

    def _refresh_device_combobox(self):
        if not hasattr(self, "ip_entry"):
            return

        devs = DeviceStore.get_basic_devices_info()

        self._device_model.removeRows(0, self._device_model.rowCount())

        if not devs:
            self.ip_entry.lineEdit().setPlaceholderText("No devices")
            return

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

        comp = QCompleter(ip_list, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.panel._apply_completer_style(comp)
        self.ip_entry.setCompleter(comp)

        self.ip_entry.setCurrentIndex(-1)
        self.ip_entry.lineEdit().clear()
        self.ip_entry.lineEdit().setPlaceholderText("Select or type IP:Port")

    def _on_ip_selected(self, i):
        if i >= 0 and i < self._device_model.rowCount():
            ip_item = self._device_model.item(i, 2)
            if ip_item:
                ip = ip_item.text()
                with BlockSignals(self.ip_entry):
                    self.ip_entry.setCurrentIndex(-1)
                    self.ip_entry.setCurrentText(ip)
                self.panel._user_selected_ip = True

    def _on_ip_edited(self, t):
        self.panel._current_ip = t.strip()

    def _on_device_double_click(self, item):
        if not (item.flags() & Qt.ItemIsUserCheckable):
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    @property
    def selected_devices(self) -> list[str]:
        return [
            self.listbox_devices.item(i).data(Qt.UserRole).get("ip", "")
            for i in range(self.listbox_devices.count())
            if self.listbox_devices.item(i).checkState() == Qt.Checked
        ]

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
                    item.setText(info.get("ip", "") + " | " + package_name)
                    apps_tab = getattr(self.panel, "_apps_tab", None)
                    if apps_tab:
                        apps_tab.add_package_to_history(package_name)
                    break

        QTimer.singleShot(0, _up)

    def connect_signals(self):
        """连接本地控件到 SidePanelSignals。"""
        LP = self.signals
        self.btn_connect_devices.clicked.connect(lambda: LP.connect_requested.emit(self.ip_address))
        self.btn_refresh_devices.clicked.connect(lambda: LP.refresh_devices_requested.emit())
        self.btn_devices_Info.clicked.connect(
            lambda: LP.device_info_requested.emit(self.selected_devices)
        )
        self.btn_disconnect_devices.clicked.connect(
            lambda: LP.disconnect_requested.emit(self.selected_devices)
        )
        self.btn_restart_devices.clicked.connect(
            lambda: LP.restart_devices_requested.emit(self.selected_devices)
        )
        self.btn_restart_adb.doubleClicked.connect(LP.restart_adb_requested.emit)
        self.btn_batch_install.clicked.connect(
            lambda: LP.batch_install_requested.emit(self.selected_devices)
        )
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_double_click)
        self.btn_sel_all.clicked.connect(
            lambda: [
                self.listbox_devices.item(i).setCheckState(Qt.Checked)
                for i in range(self.listbox_devices.count())
            ]
        )
        self.btn_sel_none.clicked.connect(
            lambda: [
                self.listbox_devices.item(i).setCheckState(Qt.Unchecked)
                for i in range(self.listbox_devices.count())
            ]
        )


# 模块级工具函数（供各标签页共用）


def _display_width(text):
    width = 0
    for ch in str(text):
        if unicodedata.east_asian_width(ch) in ("F", "W"):
            width += 2
        else:
            width += 1
    return width


def pad_display(text, width):
    text = str(text)
    pad = width - _display_width(text)
    return text + (" " * max(pad, 0))


def _pad_str(s: str, target_width: int) -> str:
    """将字符串填充到目标显示宽度（不足补空格）。"""
    cur = _display_width(s)
    return s + " " * (target_width - cur) if target_width > cur else s
