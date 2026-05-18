"""App Manager tab -- package selector, lifecycle, package info, monkey, performance."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
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
        # Row 2: Screenshot | Duration | Record | Stop
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        self.btn_screenshot = self._b("Screenshot", "camera.svg")
        self.record_duration = self._combo(["10s", "20s", "30s", "60s", "120s", "180s", "300s"])
        self.record_duration.setCurrentText("30s")
        self.btn_screen_record = self._b("Record", "video-camera.svg")
        self.btn_stop_record = self._b("Stop Rec", "stop-circle.svg")
        self.btn_stop_record.setEnabled(False)
        r2.addWidget(self.btn_screenshot, 1)
        r2.addWidget(self.record_duration, 1)
        r2.addWidget(self.btn_screen_record, 1)
        r2.addWidget(self.btn_stop_record, 1)
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

        # ── Monkey ──
        g_m = self._g("Monkey")
        gm_l = QVBoxLayout(g_m)
        gm_l.setSpacing(3)

        EVENTS_OPTS = ["100", "500", "1K", "5K", "10K", "50K", "100K", "500K"]
        THROTTLE_OPTS = ["0", "100", "200", "300", "500", "1000", "2000"]
        PCT_OPTS = ["0", "5", "10", "15", "20", "25", "30", "40", "50"]

        def _mk_combo(items):
            c = QComboBox()
            c.setEditable(True)
            c.addItems(items)
            c.setFont(self._font_sm)
            c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return c

        # ── Unified grid: Events/Throttle + Event mix + Total ──
        g_pct = QGridLayout()
        g_pct.setSpacing(3)

        # Row 0: Events | Throttle | Total
        lbl_ev = QLabel("Events:")
        lbl_ev.setFont(self._font_sm)
        self.monkey_events = _mk_combo(EVENTS_OPTS)
        lbl_th = QLabel("Throttle:")
        lbl_th.setFont(self._font_sm)
        self.monkey_throttle = _mk_combo(THROTTLE_OPTS)
        lbl_ms = QLabel("ms")
        lbl_ms.setFont(self._font_sm)
        self._pct_total_lbl = QLabel("Total: --")
        self._pct_total_lbl.setFont(self._font_sm)
        g_pct.addWidget(lbl_ev, 0, 0)
        g_pct.addWidget(self.monkey_events, 0, 1)
        g_pct.addWidget(lbl_th, 0, 2)
        g_pct.addWidget(self.monkey_throttle, 0, 3)
        g_pct.addWidget(lbl_ms, 0, 4)
        g_pct.addWidget(self._pct_total_lbl, 0, 5)

        # Row 1-3: Event mix — 3 per row
        pct_configs = [
            ("Touch", "touch"),   ("Motion", "motion"),  ("Trackball", "trackball"),
            ("Nav", "nav"),       ("MjNav", "majornav"), ("Syskey", "syskeys"),
            ("AppSw", "appswitch"), ("Any", "anyevent"),  ("Pinch", "pinch"),
        ]
        self._monkey_pct_combos = {}
        for i, (label, key) in enumerate(pct_configs):
            lbl = QLabel(f"{label}:")
            lbl.setFont(self._font_sm)
            c = _mk_combo(PCT_OPTS)
            c.currentTextChanged.connect(self._update_pct_total)
            self._monkey_pct_combos[key] = c
            row, col = divmod(i, 3)
            g_pct.addWidget(lbl, row + 1, col * 2)
            g_pct.addWidget(c, row + 1, col * 2 + 1)
        gm_l.addLayout(g_pct)

        # Flags row
        r_flags = QHBoxLayout()
        r_flags.setSpacing(8)
        self.monkey_chk_crashes = QCheckBox("Ignore crashes")
        self.monkey_chk_timeouts = QCheckBox("Ignore timeouts")
        self.monkey_chk_security = QCheckBox("Ignore security")
        for cb in (self.monkey_chk_crashes, self.monkey_chk_timeouts, self.monkey_chk_security):
            cb.setFont(self._font_sm)
            r_flags.addWidget(cb)
        gm_l.addLayout(r_flags)

        # Action row
        r_act = QHBoxLayout()
        r_act.setSpacing(4)
        self.start_monkey_btn = self._b("Start", "robot.svg")
        self.kill_monkey_btn = self._b("Stop", "skull.svg")
        r_act.addWidget(self.start_monkey_btn, 1)
        r_act.addWidget(self.kill_monkey_btn, 1)
        gm_l.addLayout(r_act)
        lo.addWidget(g_m)

        # ── Reports ──
        g_r = self._g("Reports")
        gr_l = QHBoxLayout(g_r)
        gr_l.setSpacing(4)
        self.get_bugreport_btn = self._b("Bugreport", "bug.svg")
        self.get_anr_file_btn = self._b("ANR Files", "warning.svg")
        self.btn_retrieve_devices_logs = self._b("Retrieve Logs", "file-arrow-down.svg")
        self.btn_cleanup_logs = self._b("Cleanup Logs", "broom.svg")
        gr_l.addWidget(self.get_bugreport_btn, 1)
        gr_l.addWidget(self.get_anr_file_btn, 1)
        gr_l.addWidget(self.btn_retrieve_devices_logs, 1)
        gr_l.addWidget(self.btn_cleanup_logs, 1)
        lo.addWidget(g_r)

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

        # Load last-used monkey params from settings
        self._load_monkey_params()
        return w

    # ── Monkey params persistence ───────────────────────────────────────

    def _load_monkey_params(self):
        from core.settings_manager import AppSettings
        p = AppSettings.instance().get("monkey_params", {})

        _EV_REV = {1000: "1K", 5000: "5K", 10000: "10K", 50000: "50K",
                   100000: "100K", 500000: "500K"}
        _events = int(p.get("events", 10000))
        self.monkey_events.setCurrentText(_EV_REV.get(_events, str(_events)))
        self.monkey_throttle.setCurrentText(str(p.get("throttle", 300)))
        for key, c in self._monkey_pct_combos.items():
            c.setCurrentText(str(p.get(key, 20)))
        self.monkey_chk_crashes.setChecked(p.get("ignore_crashes", True))
        self.monkey_chk_timeouts.setChecked(p.get("ignore_timeouts", True))
        self.monkey_chk_security.setChecked(p.get("ignore_security", True))
        self._update_pct_total()

    def _collect_monkey_params(self) -> dict:
        EVENTS_VALS = {"1K": 1000, "5K": 5000, "10K": 10000, "50K": 50000,
                       "100K": 100000, "500K": 500000}
        def _parse_int(t):
            try:
                return EVENTS_VALS.get(t, int(t))
            except ValueError:
                return 10000
        try:
            throttle = int(self.monkey_throttle.currentText() or "300")
        except ValueError:
            throttle = 300
        p = {
            "events": _parse_int(self.monkey_events.currentText()),
            "throttle": throttle,
            "ignore_crashes": self.monkey_chk_crashes.isChecked(),
            "ignore_timeouts": self.monkey_chk_timeouts.isChecked(),
            "ignore_security": self.monkey_chk_security.isChecked(),
        }
        for key, c in self._monkey_pct_combos.items():
            try:
                p[key] = int(c.currentText() or "20")
            except ValueError:
                p[key] = 20
        return p

    def _update_pct_total(self):
        total = 0
        for c in self._monkey_pct_combos.values():
            try:
                total += int(c.currentText() or "0")
            except ValueError:
                pass
        color = "green" if total == 100 else "red"
        self._pct_total_lbl.setText(
            f'Total: <span style="color:{color};font-weight:bold">{total}%</span>'
        )

    def _on_record_start(self):
        self.btn_screen_record.setEnabled(False)
        self.btn_stop_record.setEnabled(True)
        dur = int(self.record_duration.currentText().replace("s", ""))
        self.signals.screen_record_requested.emit(self.selected_devices, dur)

    def _on_record_stop(self):
        self.btn_screen_record.setEnabled(True)
        self.btn_stop_record.setEnabled(False)
        self.signals.stop_screen_record_requested.emit(self.selected_devices)

    # Exposed for controller to restore button state after recording ends
    def on_recording_finished(self):
        self.btn_screen_record.setEnabled(True)
        self.btn_stop_record.setEnabled(False)

    def _on_start_monkey(self):
        params = self._collect_monkey_params()
        # Validate total = 100%
        total = sum(int(c.currentText() or "0") for c in self._monkey_pct_combos.values())
        if total != 100:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Event Mix Invalid",
                f"Event percentages sum to {total}%, not 100%.\n"
                "Monkey will still run but event distribution may be unexpected.\n\n"
                "Adjust values to sum to 100% for predictable results."
            )
        params["package_name"] = self.package_text
        from core.settings_manager import AppSettings
        AppSettings.instance().set("monkey_params", params)
        self.signals.start_monkey_requested.emit(self.selected_devices, params)

    @property
    def package_text(self) -> str:
        return self.program_edit.currentText() if hasattr(self, "program_edit") else ""

    def add_package_to_history(self, pkg: str):
        if pkg not in [self.program_edit.itemText(j) for j in range(self.program_edit.count())]:
            self.program_edit.addItem(pkg)
        self.program_edit.setCurrentText(pkg)

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
        # Monkey
        self.start_monkey_btn.clicked.connect(
            lambda: self._on_start_monkey())
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
            lambda: self._on_record_start()
        )
        self.btn_stop_record.clicked.connect(
            lambda: self._on_record_stop()
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
