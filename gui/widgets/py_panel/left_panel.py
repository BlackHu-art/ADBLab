from re import search
from typing import List
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QGridLayout
)
from controllers.adb_controller import ADBController
from gui.styles import get_default_font
from models.device_store import DeviceStore

class LeftPanel(QWidget):
    PANEL_WIDTH = 500
    GROUP_TITLES = ("Device Management", "Actions")
    BUTTON_TEXTS = (
        "Connect", "Refresh", "Device Info", "Current Activity",
        "Select APK", "Get ANR Files", "Kill All Apps", "Installed Apps"
    )

    def __init__(self, main_frame: QWidget):
        super().__init__()
        self.main_frame = main_frame
        self.adb_controller = ADBController(self)
        self.connected_device_cache = []
        self._init_ui_settings()
        self._create_ui_components()

    def _init_ui_settings(self):
        self.setFixedWidth(self.PANEL_WIDTH)
        self._base_font = get_default_font()

    def _create_ui_components(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._create_device_group())
        layout.addWidget(self._create_actions_group())
        layout.addStretch()

    def _create_device_group(self) -> QGroupBox:
        group = QGroupBox(self.GROUP_TITLES[0])
        group.setFont(self._base_font)
        layout = QVBoxLayout()

        ip_layout = QHBoxLayout()
        self.ip_entry = QComboBox()
        self.ip_entry.setEditable(True)
        self.ip_entry.setFont(self._base_font)
        self.refresh_device_combobox()  # 初次加载
        self.btn_connect = QPushButton(self.BUTTON_TEXTS[0])
        self.btn_connect.setFont(self._base_font)
        self.btn_connect.clicked.connect(self.adb_controller.on_connect_device)
        ip_layout.addWidget(self.ip_entry, 3)
        ip_layout.addWidget(self.btn_connect, 1)
        layout.addLayout(ip_layout)

        device_layout = QHBoxLayout()
        self.listbox_devices = QListWidget()
        self.listbox_devices.setFont(self._base_font)
        self.listbox_devices.setSelectionMode(QListWidget.NoSelection)
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_item_double_clicked)
        self.listbox_devices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        button_panel = QFrame()
        button_layout = QVBoxLayout(button_panel)
        button_layout.setSpacing(5)
        button_layout.setContentsMargins(0, 0, 0, 0)

        button_specs = [
            (self.BUTTON_TEXTS[1], self.adb_controller.on_refresh_devices),
            (self.BUTTON_TEXTS[2], self.adb_controller.on_get_device_info),
            (self.BUTTON_TEXTS[3], self.adb_controller.on_current_activity),
            ("Example 1", lambda: None),
            ("Example 2", lambda: None),
            ("Example 3", lambda: None),
        ]
        for text, handler in button_specs:
            btn = QPushButton(text)
            btn.setFont(self._base_font)
            btn.clicked.connect(handler)
            button_layout.addWidget(btn)

        button_layout.addStretch()
        device_layout.addWidget(self.listbox_devices, 3)
        device_layout.addWidget(button_panel, 1)
        layout.addLayout(device_layout)
        group.setLayout(layout)
        return group

    def _create_actions_group(self) -> QGroupBox:
        group = QGroupBox(self.GROUP_TITLES[1])
        group.setFont(self._base_font)
        layout = QVBoxLayout()
        grid = QGridLayout()

        button_specs = [
            (self.BUTTON_TEXTS[4], self.adb_controller.on_select_apk),
            (self.BUTTON_TEXTS[5], self.adb_controller.on_get_anr_files),
            (self.BUTTON_TEXTS[6], self.adb_controller.on_kill_all_apps),
            (self.BUTTON_TEXTS[7], self.adb_controller.on_get_installed_packages)
        ]
        for idx, (text, handler) in enumerate(button_specs):
            btn = QPushButton(text)
            btn.setFont(self._base_font)
            btn.clicked.connect(handler)
            row, col = divmod(idx, 3)
            grid.addWidget(btn, row, col)

        layout.addLayout(grid)
        group.setLayout(layout)
        return group

    def update_device_list(self, devices: List[str]):
        self.listbox_devices.clear()
        self.connected_device_cache = devices
        for device in devices:
            item = QListWidgetItem(device)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setFont(self._base_font)
            self.listbox_devices.addItem(item)

    def refresh_device_combobox(self):
        if not hasattr(self, "ip_entry"):
            return  # 防止未初始化时被错误调用
        self.ip_entry.clear()
        for alias, ip in DeviceStore.get_all():
            self.ip_entry.addItem(f"{alias}: {ip}")

    def _on_device_item_double_clicked(self, item: QListWidgetItem):
        new_state = Qt.Checked if item.checkState() == Qt.Unchecked else Qt.Unchecked
        item.setCheckState(new_state)

    @property
    def selected_devices(self) -> List[str]:
        return [self.listbox_devices.item(i).text()
                for i in range(self.listbox_devices.count())
                if self.listbox_devices.item(i).checkState() == Qt.Checked]

    @property
    def ip_address(self) -> str:
        text = self.ip_entry.currentText().strip()
        # 匹配 IP:端口 格式
        match = search(r'(\d{1,3}(?:\.\d{1,3}){3}:\d+)', text)
        if match:
            return match.group(1)
        return text  # 若直接是 IP:PORT 格式，也返回原文本

