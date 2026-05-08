"""高级功能标签页 — Shell 命令、文件操作、端口转发、服务开关、系统设置、系统工具等。"""

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base_panel import BasePanel


class SystemPanel(BasePanel):
    """高级功能标签页。"""

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(3)
        lo.setContentsMargins(4, 4, 4, 4)

        # ── Shell Command ──
        g1 = self._g("Shell Command")
        gl1 = QHBoxLayout(g1)
        gl1.setSpacing(4)
        self.shell_cmd_input = self._in("adb shell <command> ...")
        self.btn_shell_run = self._b("Run", "Input.svg")
        gl1.addWidget(self.shell_cmd_input, 3)
        gl1.addWidget(self.btn_shell_run, 1)
        lo.addWidget(g1)

        # ── File Operations ──
        g2 = self._g("File Operations")
        gl2 = QVBoxLayout(g2)
        gl2.setSpacing(2)
        rf = QHBoxLayout()
        rf.setSpacing(4)
        self.file_path_input = self._in("Remote path (/sdcard/Download)")
        self.btn_file_list = self._b("List Files", "Save_alt.svg")
        rf.addWidget(self.file_path_input, 2)
        rf.addWidget(self.btn_file_list, 1)
        gl2.addLayout(rf)
        rf2 = QHBoxLayout()
        rf2.setSpacing(4)
        self.file_local_input = self._in("Local path")
        self.btn_file_push = self._b("Push to Device", "Install_app.svg")
        self.btn_file_pull = self._b("Pull from Device", "Save_alt.svg")
        rf2.addWidget(self.file_local_input, 2)
        rf2.addWidget(self.btn_file_push, 1)
        rf2.addWidget(self.btn_file_pull, 1)
        gl2.addLayout(rf2)
        lo.addWidget(g2)

        # ── Port Forwarding ──
        g3 = self._g("Port Forwarding")
        gl3 = QVBoxLayout(g3)
        gl3.setSpacing(2)
        r3a = QHBoxLayout()
        r3a.setSpacing(4)
        self.fwd_local = self._in("Local port", 90)
        self.fwd_remote = self._in("Remote port", 90)
        self.btn_forward = self._b("Forward", "Connect.svg")
        self.btn_list_fwd = self._b("List", "format_list_bulleted.svg")
        self.btn_remove_fwd = self._b("Remove", "Cleaning_services.svg")
        r3a.addWidget(self.fwd_local, 1)
        r3a.addWidget(self.fwd_remote, 1)
        r3a.addWidget(self.btn_forward, 1)
        r3a.addWidget(self.btn_list_fwd, 1)
        r3a.addWidget(self.btn_remove_fwd, 1)
        gl3.addLayout(r3a)
        r3b = QHBoxLayout()
        r3b.setSpacing(4)
        self.btn_reverse = self._b("Reverse", "Connect.svg")
        self.btn_list_rev = self._b("List Rev", "format_list_bulleted.svg")
        self.btn_remove_rev = self._b("Remove Rev", "Cleaning_services.svg")
        r3b.addWidget(self.btn_reverse)
        r3b.addWidget(self.btn_list_rev)
        r3b.addWidget(self.btn_remove_rev)
        r3b.addStretch(2)
        gl3.addLayout(r3b)
        lo.addWidget(g3)

        # ── Service Toggles (svc) ──
        gs = self._g("Service Toggles (svc)")
        gsl = QVBoxLayout(gs)
        gsl.setSpacing(2)
        rs1 = QHBoxLayout()
        rs1.setSpacing(4)
        for n, cmd in [
            ("WiFi ON", "svc wifi enable"),
            ("WiFi OFF", "svc wifi disable"),
            ("Data ON", "svc data enable"),
            ("Data OFF", "svc data disable"),
        ]:
            b = self._qb(n)
            b.clicked.connect(lambda _, c=cmd: self._sh(c))
            rs1.addWidget(b, 1)
        gsl.addLayout(rs1)
        rs2 = QHBoxLayout()
        rs2.setSpacing(4)
        for n, cmd in [
            ("BT ON", "svc bluetooth enable"),
            ("BT OFF", "svc bluetooth disable"),
            ("NFC ON", "svc nfc enable"),
            ("NFC OFF", "svc nfc disable"),
        ]:
            b = self._qb(n)
            b.clicked.connect(lambda _, c=cmd: self._sh(c))
            rs2.addWidget(b, 1)
        gsl.addLayout(rs2)
        lo.addWidget(gs)

        # ── Android Settings ──
        g4 = self._g("Android Settings")
        gl4 = QVBoxLayout(g4)
        gl4.setSpacing(2)
        r4a = QHBoxLayout()
        r4a.setSpacing(4)
        self.settings_ns = QComboBox()
        self.settings_ns.addItems(["system", "global", "secure"])
        self.settings_ns.setFont(self._font_sm)
        self.settings_key = self._in("Key", 70)
        self.settings_val = self._in("Value", 70)
        r4a.addWidget(self.settings_ns, 1)
        r4a.addWidget(self.settings_key, 1)
        r4a.addWidget(self.settings_val, 1)
        gl4.addLayout(r4a)
        r4b = QHBoxLayout()
        r4b.setSpacing(4)
        self.btn_settings_list = self._b("List All", "format_list_bulleted.svg")
        self.btn_settings_get = self._b("Get Value", "Info.svg")
        self.btn_settings_put = self._b("Set Value", "Input.svg")
        for b in (self.btn_settings_list, self.btn_settings_get, self.btn_settings_put):
            r4b.addWidget(b)
        gl4.addLayout(r4b)
        lo.addWidget(g4)

        # ── System Tools ──
        g5 = self._g("System Tools")
        gl5 = QVBoxLayout(g5)
        gl5.setSpacing(2)
        rc = QHBoxLayout()
        rc.setSpacing(4)
        self.content_uri = self._in("Content URI")
        self.btn_content_query = self._b("Query", "Info.svg")
        rc.addWidget(self.content_uri, 2)
        rc.addWidget(self.btn_content_query, 1)
        gl5.addLayout(rc)
        rp = QHBoxLayout()
        rp.setSpacing(4)
        self.btn_ps_list = self._b("Process List", "format_list_bulleted.svg")
        self.kill_pid_input = self._in("PID", 55)
        self.btn_kill_pid = self._b("Kill PID", "Kill_monkey.svg")
        self.btn_pm_features = self._b("Features", "Info.svg")
        rp.addWidget(self.btn_ps_list)
        rp.addWidget(self.kill_pid_input, 1)
        rp.addWidget(self.btn_kill_pid)
        rp.addWidget(self.btn_pm_features)
        gl5.addLayout(rp)
        rs3 = QHBoxLayout()
        rs3.setSpacing(4)
        self.dumpsys_combo = QComboBox()
        self.dumpsys_combo.setEditable(True)
        self.dumpsys_combo.setFont(self._font_sm)
        self.dumpsys_combo.addItems(
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
        self.btn_dumpsys = self._qb("Dumpsys")
        self.btn_kernel = self._qb("Kernel")
        self.btn_kernel.setToolTip("cat /proc/version")
        self.btn_cpuinfo_dev = self._qb("CPU Info")
        self.btn_cpuinfo_dev.setToolTip("cat /proc/cpuinfo")
        rs3.addWidget(self.dumpsys_combo, 2)
        rs3.addWidget(self.btn_dumpsys, 1)
        rs3.addWidget(self.btn_kernel, 1)
        rs3.addWidget(self.btn_cpuinfo_dev, 1)
        gl5.addLayout(rs3)
        lo.addWidget(g5)

        # ── Battery & Quick Settings ──
        g6 = self._g("Battery & Quick Settings")
        gl6 = QVBoxLayout(g6)
        gl6.setSpacing(2)
        rb = QHBoxLayout()
        rb.setSpacing(4)
        self.battery_param = QComboBox()
        self.battery_param.addItems(["level", "status"])
        self.battery_param.setFont(self._font_sm)
        self.battery_val = self._in("Value", 70)
        self.btn_battery_set = self._b("Set", "Input.svg")
        self.btn_battery_reset = self._b("Reset", "Restore.svg")
        rb.addWidget(QLabel("Battery"))
        rb.addWidget(self.battery_param, 1)
        rb.addWidget(self.battery_val, 1)
        rb.addWidget(self.btn_battery_set, 1)
        rb.addWidget(self.btn_battery_reset, 1)
        gl6.addLayout(rb)
        rq = QHBoxLayout()
        rq.setSpacing(4)
        self.quick_setting_combo = QComboBox()
        self.quick_setting_combo.addItem("Disable Animations", "anim_off")
        self.quick_setting_combo.addItem("Enable Animations", "anim_on")
        self.quick_setting_combo.addItem("Stay Awake", "stay_awake")
        self.quick_setting_combo.setFont(self._font_sm)
        self.btn_quick_setting = self._b("Apply", "Input.svg")
        rq.addWidget(self.quick_setting_combo, 2)
        rq.addWidget(self.btn_quick_setting, 1)
        gl6.addLayout(rq)
        lo.addWidget(g6)

        # ── IME & Emulator Control ──
        g7 = self._g("IME & Emulator Control")
        gl7 = QVBoxLayout(g7)
        gl7.setSpacing(2)
        ri = QHBoxLayout()
        ri.setSpacing(4)
        self.btn_ime_list = self._b("List IME", "format_list_bulleted.svg")
        self.ime_id_input = self._in("IME ID")
        self.btn_ime_set = self._b("Set IME", "Input.svg")
        ri.addWidget(self.btn_ime_list)
        ri.addWidget(self.ime_id_input, 2)
        ri.addWidget(self.btn_ime_set)
        gl7.addLayout(ri)
        re1 = QHBoxLayout()
        re1.setSpacing(3)
        self.emu_sms_sender = self._in("Sender", 65)
        self.emu_sms_text = self._in("SMS text", 70)
        self.btn_emu_sms = self._b("Send SMS", "Email.svg")
        re1.addWidget(QLabel("Emu"))
        re1.addWidget(self.emu_sms_sender, 1)
        re1.addWidget(self.emu_sms_text, 1)
        re1.addWidget(self.btn_emu_sms, 1)
        gl7.addLayout(re1)
        re2 = QHBoxLayout()
        re2.setSpacing(3)
        self.emu_call_num = self._in("Phone number")
        self.btn_emu_call = self._b("Call", "Input.svg")
        self.emu_geo_lon = self._in("Lon", 55)
        self.emu_geo_lat = self._in("Lat", 55)
        self.btn_emu_geo = self._b("GPS", "Input.svg")
        re2.addWidget(self.emu_call_num, 1)
        re2.addWidget(self.btn_emu_call)
        re2.addWidget(self.emu_geo_lon, 1)
        re2.addWidget(self.emu_geo_lat, 1)
        re2.addWidget(self.btn_emu_geo)
        gl7.addLayout(re2)
        lo.addWidget(g7)
        lo.addStretch()
        return w

    def _sh(self, c):
        self.signals.shell_command_requested.emit(self.selected_devices, c)

    def connect_signals(self):
        """Wire local widgets to SidePanelSignals."""
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
        self.btn_file_list.clicked.connect(
            lambda: LP.file_list_requested.emit(
                self.selected_devices, self.file_path_input.text().strip() or "/sdcard"
            )
        )
        self.btn_file_push.clicked.connect(
            lambda: LP.file_push_requested.emit(
                self.selected_devices,
                self.file_local_input.text().strip(),
                self.file_path_input.text().strip(),
            )
        )
        self.btn_file_pull.clicked.connect(
            lambda: LP.file_pull_requested.emit(
                self.selected_devices, self.file_path_input.text().strip()
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
