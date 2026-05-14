"""Device manager tab -- connect, device list, action buttons."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
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
from gui.styles import BaseStyles
from models.device_store import DeviceStore


class DeviceManager(BasePanel):
    """Device management tab."""

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

        # connect row
        rc = QHBoxLayout()
        rc.setSpacing(4)
        self.ip_entry = self._combo()
        self.ip_entry.setEditable(True)
        self._build_combo_view()
        self._refresh_device_combobox()
        self.ip_entry.currentIndexChanged.connect(self._on_ip_selected)
        self.ip_entry.editTextChanged.connect(self._on_ip_edited)
        self.btn_connect_devices = self._b("Connect", "plug.svg")
        rc.addWidget(self.ip_entry, 3)
        rc.addWidget(self.btn_connect_devices, 1)
        gd_l.addLayout(rc)

        # list + buttons
        body = QHBoxLayout()
        body.setSpacing(4)

        self.listbox_devices = QListWidget()
        self.listbox_devices.setObjectName("deviceList")
        self.listbox_devices.setEditTriggers(QListWidget.NoEditTriggers)
        self.listbox_devices.setSelectionBehavior(QListWidget.SelectRows)
        self.listbox_devices.setSelectionMode(QListWidget.MultiSelection)
        self.listbox_devices.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.listbox_devices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._apply_device_list_style()

        side = QFrame()
        sl = QVBoxLayout(side)
        sl.setSpacing(2)
        sl.setContentsMargins(0, 0, 0, 0)
        self.btn_refresh = self._b("Refresh", "arrows-clockwise.svg")
        self.btn_info = self._b("Device Info", "info.svg")
        self.btn_disconnect = self._b("Disconnect", "link-break.svg")
        self.btn_restart_dev = self._b("Restart", "arrow-counter-clockwise.svg")
        self.btn_restart_adb = self._db("ADB Server", "arrow-u-up-left.svg")
        self.btn_restart_adb.setToolTip("Double-click to restart ADB server")
        self.btn_batch = self._b("Batch Install", "stack-plus.svg")
        self.btn_all = self._b("Select All", "check-square.svg")
        self.btn_none = self._b("Deselect All", "square.svg")
        for b in (self.btn_refresh, self.btn_info, self.btn_disconnect,
                  self.btn_restart_dev, self.btn_restart_adb, self.btn_batch,
                  self.btn_all, self.btn_none):
            sl.addWidget(b)
        sl.addStretch()
        body.addWidget(self.listbox_devices, 3)
        body.addWidget(side, 1)
        gd_l.addLayout(body)
        lo.addWidget(g_dev)
        return w

    # -- style ------------------------------------------------------------

    def _apply_device_list_style(self):
        from core.settings_manager import AppSettings
        ui_size = AppSettings.instance().get("ui_font_size", 12)
        mono_size = max(8, ui_size - 2)
        font = QFont("Courier New", mono_size)
        font.setStyleHint(QFont.Monospace)
        self.listbox_devices.setFont(font)
        for i in range(self.listbox_devices.count()):
            item = self.listbox_devices.item(i)
            if item:
                item.setFont(font)
        self.listbox_devices.setStyleSheet(BaseStyles.DEVICE_LIST_STYLE())

    # -- device list ------------------------------------------------------

    def update_device_list(self, devices: list[str] = None):
        if devices is None:
            from models.adb_device import ADBDevice
            devices = ADBDevice.get_connected_devices_async()
        prev = set(self.selected_devices)
        self.listbox_devices.clear()
        if not devices:
            return
        self.panel._connected_device_cache = devices
        infos = DeviceStore.get_full_devices_info(devices)
        for info in infos:
            brand = str(info.get("Brand", ""))
            model = str(info.get("Model", ""))
            version = str(info.get("Aversion", ""))
            ip_addr = str(info.get("ip", ""))
            txt = f"{brand}  |  {model}  |  {version}  |  {ip_addr}"
            item = QListWidgetItem(txt)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if ip_addr in prev else Qt.Unchecked)
            item.setData(Qt.UserRole, info)
            self.listbox_devices.addItem(item)

    # -- combo dropdown ---------------------------------------------------

    def _build_combo_view(self):
        model = QStandardItemModel(0, 3)
        model.setHorizontalHeaderLabels(["Brand", "Model", "IP"])
        self._device_model = model
        tv = QTableView()
        tv.setModel(model)
        tv.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)  # Brand列 - 占剩余空间
        tv.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)  # Model列 - 占剩余空间
        tv.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)  # IP列 - 适应内容
        # tv.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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
        self._device_model.removeRows(0, self._device_model.rowCount())
        if not devs:
            self.ip_entry.lineEdit().setPlaceholderText("No devices")
            return
        ip_list = []
        for brand, model, ip in devs:
            ip_list.append(ip)
            self._device_model.appendRow([
                QStandardItem(str(brand)),
                QStandardItem(str(model)),
                QStandardItem(str(ip)),
            ])
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

    # -- selection --------------------------------------------------------

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

    # -- signals ----------------------------------------------------------

    def connect_signals(self):
        LP = self.signals
        self.btn_connect_devices.clicked.connect(lambda: LP.connect_requested.emit(self.ip_address))
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
