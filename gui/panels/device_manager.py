"""提供设备连接、发现、选择和基础操作面板。"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QComboBox,
    QFrame,
    QGridLayout,
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
from gui.styles import BaseStyles, FontRole
from models.device_store import DeviceStore
from utils.adb_targets import normalize_adb_connect_target


class DeviceManager(BasePanel):
    """维护设备列表展示，并向统一信号层转发设备操作。"""

    def build_ui(self) -> QWidget:
        w = QWidget()
        w.setObjectName("deviceManager")
        w.setAttribute(Qt.WA_StyledBackground, True)
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)

        g_dev = self._g("Devices")
        gd_l = QVBoxLayout(g_dev)
        gd_l.setSpacing(2)

        rc = QHBoxLayout()
        rc.setSpacing(4)
        self.ip_entry = self._combo_editable()
        self.ip_entry.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._build_combo_view()
        self._refresh_device_combobox()
        self.ip_entry.currentIndexChanged.connect(self._on_ip_selected)
        self.ip_entry.editTextChanged.connect(self._on_ip_edited)
        self.btn_connect_devices = self._b("Connect", "plug.svg")
        rc.addWidget(self.ip_entry, 3)
        rc.addWidget(self.btn_connect_devices, 1)
        gd_l.addLayout(rc)

        body = QGridLayout()
        body.setSpacing(4)
        body.setContentsMargins(0, 0, 0, 0)
        self._device_body_layout = body

        self.listbox_devices = QListWidget()
        self.listbox_devices.setObjectName("deviceList")
        self.listbox_devices.setEditTriggers(QListWidget.NoEditTriggers)
        self.listbox_devices.setSelectionBehavior(QListWidget.SelectRows)
        self.listbox_devices.setSelectionMode(QListWidget.MultiSelection)
        self.listbox_devices.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.listbox_devices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._apply_device_list_style()

        side = QFrame()
        sl = QGridLayout(side)
        sl.setSpacing(2)
        sl.setContentsMargins(0, 0, 0, 0)
        self._device_actions_layout = sl
        self.btn_refresh = self._b("Refresh", "arrows-clockwise.svg")
        self.btn_info = self._b("Device Info", "info.svg")
        self.btn_disconnect = self._b("Disconnect", "link-break.svg")
        self.btn_restart_dev = self._b("Restart", "arrow-counter-clockwise.svg")
        self.btn_restart_adb = self._db("ADB Server", "arrow-u-up-left.svg")
        self.btn_restart_adb.setToolTip("Double-click to restart ADB server")
        self.btn_batch = self._b("Batch Install", "stack-plus.svg")
        self.btn_all = self._b("Select All", "check-square.svg")
        self.btn_none = self._b("Deselect All", "square.svg")
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
        self._device_action_frame = side
        body.addWidget(self.listbox_devices, 0, 0)
        body.addWidget(side, 0, 1)
        body.setColumnStretch(0, 3)
        body.setColumnStretch(1, 1)
        self.apply_responsive_width(360)
        gd_l.addLayout(body)
        lo.addWidget(g_dev)
        return w

    def apply_responsive_width(self, width: int) -> None:
        """根据左栏宽度切换设备列表与操作按钮的排布。"""

        compact = int(width) < 360
        mode = "compact" if compact else "wide"
        if getattr(self, "_device_layout_mode", None) == mode:
            return
        self._device_layout_mode = mode

        body = self._device_body_layout
        body.removeWidget(self.listbox_devices)
        body.removeWidget(self._device_action_frame)
        actions = self._device_actions_layout
        while actions.count():
            actions.takeAt(0)

        if compact:
            body.addWidget(self.listbox_devices, 0, 0, 1, 2)
            body.addWidget(self._device_action_frame, 1, 0, 1, 2)
            for index, button in enumerate(self._device_action_buttons):
                row, column = divmod(index, 2)
                actions.addWidget(button, row, column)
                actions.setColumnStretch(column, 1)
            actions.setRowStretch(len(self._device_action_buttons), 0)
            body.setColumnStretch(0, 1)
            body.setColumnStretch(1, 1)
        else:
            body.addWidget(self.listbox_devices, 0, 0)
            body.addWidget(self._device_action_frame, 0, 1)
            for row, button in enumerate(self._device_action_buttons):
                actions.addWidget(button, row, 0)
            actions.setColumnStretch(0, 1)
            actions.setColumnStretch(1, 0)
            actions.setRowStretch(len(self._device_action_buttons), 1)
            body.setColumnStretch(0, 3)
            body.setColumnStretch(1, 1)

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

    def _apply_device_list_style(self):
        self.apply_fonts()
        self.listbox_devices.setStyleSheet(BaseStyles.DEVICE_LIST_STYLE())

    # ── 设备列表 ────────────────────────────────────────────────────────

    def update_device_list(self, devices: list[str] = None):
        if devices is None:
            devices = []
        devices = list(dict.fromkeys(devices or []))
        prev = set(self.selected_devices)
        existing = self._device_items_by_ip()
        device_set = set(devices)
        for ip, item in list(existing.items()):
            if ip not in device_set:
                row = self.listbox_devices.row(item)
                if row >= 0:
                    self.listbox_devices.takeItem(row)
        if not devices:
            self.panel._connected_device_cache = []
            return
        self.panel._connected_device_cache = devices
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
            item.setCheckState(Qt.Checked if ip_addr in prev else Qt.Unchecked)
            item.setData(Qt.UserRole, info)
            item.setToolTip(txt)

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
        tv.setMinimumWidth(380)
        tv.setMaximumHeight(240)
        tv.setStyleSheet("QTableView { border: none; }"
                         "QHeaderView::section { padding: 2px 6px; font-weight: bold; }")
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
            self._device_model.appendRow([
                QStandardItem(str(brand)),
                QStandardItem(str(model)),
                QStandardItem(str(ip)),
            ])
        if ip_list:
            comp = QCompleter(ip_list, self)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            self.panel._apply_completer_style(comp)
            self.ip_entry.setCompleter(comp)
        self.ip_entry.setCurrentIndex(-1)
        self.ip_entry.lineEdit().clear()
        self.ip_entry.lineEdit().setPlaceholderText("Select or type IP : Port")

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

    def connect_signals(self):
        LP = self.signals
        self.btn_connect_devices.clicked.connect(self._request_connect)
        line_edit = self.ip_entry.lineEdit()
        if line_edit:
            line_edit.returnPressed.connect(self._request_connect)
        self.btn_refresh.clicked.connect(lambda: LP.refresh_devices_requested.emit())
        self.btn_info.clicked.connect(lambda: LP.device_info_requested.emit(self.selected_devices))
        self.btn_disconnect.clicked.connect(lambda: LP.disconnect_requested.emit(self.selected_devices))
        self.btn_restart_dev.clicked.connect(lambda: LP.restart_devices_requested.emit(self.selected_devices))
        self.btn_restart_adb.doubleClicked.connect(LP.restart_adb_requested.emit)
        self.btn_batch.clicked.connect(lambda: LP.batch_install_requested.emit(self.selected_devices))
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_double_click)
        self.btn_all.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_none.clicked.connect(lambda: self._set_all_checked(False))

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.listbox_devices.count()):
            self.listbox_devices.item(i).setCheckState(state)
