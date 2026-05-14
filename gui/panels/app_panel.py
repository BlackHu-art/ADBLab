"""App Manager tab -- package selector, lifecycle, package info, reboot, monkey, performance."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base_panel import BasePanel


class AppPanel(BasePanel):
    """App management tab."""

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)

        # ── Text, Email & Screen Capture ──
        g_ts = self._g("Text, Email & Screen Capture")
        gts_l = QVBoxLayout(g_ts)
        gts_l.setSpacing(2)
        # Row 1: Get Email | Email input | Send Text | Verification input
        r1 = QHBoxLayout()
        r1.setSpacing(4)
        self.btn_generate_email = self._b("Get Email", "envelope.svg")
        self.email_text_sender = self._in("Email address")
        self.btn_send_text = self._b("Send Text", "text-aa.svg")
        self.verification_text_sender = self._in("Verification code or text...")
        r1.addWidget(self.btn_generate_email, 1)
        r1.addWidget(self.email_text_sender, 1)
        r1.addWidget(self.btn_send_text, 1)
        r1.addWidget(self.verification_text_sender, 1)
        gts_l.addLayout(r1)
        # Row 2: Screenshot | Duration | Record Screen | Pull Video
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        self.btn_screenshot = self._b("Screenshot", "camera.svg")
        self.record_duration = self._combo(["30s", "60s", "120s", "180s", "300s"])
        self.record_duration.setCurrentText("180s")
        self.btn_screen_record = self._b("Record Screen", "video-camera.svg")
        self.btn_pull_recording = self._b("Pull Video", "film-strip.svg")
        r2.addWidget(self.btn_screenshot, 1)
        r2.addWidget(self.record_duration, 1)
        r2.addWidget(self.btn_screen_record, 1)
        r2.addWidget(self.btn_pull_recording, 1)
        gts_l.addLayout(r2)
        lo.addWidget(g_ts)

        # ── Package Manager ──
        g_pm = self._g("Package Manager")
        gl_pm = QVBoxLayout(g_pm)
        gl_pm.setSpacing(2)
        # Row 0: package selector (combo = 2-btn width, button = 1-btn width)
        r0 = QHBoxLayout()
        r0.setSpacing(4)
        self.program_edit = QComboBox()
        self.program_edit.setEditable(True)
        self.program_edit.setFont(self._font_sm)
        self.program_edit.setFixedHeight(28)
        self.program_edit.lineEdit().setFont(self._font_sm)
        self.program_edit.lineEdit().setPlaceholderText("Package name")
        self.completer = QCompleter(self.panel._package_history)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.panel._apply_completer_style(self.completer)
        self.program_edit.setCompleter(self.completer)
        self.btn_get_program = self._b("Get Package", "target.svg")
        r0.addWidget(self.program_edit, 2)
        r0.addWidget(self.btn_get_program, 1)
        gl_pm.addLayout(r0)
        # Row 1: uninstall / clear data / restart
        r1 = QHBoxLayout()
        r1.setSpacing(4)
        self.uninstall_btn = self._b("Uninstall App", "trash.svg")
        self.clear_app_data_btn = self._b("Clear Data", "eraser.svg")
        self.restart_app_btn = self._b("Restart App", "repeat.svg")
        r1.addWidget(self.uninstall_btn, 1)
        r1.addWidget(self.clear_app_data_btn, 1)
        r1.addWidget(self.restart_app_btn, 1)
        gl_pm.addLayout(r1)
        # Row 2: activity / parse / force stop
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        self.print_activity_btn = self._b("Activity Info", "scroll.svg")
        self.parse_apk_info_btn = self._b("Parse APK", "magnifying-glass.svg")
        self.btn_force_stop = self._b("Force Stop App", "stop-circle.svg")
        r2.addWidget(self.print_activity_btn, 1)
        r2.addWidget(self.parse_apk_info_btn, 1)
        r2.addWidget(self.btn_force_stop, 1)
        gl_pm.addLayout(r2)
        # Row 3: disable / enable / disable for user
        r3 = QHBoxLayout()
        r3.setSpacing(4)
        self.btn_disable_app = self._b("Disable App", "prohibit.svg")
        self.btn_enable_app = self._b("Enable App", "check-circle.svg")
        self.btn_disable_user = self._b("Disable for User", "user-switch.svg")
        r3.addWidget(self.btn_disable_app, 1)
        r3.addWidget(self.btn_enable_app, 1)
        r3.addWidget(self.btn_disable_user, 1)
        gl_pm.addLayout(r3)
        lo.addWidget(g_pm)

        # ── Reboot & Modes ──
        g_rb = self._g("Reboot & Modes")
        gl_rb = QHBoxLayout(g_rb)
        gl_rb.setSpacing(4)
        self.reboot_mode_combo = QComboBox()
        self.reboot_mode_combo.addItems(["System", "Bootloader", "Recovery", "Fastboot"])
        self.reboot_mode_combo.setFont(self._font_sm)
        self.reboot_mode_combo.setFixedHeight(28)
        self.btn_reboot_mode = self._b("Reboot", "power.svg")
        self.tcpip_port_input = self._in("5555", 45)
        self.tcpip_port_input.setFixedHeight(28)
        self.btn_tcpip_mode = self._b("TCP/IP", "wifi-high.svg")
        gl_rb.addWidget(self.reboot_mode_combo, 1)
        gl_rb.addWidget(self.btn_reboot_mode, 1)
        gl_rb.addWidget(self.tcpip_port_input, 1)
        gl_rb.addWidget(self.btn_tcpip_mode, 1)
        lo.addWidget(g_rb)

        # ── Monkey & Reports ──
        g_mr = self._g("Monkey & Reports")
        gl_mr = QVBoxLayout(g_mr)
        gl_mr.setSpacing(2)

        r_m1 = QHBoxLayout()
        r_m1.setSpacing(4)
        self.device_type = QComboBox()
        self.device_type.addItems(["STB", "Mobile"])
        self.device_type.setFont(self._font_sm)
        self.select_times = QComboBox()
        self.select_times.addItems(["100", "10000", "100000", "500000"])
        self.select_times.setFont(self._font_sm)
        self.start_monkey_btn = self._b("Start Monkey", "robot.svg")
        self.kill_monkey_btn = self._b("Kill Monkey", "skull.svg")
        r_m1.addWidget(self.device_type, 1)
        r_m1.addWidget(self.select_times, 1)
        r_m1.addWidget(self.start_monkey_btn, 1)
        r_m1.addWidget(self.kill_monkey_btn, 1)
        gl_mr.addLayout(r_m1)

        r_m2 = QHBoxLayout()
        r_m2.setSpacing(4)
        self.get_bugreport_btn = self._b("Bugreport", "bug.svg")
        self.get_anr_file_btn = self._b("ANR Files", "warning.svg")
        self.btn_retrieve_devices_logs = self._b("Retrieve Logs", "file-arrow-down.svg")
        self.btn_cleanup_logs = self._b("Cleanup Logs", "broom.svg")
        r_m2.addWidget(self.get_bugreport_btn, 1)
        r_m2.addWidget(self.get_anr_file_btn, 1)
        r_m2.addWidget(self.btn_retrieve_devices_logs, 1)
        r_m2.addWidget(self.btn_cleanup_logs, 1)
        gl_mr.addLayout(r_m2)
        lo.addWidget(g_mr)

        # ── Performance ──
        g_perf = self._g("Performance Diagnostics")
        gl_perf = QVBoxLayout(g_perf)
        gl_perf.setSpacing(2)

        r_p1 = QHBoxLayout()
        r_p1.setSpacing(4)
        self.btn_meminfo = self._b("Memory", "memory.svg")
        self.btn_cpuinfo = self._b("CPU Load", "cpu.svg")
        self.btn_battery_info = self._b("Battery", "battery-full.svg")
        self.btn_uptime = self._b("Uptime", "clock.svg")
        r_p1.addWidget(self.btn_meminfo, 1)
        r_p1.addWidget(self.btn_cpuinfo, 1)
        r_p1.addWidget(self.btn_battery_info, 1)
        r_p1.addWidget(self.btn_uptime, 1)
        gl_perf.addLayout(r_p1)

        r_p2 = QHBoxLayout()
        r_p2.setSpacing(4)
        self.btn_top = self._b("Top Snapshot", "chart-bar.svg")
        self.btn_gfx = self._b("GFX Info", "image.svg")
        self.btn_wakelock = self._b("Wakelocks", "lock.svg")
        self.btn_netstats = self._b("Net Stats", "chart-line.svg")
        r_p2.addWidget(self.btn_top, 1)
        r_p2.addWidget(self.btn_gfx, 1)
        r_p2.addWidget(self.btn_wakelock, 1)
        r_p2.addWidget(self.btn_netstats, 1)
        gl_perf.addLayout(r_p2)
        lo.addWidget(g_perf)

        lo.addStretch()
        return w

    @property
    def package_text(self) -> str:
        return self.program_edit.currentText() if hasattr(self, "program_edit") else ""

    def add_package_to_history(self, pkg: str):
        if pkg not in [self.program_edit.itemText(j) for j in range(self.program_edit.count())]:
            self.program_edit.addItem(pkg)

    def connect_signals(self):
        """Wire local widgets to SidePanelSignals."""
        LP = self.signals
        self.btn_get_program.clicked.connect(
            lambda: LP.get_program_requested.emit(self.selected_devices)
        )
        self.uninstall_btn.clicked.connect(
            lambda: LP.uninstall_app_requested.emit(self.selected_devices, self.package_text)
        )
        self.clear_app_data_btn.clicked.connect(
            lambda: LP.clear_app_data_requested.emit(self.selected_devices, self.package_text)
        )
        self.restart_app_btn.clicked.connect(
            lambda: LP.restart_app_requested.emit(self.selected_devices, self.package_text)
        )
        self.print_activity_btn.clicked.connect(
            lambda: LP.print_activity_requested.emit(self.selected_devices)
        )
        self.parse_apk_info_btn.clicked.connect(lambda: LP.parse_apk_info_requested.emit())
        self.btn_disable_app.clicked.connect(
            lambda: LP.disable_app_requested.emit(self.selected_devices, self.package_text)
        )
        self.btn_enable_app.clicked.connect(
            lambda: LP.enable_app_requested.emit(self.selected_devices, self.package_text)
        )
        self.btn_force_stop.clicked.connect(
            lambda: LP.force_stop_requested.emit(self.selected_devices, self.package_text)
        )
        self.btn_disable_user.clicked.connect(
            lambda: LP.disable_app_requested.emit(self.selected_devices, self.package_text)
        )
        # Reboot
        self.btn_reboot_mode.clicked.connect(
            lambda: LP.reboot_mode_requested.emit(self.selected_devices, self.reboot_mode_combo.currentText().lower()))
        self.btn_tcpip_mode.clicked.connect(
            lambda: LP.tcpip_mode_requested.emit(self.selected_devices, self.tcpip_port_input.text().strip() or "5555"))
        # Monkey
        self.start_monkey_btn.clicked.connect(
            lambda: LP.start_monkey_requested.emit(self.selected_devices, self.device_type.currentText(), self.package_text, self.select_times.currentText()))
        self.kill_monkey_btn.clicked.connect(lambda: LP.kill_monkey_requested.emit(self.selected_devices))
        # Reports
        self.get_bugreport_btn.clicked.connect(lambda: LP.capture_bugreport_requested.emit(self.selected_devices))
        self.get_anr_file_btn.clicked.connect(lambda: LP.pull_anr_file_requested.emit(self.selected_devices))
        self.btn_retrieve_devices_logs.clicked.connect(lambda: LP.retrieve_logs_requested.emit(self.selected_devices))
        self.btn_cleanup_logs.clicked.connect(lambda: LP.cleanup_logs_requested.emit(self.selected_devices))
        # Performance
        self.btn_meminfo.clicked.connect(lambda: LP.dumpsys_meminfo_requested.emit(self.selected_devices, self.package_text))
        self.btn_cpuinfo.clicked.connect(lambda: LP.dumpsys_cpuinfo_requested.emit(self.selected_devices))
        self.btn_battery_info.clicked.connect(lambda: LP.dumpsys_battery_requested.emit(self.selected_devices))
        self.btn_uptime.clicked.connect(lambda: LP.device_uptime_requested.emit(self.selected_devices))
        self.btn_top.clicked.connect(lambda: self._sh("top -b -n 1 -m 20"))
        self.btn_gfx.clicked.connect(lambda: self._sh(f"dumpsys gfxinfo {self.package_text} framestats | head -60"))
        self.btn_wakelock.clicked.connect(lambda: self._sh("cat /proc/wakelocks | head -40"))
        self.btn_netstats.clicked.connect(lambda: self._sh("dumpsys netstats detail | head -60"))
        # Text & Email signals
        self.btn_screenshot.clicked.connect(
            lambda: LP.screenshot_requested.emit(self.selected_devices)
        )
        self.btn_screen_record.clicked.connect(
            lambda: LP.screen_record_requested.emit(
                self.selected_devices, int(self.record_duration.currentText().replace("s", ""))
            )
        )
        self.btn_pull_recording.clicked.connect(
            lambda: LP.pull_recording_requested.emit(self.selected_devices)
        )
        self.btn_send_text.clicked.connect(
            lambda: LP.send_text_requested.emit(
                self.selected_devices, self.verification_text_sender.text()
            )
        )
        self.btn_generate_email.clicked.connect(lambda: LP.generate_email_requested.emit())
        self.email_text_sender.returnPressed.connect(
            lambda: LP.send_text_requested.emit(
                self.selected_devices, self.email_text_sender.text()
            )
        )
        self.verification_text_sender.returnPressed.connect(
            lambda: LP.send_text_requested.emit(
                self.selected_devices, self.verification_text_sender.text()
            )
        )

    def update_email(self, t):
        self.email_text_sender.setText(t)

    def update_vercode(self, t):
        self.verification_text_sender.setText(t)
