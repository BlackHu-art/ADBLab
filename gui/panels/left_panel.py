"""
Left control panel for ADBLab.

Contains three grouped sections (Device Management, Actions, Performance)
with buttons, inputs, and a device list. Emits signals via LeftPanelSignals
for all operations, which are wired to ADBController in main_frame.py.
"""

from typing import List, Union
from PySide6.QtCore import Qt, Slot, QTimer, QSize
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QAbstractItemView,
    QLineEdit, QCompleter, QLabel
)
from gui.styles.base_styles import get_default_font, BaseStyles
from models.device_store import DeviceStore
from contextlib import contextmanager
from gui.panels.left_panel_signals import LeftPanelSignals
from gui.widgets.double_click_button import DoubleClickButton
from models.adb_device import ADBDevice


@contextmanager
def BlockSignals(widget):
    """Context manager to safely block/unblock widget signals."""
    widget.blockSignals(True)
    try:
        yield
    finally:
        widget.blockSignals(False)


class LeftPanel(QWidget):
    """Main control panel with device list, action buttons, and perf tools."""

    PANEL_WIDTH = 600
    GROUP_TITLES = ("Device Management", "Actions", "Performance")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = LeftPanelSignals()
        self.connected_device_cache = []
        self.package_history = []
        self._user_selected_ip = False

        self._init_ui_settings()
        self._create_ui_components()
        self._connect_signals()

    def _init_ui_settings(self):
        self.setFixedWidth(self.PANEL_WIDTH)
        self._base_font = get_default_font()
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        BaseStyles.theme_changed.connect(self._on_theme_changed)

    def _create_ui_components(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(3)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._create_device_group())
        layout.addWidget(self._create_actions_group())
        layout.addWidget(self._create_performance_group())
        layout.addStretch()

    def _apply_completer_popup_style(self, completer):
        """Style a QCompleter popup with current theme colors."""
        if completer is None:
            return
        popup = completer.popup()
        if popup is None:
            return
        popup.setFont(QFont("Courier New", self._base_font.pointSize()))
        popup.setStyleSheet(f"""
            QListView {{
                background-color: {BaseStyles.color('INPUT_BG')};
                color: {BaseStyles.color('TEXT_PRIMARY')};
                border: 1px solid {BaseStyles.color('BORDER_COLOR')};
                border-radius: {BaseStyles.RADIUS_SM}px;
                padding: 2px;
                outline: none;
                font-family: 'Courier New', monospace;
            }}
            QListView::item {{
                padding: 4px 8px;
                color: {BaseStyles.color('TEXT_PRIMARY')};
            }}
            QListView::item:selected {{
                background-color: {BaseStyles.color('SELECTION_BG')};
                color: {BaseStyles.color('SELECTION_TEXT')};
            }}
            QListView::item:hover {{
                background-color: {BaseStyles.color('BUTTON_HOVER')};
            }}
        """)

    def _apply_device_list_style(self):
        """Apply explicit theme-aware stylesheet to device list widget."""
        self.listbox_devices.setStyleSheet(f"""
            QListWidget#deviceList {{
                background-color: {BaseStyles.color('INPUT_BG')};
                color: {BaseStyles.color('TEXT_PRIMARY')};
                border: 1px solid {BaseStyles.color('BORDER_COLOR')};
                border-radius: {BaseStyles.RADIUS_MD}px;
                padding: 2px;
                font-family: 'Courier New';
                font-size: 9px;
                outline: none;
            }}
            QListWidget#deviceList::item {{
                padding: 3px 6px;
                border-radius: {BaseStyles.RADIUS_SM}px;
                color: {BaseStyles.color('TEXT_PRIMARY')};
            }}
            QListWidget#deviceList::item:selected {{
                background-color: {BaseStyles.color('SELECTION_BG')};
                color: {BaseStyles.color('SELECTION_TEXT')};
            }}
            QListWidget#deviceList::item:hover {{
                background-color: {BaseStyles.color('BUTTON_HOVER')};
            }}
        """)

    def _on_theme_changed(self, _name: str):
        """Re-apply panel and group-box styles on theme switch."""
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        for group in self.findChildren(QGroupBox):
            group.setStyleSheet(BaseStyles.GROUP_BOX_STYLE())
        self._apply_device_list_style()
        # Re-style completer popups (may not exist yet on first theme change)
        if hasattr(self, 'ip_entry'):
            self._apply_completer_popup_style(self.ip_entry.completer())
        if hasattr(self, 'completer'):
            self._apply_completer_popup_style(self.completer)

    def _connect_signals(self):
        # Device management buttons
        self.btn_connect_devices.clicked.connect(lambda: self.signals.connect_requested.emit(self.ip_address))
        self.btn_refresh_devices.clicked.connect(lambda: self.signals.refresh_devices_requested.emit())
        self.btn_devices_Info.clicked.connect(lambda: self.signals.device_info_requested.emit(self.selected_devices))
        self.btn_disconnect_devices.clicked.connect(lambda: self.signals.disconnect_requested.emit(self.selected_devices))
        self.btn_restart_devices.clicked.connect(lambda: self.signals.restart_devices_requested.emit(self.selected_devices))
        self.btn_restart_adb.doubleClicked.connect(self.signals.restart_adb_requested.emit)
        self.btn_screenshot.clicked.connect(lambda: self.signals.screenshot_requested.emit(self.selected_devices))
        self.btn_retrieve_devices_logs.clicked.connect(lambda: self.signals.retrieve_logs_requested.emit(self.selected_devices))
        self.btn_cleanup_logs.clicked.connect(lambda: self.signals.cleanup_logs_requested.emit(self.selected_devices))
        self.btn_send_text.clicked.connect(lambda: self.signals.send_text_requested.emit(self.selected_devices, self.input_text_edit.text()))
        self.input_text_edit.returnPressed.connect(lambda: self.signals.send_text_requested.emit(self.selected_devices, self.input_text_edit.text()))
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_double_click)
        self.btn_get_program.clicked.connect(lambda: self.signals.get_program_requested.emit(self.selected_devices))
        self.btn_install_app.clicked.connect(lambda: self.signals.install_app_requested.emit(self.selected_devices))
        self.uninstall_btn.clicked.connect(lambda: self.signals.uninstall_app_requested.emit(self.selected_devices, self.program_edit.currentText()))
        self.clear_app_data_btn.clicked.connect(lambda: self.signals.clear_app_data_requested.emit(self.selected_devices, self.program_edit.currentText()))
        self.restart_app_btn.clicked.connect(lambda: self.signals.restart_app_requested.emit(self.selected_devices, self.program_edit.currentText()))
        self.print_activity_btn.clicked.connect(lambda: self.signals.print_activity_requested.emit(self.selected_devices))
        self.parse_apk_info_btn.clicked.connect(lambda: self.signals.parse_apk_info_requested.emit())
        self.start_monkey_btn.clicked.connect(lambda: self.signals.start_monkey_requested.emit(self.selected_devices, self.device_type.currentText(), self.program_edit.currentText(), self.select_times.currentText()))
        self.kill_monkey_btn.clicked.connect(lambda: self.signals.kill_monkey_requested.emit(self.selected_devices))
        self.list_package_btn.clicked.connect(lambda: self.signals.list_installed_packages_requested.emit(self.selected_devices))
        self.get_bugreport_btn.clicked.connect(lambda: self.signals.capture_bugreport_requested.emit(self.selected_devices))
        self.get_anr_file_btn.clicked.connect(lambda: self.signals.pull_anr_file_requested.emit(self.selected_devices))

        self.btn_generate_email.clicked.connect(lambda: self.signals.generate_email_requested.emit())
        self.email_text_sender.returnPressed.connect(lambda: self.signals.send_text_requested.emit(self.selected_devices, self.email_text_sender.text()))
        self.verfication_text_sender.returnPressed.connect(lambda: self.signals.send_text_requested.emit(self.selected_devices, self.verfication_text_sender.text()))

    # ── Group builders ──────────────────────────────────────────────────

    def _create_device_group(self) -> QGroupBox:
        """Build the Device Management group: IP input, device list, action buttons."""
        group = QGroupBox(self.GROUP_TITLES[0])
        group.setFont(self._base_font)
        group.setStyleSheet(BaseStyles.GROUP_BOX_STYLE())

        main_layout = QVBoxLayout()
        main_layout.setSpacing(3)

        # IP input + Connect
        ip_row = QHBoxLayout()
        ip_row.setSpacing(3)
        self.ip_entry = QComboBox()
        self.ip_entry.setEditable(True)
        self.ip_entry.setFont(self._base_font)
        self._refresh_device_combobox()
        self.ip_entry.currentIndexChanged.connect(self._on_ip_selected)
        self.ip_entry.editTextChanged.connect(self._on_ip_edited)
        self.ip_entry.completer().activated.connect(lambda text: self._on_ip_selected_completer(text))
        self.btn_connect_devices = self._create_button("Connect", "resources/icons/Connect.svg")
        ip_row.addWidget(self.ip_entry, 2)
        ip_row.addWidget(self.btn_connect_devices, 1)
        main_layout.addLayout(ip_row)

        # Device list + buttons
        device_row = QHBoxLayout()
        device_row.setSpacing(3)
        self.listbox_devices = QListWidget()
        self.listbox_devices.setObjectName("deviceList")
        self.listbox_devices.setEditTriggers(QListWidget.NoEditTriggers)
        self.listbox_devices.setSelectionBehavior(QListWidget.SelectRows)
        self.listbox_devices.setSelectionMode(QListWidget.MultiSelection)
        self.listbox_devices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.listbox_devices.setFont(self._base_font)
        self.listbox_devices.setMinimumHeight(120)
        self.listbox_devices.setProperty("showDropIndicator", False)
        self.listbox_devices.setDragDropMode(QAbstractItemView.NoDragDrop)
        self._apply_device_list_style()

        button_panel = QFrame()
        button_layout = QVBoxLayout(button_panel)
        button_layout.setSpacing(2)
        button_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_refresh_devices = self._create_button("Refresh", "resources/icons/Refresh.svg")
        self.btn_devices_Info = self._create_button("Device Info", "resources/icons/Info.svg")
        self.btn_disconnect_devices = self._create_button("Disconnect", "resources/icons/Disconnect.svg")
        self.btn_restart_devices = self._create_button("Restart Devices", "resources/icons/Restart.svg")
        self.btn_restart_adb = self._create_button("Restart ADB", "resources/icons/Restore.svg", double_click=True)
        self.btn_restart_adb.setToolTip("Double click to restart")
        self.btn_screenshot = self._create_button("Screenshot", "resources/icons/Screenshot.svg")
        self.btn_screenshot.setToolTip("Select a file save path once")
        self.btn_retrieve_devices_logs = self._create_button("Retrieve device logs", "resources/icons/Save_alt.svg")
        self.btn_cleanup_logs = self._create_button("Cleanup logs", "resources/icons/Cleaning_services.svg")
        for b in (self.btn_refresh_devices, self.btn_devices_Info, self.btn_disconnect_devices,
                  self.btn_restart_devices, self.btn_restart_adb, self.btn_screenshot,
                  self.btn_retrieve_devices_logs, self.btn_cleanup_logs):
            button_layout.addWidget(b)
        button_layout.addStretch()

        device_row.addWidget(self.listbox_devices, 2)
        device_row.addWidget(button_panel, 1)
        main_layout.addLayout(device_row)

        # Bottom input rows
        last_row = QVBoxLayout()
        last_row.setSpacing(3)
        last_row1 = QHBoxLayout()
        last_row1.setSpacing(3)
        self.btn_send_text = self._create_button("Send txt to devices", "resources/icons/Input.svg")
        self.input_text_edit = QLineEdit()
        self.input_text_edit.setFont(self._base_font)
        self.input_text_edit.setPlaceholderText("Input text here, Press Enter to send")
        last_row1.addWidget(self.btn_send_text, 1)
        last_row1.addWidget(self.input_text_edit, 2)
        last_row.addLayout(last_row1)

        last_row2 = QHBoxLayout()
        last_row2.setSpacing(3)
        self.btn_generate_email = self._create_button("Generate Email", "resources/icons/Email.svg")
        self.email_text_sender = QLineEdit()
        self.email_text_sender.setFont(self._base_font)
        self.email_text_sender.setPlaceholderText("Generate Email")
        self.verfication_text_sender = QLineEdit()
        self.verfication_text_sender.setFont(self._base_font)
        self.verfication_text_sender.setPlaceholderText("verification code")
        last_row2.addWidget(self.btn_generate_email, 1)
        last_row2.addWidget(self.email_text_sender, 1)
        last_row2.addWidget(self.verfication_text_sender, 1)
        last_row.addLayout(last_row2)

        main_layout.addLayout(last_row)
        group.setLayout(main_layout)
        return group

    def _create_actions_group(self) -> QGroupBox:
        """Build the Actions group: package selector, install/uninstall/clear/restart."""
        group = QGroupBox(self.GROUP_TITLES[1])
        group.setFont(self._base_font)
        group.setStyleSheet(BaseStyles.GROUP_BOX_STYLE())
        layout = QVBoxLayout()
        layout.setSpacing(3)

        action_row1 = QHBoxLayout()
        action_row1.setSpacing(3)
        self.program_edit = QComboBox()
        self.program_edit.setEditable(True)
        self.program_edit.setFont(self._base_font)
        self.program_edit.lineEdit().setPlaceholderText("Select or input package name")
        self.completer = QCompleter(self.package_history)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._apply_completer_popup_style(self.completer)
        self.program_edit.setCompleter(self.completer)
        self.btn_get_program = self._create_button("Get current program", "resources/icons/Select_activity.svg")
        action_row1.addWidget(self.program_edit, 2)
        action_row1.addWidget(self.btn_get_program, 1)
        layout.addLayout(action_row1)

        action_row2 = QHBoxLayout()
        action_row2.setSpacing(3)
        self.btn_install_app = self._create_button("Install App", "resources/icons/Install_App.svg")
        self.uninstall_btn = self._create_button("Uninstall App", "resources/icons/Uninstall_app.svg")
        self.clear_app_data_btn = self._create_button("Clear App Data", "resources/icons/Clear_data.svg")
        for btn in (self.btn_install_app, self.uninstall_btn, self.clear_app_data_btn):
            action_row2.addWidget(btn, 1)
        layout.addLayout(action_row2)

        action_row3 = QHBoxLayout()
        action_row3.setSpacing(3)
        self.restart_app_btn = self._create_button("Restart App", "resources/icons/Restart_app.svg")
        self.print_activity_btn = self._create_button("Print Current Activity", "resources/icons/Print.svg")
        self.parse_apk_info_btn = self._create_button("Parse APK Info", "resources/icons/Parse_APK.svg")
        for btn in (self.restart_app_btn, self.print_activity_btn, self.parse_apk_info_btn):
            action_row3.addWidget(btn, 1)
        layout.addLayout(action_row3)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def _create_performance_group(self) -> QGroupBox:
        """Build the Performance group: monkey test, bugreport, ANR tools."""
        group = QGroupBox(self.GROUP_TITLES[2])
        group.setFont(self._base_font)
        group.setStyleSheet(BaseStyles.GROUP_BOX_STYLE())
        layout = QVBoxLayout()
        layout.setSpacing(3)

        perf_row1 = QHBoxLayout()
        perf_row1.setSpacing(3)
        self.device_type = QComboBox()
        self.device_type.addItems(["STB", "Mobile"])
        self.device_type.setToolTip("Select Device Type")
        self.device_type.setFont(self._base_font)
        self.select_times = QComboBox()
        self.select_times.addItems(["100", "10000", "100000", "500000"])
        self.select_times.setCurrentIndex(0)
        self.select_times.setFont(self._base_font)
        self.select_times.setToolTip("Select the number of times to run")
        self.start_monkey_btn = self._create_button("Start Monkey", "resources/icons/Monkey.svg")
        perf_row1.addWidget(self.device_type, 1)
        perf_row1.addWidget(self.select_times, 1)
        perf_row1.addWidget(self.start_monkey_btn, 1)
        layout.addLayout(perf_row1)

        perf_row2 = QHBoxLayout()
        perf_row2.setSpacing(3)
        self.kill_monkey_btn = self._create_button("Kill Monkey", "resources/icons/Kill_monkey.svg")
        self.list_package_btn = self._create_button("Packages List", "resources/icons/format_list_bulleted.svg")
        self.get_bugreport_btn = self._create_button("Capture Bugreport", "resources/icons/bugreport.svg")
        for btn in (self.kill_monkey_btn, self.list_package_btn, self.get_bugreport_btn):
            perf_row2.addWidget(btn, 1)
        layout.addLayout(perf_row2)

        perf_row3 = QHBoxLayout()
        perf_row3.setSpacing(3)
        self.get_anr_file_btn = self._create_button("Get ANR File", "resources/icons/Get_ANR.svg")
        perf_btn2 = self._create_button("Print", "resources/icons/Print.svg")
        perf_btn3 = self._create_button("Parse", "resources/icons/Parse_APK.svg")
        for btn in (self.get_anr_file_btn, perf_btn2, perf_btn3):
            perf_row3.addWidget(btn, 1)
        layout.addLayout(perf_row3)

        layout.addStretch()
        group.setLayout(layout)
        return group

    # ── Button factory ──────────────────────────────────────────────────

    def _create_button(self, text: str, icon_path: str = None, double_click: bool = False) -> Union[QPushButton, DoubleClickButton]:
        """Create a standard action button with icon and optional double-click support."""
        btn = DoubleClickButton(text) if double_click else QPushButton(text)
        btn.setFont(self._base_font)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if icon_path:
            btn.setIcon(QIcon(icon_path))
            btn.setIconSize(QSize(16, 16))
        return btn

    # ── Device list ─────────────────────────────────────────────────────

    def update_device_list(self, devices: List[str] = None):
        if devices is None:
            devices = ADBDevice.get_connected_devices_async()
            if not devices:
                return

        previously_selected_ips = set(self.selected_devices)

        self.listbox_devices.clear()
        self.connected_device_cache = devices

        device_info_list = DeviceStore.get_full_devices_info(devices)

        max_lengths = {'model': 0, 'brand': 0, 'version': 0, 'ip': 0}
        for info in device_info_list:
            max_lengths['model'] = max(max_lengths['model'], len(info.get('Model', 'Unknown')))
            max_lengths['brand'] = max(max_lengths['brand'], len(info.get('Brand', 'Unknown')))
            max_lengths['version'] = max(max_lengths['version'], len(info.get('Aversion', 'Unknown')))
            max_lengths['ip'] = max(max_lengths['ip'], len(info.get('ip', '')))

        for info in device_info_list:
            model = info.get('Model', 'Unknown').ljust(max_lengths['model'])
            brand = info.get('Brand', 'Unknown').ljust(max_lengths['brand'])
            version = info.get('Aversion', 'Unknown').ljust(max_lengths['version'])
            ip = info.get('ip', '').ljust(max_lengths['ip'])

            display = f"{model} | {brand} | {version} | {ip}"
            item = QListWidgetItem(display)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)

            if info.get('ip') in previously_selected_ips:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)

            font = QFont("Courier New", 9)
            font.setStyleHint(QFont.Monospace)
            item.setFont(font)
            item.setData(Qt.UserRole, info)
            self.listbox_devices.addItem(item)

    @Slot()
    def _refresh_device_combobox(self):
        if not hasattr(self, "ip_entry"):
            return

        font = QFont("Courier New", self._base_font.pointSize())
        self.ip_entry.setFont(font)

        with BlockSignals(self.ip_entry):
            self.ip_entry.clear()

            devices = DeviceStore.get_basic_devices_info()
            if not devices:
                self.ip_entry.lineEdit().setPlaceholderText("No devices available")
                return

            ip_list = [ip for _, _, ip in devices]

            max_lens = {
                'brand': max(len(brand) for brand, _, _ in devices),
                'model': max(len(model) for _, model, _ in devices),
                'ip': max(len(ip) for _, _, ip in devices)
            }
            fmt_str = (f"{{brand:<{max_lens['brand']}}} | "
                       f"{{model:<{max_lens['model']}}} | "
                       f"{{ip:<{max_lens['ip']}}}")

            for brand, model, ip in devices:
                display = fmt_str.format(brand=brand, model=model, ip=ip)
                self.ip_entry.addItem(display, userData=ip)

            completer = QCompleter(ip_list, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            self._apply_completer_popup_style(completer)
            self.ip_entry.setCompleter(completer)

            self.ip_entry.setCurrentIndex(-1)
            self.ip_entry.lineEdit().clear()
            self.ip_entry.lineEdit().setPlaceholderText("Select or input IP:port")
            self.ip_entry.setInsertPolicy(QComboBox.NoInsert)

    def _on_ip_selected_completer(self, ip):
        with BlockSignals(self.ip_entry):
            self.ip_entry.setCurrentText(ip)
        self._user_selected_ip = True

    def _on_ip_selected(self, index):
        if index >= 0:
            ip = self.ip_entry.itemData(index)
            if ip:
                with BlockSignals(self.ip_entry):
                    self.ip_entry.setCurrentIndex(-1)
                    self.ip_entry.setCurrentText(ip)
                self._user_selected_ip = True

    def _on_ip_edited(self, text):
        self._current_ip = text.strip()

    def _on_device_double_click(self, item: QListWidgetItem):
        if not (item.flags() & Qt.ItemIsUserCheckable):
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self.listbox_devices.viewport().update()

    @property
    def selected_devices(self) -> List[str]:
        selected_ips = []
        for i in range(self.listbox_devices.count()):
            item = self.listbox_devices.item(i)
            if item.checkState() == Qt.Checked:
                info = item.data(Qt.UserRole)
                ip = info.get("ip", "")
                if ip:
                    selected_ips.append(ip)
        return selected_ips

    @property
    def ip_address(self) -> str:
        text = self.ip_entry.currentText().strip()
        return text if self._user_selected_ip or text else ""

    def update_current_package(self, device_ip: str, package_name: str):
        def _update():
            for i in range(self.listbox_devices.count()):
                item = self.listbox_devices.item(i)
                info = item.data(Qt.UserRole)
                if not info:
                    continue
                ip = info.get("ip", "")
                if ip == device_ip:
                    display = f"{ip} | {package_name}"
                    item.setText(display)
                    if package_name not in [self.program_edit.itemText(i) for i in range(self.program_edit.count())]:
                        self.program_edit.addItem(package_name)
                    break
        QTimer.singleShot(0, _update)

    def update_email(self, text: str):
        self.email_text_sender.setText(text)

    def update_vercode(self, text: str):
        self.verfication_text_sender.setText(text)



