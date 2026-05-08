"""应用管理标签页 — 包选择器、生命周期、权限、广播与 Intent。"""

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
    """应用管理标签页。"""

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)

        # ── 文本与邮箱 ──
        g_te = self._g("Text & Email")
        te_l = QHBoxLayout(g_te)
        te_l.setSpacing(4)
        self.btn_generate_email = self._b("Get Email", "Email.svg")
        self.email_text_sender = self._in("Email address")
        self.btn_send_text = self._b("Send Text", "Input.svg")
        self.verfication_text_sender = self._in("Verification code or text...")
        te_l.addWidget(self.btn_generate_email, 1)
        te_l.addWidget(self.email_text_sender, 2)
        te_l.addWidget(self.btn_send_text, 1)
        te_l.addWidget(self.verfication_text_sender, 2)
        lo.addWidget(g_te)

        # ── 屏幕捕获 ──
        g_sc = self._g("Screen Capture")
        sc_l = QHBoxLayout(g_sc)
        sc_l.setSpacing(4)
        self.btn_screenshot = self._b("Screenshot", "Screenshot.svg")
        self.record_duration = self._combo(["30s", "60s", "120s", "180s", "300s"])
        self.record_duration.setCurrentText("180s")
        self.btn_screen_record = self._b("Record Screen", "Screenshot.svg")
        self.btn_pull_recording = self._b("Pull Video", "Save_alt.svg")
        sc_l.addWidget(self.btn_screenshot, 1)
        sc_l.addWidget(self.record_duration, 1)
        sc_l.addWidget(self.btn_screen_record, 1)
        sc_l.addWidget(self.btn_pull_recording, 1)
        lo.addWidget(g_sc)

        # ── Package Selector ──
        g0 = self._g("Package Selector")
        gl0 = QHBoxLayout(g0)
        gl0.setSpacing(4)
        self.program_edit = QComboBox()
        self.program_edit.setEditable(True)
        self.program_edit.setFont(self._font_sm)
        self.program_edit.lineEdit().setPlaceholderText("Package name")
        self.completer = QCompleter(self.panel._package_history)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.panel._apply_completer_style(self.completer)
        self.program_edit.setCompleter(self.completer)
        self.btn_get_program = self._b("Get Package", "Select_activity.svg")
        gl0.addWidget(self.program_edit, 3)
        gl0.addWidget(self.btn_get_program, 1)
        lo.addWidget(g0)

        # ── App Lifecycle ──
        g1 = self._g("App Lifecycle")
        gl1 = QVBoxLayout(g1)
        gl1.setSpacing(2)
        r1 = QHBoxLayout()
        r1.setSpacing(4)
        self.uninstall_btn = self._b("Uninstall App", "Uninstall_app.svg")
        self.clear_app_data_btn = self._b("Clear Data", "Clear_data.svg")
        self.restart_app_btn = self._b("Restart App", "Restart_app.svg")
        for b in (
            self.uninstall_btn,
            self.clear_app_data_btn,
            self.restart_app_btn,
        ):
            r1.addWidget(b, 1)
        gl1.addLayout(r1)
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        self.print_activity_btn = self._b("Activity Info", "Print.svg")
        self.btn_force_stop = self._b("Force Stop App", "Kill_monkey.svg")
        r2.addWidget(self.print_activity_btn, 1)
        r2.addWidget(self.btn_force_stop, 1)
        gl1.addLayout(r2)
        lo.addWidget(g1)

        # ── Package Info ──
        g1b = self._g("Package Info")
        gl1b = QHBoxLayout(g1b)
        gl1b.setSpacing(4)
        self.parse_apk_info_btn = self._b("Parse APK", "Parse_APK.svg")
        self.btn_pm_path = self._qb("PM Path")
        self.btn_pm_path.setToolTip("Get APK file path")
        self.btn_pm_dump = self._qb("PM Dump")
        self.btn_pm_dump.setToolTip("Dump package info")
        self.btn_3rd_party = self._qb("3rd Party")
        self.btn_3rd_party.setToolTip("Third-party packages")
        self.btn_sys_pkg = self._qb("System")
        self.btn_sys_pkg.setToolTip("System packages")
        for b in (
            self.parse_apk_info_btn,
            self.btn_pm_path,
            self.btn_pm_dump,
            self.btn_3rd_party,
            self.btn_sys_pkg,
        ):
            gl1b.addWidget(b, 1)
        lo.addWidget(g1b)

        # ── Permissions ──
        g2 = self._g("Permissions")
        gl2 = QVBoxLayout(g2)
        gl2.setSpacing(2)
        rp1 = QHBoxLayout()
        rp1.setSpacing(4)
        self.perm_package = self._in("Package (blank = use selector)")
        self.perm_name = self._in("Permission")
        rp1.addWidget(self.perm_package, 1)
        rp1.addWidget(self.perm_name, 2)
        gl2.addLayout(rp1)
        rp2 = QHBoxLayout()
        rp2.setSpacing(4)
        self.btn_grant_perm = self._b("Grant Permission", "Install_app.svg")
        self.btn_revoke_perm = self._b("Revoke Permission", "Uninstall_app.svg")
        self.btn_list_perm = self._qb("List Perms")
        rp2.addWidget(self.btn_grant_perm)
        rp2.addWidget(self.btn_revoke_perm)
        rp2.addWidget(self.btn_list_perm)
        gl2.addLayout(rp2)
        lo.addWidget(g2)

        # ── Package State ──
        g3 = self._g("Package State")
        gl3 = QHBoxLayout(g3)
        gl3.setSpacing(4)
        self.btn_disable_app = self._b("Disable App", "Kill_monkey.svg")
        self.btn_enable_app = self._b("Enable App", "Restart_app.svg")
        self.btn_disable_user = self._qb("Disable for User")
        gl3.addWidget(self.btn_disable_app, 1)
        gl3.addWidget(self.btn_enable_app, 1)
        gl3.addWidget(self.btn_disable_user, 1)
        lo.addWidget(g3)

        # ── Broadcast & Intents ──
        g4 = self._g("Broadcast & Intents")
        gl4 = QVBoxLayout(g4)
        gl4.setSpacing(2)
        rb = QHBoxLayout()
        rb.setSpacing(4)
        self.broadcast_action = self._in("Broadcast action")
        self.btn_broadcast = self._b("Send Broadcast", "Input.svg")
        rb.addWidget(self.broadcast_action, 2)
        rb.addWidget(self.btn_broadcast, 1)
        gl4.addLayout(rb)
        ra = QHBoxLayout()
        ra.setSpacing(4)
        self.activity_spec = self._in("Component (pkg/.Activity) or action")
        self.btn_start_activity = self._b("Start Activity", "Select_activity.svg")
        ra.addWidget(self.activity_spec, 2)
        ra.addWidget(self.btn_start_activity, 1)
        gl4.addLayout(ra)
        rd_ = QHBoxLayout()
        rd_.setSpacing(4)
        self.deep_link_uri = self._in("Deep link URL")
        self.btn_deep_link = self._b("Open Link", "Connect.svg")
        rd_.addWidget(self.deep_link_uri, 2)
        rd_.addWidget(self.btn_deep_link, 1)
        gl4.addLayout(rd_)
        lo.addWidget(g4)
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
        self.btn_grant_perm.clicked.connect(
            lambda: LP.grant_permission_requested.emit(
                self.selected_devices,
                self.perm_package.text().strip() or self.package_text,
                self.perm_name.text().strip(),
            )
        )
        self.btn_revoke_perm.clicked.connect(
            lambda: LP.revoke_permission_requested.emit(
                self.selected_devices,
                self.perm_package.text().strip() or self.package_text,
                self.perm_name.text().strip(),
            )
        )
        self.btn_disable_app.clicked.connect(
            lambda: LP.disable_app_requested.emit(self.selected_devices, self.package_text)
        )
        self.btn_enable_app.clicked.connect(
            lambda: LP.enable_app_requested.emit(self.selected_devices, self.package_text)
        )
        self.btn_force_stop.clicked.connect(
            lambda: LP.force_stop_requested.emit(self.selected_devices, self.package_text)
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
        self.btn_pm_path.clicked.connect(lambda: self._sh(f"pm path {self.package_text}"))
        self.btn_pm_dump.clicked.connect(
            lambda: self._sh(f"pm dump {self.package_text} | head -80")
        )
        self.btn_3rd_party.clicked.connect(lambda: self._sh("pm list packages -3"))
        self.btn_sys_pkg.clicked.connect(lambda: self._sh("pm list packages -s"))
        self.btn_list_perm.clicked.connect(
            lambda: self._sh(
                f"pm dump {self.perm_package.text().strip() or self.package_text} | grep -A999 'requested permissions' | head -100"
            )
        )
        self.btn_disable_user.clicked.connect(
            lambda: LP.disable_app_requested.emit(self.selected_devices, self.package_text)
        )
        # 文本与邮箱
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
                self.selected_devices, self.verfication_text_sender.text()
            )
        )
        self.btn_generate_email.clicked.connect(lambda: LP.generate_email_requested.emit())
        self.email_text_sender.returnPressed.connect(
            lambda: LP.send_text_requested.emit(
                self.selected_devices, self.email_text_sender.text()
            )
        )
        self.verfication_text_sender.returnPressed.connect(
            lambda: LP.send_text_requested.emit(
                self.selected_devices, self.verfication_text_sender.text()
            )
        )

    def _sh(self, c):
        self.signals.shell_command_requested.emit(self.selected_devices, c)

    def update_email(self, t):
        self.email_text_sender.setText(t)

    def update_vercode(self, t):
        self.verfication_text_sender.setText(t)
