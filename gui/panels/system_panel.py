"""提供 Shell、系统设置、端口转发、电池和模拟器操作面板。"""

from typing import Any, cast

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QIntValidator, QRegularExpressionValidator
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, HeaderCardWidget, InfoBadge, InfoLevel

from gui.panels.base_panel import BasePanel
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role
from gui.widgets.category_stack import AdaptiveCategoryStack
from gui.widgets.responsive_layout import WidthPolicy


class SystemPanel(BasePanel):
    """构建系统工具控件，并向统一信号层转发用户操作。"""

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)
        self._system_section_groups: list[HeaderCardWidget] = []
        self._build_system_header(lo)
        self.category_stack = AdaptiveCategoryStack("system", w)

        g1 = self._card_group("Shell 命令")
        gl1 = g1.viewLayout
        gl1.setSpacing(2)
        self.shell_cmd_input = self._in("输入 adb shell 命令…")
        self.btn_shell_run = self._b(
            "执行", "terminal-window.svg", tooltip="执行输入的 Shell 命令"
        )
        self.shell_action_binding = self._add_responsive_row(
            gl1,
            (self.shell_cmd_input, 3),
            (self.btn_shell_run, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        g_rb = self._card_group("重启与模式")
        gl_rb = g_rb.viewLayout
        gl_rb.setSpacing(2)
        self.reboot_mode_combo = self._combo(["System", "Bootloader", "Recovery", "Fastboot"])
        self.btn_reboot_mode = self._b(
            "重启", "power.svg", tooltip="将所选设备重启到指定模式"
        )
        self.tcpip_port_input = self._in_int("5555", 1, 65535, 72)
        self.tcpip_port_input.setText("5555")
        self.btn_tcpip_mode = self._b(
            "启用 TCP/IP", "wifi-high.svg", tooltip="在指定端口启用无线 ADB"
        )
        self._add_responsive_row(
            gl_rb,
            (self.reboot_mode_combo, 1),
            (self.btn_reboot_mode, 1),
            (self.tcpip_port_input, 1),
            (self.btn_tcpip_mode, 1),
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )
        gb = self._card_group("广播与 Intent")
        glb = gb.viewLayout
        glb.setSpacing(2)
        self.broadcast_action = self._in("输入广播 Action")
        self.btn_broadcast = self._b(
            "发送广播", "broadcast.svg", tooltip="发送输入的 Android 广播"
        )
        self._add_responsive_row(
            glb,
            (self.broadcast_action, 2),
            (self.btn_broadcast, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        self.activity_spec = self._in("组件（包名/.Activity）或 Action")
        self.btn_start_activity = self._b(
            "启动 Activity", "play.svg", tooltip="启动输入的 Activity 或 Intent"
        )
        self._add_responsive_row(
            glb,
            (self.activity_spec, 2),
            (self.btn_start_activity, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        self.deep_link_uri = self._in("输入深层链接 URL")
        self.deep_link_uri.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"https?://\S+"), self.deep_link_uri)
        )
        self.btn_deep_link = self._b(
            "打开链接", "link.svg", tooltip="在所选设备上打开输入的 URL"
        )
        self._add_responsive_row(
            glb,
            (self.deep_link_uri, 2),
            (self.btn_deep_link, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        g3 = self._card_group("端口转发")
        gl3 = g3.viewLayout
        gl3.setSpacing(2)
        self.fwd_local = self._in_int("本机端口", 1, 65535, 96)
        self.fwd_remote = self._in_int("设备端口", 1, 65535, 96)
        self.btn_forward = self._b(
            "正向转发", "arrow-square-out.svg", tooltip="将本机端口转发到设备"
        )
        self.btn_reverse = self._b(
            "反向转发", "arrow-square-in.svg", tooltip="将设备端口转发到电脑"
        )
        self._add_responsive_row(
            gl3,
            (self.fwd_local, 1),
            (self.fwd_remote, 1),
            (self.btn_forward, 1),
            (self.btn_reverse, 1),
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )
        self.btn_list_fwd = self._b(
            "正向规则", "list-bullets.svg", tooltip="显示当前正向端口转发规则"
        )
        self.btn_remove_fwd = self._b(
            "移除正向", "x-circle.svg", tooltip="移除输入的正向端口转发规则"
        )
        self.btn_list_rev = self._b(
            "反向规则", "list-bullets.svg", tooltip="显示当前反向端口转发规则"
        )
        self.btn_remove_rev = self._b(
            "移除反向", "x-circle.svg", tooltip="移除输入的反向端口转发规则"
        )
        self._add_responsive_row(
            gl3,
            (self.btn_list_fwd, 1),
            (self.btn_remove_fwd, 1),
            (self.btn_list_rev, 1),
            (self.btn_remove_rev, 1),
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )
        gs = self._card_group("系统服务开关 (svc)")
        gsl = gs.viewLayout
        gsl.setSpacing(2)
        _toggle_icons = {
            "WiFi": "wifi-high.svg",
            "Data": "broadcast.svg",
            "BT": "bluetooth.svg",
            "NFC": "radio-button.svg",
        }
        for row_cmds in [
            [
                ("启用 WiFi", "svc wifi enable"),
                ("关闭 WiFi", "svc wifi disable"),
                ("启用数据", "svc data enable"),
                ("关闭数据", "svc data disable"),
            ],
            [
                ("启用蓝牙", "svc bluetooth enable"),
                ("关闭蓝牙", "svc bluetooth disable"),
                ("启用 NFC", "svc nfc enable"),
                ("关闭 NFC", "svc nfc disable"),
            ],
        ]:
            row_buttons = []
            for n, cmd in row_cmds:
                service = cmd.split()[1]
                icon_key = {
                    "wifi": "WiFi",
                    "data": "Data",
                    "bluetooth": "BT",
                    "nfc": "NFC",
                }[service]
                icon = _toggle_icons.get(icon_key, "info.svg")
                b = self._b(n, icon, tooltip=f"{n} 服务")
                b.clicked.connect(lambda _, c=cmd: self._sh(c))
                row_buttons.append((b, 1))
            self._add_responsive_row(
                gsl,
                *row_buttons,
                compact_columns=2,
                medium_columns=2,
                wide_columns=4,
            )
        g4 = self._card_group("Android 设置")
        gl4 = g4.viewLayout
        gl4.setSpacing(2)
        self.settings_ns = self._combo(["system", "global", "secure"])
        self.settings_key = self._in("设置键", 70)
        self.settings_val = self._in("设置值", 70)
        self._add_responsive_row(
            gl4,
            (self.settings_ns, 1),
            (self.settings_key, 1),
            (self.settings_val, 1),
            compact_columns=1,
            medium_columns=3,
            wide_columns=3,
        )
        self.btn_settings_list = self._b(
            "列出全部", "list.svg", tooltip="显示所选命名空间中的设置"
        )
        self.btn_settings_get = self._b(
            "读取值", "magnifying-glass.svg", tooltip="读取指定 Android 设置"
        )
        self.btn_settings_put = self._b(
            "写入值", "pencil-simple.svg", tooltip="写入指定 Android 设置"
        )
        self._add_responsive_row(
            gl4,
            self.btn_settings_list,
            self.btn_settings_get,
            self.btn_settings_put,
            compact_columns=1,
            medium_columns=3,
            wide_columns=3,
        )
        g5 = self._card_group("系统工具")
        gl5 = g5.viewLayout
        gl5.setSpacing(2)
        self.content_uri = self._in("输入 Content URI")
        self.btn_content_query = self._b(
            "查询", "database.svg", tooltip="查询输入的 Content Provider URI"
        )
        self._add_responsive_row(
            gl5,
            (self.content_uri, 2),
            (self.btn_content_query, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        self.btn_ps_list = self._b(
            "进程列表", "tree-structure.svg", tooltip="显示设备上正在运行的进程"
        )
        self.kill_pid_input = self._in_int("PID", 1, 2_147_483_647, 88)
        self.btn_kill_pid = self._b(
            "结束 PID", "skull.svg", tooltip="结束输入的进程 ID"
        )
        self.btn_pm_features = self._b(
            "设备特性", "star.svg", tooltip="显示设备支持的系统特性"
        )
        self._add_responsive_row(
            gl5,
            self.btn_ps_list,
            (self.kill_pid_input, 1),
            self.btn_kill_pid,
            self.btn_pm_features,
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )
        self.dumpsys_combo = self._combo_editable(
            [
                "",
                "package",
                "activity",
                "window",
                "wifi",
                "battery",
                "power",
                "alarm",
                "usb",
                "input",
                "notification",
                "connectivity",
                "audio",
                "display",
                "meminfo",
                "cpuinfo",
                "netstats",
            ]
        )
        self.btn_dumpsys = self._b(
            "运行 Dumpsys", "clipboard-text.svg", tooltip="对所选服务运行 dumpsys"
        )
        self.btn_kernel = self._b("内核版本", "cpu.svg", tooltip="显示设备内核版本")
        self.btn_cpuinfo_dev = self._b(
            "CPU 信息", "cpu.svg", tooltip="显示设备处理器详情"
        )
        self._add_responsive_row(
            gl5,
            (self.dumpsys_combo, 2),
            (self.btn_dumpsys, 1),
            (self.btn_kernel, 1),
            (self.btn_cpuinfo_dev, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=4,
        )
        g6 = self._card_group("电池与快捷设置")
        gl6 = g6.viewLayout
        gl6.setSpacing(2)
        self.battery_param = self._combo(["level", "status"])
        self.battery_val = self._in_int("数值", 0, 100, 88)
        self.btn_battery_set = self._b(
            "应用", "pencil-simple.svg", tooltip="应用模拟电池数值"
        )
        self.btn_battery_reset = self._b(
            "重置", "arrow-u-up-left.svg", tooltip="清除模拟电池数值"
        )
        self.battery_label = self._label("电池")
        self._battery_value_pair = self._atomic_form_pair(
            self.battery_label,
            self.battery_val,
        )
        self.battery_parameter_binding = self._add_responsive_row(
            gl6,
            self._battery_value_pair,
            (self.battery_param, 1),
            (self.btn_battery_set, 1),
            (self.btn_battery_reset, 1),
            policies=(
                WidthPolicy.NATURAL,
                WidthPolicy.SHRINKABLE,
                WidthPolicy.NATURAL,
                WidthPolicy.NATURAL,
            ),
            compact_columns=1,
            medium_columns=2,
            wide_columns=4,
        )
        self.quick_setting_combo = self._combo()
        self.quick_setting_combo.addItem("关闭动画", "anim_off")
        self.quick_setting_combo.addItem("启用动画", "anim_on")
        self.quick_setting_combo.addItem("保持唤醒", "stay_awake")
        self.btn_quick_setting = self._b(
            "应用设置", "check-circle.svg", tooltip="应用所选快捷设置"
        )
        self._add_responsive_row(
            gl6,
            (self.quick_setting_combo, 2),
            (self.btn_quick_setting, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        g7 = self._card_group("输入法与模拟器控制")
        gl7 = g7.viewLayout
        gl7.setSpacing(2)
        self.btn_ime_list = self._b(
            "输入法列表", "keyboard.svg", tooltip="显示已安装的输入法"
        )
        self.ime_id_input = self._in("输入法 ID")
        self.btn_ime_set = self._b(
            "切换输入法", "pencil-simple.svg", tooltip="启用输入的输入法 ID"
        )
        self._add_responsive_row(
            gl7,
            self.btn_ime_list,
            (self.ime_id_input, 2),
            self.btn_ime_set,
            compact_columns=1,
            medium_columns=3,
            wide_columns=3,
        )
        self.emu_sms_sender = self._in("发件人", 65)
        self.emu_sms_text = self._in("短信内容", 70)
        self.btn_emu_sms = self._b(
            "模拟短信", "chat-text.svg", tooltip="模拟一条收到的短信"
        )
        self.emu_label = self._label("模拟器")
        self._emu_sender_pair = self._atomic_form_pair(self.emu_label, self.emu_sms_sender)
        self.emu_sms_binding = self._add_responsive_row(
            gl7,
            self._emu_sender_pair,
            (self.emu_sms_text, 1),
            (self.btn_emu_sms, 1),
            spacing=3,
            policies=(
                WidthPolicy.NATURAL,
                WidthPolicy.SHRINKABLE,
                WidthPolicy.NATURAL,
            ),
            compact_columns=1,
            medium_columns=2,
            wide_columns=3,
        )
        self.emu_call_num = self._in("电话号码")
        self.btn_emu_call = self._b(
            "模拟来电", "phone-call.svg", tooltip="模拟模拟器收到来电"
        )
        self.emu_geo_lon = self._in_float("经度", -180.0, 180.0, width=96)
        self.emu_geo_lat = self._in_float("纬度", -90.0, 90.0, width=96)
        self.btn_emu_geo = self._b(
            "设置 GPS", "map-pin.svg", tooltip="设置模拟器位置坐标"
        )
        self._add_responsive_row(
            gl7,
            (self.emu_call_num, 1),
            self.btn_emu_call,
            (self.emu_geo_lon, 1),
            (self.emu_geo_lat, 1),
            self.btn_emu_geo,
            spacing=3,
            compact_columns=2,
            medium_columns=2,
            wide_columns=5,
        )
        self.category_stack.add_category(
            "commands",
            "命令与启动",
            (g1, g_rb, gb),
        )
        self.category_stack.add_category(
            "connectivity",
            "连接与服务",
            (g3, gs),
        )
        self.category_stack.add_category(
            "settings",
            "设置与工具",
            (g4, g5),
        )
        self.category_stack.add_category(
            "device",
            "设备与模拟器",
            (g6, g7),
        )
        self.category_stack.current_changed.connect(
            lambda _key: self.apply_responsive_width(0)
        )
        lo.addWidget(self.category_stack)
        lo.addStretch()
        self.battery_param.currentTextChanged.connect(self._on_battery_param_changed)
        for field in (
            self.shell_cmd_input,
            self.tcpip_port_input,
            self.broadcast_action,
            self.activity_spec,
            self.deep_link_uri,
            self.fwd_local,
            self.fwd_remote,
            self.settings_key,
            self.settings_val,
            self.content_uri,
            self.kill_pid_input,
            self.battery_val,
            self.ime_id_input,
            self.emu_sms_sender,
            self.emu_sms_text,
            self.emu_call_num,
            self.emu_geo_lon,
            self.emu_geo_lat,
        ):
            field.textChanged.connect(lambda _text: self._update_action_states())
        self._action_buttons = tuple(w.findChildren(QPushButton))
        BaseStyles.theme_changed.connect(self._on_theme_changed_system)
        return w

    # ── 卡片化页头与分区视觉 ─────────────────────────────────────────────

    def _card_group(self, t: str) -> HeaderCardWidget:
        """创建 qfluentwidgets Card 分区；标题与内容区由 Card 提供。"""

        card = self._card(t)
        self._system_section_groups.append(card)
        return card

    def _build_system_header(self, lo) -> None:
        """构建页头：标题、副标题与设备可用性状态徽标。"""

        header = QWidget()
        header.setObjectName("systemHeader")
        self.panel_header = header
        hl = QVBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 4)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.system_title = apply_label_role(
            BodyLabel("系统与诊断"), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self.system_status_badge = InfoBadge("未选择", self)
        self.system_status_badge.setObjectName("systemStatusBadge")
        self.system_status_badge.setProperty("fontRole", FontRole.UI.value)
        self.system_status_badge.setFont(self._font_sm)
        # InfoBadge 默认对鼠标透明，会吞掉 tooltip 的悬停事件，这里恢复接收。
        self.system_status_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
        )
        self.system_status_badge.setToolTip("系统操作的设备选择状态")
        title_row.addWidget(self.system_title)
        title_row.addStretch(1)
        title_row.addWidget(self.system_status_badge)
        self.system_subtitle = apply_label_role(
            BodyLabel("Shell、系统设置、端口转发和模拟器工具"),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        # 页签字体爆发测试断言面板内不存在 UI_SMALL 角色控件（历史不变式），
        # 副标题用 UI 角色 + 次级文字色维持视觉层级。
        self.system_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self.system_subtitle)
        lo.addWidget(header)
        self._apply_system_header_style()

    def _apply_system_header_style(self) -> None:
        """按当前主题刷新页头徽标颜色。"""

        if not hasattr(self, "system_title"):
            return
        self._refresh_system_status_badge()

    def _refresh_system_status_badge(self) -> None:
        """按设备选中状态刷新徽标；绿=可用，灰=未选择设备。"""

        if not hasattr(self, "system_status_badge"):
            return
        has_device = bool(self.selected_devices)
        self.system_status_badge.setText("可操作" if has_device else "未选择")
        self.system_status_badge.setLevel(InfoLevel.SUCCESS if has_device else InfoLevel.INFOAMTION)

    def _on_theme_changed_system(self, _name: str) -> None:
        """主题切换时重建页头样式（分区 Card 自动跟随主题）。"""

        self._apply_system_header_style()

    def connect_signals(self):
        LP = self.signals
        self.btn_shell_run.clicked.connect(
            lambda: LP.shell_command_requested.emit(
                self.selected_devices, self.shell_cmd_input.text()
            )
        )
        self.shell_cmd_input.returnPressed.connect(
            lambda: LP.shell_command_requested.emit(
                self.selected_devices, self.shell_cmd_input.text()
            )
        )
        self.btn_reboot_mode.clicked.connect(
            lambda: LP.reboot_mode_requested.emit(
                self.selected_devices, self.reboot_mode_combo.currentText().lower()
            )
        )
        self.btn_tcpip_mode.clicked.connect(
            lambda: self._submit_device_action(
                (self.tcpip_port_input,),
                lambda devices: LP.tcpip_mode_requested.emit(
                    devices, self.tcpip_port_input.text().strip()
                ),
            )
        )
        self.btn_broadcast.clicked.connect(
            lambda: LP.send_broadcast_requested.emit(
                self.selected_devices, self.broadcast_action.text().strip()
            )
        )
        self.btn_start_activity.clicked.connect(
            lambda: LP.start_activity_requested.emit(
                self.selected_devices, self.activity_spec.text().strip()
            )
        )
        self.btn_deep_link.clicked.connect(
            lambda: self._submit_device_action(
                (self.deep_link_uri,),
                lambda devices: LP.open_deep_link_requested.emit(
                    devices, self.deep_link_uri.text().strip()
                ),
            )
        )
        self.btn_forward.clicked.connect(
            lambda: self._submit_device_action(
                (self.fwd_local, self.fwd_remote),
                lambda devices: LP.forward_port_requested.emit(
                    devices, self.fwd_local.text().strip(), self.fwd_remote.text().strip()
                ),
            )
        )
        self.btn_list_fwd.clicked.connect(
            lambda: LP.list_forwards_requested.emit(self.selected_devices)
        )
        self.btn_remove_fwd.clicked.connect(
            lambda: LP.remove_forwards_requested.emit(self.selected_devices)
        )
        self.btn_reverse.clicked.connect(
            lambda: self._submit_device_action(
                (self.fwd_remote, self.fwd_local),
                lambda devices: LP.reverse_port_requested.emit(
                    devices, self.fwd_remote.text().strip(), self.fwd_local.text().strip()
                ),
            )
        )
        self.btn_list_rev.clicked.connect(
            lambda: LP.list_reverse_requested.emit(self.selected_devices)
        )
        self.btn_remove_rev.clicked.connect(
            lambda: LP.remove_reverse_requested.emit(self.selected_devices)
        )
        self.btn_settings_list.clicked.connect(
            lambda: LP.settings_list_requested.emit(
                self.selected_devices, self.settings_ns.currentText()
            )
        )
        self.btn_settings_get.clicked.connect(
            lambda: LP.settings_get_requested.emit(
                self.selected_devices,
                self.settings_ns.currentText(),
                self.settings_key.text().strip(),
            )
        )
        self.btn_settings_put.clicked.connect(
            lambda: LP.settings_put_requested.emit(
                self.selected_devices,
                self.settings_ns.currentText(),
                self.settings_key.text().strip(),
                self.settings_val.text().strip(),
            )
        )
        self.btn_content_query.clicked.connect(
            lambda: LP.content_query_requested.emit(
                self.selected_devices, self.content_uri.text().strip()
            )
        )
        self.btn_ps_list.clicked.connect(
            lambda: LP.list_processes_requested.emit(self.selected_devices)
        )
        self.btn_kill_pid.clicked.connect(
            lambda: self._submit_device_action(
                (self.kill_pid_input,),
                lambda devices: LP.kill_process_requested.emit(
                    devices, self.kill_pid_input.text().strip()
                ),
            )
        )
        self.btn_battery_set.clicked.connect(
            lambda: self._submit_device_action(
                (self.battery_val,),
                lambda devices: LP.battery_set_requested.emit(
                    devices,
                    self.battery_param.currentText(),
                    self.battery_val.text().strip(),
                ),
            )
        )
        self.btn_battery_reset.clicked.connect(
            lambda: LP.battery_reset_requested.emit(self.selected_devices)
        )
        self.btn_quick_setting.clicked.connect(
            lambda: LP.quick_setting_requested.emit(
                self.selected_devices, self.quick_setting_combo.currentData()
            )
        )
        self.btn_ime_list.clicked.connect(lambda: LP.ime_list_requested.emit(self.selected_devices))
        self.btn_ime_set.clicked.connect(
            lambda: LP.ime_set_requested.emit(
                self.selected_devices, self.ime_id_input.text().strip()
            )
        )
        self.btn_pm_features.clicked.connect(
            lambda: LP.pm_features_requested.emit(self.selected_devices)
        )
        self.btn_emu_sms.clicked.connect(
            lambda: LP.emu_sms_requested.emit(
                self.selected_devices,
                self.emu_sms_sender.text().strip(),
                self.emu_sms_text.text().strip(),
            )
        )
        self.btn_emu_call.clicked.connect(
            lambda: LP.emu_call_requested.emit(
                self.selected_devices, self.emu_call_num.text().strip()
            )
        )
        self.btn_emu_geo.clicked.connect(
            lambda: self._submit_device_action(
                (self.emu_geo_lon, self.emu_geo_lat),
                lambda devices: LP.emu_geo_requested.emit(
                    devices,
                    self.emu_geo_lon.text().strip(),
                    self.emu_geo_lat.text().strip(),
                ),
            )
        )
        self.btn_dumpsys.clicked.connect(
            lambda: LP.dumpsys_service_requested.emit(
                self.selected_devices,
                self.dumpsys_combo.currentText().strip(),
            )
        )
        self.btn_kernel.clicked.connect(
            lambda: LP.kernel_version_requested.emit(self.selected_devices)
        )
        self.btn_cpuinfo_dev.clicked.connect(
            lambda: LP.cpu_info_requested.emit(self.selected_devices)
        )
        self._update_action_states()

    def _on_battery_param_changed(self, param: str) -> None:
        maximum = 100 if param == "level" else 5
        minimum = 0 if param == "level" else 1
        self.battery_val.setValidator(QIntValidator(minimum, maximum, self.battery_val))
        self._update_action_states()

    def _submit_device_action(self, fields, callback) -> bool:
        devices = list(dict.fromkeys(device for device in self.selected_devices if device))
        if not devices or (fields and not self._validate_fields(*fields)):
            self._update_action_states()
            return False
        callback(devices)
        return True

    def _update_action_states(self) -> None:
        """按设备和字段有效性更新 System 页动作状态。"""

        self._refresh_system_status_badge()
        if not hasattr(self, "btn_shell_run"):
            return
        has_device = bool(self.selected_devices)
        for button in getattr(self, "_action_buttons", ()):
            self._set_button_enabled(button, has_device)

        field_requirements = {
            self.btn_shell_run: (self.shell_cmd_input,),
            self.btn_tcpip_mode: (self.tcpip_port_input,),
            self.btn_broadcast: (self.broadcast_action,),
            self.btn_start_activity: (self.activity_spec,),
            self.btn_deep_link: (self.deep_link_uri,),
            self.btn_forward: (self.fwd_local, self.fwd_remote),
            self.btn_reverse: (self.fwd_remote, self.fwd_local),
            self.btn_settings_get: (self.settings_key,),
            self.btn_settings_put: (self.settings_key, self.settings_val),
            self.btn_content_query: (self.content_uri,),
            self.btn_kill_pid: (self.kill_pid_input,),
            self.btn_battery_set: (self.battery_val,),
            self.btn_ime_set: (self.ime_id_input,),
            self.btn_emu_sms: (self.emu_sms_sender, self.emu_sms_text),
            self.btn_emu_call: (self.emu_call_num,),
            self.btn_emu_geo: (self.emu_geo_lon, self.emu_geo_lat),
        }
        for button, fields in field_requirements.items():
            valid = all(
                bool(cast(Any, self._input_widget(field)).text().strip())
                and cast(Any, self._input_widget(field)).hasAcceptableInput()
                for field in fields
            )
            self._set_button_enabled(button, has_device and valid)

    def update_action_states(self) -> None:
        """供设备选择协调层刷新 System 页动作状态。"""

        self._update_action_states()

    def showEvent(self, event):
        self._update_action_states()
        super().showEvent(event)
