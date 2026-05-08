"""输入与诊断标签页 — 重启模式、Monkey 测试、报告日志、性能诊断、按键、手势、Logcat。"""

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base_panel import BasePanel


class TestingPanel(BasePanel):
    """输入与诊断标签页。"""

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(3)
        lo.setContentsMargins(4, 4, 4, 4)

        # ── Reboot & Modes ──
        g0 = self._g("Reboot & Modes")
        gl0 = QHBoxLayout(g0)
        gl0.setSpacing(4)
        self.reboot_mode_combo = QComboBox()
        self.reboot_mode_combo.addItems(["System", "Bootloader", "Recovery", "Fastboot"])
        self.reboot_mode_combo.setFont(self._font_sm)
        self.btn_reboot_mode = self._b("Reboot Mode", "Restart.svg")
        self.tcpip_port_input = self._in("5555", 45)
        self.btn_tcpip_mode = self._b("TCP/IP Mode", "Connect.svg")
        gl0.addWidget(self.reboot_mode_combo, 1)
        gl0.addWidget(self.btn_reboot_mode, 1)
        gl0.addWidget(self.tcpip_port_input, 1)
        gl0.addWidget(self.btn_tcpip_mode, 1)
        lo.addWidget(g0)

        # ── Monkey Stress Test ──
        g4 = self._g("Monkey Stress Test")
        gl4 = QVBoxLayout(g4)
        gl4.setSpacing(2)
        r4 = QHBoxLayout()
        r4.setSpacing(4)
        self.device_type = QComboBox()
        self.device_type.addItems(["STB", "Mobile"])
        self.device_type.setFont(self._font_sm)
        self.select_times = QComboBox()
        self.select_times.addItems(["100", "10000", "100000", "500000"])
        self.select_times.setFont(self._font_sm)
        self.start_monkey_btn = self._b("Start Monkey", "Monkey.svg")
        self.kill_monkey_btn = self._b("Kill Monkey", "Kill_monkey.svg")
        r4.addWidget(self.device_type, 1)
        r4.addWidget(self.select_times, 1)
        r4.addWidget(self.start_monkey_btn, 1)
        r4.addWidget(self.kill_monkey_btn, 1)
        gl4.addLayout(r4)
        lo.addWidget(g4)

        # ── Reports & Logs ──
        g5 = self._g("Reports & Logs")
        gl5 = QVBoxLayout(g5)
        gl5.setSpacing(2)
        r5a = QHBoxLayout()
        r5a.setSpacing(4)
        self.list_package_btn = self._b("List Packages", "format_list_bulleted.svg")
        self.get_bugreport_btn = self._b("Bugreport", "Bugreport.svg")
        self.get_anr_file_btn = self._b("ANR Files", "Get_ANR.svg")
        r5a.addWidget(self.list_package_btn)
        r5a.addWidget(self.get_bugreport_btn)
        r5a.addWidget(self.get_anr_file_btn)
        gl5.addLayout(r5a)
        r5b = QHBoxLayout()
        r5b.setSpacing(4)
        self.btn_retrieve_devices_logs = self._b("Retrieve Logs", "Save_alt.svg")
        self.btn_cleanup_logs = self._b("Cleanup Logs", "Cleaning_services.svg")
        r5b.addWidget(self.btn_retrieve_devices_logs)
        r5b.addWidget(self.btn_cleanup_logs)
        gl5.addLayout(r5b)
        lo.addWidget(g5)

        # ── Performance Diagnostics ──
        g6 = self._g("Performance Diagnostics")
        gl6 = QVBoxLayout(g6)
        gl6.setSpacing(2)
        r6a = QHBoxLayout()
        r6a.setSpacing(4)
        self.btn_meminfo = self._b("Memory", "Info.svg")
        self.btn_cpuinfo = self._b("CPU Load", "Info.svg")
        self.btn_battery_info = self._b("Battery", "Info.svg")
        self.btn_uptime = self._b("Uptime", "Info.svg")
        for b in (self.btn_meminfo, self.btn_cpuinfo, self.btn_battery_info, self.btn_uptime):
            r6a.addWidget(b, 1)
        gl6.addLayout(r6a)
        r6b = QHBoxLayout()
        r6b.setSpacing(4)
        self.btn_top = self._qb("Top Snapshot")
        self.btn_top.setToolTip("top -b -n 1")
        self.btn_gfx = self._qb("GFX Info")
        self.btn_gfx.setToolTip("dumpsys gfxinfo")
        self.btn_wakelock = self._qb("Wakelocks")
        self.btn_wakelock.setToolTip("kernel wakelocks")
        self.btn_netstats = self._qb("Net Stats")
        self.btn_netstats.setToolTip("dumpsys netstats")
        for b in (self.btn_top, self.btn_gfx, self.btn_wakelock, self.btn_netstats):
            r6b.addWidget(b, 1)
        gl6.addLayout(r6b)
        lo.addWidget(g6)

        # ── Logcat Filter ──
        g7 = self._g("Logcat Filter")
        gl7 = QVBoxLayout(g7)
        gl7.setSpacing(2)
        r7a = QHBoxLayout()
        r7a.setSpacing(4)
        self.logcat_buffer = QComboBox()
        self.logcat_buffer.addItems(["main", "system", "crash", "events", "radio"])
        self.logcat_buffer.setFont(self._font_sm)
        self.logcat_priority = QComboBox()
        self.logcat_priority.addItems(["V", "D", "I", "W", "E", "F"])
        self.logcat_priority.setCurrentText("V")
        self.logcat_priority.setFont(self._font_sm)
        r7a.addWidget(QLabel("Buf"))
        r7a.addWidget(self.logcat_buffer, 1)
        r7a.addWidget(QLabel("Prio"))
        r7a.addWidget(self.logcat_priority, 1)
        gl7.addLayout(r7a)
        r7b = QHBoxLayout()
        r7b.setSpacing(4)
        self.logcat_tag = self._in("Tag", 70)
        self.logcat_regex = self._in("Regex", 70)
        self.btn_logcat_filter = self._b("Fetch Logs", "Save_alt.svg")
        r7b.addWidget(self.logcat_tag, 1)
        r7b.addWidget(self.logcat_regex, 1)
        r7b.addWidget(self.btn_logcat_filter, 1)
        gl7.addLayout(r7b)
        lo.addWidget(g7)
        lo.addStretch()
        return w

    def _sh(self, c):
        self.signals.shell_command_requested.emit(self.selected_devices, c)

    def connect_signals(self):
        """Wire local widgets to SidePanelSignals."""
        LP = self.signals
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
        self.start_monkey_btn.clicked.connect(
            lambda: LP.start_monkey_requested.emit(
                self.selected_devices,
                self.device_type.currentText(),
                self.current_package,
                self.select_times.currentText(),
            )
        )
        self.kill_monkey_btn.clicked.connect(
            lambda: LP.kill_monkey_requested.emit(self.selected_devices)
        )
        self.list_package_btn.clicked.connect(
            lambda: LP.list_installed_packages_requested.emit(self.selected_devices)
        )
        self.get_bugreport_btn.clicked.connect(
            lambda: LP.capture_bugreport_requested.emit(self.selected_devices)
        )
        self.get_anr_file_btn.clicked.connect(
            lambda: LP.pull_anr_file_requested.emit(self.selected_devices)
        )
        self.btn_retrieve_devices_logs.clicked.connect(
            lambda: LP.retrieve_logs_requested.emit(self.selected_devices)
        )
        self.btn_cleanup_logs.clicked.connect(
            lambda: LP.cleanup_logs_requested.emit(self.selected_devices)
        )
        self.btn_meminfo.clicked.connect(
            lambda: LP.dumpsys_meminfo_requested.emit(self.selected_devices, self.current_package)
        )
        self.btn_cpuinfo.clicked.connect(
            lambda: LP.dumpsys_cpuinfo_requested.emit(self.selected_devices)
        )
        self.btn_battery_info.clicked.connect(
            lambda: LP.dumpsys_battery_requested.emit(self.selected_devices)
        )
        self.btn_uptime.clicked.connect(
            lambda: LP.device_uptime_requested.emit(self.selected_devices)
        )
        self.btn_top.clicked.connect(lambda: self._sh("top -b -n 1 -m 20"))
        self.btn_gfx.clicked.connect(
            lambda: self._sh(f"dumpsys gfxinfo {self.current_package} framestats | head -60")
        )
        self.btn_wakelock.clicked.connect(lambda: self._sh("cat /proc/wakelocks | head -40"))
        self.btn_netstats.clicked.connect(lambda: self._sh("dumpsys netstats detail | head -60"))
        self.btn_logcat_filter.clicked.connect(
            lambda: LP.logcat_filtered_requested.emit(
                self.selected_devices,
                self.logcat_buffer.currentText(),
                self.logcat_priority.currentText(),
                self.logcat_tag.text().strip(),
                self.logcat_regex.text().strip(),
            )
        )
