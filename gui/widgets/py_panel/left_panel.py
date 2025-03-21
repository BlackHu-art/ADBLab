# left_panel.py
from typing import List
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                              QGroupBox, QComboBox, QPushButton, QListWidget)
from controllers.adb_controller import ADBController
from gui.styles import get_default_font


class LeftPanel(QWidget):
    """左侧操作面板，集成ADB设备管理功能"""
    # 界面常量
    PANEL_WIDTH = 500
    GROUP_TITLES = ("Device Management", "Actions")
    BUTTON_TEXTS = (
        "Connect", "Refresh", "Device Info", "Current Activity",
        "Select APK", "Get ANR Files", "Kill All Apps", "Installed Apps"
    )

    def __init__(self, main_frame: QWidget):
        super().__init__()
        self.main_frame = main_frame  # 主窗口引用
        self.adb_controller = ADBController(self)
        self._init_ui_settings()
        self._create_ui_components()

    def _init_ui_settings(self):
        """初始化界面基本设置"""
        self.setFixedWidth(self.PANEL_WIDTH)
        self._base_font = get_default_font()

    def _create_ui_components(self):
        """创建所有UI组件"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # 设备管理区域
        main_layout.addWidget(self._create_device_group())
        # 操作按钮区域
        main_layout.addWidget(self._create_actions_group())
        main_layout.addStretch()

    def _create_device_group(self) -> QGroupBox:
        """创建设备管理分组"""
        group = QGroupBox(self.GROUP_TITLES[0])
        group.setFont(self._base_font)

        layout = QVBoxLayout()
        layout.addLayout(self._create_connect_bar())
        layout.addWidget(self._create_device_list())
        group.setLayout(layout)

        return group

    def _create_connect_bar(self) -> QHBoxLayout:
        """创建IP输入栏和连接按钮"""
        self.ip_entry = QComboBox()
        self.ip_entry.setEditable(True)
        self.ip_entry.setFont(self._base_font)

        self.btn_connect = self._create_button(self.BUTTON_TEXTS[0], 
                                             self.adb_controller.on_connect_device)

        connect_layout = QHBoxLayout()
        connect_layout.addWidget(self.ip_entry, stretch=3)
        connect_layout.addWidget(self.btn_connect, stretch=1)
        return connect_layout

    def _create_device_list(self) -> QListWidget:
        """创建设备列表"""
        self.listbox_devices = QListWidget()
        self.listbox_devices.setFont(self._base_font)
        return self.listbox_devices

    def _create_actions_group(self) -> QGroupBox:
        """创建操作按钮分组"""
        group = QGroupBox(self.GROUP_TITLES[1])
        group.setFont(self._base_font)

        layout = QVBoxLayout()
        layout.addLayout(self._create_action_row1())
        layout.addLayout(self._create_action_row2())
        layout.addLayout(self._create_action_row3())
        group.setLayout(layout)

        return group

    def _create_action_row1(self) -> QHBoxLayout:
        """创建第一行操作按钮"""
        return self._create_button_row([
            (self.BUTTON_TEXTS[1], self.adb_controller.on_refresh_devices),
            (self.BUTTON_TEXTS[2], self.adb_controller.on_get_device_info),
            (self.BUTTON_TEXTS[3], self.adb_controller.on_current_activity)
        ])

    def _create_action_row2(self) -> QHBoxLayout:
        """创建第二行操作按钮"""
        return self._create_button_row([
            (self.BUTTON_TEXTS[4], self.adb_controller.on_select_apk)
        ])

    def _create_action_row3(self) -> QHBoxLayout:
        """创建第三行操作按钮"""
        return self._create_button_row([
            (self.BUTTON_TEXTS[5], self.adb_controller.on_get_anr_files),
            (self.BUTTON_TEXTS[6], self.adb_controller.on_kill_all_apps),
            (self.BUTTON_TEXTS[7], self.adb_controller.on_get_installed_packages)
        ])

    def _create_button_row(self, button_specs: List[tuple]) -> QHBoxLayout:
        """通用按钮行创建方法"""
        row = QHBoxLayout()
        for text, callback in button_specs:
            btn = self._create_button(text, callback)
            row.addWidget(btn)
        return row

    def _create_button(self, text: str, callback) -> QPushButton:
        """通用按钮创建方法"""
        btn = QPushButton(text)
        btn.setFont(self._base_font)
        btn.clicked.connect(callback)
        return btn

    @property
    def selected_devices(self) -> List[str]:
        """获取已选设备列表（属性方式访问）"""
        return [item.text() for item in self.listbox_devices.selectedItems()]

    @property
    def ip_address(self) -> str:
        """获取当前输入的IP地址"""
        return self.ip_entry.currentText()