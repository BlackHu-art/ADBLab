from re import search
from typing import List, Union
from PySide6.QtCore import Qt, Slot, QTimer
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
from models.device_store import DeviceStore
from models.adb_model import ADBModel

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
        # 添加包名历史记录
        self.package_history = []
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
        # 顶部
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
        self.btn_generate_email.clicked.connect(lambda: self.signals.generate_email_requested.emit(self.ip_address))
        # 设备列表双击事件
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_double_click)
        self.btn_get_program.clicked.connect(lambda: self.signals.get_program_requested.emit(self.selected_devices))
        self.btn_install_app.clicked.connect(lambda: self.signals.install_app_requested.emit(self.selected_devices))
        self.uninstall_btn.clicked.connect(lambda: self.signals.uninstall_app_requested.emit(self.selected_devices, self.program_edit.currentText()))
        self.clear_app_data_btn.clicked.connect(lambda: self.signals.clear_app_data_requested.emit(self.selected_devices, self.program_edit.currentText()))
        self.restart_app_btn.clicked.connect(lambda: self.signals.restart_app_requested.emit(self.selected_devices, self.program_edit.currentText()))
        self.print_activity_btn.clicked.connect(lambda: self.signals.print_activity_requested.emit(self.selected_devices))
        
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
        self.ip_entry.completer().activated.connect(lambda text: self._on_ip_selected_completer(text))
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

        button_panel = QFrame()
        button_layout = QVBoxLayout(button_panel)
        button_layout.setSpacing(5)
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
        self.btn_send_text = self._create_button("Send txt to devices", "resources/icons/Input.svg")
        self.input_text_edit = QLineEdit()
        self.input_text_edit.setFont(self._base_font)
        self.input_text_edit.setPlaceholderText("Input text here, Press Enter to send")
        last_row1.addWidget(self.btn_send_text, 1)
        last_row1.addWidget(self.input_text_edit, 2)
        last_row.addLayout(last_row1)
        
        last_row2 = QHBoxLayout()
        self.btn_generate_email = self._create_button("Generate Email", "resources/icons/Email.svg")
        self.email_text_sender = QLineEdit()
        self.email_text_sender.setFont(self._base_font)
        self.email_text_sender.setPlaceholderText("Generate Email")
        verfication_text_send = QLineEdit()
        verfication_text_send.setFont(self._base_font)
        verfication_text_send.setPlaceholderText("Get verification code")
        last_row2.addWidget(self.btn_generate_email, 1)
        last_row2.addWidget(self.email_text_sender, 1)
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
        self.program_edit = QComboBox()
        self.program_edit.setEditable(True)
        self.program_edit.setFont(self._base_font)
        self.program_edit.lineEdit().setPlaceholderText("Select or input package name")
        # 添加自动补全
        self.completer = QCompleter(self.package_history)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.program_edit.setCompleter(self.completer)
        self.btn_get_program = self._create_button("Get current program", "resources/icons/Select_activity.svg")
        action_row1.addWidget(self.program_edit, 2)
        action_row1.addWidget(self.btn_get_program, 1)
        layout.addLayout(action_row1)

        # ▶️ 第二行
        action_row2 = QHBoxLayout()
        self.btn_install_app = self._create_button("Install App", "resources/icons/Install_App.svg")
        self.uninstall_btn = self._create_button("Uninstall App", "resources/icons/Uninstall_app.svg")
        self.clear_app_data_btn = self._create_button("Clear App Data", "resources/icons/Clear_data.svg")
        for btn in (self.btn_install_app, self.uninstall_btn, self.clear_app_data_btn):
            action_row2.addWidget(btn, 1)
        layout.addLayout(action_row2)

        # ▶️ 第三行
        action_row3 = QHBoxLayout()
        self.restart_app_btn = self._create_button("Restart App", "resources/icons/Restart_app.svg")
        self.print_activity_btn = self._create_button("Print Current Activity", "resources/icons/Print.svg")
        action_btn3 = self._create_button("Parse APK Info", "resources/icons/Parse_APK.svg")
        for btn in (self.restart_app_btn, self.print_activity_btn, action_btn3):
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
        """刷新设备列表（保留勾选状态 + 等宽字体显示 + 用户数据绑定）"""
        # ① 若未传入则主动获取当前在线设备
        if devices is None:
            devices = ADBModel.get_connected_devices_async()
        
        # ② 获取之前勾选的设备 IP
        previously_selected_ips = set(self.selected_devices)
        
        # ③ 清空设备列表，更新缓存
        self.listbox_devices.clear()
        self.connected_device_cache = devices
        
        # ④ 获取完整设备信息
        device_info_list = DeviceStore.get_full_devices_info(devices)

        # ⑤ 计算最大宽度以便等宽对齐
        max_lengths = {'model': 0, 'brand': 0, 'version': 0, 'ip': 0}
        for info in device_info_list:
            max_lengths['model'] = max(max_lengths['model'], len(info.get('Model', 'Unknown')))
            max_lengths['brand'] = max(max_lengths['brand'], len(info.get('Brand', 'Unknown')))
            max_lengths['version'] = max(max_lengths['version'], len(info.get('Aversion', 'Unknown')))
            max_lengths['ip'] = max(max_lengths['ip'], len(info.get('ip', '')))

        # ⑥ 遍历设备，创建列表项
        for info in device_info_list:
            model = info.get('Model', 'Unknown').ljust(max_lengths['model'])
            brand = info.get('Brand', 'Unknown').ljust(max_lengths['brand'])
            version = info.get('Aversion', 'Unknown').ljust(max_lengths['version'])
            ip = info.get('ip', '').ljust(max_lengths['ip'])
            
            display = f"{model} | {brand} | {version} | {ip}"
            item = QListWidgetItem(display)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            
            # 如果之前选中过这个设备，则恢复选中状态
            if info.get('ip') in previously_selected_ips:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            
            # 设置等宽字体
            font = self._base_font
            font.setFamily("Courier New")
            item.setFont(font)

            # 存储原始设备信息到 UserRole
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

            # 新增：收集纯IP列表
            ip_list = [ip for _, _, ip in devices]  # ✅ 保持原有设备数据获取逻辑
            
            # 生成格式化字符串模板（保持原有显示逻辑）
            max_lens = {
                'brand': max(len(brand) for brand, _, _ in devices),
                'model': max(len(model) for _, model, _ in devices),
                'ip': max(len(ip) for _, _, ip in devices)
            }
            fmt_str = (f"{{brand:<{max_lens['brand']}}} | "
                    f"{{model:<{max_lens['model']}}} | "
                    f"{{ip:<{max_lens['ip']}}}")

            # 添加格式化后的选项（保持原有显示逻辑）
            for brand, model, ip in devices:
                display = fmt_str.format(brand=brand, model=model, ip=ip)
                self.ip_entry.addItem(display, userData=ip)  # ✅ 显示格式不变

            # 改进自动完成配置
            completer = QCompleter(ip_list, self)  # ✅ 使用纯IP列表
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            self.ip_entry.setCompleter(completer)  # ✅ 替换为专用自动完成器

            # 保持原有控件状态设置
            self.ip_entry.setCurrentIndex(-1)
            self.ip_entry.lineEdit().clear()
            self.ip_entry.lineEdit().setPlaceholderText("Select or input IP:port")
            self.ip_entry.setInsertPolicy(QComboBox.NoInsert)
    
    def _on_ip_selected_completer(self, ip):
        """处理补全列表的选择"""
        with BlockSignals(self.ip_entry):
            self.ip_entry.setCurrentText(ip)
        self._user_selected_ip = True

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

    def _on_device_double_click(self, item: QListWidgetItem):
        """处理设备列表双击事件（切换勾选状态）"""
        if not (item.flags() & Qt.ItemIsUserCheckable):
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self.listbox_devices.viewport().update()

    @property
    def selected_devices(self) -> List[str]:
        """返回所有勾选设备的 IP 列表"""
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
        """更新设备列表中对应设备的程序包名显示"""
        def _update():
            for i in range(self.listbox_devices.count()):
                item = self.listbox_devices.item(i)
                info = item.data(Qt.UserRole)
                if not info:
                    continue
                ip = info.get("ip", "")
                if ip == device_ip:
                    # 更新 item 显示文本，仅在末尾加上包名提示
                    # model = info.get("Model", "Unknown")
                    # brand = info.get("Brand", "Unknown")
                    # version = info.get("Aversion", "Unknown")
                    display = f"{ip} | {package_name}"
                    item.setText(display)

                    # 自动添加到下拉框（避免重复）
                    if package_name not in [self.program_edit.itemText(i) for i in range(self.program_edit.count())]:
                        self.program_edit.addItem(package_name)
                    break

        QTimer.singleShot(0, _update)




