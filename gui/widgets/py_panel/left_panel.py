from re import search
from typing import List, Union
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QAbstractItemView, QLineEdit, QCompleter
)
from gui.widgets.style.base_styles import get_default_font
from models.device_store import DeviceStore
from contextlib import contextmanager
from gui.widgets.py_panel.left_panel_signals import LeftPanelSignals
from utils.double_click_button import DoubleClickButton

@contextmanager
def BlockSignals(widget):
    """通用信号阻断工具"""
    widget.blockSignals(True)
    try:
        yield
    finally:
        widget.blockSignals(False)
        
class LeftPanel(QWidget):
    PANEL_WIDTH = 600
    GROUP_TITLES = ("Device Management", "Actions", "Performance")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = LeftPanelSignals()
        self.connected_device_cache = []
        self._user_selected_ip = False
        
        self._init_ui_settings()
        self._create_ui_components()
        self._connect_signals()

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
    
    def _connect_signals(self):
        """连接所有按钮信号到对应的控制器方法"""
        # 连接IP输入框信号按钮
        self.btn_connect_devices.clicked.connect(lambda: self.signals.connect_requested.emit(self.ip_address))
        # 刷新设备按钮
        self.btn_refresh_devices.clicked.connect(lambda: self.signals.refresh_devices_requested.emit())
        # 设备信息按钮
        self.btn_devices_Info.clicked.connect(lambda: self.signals.device_info_requested.emit(self.selected_devices))
        # 断开设备连接按钮
        self.btn_disconnect_devices.clicked.connect(lambda: self.signals.disconnect_requested.emit(self.selected_devices))
        # 重启设备按钮
        self.btn_restart_devices.clicked.connect(lambda: self.signals.restart_devices_requested.emit(self.selected_devices))
        # 重启ADB按钮,需要双击启用
        self.btn_restart_adb.doubleClicked.connect(self.signals.restart_adb_requested.emit)
        # 截图按钮
        self.btn_screenshot.clicked.connect(lambda: self.signals.screenshot_requested.emit(self.selected_devices))
        # 获取设备日志按钮
        self.btn_retrieve_devices_logs.clicked.connect(lambda: self.signals.retrieve_logs_requested.emit(self.selected_devices))
        # 清理日志按钮
        self.btn_cleanup_logs.clicked.connect(lambda: self.signals.cleanup_logs_requested.emit(self.selected_devices))
        # 设备列表双击事件
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_double_click)
        # 连接其他按钮信号...

    def _create_device_group(self) -> QGroupBox:
        group = QGroupBox(self.GROUP_TITLES[0])
        group.setFont(self._base_font)

        main_layout = QVBoxLayout()

        # ▶️ 顶部 IP输入框 + Connect 按钮
        ip_row = QHBoxLayout()
        self.ip_entry = QComboBox()
        self.ip_entry.setEditable(True)
        self.ip_entry.setFont(self._base_font)
        self._refresh_device_combobox()
        self.ip_entry.currentIndexChanged.connect(self._on_ip_selected)
        self.ip_entry.editTextChanged.connect(self._on_ip_edited)
        # 使用统一按钮创建方法
        self.btn_connect_devices = self._create_button("Connect", "resources/icons/Connect.svg")
        ip_row.addWidget(self.ip_entry, 2)
        ip_row.addWidget(self.btn_connect_devices, 1)
        main_layout.addLayout(ip_row)


        # ▶️ 中部 设备列表 + 按钮操作面板
        device_row = QHBoxLayout()
        self.listbox_devices = QListWidget()
        self.listbox_devices.setEditTriggers(QListWidget.NoEditTriggers)
        self.listbox_devices.setSelectionBehavior(QListWidget.SelectRows)
        self.listbox_devices.setSelectionMode(QListWidget.MultiSelection)
        self.listbox_devices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.listbox_devices.setFont(self._base_font)
        # 关键修复：设置Item特性
        self.listbox_devices.setProperty("showDropIndicator", False)
        self.listbox_devices.setDragDropMode(QAbstractItemView.NoDragDrop)
        # self.listbox_devices.itemDoubleClicked.connect(self._on_device_double_click)

        button_panel = QFrame()
        button_layout = QVBoxLayout(button_panel)
        button_layout.setSpacing(0)
        button_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_refresh_devices = self._create_button("Refresh", "resources/icons/Refresh.svg")
        self.btn_devices_Info = self._create_button("Device Info", "resources/icons/Info.svg")
        self.btn_disconnect_devices = self._create_button("Disconnect", "resources/icons/Disconnect.svg")
        self.btn_restart_devices = self._create_button("Restart Devices", "resources/icons/Restart.svg")
        self.btn_restart_adb = self._create_button("Restart ADB", "resources/icons/Restore.svg", double_click=True)
        self.btn_restart_adb.setToolTip("Double click to restart")
        self.btn_screenshot = self._create_button("Screenshot", "resources/icons/Screenshot.svg")
        self.btn_retrieve_devices_logs = self._create_button("Retrieve device logs", "resources/icons/Save_alt.svg")
        self.btn_cleanup_logs = self._create_button("Cleanup logs", "resources/icons/Cleaning_services.svg")
        button_layout.addWidget(self.btn_refresh_devices)
        button_layout.addWidget(self.btn_devices_Info)
        button_layout.addWidget(self.btn_disconnect_devices)
        button_layout.addWidget(self.btn_restart_devices)
        button_layout.addWidget(self.btn_restart_adb)
        button_layout.addWidget(self.btn_screenshot)
        button_layout.addWidget(self.btn_retrieve_devices_logs)
        button_layout.addWidget(self.btn_cleanup_logs)

        button_layout.addStretch()
        device_row.addWidget(self.listbox_devices, 2)
        device_row.addWidget(button_panel, 1)
        main_layout.addLayout(device_row)
        
        # ▶️ 底部布局改为垂直布局
        last_row = QVBoxLayout()
        last_row1 = QHBoxLayout()
        btn_send_text = self._create_button("Send to devices", "resources/icons/Input.svg")
        input_edit = QLineEdit()
        input_edit.setFont(self._base_font)
        input_edit.setPlaceholderText("Input text here")
        last_row1.addWidget(btn_send_text, 1)
        last_row1.addWidget(input_edit, 2)
        last_row.addLayout(last_row1)
        
        last_row2 = QHBoxLayout()
        btn_generate_email = self._create_button("Generate Email", "resources/icons/Email.svg")
        email_text_sender = QLineEdit()
        email_text_sender.setFont(self._base_font)
        email_text_sender.setPlaceholderText("Generate Email")
        verfication_text_send = QLineEdit()
        verfication_text_send.setFont(self._base_font)
        verfication_text_send.setPlaceholderText("Get verification code")
        last_row2.addWidget(btn_generate_email, 1)
        last_row2.addWidget(email_text_sender, 1)
        last_row2.addWidget(verfication_text_send, 1)
        last_row.addLayout(last_row2)
        
        main_layout.addLayout(last_row)
        group.setLayout(main_layout)
        return group

    def _create_button(self, text: str, icon_path: str = None, double_click: bool = False) -> Union[QPushButton, DoubleClickButton]:
        """扩展按钮创建方法"""
        btn = DoubleClickButton(text) if double_click else QPushButton(text)
        btn.setFont(self._base_font)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
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
        btn_input = self._create_button("Get current program", "resources/icons/Select_activity.svg")
        action_row1.addWidget(input_edit, 2)
        action_row1.addWidget(btn_input, 1)
        layout.addLayout(action_row1)

        # ▶️ 第二行
        action_row2 = QHBoxLayout()
        action_btn1 = self._create_button("Install App", "resources/icons/Install_App.svg")
        action_btn2 = self._create_button("Uninstall App", "resources/icons/Uninstall_app.svg")
        action_btn3 = self._create_button("Clear App Data", "resources/icons/Clear_data.svg")
        for btn in (action_btn1, action_btn2, action_btn3):
            action_row2.addWidget(btn, 1)
        layout.addLayout(action_row2)

        # ▶️ 第三行
        action_row3 = QHBoxLayout()
        action_btn1 = self._create_button("Restart App", "resources/icons/Restart_app.svg")
        action_btn2 = self._create_button("Print Current Activity", "resources/icons/Print.svg")
        action_btn3 = self._create_button("Parse APK Info", "resources/icons/Parse_APK.svg")
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
        btn_start = self._create_button("Start Monkey", "resources/icons/Monkey.svg")
        perf_row1.addWidget(device_type, 1)
        perf_row1.addWidget(input_times, 1)
        perf_row1.addWidget(btn_start, 1)
        layout.addLayout(perf_row1)
        
        # ▶️ 第二行：三个按钮
        perf_row2 = QHBoxLayout()
        perf_btn1 = self._create_button("Kill Monkey", "resources/icons/Kill_monkey.svg")
        perf_btn2 = self._create_button("Get ANR File", "resources/icons/Get_ANR.svg")
        perf_btn3 = self._create_button("Get Bugreport", "resources/icons/bugreport.svg")
        for btn in (perf_btn1, perf_btn2, perf_btn3):
            perf_row2.addWidget(btn, 1)
        layout.addLayout(perf_row2)
        
                # ▶️ 第三行
        perf_row3 = QHBoxLayout()
        perf_btn1 = self._create_button("Packages List", "resources/icons/Restart_app.svg")
        perf_btn2 = self._create_button("Print", "resources/icons/Print.svg")
        perf_btn3 = self._create_button("Parse", "resources/icons/Parse_APK.svg")
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
        # 获取完整设备信息
        device_info_list = DeviceStore.get_full_devices_info(devices)
        # 计算各字段最大宽度
        max_lengths = {'model': 0,'brand': 0,'version': 0,'ip': 0}
        # 第一次遍历计算最大宽度
        for info in device_info_list:
            max_lengths['model'] = max(max_lengths['model'], len(info.get('Model', 'Unknown')))
            max_lengths['brand'] = max(max_lengths['brand'], len(info.get('Brand', 'Unknown')))
            max_lengths['ip'] = max(max_lengths['ip'], len(info.get('ip', '')))
        # 第二次遍历创建对齐的显示项
        for info in device_info_list:
            model = info.get('Model', 'Unknown').ljust(max_lengths['model'])
            brand = info.get('Brand', 'Unknown').ljust(max_lengths['brand'])
            version = info.get('Aversion', 'Unknown')
            ip = info.get('ip', '').ljust(max_lengths['ip'])
            
            # 使用等宽字体保证对齐效果
            display = f"{model} | {brand} | {version} | {ip}"
            
            item = QListWidgetItem(display)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            # 设置等宽字体（确保对齐）
            font = self._base_font
            font.setFamily("Courier New")  # 等宽字体
            item.setFont(self._base_font)
            # 存储原始数据用于后续操作
            item.setData(Qt.UserRole, info)
            self.listbox_devices.addItem(item)

    @Slot()
    def _refresh_device_combobox(self):
        """使用等宽字体优化设备下拉框显示"""
        if not hasattr(self, "ip_entry"):
            return

        # 使用等宽字体确保对齐
        font = QFont("Courier New", self.ip_entry.font().pointSize())
        self.ip_entry.setFont(font)
        
        with BlockSignals(self.ip_entry):
            self.ip_entry.clear()
            
            # 获取设备数据
            devices = DeviceStore.get_basic_devices_info()
            if not devices:
                self.ip_entry.lineEdit().setPlaceholderText("No devices available")
                return

            # 计算各列最大字符长度（等宽字体下字符宽度相同）
            max_lens = {
                'brand': max(len(brand) for brand, _, _ in devices),
                'model': max(len(model) for _, model, _ in devices),
                'ip': max(len(ip) for _, _, ip in devices)
            }

            # 生成格式化字符串模板
            fmt_str = (f"{{brand:<{max_lens['brand']}}} | "
                    f"{{model:<{max_lens['model']}}} | "
                    f"{{ip:<{max_lens['ip']}}}")

            # 添加格式化后的选项
            for brand, model, ip in devices:
                display = fmt_str.format(brand=brand, model=model, ip=ip)
                self.ip_entry.addItem(display, userData=ip)

            # 重置控件状态
            self.ip_entry.setCurrentIndex(-1)
            self.ip_entry.lineEdit().clear()
            self.ip_entry.lineEdit().setPlaceholderText("Select or input IP:port")
            
            # 配置自动完成行为
            self.ip_entry.setInsertPolicy(QComboBox.NoInsert)
            completer = self.ip_entry.completer()
            completer.setCompletionMode(QCompleter.PopupCompletion)
            completer.setFilterMode(Qt.MatchContains)

    def _on_ip_selected(self, index):
        """当用户从下拉中选中设备时，仅显示 IP"""
        if index >= 0:
            ip = self.ip_entry.itemData(index)
            if ip:
                with BlockSignals(self.ip_entry):
                    self.ip_entry.setCurrentIndex(-1)
                    self.ip_entry.setCurrentText(ip)
                self._user_selected_ip = True  # ✅ 标记为用户主动选择
                
    def _on_ip_edited(self, text):
        """处理手动输入IP"""
        self._current_ip = text.strip()  # 更新当前IP

    def _on_device_double_click(self, item):
        """处理设备列表双击事件（优化版）"""
        # 1. 确保item是可勾选的（安全检查）
        if not (item.flags() & Qt.ItemIsUserCheckable):
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        
        # 2. 直接切换状态（更高效的方式）
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        
        # 3. 确保视觉反馈（可选）
        self.listbox_devices.viewport().update()
        
        # 4. 打印调试信息
        # state = "Checked" if item.checkState() == Qt.Checked else "Unchecked"
        # print(f"设备 {item.text()} 状态已切换为: {state}")

    @property
    def selected_devices(self) -> List[str]:
        selected_ips = []
        for i in range(self.listbox_devices.count()):
            item = self.listbox_devices.item(i)
            if item.checkState() == Qt.Checked:
                text = item.text()
                parts = text.split("|")
                if len(parts) >= 3:
                    selected_ips.append(parts[3].strip())  # 提取 IP
        return selected_ips


    @property
    def ip_address(self) -> str:
        text = self.ip_entry.currentText().strip()
        return text if self._user_selected_ip or text else ""




