"""提供 Shell、系统设置、端口转发、电池和模拟器操作面板。"""

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QIntValidator, QRegularExpressionValidator
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from gui.panels.base_panel import BasePanel
from gui.widgets.responsive_layout import WidthPolicy


class SystemPanel(BasePanel):
    """构建系统工具控件，并向统一信号层转发用户操作。"""

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)

        g1 = self._g("Shell Command")
        gl1 = QVBoxLayout(g1)
        gl1.setSpacing(2)
        self.shell_cmd_input = self._in("adb shell <command> ...")
        self.btn_shell_run = self._b(
            "Run", "terminal-window.svg", tooltip="Run the entered shell command"
        )
        self.shell_action_binding = self._add_responsive_row(
            gl1,
            (self.shell_cmd_input, 3),
            (self.btn_shell_run, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        lo.addWidget(g1)

        g_rb = self._g("Reboot & Modes")
        gl_rb = QVBoxLayout(g_rb)
        gl_rb.setSpacing(2)
        self.reboot_mode_combo = self._combo(["System", "Bootloader", "Recovery", "Fastboot"])
        self.btn_reboot_mode = self._b(
            "Reboot", "power.svg", tooltip="Restart devices into the selected mode"
        )
        self.tcpip_port_input = self._in_int("5555", 1, 65535, 72)
        self.tcpip_port_input.setText("5555")
        self.btn_tcpip_mode = self._b(
            "TCP/IP", "wifi-high.svg", tooltip="Enable wireless ADB on the selected port"
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
        lo.addWidget(g_rb)

        gb = self._g("Broadcast & Intents")
        glb = QVBoxLayout(gb)
        glb.setSpacing(2)
        self.broadcast_action = self._in("Broadcast action")
        self.btn_broadcast = self._b(
            "Send Broadcast", "broadcast.svg", tooltip="Send the entered Android broadcast"
        )
        self._add_responsive_row(
            glb,
            (self.broadcast_action, 2),
            (self.btn_broadcast, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        self.activity_spec = self._in("Component (pkg/.Activity) or action")
        self.btn_start_activity = self._b(
            "Start Activity", "play.svg", tooltip="Launch the entered activity or intent"
        )
        self._add_responsive_row(
            glb,
            (self.activity_spec, 2),
            (self.btn_start_activity, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        self.deep_link_uri = self._in("Deep link URL")
        self.deep_link_uri.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"https?://\S+"), self.deep_link_uri)
        )
        self.btn_deep_link = self._b(
            "Open Link", "link.svg", tooltip="Open the entered URL on selected devices"
        )
        self._add_responsive_row(
            glb,
            (self.deep_link_uri, 2),
            (self.btn_deep_link, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        lo.addWidget(gb)

        g3 = self._g("Port Forwarding")
        gl3 = QVBoxLayout(g3)
        gl3.setSpacing(2)
        self.fwd_local = self._in_int("Local port", 1, 65535, 96)
        self.fwd_remote = self._in_int("Remote port", 1, 65535, 96)
        self.btn_forward = self._b(
            "Forward", "arrow-square-out.svg", tooltip="Forward a local port to the device"
        )
        self.btn_reverse = self._b(
            "Reverse", "arrow-square-in.svg", tooltip="Forward a device port to the computer"
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
            "List", "list-bullets.svg", tooltip="Show active forward port rules"
        )
        self.btn_remove_fwd = self._b(
            "Remove", "x-circle.svg", tooltip="Remove the entered forward port rule"
        )
        self.btn_list_rev = self._b(
            "List Rev", "list-bullets.svg", tooltip="Show active reverse port rules"
        )
        self.btn_remove_rev = self._b(
            "Remove Rev", "x-circle.svg", tooltip="Remove the entered reverse port rule"
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
        lo.addWidget(g3)

        gs = self._g("Service Toggles (svc)")
        gsl = QVBoxLayout(gs)
        gsl.setSpacing(2)
        _toggle_icons = {
            "WiFi": "wifi-high.svg",
            "Data": "broadcast.svg",
            "BT": "bluetooth.svg",
            "NFC": "radio-button.svg",
        }
        for row_cmds in [
            [
                ("WiFi ON", "svc wifi enable"),
                ("WiFi OFF", "svc wifi disable"),
                ("Data ON", "svc data enable"),
                ("Data OFF", "svc data disable"),
            ],
            [
                ("BT ON", "svc bluetooth enable"),
                ("BT OFF", "svc bluetooth disable"),
                ("NFC ON", "svc nfc enable"),
                ("NFC OFF", "svc nfc disable"),
            ],
        ]:
            row_buttons = []
            for n, cmd in row_cmds:
                icon = _toggle_icons.get(n.split()[0], "info.svg")
                service, state = n.split()
                verb = "Enable" if state == "ON" else "Disable"
                b = self._b(n, icon, tooltip=f"{verb} the {service} service")
                b.clicked.connect(lambda _, c=cmd: self._sh(c))
                row_buttons.append((b, 1))
            self._add_responsive_row(
                gsl,
                *row_buttons,
                compact_columns=2,
                medium_columns=2,
                wide_columns=4,
            )
        lo.addWidget(gs)

        g4 = self._g("Android Settings")
        gl4 = QVBoxLayout(g4)
        gl4.setSpacing(2)
        self.settings_ns = self._combo(["system", "global", "secure"])
        self.settings_key = self._in("Key", 70)
        self.settings_val = self._in("Value", 70)
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
            "List All", "list.svg", tooltip="Show settings in the selected namespace"
        )
        self.btn_settings_get = self._b(
            "Get Value", "magnifying-glass.svg", tooltip="Read the selected Android setting"
        )
        self.btn_settings_put = self._b(
            "Set Value", "pencil-simple.svg", tooltip="Write the selected Android setting"
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
        lo.addWidget(g4)

        g5 = self._g("System Tools")
        gl5 = QVBoxLayout(g5)
        gl5.setSpacing(2)
        self.content_uri = self._in("Content URI")
        self.btn_content_query = self._b(
            "Query", "database.svg", tooltip="Query the entered content provider URI"
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
            "Process List", "tree-structure.svg", tooltip="Show running device processes"
        )
        self.kill_pid_input = self._in_int("PID", 1, 2_147_483_647, 88)
        self.btn_kill_pid = self._b(
            "Kill PID", "skull.svg", tooltip="Terminate the entered process ID"
        )
        self.btn_pm_features = self._b(
            "Features", "star.svg", tooltip="Show supported device features"
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
            "Dumpsys", "clipboard-text.svg", tooltip="Run dumpsys for the selected service"
        )
        self.btn_kernel = self._b("Kernel", "cpu.svg", tooltip="Show the device kernel version")
        self.btn_cpuinfo_dev = self._b(
            "CPU Info", "cpu.svg", tooltip="Show device processor details"
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
        lo.addWidget(g5)

        g6 = self._g("Battery & Quick Settings")
        gl6 = QVBoxLayout(g6)
        gl6.setSpacing(2)
        self.battery_param = self._combo(["level", "status"])
        self.battery_val = self._in_int("Value", 0, 100, 88)
        self.btn_battery_set = self._b(
            "Set", "pencil-simple.svg", tooltip="Apply the simulated battery value"
        )
        self.btn_battery_reset = self._b(
            "Reset", "arrow-u-up-left.svg", tooltip="Clear simulated battery values"
        )
        self.battery_label = self._label("Battery")
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
        self.quick_setting_combo.addItem("Disable Animations", "anim_off")
        self.quick_setting_combo.addItem("Enable Animations", "anim_on")
        self.quick_setting_combo.addItem("Stay Awake", "stay_awake")
        self.btn_quick_setting = self._b(
            "Apply", "check-circle.svg", tooltip="Apply the selected quick setting"
        )
        self._add_responsive_row(
            gl6,
            (self.quick_setting_combo, 2),
            (self.btn_quick_setting, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        lo.addWidget(g6)

        g7 = self._g("IME & Emulator Control")
        gl7 = QVBoxLayout(g7)
        gl7.setSpacing(2)
        self.btn_ime_list = self._b(
            "List IME", "keyboard.svg", tooltip="Show installed input methods"
        )
        self.ime_id_input = self._in("IME ID")
        self.btn_ime_set = self._b(
            "Set IME", "pencil-simple.svg", tooltip="Activate the entered input method"
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
        self.emu_sms_sender = self._in("Sender", 65)
        self.emu_sms_text = self._in("SMS text", 70)
        self.btn_emu_sms = self._b(
            "Send SMS", "chat-text.svg", tooltip="Simulate an incoming emulator message"
        )
        self.emu_label = self._label("Emu")
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
        self.emu_call_num = self._in("Phone number")
        self.btn_emu_call = self._b(
            "Call", "phone-call.svg", tooltip="Simulate an incoming emulator call"
        )
        self.emu_geo_lon = self._in_float("Longitude", -180.0, 180.0, width=96)
        self.emu_geo_lat = self._in_float("Latitude", -90.0, 90.0, width=96)
        self.btn_emu_geo = self._b(
            "GPS", "map-pin.svg", tooltip="Set the emulator location coordinates"
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
        lo.addWidget(g7)
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
        return w

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
                bool(self._input_widget(field).text().strip())
                and self._input_widget(field).hasAcceptableInput()
                for field in fields
            )
            self._set_button_enabled(button, has_device and valid)

    def update_action_states(self) -> None:
        """供设备选择协调层刷新 System 页动作状态。"""

        self._update_action_states()

    def showEvent(self, event):
        self._update_action_states()
        super().showEvent(event)
