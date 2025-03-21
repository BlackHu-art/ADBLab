# left_panel.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, QPushButton, QListWidget
from controllers.adb_controller import ADBController
from gui.styles import Styles, get_default_font


class LeftPanel(QWidget):
    """ 左侧面板，包含设备管理和操作按钮 """

    def __init__(self, main_frame):
        super().__init__()
        self.main_frame = main_frame  # 保存主窗口实例以调用日志方法
        self.setFixedWidth(500)

        # 初始化控制器
        self.adb_controller = ADBController(self)  # 将 LeftPanel 实例传递给 ADBController

        self._setup_ui()

    def _setup_ui(self):
        """ 设置左侧面板布局 """
        layout = QVBoxLayout(self)
        layout.setSpacing(1)
        layout.setContentsMargins(1, 1, 1, 1)

        # Device Management
        device_group = QGroupBox("Device Management")
        device_group.setFont(get_default_font())
        device_layout = QVBoxLayout()

        # IP Address Entry and Connect Button
        ip_layout = QHBoxLayout()
        self.ip_entry = QComboBox()
        self.ip_entry.setEditable(True)
        self.ip_entry.setFont(get_default_font())
        ip_layout.addWidget(self.ip_entry)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setFont(get_default_font())
        self.btn_connect.clicked.connect(self.adb_controller.on_connect_device)
        ip_layout.addWidget(self.btn_connect)
        device_layout.addLayout(ip_layout)

        # Device List
        self.listbox_devices = QListWidget()
        self.listbox_devices.setFont(get_default_font())
        device_layout.addWidget(self.listbox_devices)
        device_group.setLayout(device_layout)
        layout.addWidget(device_group)

        # Actions
        actions_group = QGroupBox("Actions")
        actions_group.setFont(get_default_font())
        actions_layout = QVBoxLayout()

        # Row 1: Refresh Devices, Get Info, Get Activity
        row1 = QHBoxLayout()
        self.btn_refresh_devices = QPushButton("Refresh")
        self.btn_refresh_devices.setFont(get_default_font())
        self.btn_refresh_devices.clicked.connect(self.adb_controller.on_refresh_devices)
        row1.addWidget(self.btn_refresh_devices)
        self.btn_get_device_info = QPushButton("Device Info")
        self.btn_get_device_info.setFont(get_default_font())
        self.btn_get_device_info.clicked.connect(self.adb_controller.on_get_device_info)
        row1.addWidget(self.btn_get_device_info)
        self.btn_current_activity = QPushButton("Current Activity")
        self.btn_current_activity.setFont(get_default_font())
        self.btn_current_activity.clicked.connect(self.adb_controller.on_current_activity)
        row1.addWidget(self.btn_current_activity)
        actions_layout.addLayout(row1)

        # Row 2: Select APK
        row2 = QHBoxLayout()
        self.btn_select_apk = QPushButton("Select APK")
        self.btn_select_apk.setFont(get_default_font())
        self.btn_select_apk.clicked.connect(self.adb_controller.on_select_apk)
        row2.addWidget(self.btn_select_apk)
        actions_layout.addLayout(row2)

        # Row 3: ANR Files, Kill Apps, Package List
        row3 = QHBoxLayout()
        self.btn_get_anr_files = QPushButton("Get ANR Files")
        self.btn_get_anr_files.setFont(get_default_font())
        self.btn_get_anr_files.clicked.connect(self.adb_controller.on_get_anr_files)
        row3.addWidget(self.btn_get_anr_files)
        self.btn_kill_all_apps = QPushButton("Kill All Apps")
        self.btn_kill_all_apps.setFont(get_default_font())
        self.btn_kill_all_apps.clicked.connect(self.adb_controller.on_kill_all_apps)
        row3.addWidget(self.btn_kill_all_apps)
        self.btn_get_packages = QPushButton("Installed Apps")
        self.btn_get_packages.setFont(get_default_font())
        self.btn_get_packages.clicked.connect(self.adb_controller.on_get_installed_packages)
        row3.addWidget(self.btn_get_packages)
        actions_layout.addLayout(row3)
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        layout.addStretch()

    # 提供对控件的访问接口
    def get_ip_entry(self):
        return self.ip_entry

    def get_listbox_devices(self):
        return self.listbox_devices

    def get_selected_devices(self):
        return [item.text() for item in self.listbox_devices.selectedItems()]