from re import search
from typing import List
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QGridLayout
)
from controllers.adb_controller import ADBController
from gui.styles import get_default_font
from models.device_store import DeviceStore
from contextlib import contextmanager

@contextmanager
def BlockSignals(widget):
    """通用信号阻断工具"""
    widget.blockSignals(True)
    try:
        yield
    finally:
        widget.blockSignals(False)
        
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

        main_layout = QVBoxLayout()

        # ▶️ 顶部 IP输入框 + Connect 按钮
        ip_row = QHBoxLayout()
        self.ip_entry = QComboBox()
        self.ip_entry.setEditable(True)
        self.ip_entry.setFont(self._base_font)
        self.refresh_device_combobox()
        self.ip_entry.activated[int].connect(self._on_ip_selected)

        self.btn_connect = QPushButton(self.BUTTON_TEXTS[0])
        self.btn_connect.setFont(self._base_font)
        self.btn_connect.clicked.connect(self.adb_controller.on_connect_device)

        ip_row.addWidget(self.ip_entry, 2)
        ip_row.addWidget(self.btn_connect, 1)
        main_layout.addLayout(ip_row)

        # ▶️ 中部 设备列表 + 按钮操作面板
        device_row = QHBoxLayout()
        self.listbox_devices = QListWidget()
        self.listbox_devices.setFont(self._base_font)
        self.listbox_devices.setSelectionMode(QListWidget.NoSelection)
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_item_double_clicked)
        self.listbox_devices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # 动态设置，读取右侧按钮区域高度

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
        device_row.addWidget(self.listbox_devices, 2)
        device_row.addWidget(button_panel, 1)

        main_layout.addLayout(device_row)
        group.setLayout(main_layout)
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
            return

        with BlockSignals(self.ip_entry):
            self.ip_entry.clear()

            font_metrics = QFontMetrics(self.ip_entry.font())  # 使用当前字体度量

            # 先计算最长 Brand 和 Model 的宽度（像素）
            max_brand_width = max_model_width = 0
            data = DeviceStore.get_basic_devices_info()
            for brand, model, _ in data:
                max_brand_width = max(max_brand_width, font_metrics.horizontalAdvance(brand))
                max_model_width = max(max_model_width, font_metrics.horizontalAdvance(model))

            # 添加项时用空格填充对齐
            for brand, model, ip in data:
                padded_brand = brand + " " * ((max_brand_width - font_metrics.horizontalAdvance(brand)) // font_metrics.horizontalAdvance(" "))
                padded_model = model + " " * ((max_model_width - font_metrics.horizontalAdvance(model)) // font_metrics.horizontalAdvance(" "))
                display = f"{padded_brand} | {padded_model} | {ip}"
                self.ip_entry.addItem(display, userData=ip)

            self.ip_entry.setCurrentText("")
            self._user_selected_ip = False
            self.ip_entry.lineEdit().setPlaceholderText("Select or input IP:port")

    def _on_ip_selected(self, index):
        """当用户从下拉中选中设备时，仅显示 IP"""
        if index >= 0:
            ip = self.ip_entry.itemData(index)
            if ip:
                with BlockSignals(self.ip_entry):
                    self.ip_entry.setCurrentText(ip)
                self._user_selected_ip = True  # ✅ 标记为用户主动选择

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
        return text if self._user_selected_ip or text else ""




