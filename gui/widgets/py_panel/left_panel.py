from typing import List
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QComboBox, QPushButton, QListWidget, QListWidgetItem, QFrame
)
from controllers.adb_controller import ADBController
from gui.styles import get_default_font


class LeftPanel(QWidget):
    """左侧操作面板，集成ADB设备管理功能"""
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
        self._init_ui_settings()
        self._create_ui_components()

    def _init_ui_settings(self):
        self.setFixedWidth(self.PANEL_WIDTH)
        self._base_font = get_default_font()

    def _create_ui_components(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        main_layout.addWidget(self._create_device_group())
        main_layout.addWidget(self._create_actions_group())
        main_layout.addStretch()

    def _create_device_group(self) -> QGroupBox:
        group = QGroupBox(self.GROUP_TITLES[0])
        group.setFont(self._base_font)

        layout = QVBoxLayout()
        layout.addLayout(self._create_connect_bar())
        layout.addLayout(self._create_device_list_section())
        group.setLayout(layout)

        return group

    def _create_connect_bar(self) -> QHBoxLayout:
        self.ip_entry = QComboBox()
        self.ip_entry.setEditable(True)
        self.ip_entry.setFont(self._base_font)

        self.btn_connect = QPushButton(self.BUTTON_TEXTS[0])
        self.btn_connect.setFont(self._base_font)
        self.btn_connect.clicked.connect(self.adb_controller.on_connect_device)

        connect_layout = QHBoxLayout()
        connect_layout.addWidget(self.ip_entry, stretch=3)
        connect_layout.addWidget(self.btn_connect, stretch=1)
        return connect_layout

    def _create_device_list_section(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        self.listbox_devices = QListWidget()
        self.listbox_devices.setFont(self._base_font)
        self.listbox_devices.setSelectionMode(QListWidget.NoSelection)
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_item_double_clicked)

        button_panel = QFrame()
        button_layout = QVBoxLayout(button_panel)
        button_layout.setSpacing(5)
        button_layout.setContentsMargins(0, 0, 0, 0)
        btn1 = QPushButton("Example 1")
        btn2 = QPushButton("Example 2")
        btn1.setFont(self._base_font)
        btn2.setFont(self._base_font)
        button_layout.addWidget(btn1)
        button_layout.addWidget(btn2)
        button_layout.addStretch()

        layout.addWidget(self.listbox_devices, 1)
        layout.addWidget(button_panel, 1)
        return layout

    def _create_actions_group(self) -> QGroupBox:
        group = QGroupBox(self.GROUP_TITLES[1])
        group.setFont(self._base_font)

        layout = QVBoxLayout()
        layout.addLayout(self._create_action_row1())
        layout.addLayout(self._create_action_row2())
        layout.addLayout(self._create_action_row3())
        group.setLayout(layout)

        return group

    def _create_action_row1(self) -> QHBoxLayout:
        return self._create_button_row([
            (self.BUTTON_TEXTS[1], self.adb_controller.on_refresh_devices),
            (self.BUTTON_TEXTS[2], self.adb_controller.on_get_device_info),
            (self.BUTTON_TEXTS[3], self.adb_controller.on_current_activity)
        ])

    def _create_action_row2(self) -> QHBoxLayout:
        return self._create_button_row([
            (self.BUTTON_TEXTS[4], self.adb_controller.on_select_apk)
        ])

    def _create_action_row3(self) -> QHBoxLayout:
        return self._create_button_row([
            (self.BUTTON_TEXTS[5], self.adb_controller.on_get_anr_files),
            (self.BUTTON_TEXTS[6], self.adb_controller.on_kill_all_apps),
            (self.BUTTON_TEXTS[7], self.adb_controller.on_get_installed_packages)
        ])

    def _create_button_row(self, button_specs: List[tuple]) -> QHBoxLayout:
        row = QHBoxLayout()
        for text, callback in button_specs:
            btn = QPushButton(text)
            btn.setFont(self._base_font)
            btn.clicked.connect(callback)
            row.addWidget(btn)
        return row

    def update_device_list(self, devices: List[str]):
        self.listbox_devices.clear()
        for device in devices:
            item = QListWidgetItem(device)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setFont(self._base_font)
            self.listbox_devices.addItem(item)

    def _on_device_item_double_clicked(self, item: QListWidgetItem):
        """双击设备列表项，切换其选中状态"""
        new_state = Qt.Checked if item.checkState() == Qt.Unchecked else Qt.Unchecked
        item.setCheckState(new_state)

    @property
    def selected_devices(self) -> List[str]:
        return [self.listbox_devices.item(i).text()
                for i in range(self.listbox_devices.count())
                if self.listbox_devices.item(i).checkState() == Qt.Checked]

    @property
    def ip_address(self) -> str:
        return self.ip_entry.currentText()
