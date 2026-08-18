"""提供 Shell、系统设置、端口转发、电池和模拟器操作面板。"""

from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.panels.base_panel import BasePanel


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
        self.btn_shell_run = self._b("Run", "terminal-window.svg")
        self._add_responsive_row(
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
        self.btn_reboot_mode = self._b("Reboot", "power.svg")
        self.tcpip_port_input = self._in("5555", 52)
        self.btn_tcpip_mode = self._b("TCP/IP", "wifi-high.svg")
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
        self.btn_broadcast = self._b("Send Broadcast", "broadcast.svg")
        self._add_responsive_row(
            glb,
            (self.broadcast_action, 2),
            (self.btn_broadcast, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        self.activity_spec = self._in("Component (pkg/.Activity) or action")
        self.btn_start_activity = self._b("Start Activity", "play.svg")
        self._add_responsive_row(
            glb,
            (self.activity_spec, 2),
            (self.btn_start_activity, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        self.deep_link_uri = self._in("Deep link URL")
        self.btn_deep_link = self._b("Open Link", "link.svg")
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
        self.fwd_local = self._in("Local port", 80)
        self.fwd_remote = self._in("Remote port", 80)
        self.btn_forward = self._b("Forward", "arrow-square-out.svg")
        self.btn_reverse = self._b("Reverse", "arrow-square-in.svg")
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
        self.btn_list_fwd = self._b("List", "list-bullets.svg")
        self.btn_remove_fwd = self._b("Remove", "x-circle.svg")
        self.btn_list_rev = self._b("List Rev", "list-bullets.svg")
        self.btn_remove_rev = self._b("Remove Rev", "x-circle.svg")
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
                b = self._b(n, icon)
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
        self.btn_settings_list = self._b("List All", "list.svg")
        self.btn_settings_get = self._b("Get Value", "magnifying-glass.svg")
        self.btn_settings_put = self._b("Set Value", "pencil-simple.svg")
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
        self.btn_content_query = self._b("Query", "database.svg")
        self._add_responsive_row(
            gl5,
            (self.content_uri, 2),
            (self.btn_content_query, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        self.btn_ps_list = self._b("Process List", "tree-structure.svg")
        self.kill_pid_input = self._in("PID", 55)
        self.btn_kill_pid = self._b("Kill PID", "skull.svg")
        self.btn_pm_features = self._b("Features", "star.svg")
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
        self.btn_dumpsys = self._b("Dumpsys", "clipboard-text.svg")
        self.btn_kernel = self._b("Kernel", "cpu.svg")
        self.btn_kernel.setToolTip("cat /proc/version")
        self.btn_cpuinfo_dev = self._b("CPU Info", "cpu.svg")
        self.btn_cpuinfo_dev.setToolTip("cat /proc/cpuinfo")
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
        self.battery_val = self._in("Value", 70)
        self.btn_battery_set = self._b("Set", "pencil-simple.svg")
        self.btn_battery_reset = self._b("Reset", "arrow-u-up-left.svg")
        battery_label = self._label("Battery")
        self._add_responsive_row(
            gl6,
            battery_label,
            (self.battery_param, 1),
            (self.battery_val, 1),
            (self.btn_battery_set, 1),
            (self.btn_battery_reset, 1),
            compact_columns=2,
            medium_columns=2,
            wide_columns=5,
        )
        self.quick_setting_combo = self._combo()
        self.quick_setting_combo.addItem("Disable Animations", "anim_off")
        self.quick_setting_combo.addItem("Enable Animations", "anim_on")
        self.quick_setting_combo.addItem("Stay Awake", "stay_awake")
        self.btn_quick_setting = self._b("Apply", "check-circle.svg")
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
        self.btn_ime_list = self._b("List IME", "keyboard.svg")
        self.ime_id_input = self._in("IME ID")
        self.btn_ime_set = self._b("Set IME", "pencil-simple.svg")
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
        self.btn_emu_sms = self._b("Send SMS", "chat-text.svg")
        emu_label = self._label("Emu")
        self._add_responsive_row(
            gl7,
            emu_label,
            (self.emu_sms_sender, 1),
            (self.emu_sms_text, 1),
            (self.btn_emu_sms, 1),
            spacing=3,
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )
        self.emu_call_num = self._in("Phone number")
        self.btn_emu_call = self._b("Call", "phone-call.svg")
        self.emu_geo_lon = self._in("Lon", 55)
        self.emu_geo_lat = self._in("Lat", 55)
        self.btn_emu_geo = self._b("GPS", "map-pin.svg")
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
            lambda: LP.tcpip_mode_requested.emit(
                self.selected_devices, self.tcpip_port_input.text().strip() or "5555"
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
            lambda: LP.open_deep_link_requested.emit(
                self.selected_devices, self.deep_link_uri.text().strip()
            )
        )
        self.btn_forward.clicked.connect(
            lambda: LP.forward_port_requested.emit(
                self.selected_devices, self.fwd_local.text().strip(), self.fwd_remote.text().strip()
            )
        )
        self.btn_list_fwd.clicked.connect(
            lambda: LP.list_forwards_requested.emit(self.selected_devices)
        )
        self.btn_remove_fwd.clicked.connect(
            lambda: LP.remove_forwards_requested.emit(self.selected_devices)
        )
        self.btn_reverse.clicked.connect(
            lambda: LP.reverse_port_requested.emit(
                self.selected_devices, self.fwd_remote.text().strip(), self.fwd_local.text().strip()
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
            lambda: LP.kill_process_requested.emit(
                self.selected_devices, self.kill_pid_input.text().strip()
            )
        )
        self.btn_battery_set.clicked.connect(
            lambda: LP.battery_set_requested.emit(
                self.selected_devices,
                self.battery_param.currentText(),
                self.battery_val.text().strip(),
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
            lambda: LP.emu_geo_requested.emit(
                self.selected_devices,
                self.emu_geo_lon.text().strip(),
                self.emu_geo_lat.text().strip(),
            )
        )
        self.btn_dumpsys.clicked.connect(
            lambda: self._sh(
                f"dumpsys {self.dumpsys_combo.currentText().strip()} | head -80"
                if self.dumpsys_combo.currentText().strip()
                else "service list"
            )
        )
        self.btn_kernel.clicked.connect(lambda: self._sh("cat /proc/version"))
        self.btn_cpuinfo_dev.clicked.connect(lambda: self._sh("cat /proc/cpuinfo | head -40"))
