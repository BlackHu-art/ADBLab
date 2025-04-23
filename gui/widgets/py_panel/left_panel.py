from re import search
from typing import List
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QGridLayout, QLineEdit
)
from controllers.adb_controller import ADBController
from gui.widgets.style.base_styles import get_default_font
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
    GROUP_TITLES = ("Device Management", "Actions", "Performance")
    BUTTON_TEXTS = (
        "Connect", "Refresh", "Device Info", "Disconnect", "Restart Devices", "Restart ADB",
        "Screenshot", "Retrieve device logs", "Clean up device logs"
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
        layout.addWidget(self._create_performance_group())
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
        # 使用统一按钮创建方法
        self.btn_connect = self._create_button("Connect", self.adb_controller.on_connect_device, "resources/icons/Connect.svg")
        ip_row.addWidget(self.ip_entry, 2)
        ip_row.addWidget(self.btn_connect, 1)
        main_layout.addLayout(ip_row)


        # ▶️ 中部 设备列表 + 按钮操作面板
        device_row = QHBoxLayout()
        self.listbox_devices = QListWidget()
        self.listbox_devices.setEditTriggers(QListWidget.NoEditTriggers)
        self.listbox_devices.setSelectionBehavior(QListWidget.SelectRows)
        self.listbox_devices.setSelectionMode(QListWidget.NoSelection)  # 只通过勾选来选中
        self.listbox_devices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.listbox_devices.setFont(self._base_font)
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_item_double_clicked)

        button_panel = QFrame()
        button_layout = QVBoxLayout(button_panel)
        button_layout.setSpacing(5)
        button_layout.setContentsMargins(0, 0, 0, 0)

        button_specs = [
            {"text": self.BUTTON_TEXTS[1], "handler": self.adb_controller.on_refresh_devices, "icon": "resources/icons/Refresh.svg"},
            {"text": self.BUTTON_TEXTS[2], "handler": self.adb_controller.on_get_device_info, "icon": "resources/icons/Info.svg"},
            {"text": self.BUTTON_TEXTS[3], "handler": self.adb_controller.on_disconnect_device, "icon": "resources/icons/Disconnect.svg"},
            {"text": self.BUTTON_TEXTS[4], "handler": self.adb_controller.on_restart_devices, "icon": "resources/icons/Restart.svg"},
            {"text": self.BUTTON_TEXTS[5], "handler": self.adb_controller.on_restart_adb, "icon": "resources/icons/Restore.svg"},
            {"text": self.BUTTON_TEXTS[6], "handler": "","icon": "resources/icons/Screenshot.svg"},
            {"text": self.BUTTON_TEXTS[7], "handler": "","icon": "resources/icons/Save_alt.svg"},
            {"text": self.BUTTON_TEXTS[8], "handler": "","icon": "resources/icons/Cleaning_services.svg"},
        ]
        for spec in button_specs:
            btn = self._create_button(
                text=spec["text"],
                handler=spec.get("handler"),  # 使用get方法安全访问
                icon_path=spec.get("icon")     # 键名改为icon_path对应
            )
            button_layout.addWidget(btn)

        button_layout.addStretch()
        device_row.addWidget(self.listbox_devices, 2)
        device_row.addWidget(button_panel, 1)
        main_layout.addLayout(device_row)
        
        # ▶️ 底部布局改为垂直布局
        last_row = QVBoxLayout()
        last_row1 = QHBoxLayout()
        btn_input = self._create_button("Send to devices", "", "resources/icons/Input.svg")
        input_edit = QLineEdit()
        input_edit.setFont(self._base_font)
        input_edit.setPlaceholderText("Input text here")
        last_row1.addWidget(btn_input, 1)
        last_row1.addWidget(input_edit, 2)
        last_row.addLayout(last_row1)
        
        last_row2 = QHBoxLayout()
        btn_generate_email = self._create_button("Generate Email", "", "resources/icons/Email.svg")
        device_input_1 = QLineEdit()
        device_input_1.setFont(self._base_font)
        device_input_1.setPlaceholderText("Generate Email")
        device_input_2 = QLineEdit()
        device_input_2.setFont(self._base_font)
        device_input_2.setPlaceholderText("Get verification code")
        last_row2.addWidget(btn_generate_email, 1)
        last_row2.addWidget(device_input_1, 1)
        last_row2.addWidget(device_input_2, 1)
        last_row.addLayout(last_row2)
        
        main_layout.addLayout(last_row)
        group.setLayout(main_layout)
        return group

    def _create_button(self, text: str, handler=None, icon_path: str = None) -> QPushButton:
        btn = QPushButton(text)
        btn.setFont(self._base_font)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if handler:
            btn.clicked.connect(handler)
        if icon_path:
            btn.setIcon(QIcon(icon_path))
        return btn

    def _create_actions_group(self) -> QGroupBox:
        group = QGroupBox(self.GROUP_TITLES[1])
        group.setFont(self._base_font)
        layout = QVBoxLayout()

        # ▶️ 第一行：输入框 + 按钮
        action_row1 = QHBoxLayout()
        input_edit = QComboBox()
        input_edit.setEditable(True)
        input_edit.setFont(self._base_font)
        input_edit.lineEdit().setPlaceholderText("Select program")
        btn_input = self._create_button("Get current program", "", "resources/icons/Select_activity.svg")
        action_row1.addWidget(input_edit, 2)
        action_row1.addWidget(btn_input, 1)
        layout.addLayout(action_row1)

        # ▶️ 第二行
        action_row2 = QHBoxLayout()
        action_btn1 = self._create_button("Install App", "", "resources/icons/Install_App.svg")
        action_btn2 = self._create_button("Uninstall App", "", "resources/icons/Uninstall_app.svg")
        action_btn3 = self._create_button("Clear App Data", "", "resources/icons/Clear_data.svg")
        for btn in (action_btn1, action_btn2, action_btn3):
            action_row2.addWidget(btn, 1)
        layout.addLayout(action_row2)

        # ▶️ 第三行
        action_row3 = QHBoxLayout()
        action_btn1 = self._create_button("Restart App", "", "resources/icons/Restart_app.svg")
        action_btn2 = self._create_button("Print Current Activity", "", "resources/icons/Print.svg")
        action_btn3 = self._create_button("Parse APK Info", "", "resources/icons/Parse_APK.svg")
        for btn in (action_btn1, action_btn2, action_btn3):
            action_row3.addWidget(btn, 1)
        layout.addLayout(action_row3)

        layout.addStretch()
        group.setLayout(layout)
        return group
    
    def _create_performance_group(self) -> QGroupBox:
        group = QGroupBox(self.GROUP_TITLES[2])
        group.setFont(self._base_font)
        layout = QVBoxLayout()
        
        # ▶️ 第一行：输入框 + 按钮
        perf_row1 = QHBoxLayout()
        # 添加设备类型下拉框
        device_type = QComboBox()
        device_type.addItems(["STB", "Mobile"])  # 固定选项
        device_type.setFont(self._base_font)
        input_times = QLineEdit()
        input_times.setFont(self._base_font)
        input_times.setPlaceholderText("Input Run times")
        btn_start = self._create_button("Start Monkey", "", "resources/icons/Monkey.svg")
        perf_row1.addWidget(device_type, 1)
        perf_row1.addWidget(input_times, 1)
        perf_row1.addWidget(btn_start, 1)
        layout.addLayout(perf_row1)
        
        # ▶️ 第二行：三个按钮
        perf_row2 = QHBoxLayout()
        perf_btn1 = self._create_button("Kill Monkey", "", "resources/icons/Kill_monkey.svg")
        perf_btn2 = self._create_button("Get ANR File", "", "resources/icons/Get_ANR.svg")
        perf_btn3 = self._create_button("Get Bugreport", "", "resources/icons/bugreport.svg")
        for btn in (perf_btn1, perf_btn2, perf_btn3):
            perf_row2.addWidget(btn, 1)
        layout.addLayout(perf_row2)
        
                # ▶️ 第三行
        perf_row3 = QHBoxLayout()
        perf_btn1 = self._create_button("Packages List", "", "resources/icons/Restart_app.svg")
        perf_btn2 = self._create_button("Print", "", "resources/icons/Print.svg")
        perf_btn3 = self._create_button("Parse", "", "resources/icons/Parse_APK.svg")
        for btn in (perf_btn1, perf_btn2, perf_btn3):
            perf_row3.addWidget(btn, 1)
        layout.addLayout(perf_row3)
        
        layout.addStretch()
        group.setLayout(layout)
        return group


    def update_device_list(self, devices: List[str] = None):
        from models.device_store import DeviceStore
        from models.adb_model import ADBModel

        # ① 若未传入则主动获取当前在线设备
        if devices is None:
            devices = ADBModel.get_connected_devices()

        self.listbox_devices.clear()
        self.connected_device_cache = devices

        device_info_list = DeviceStore.get_full_devices_info(devices)

        for info in device_info_list:
            display = f"{info.get('Model', 'Unknown')} | {info.get('Brand', 'Unknown')} | " \
                    f"{info.get('ip', '')}"
            item = QListWidgetItem(display)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setFont(self._base_font)
            self.listbox_devices.addItem(item)

    @Slot()
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
        selected_ips = []
        for i in range(self.listbox_devices.count()):
            item = self.listbox_devices.item(i)
            if item.checkState() == Qt.Checked:
                text = item.text()
                parts = text.split("|")
                if len(parts) >= 3:
                    selected_ips.append(parts[2].strip())  # 提取 IP
        return selected_ips


    @property
    def ip_address(self) -> str:
        text = self.ip_entry.currentText().strip()
        return text if self._user_selected_ip or text else ""




