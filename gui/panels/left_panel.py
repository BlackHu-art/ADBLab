"""左侧控制面板 — 四标签页：设备管理 | 应用管理 | 输入与诊断 | 高级功能"""
from typing import List, Union
from PySide6.QtCore import Qt, Slot, QTimer, QSize
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QAbstractItemView,
    QLineEdit, QCompleter, QLabel, QTabWidget, QScrollArea,
)
from gui.styles.base_styles import BaseStyles
from models.device_store import DeviceStore
from contextlib import contextmanager
from gui.panels.left_panel_signals import LeftPanelSignals
from gui.widgets.double_click_button import DoubleClickButton
from models.adb_device import ADBDevice
from utils.resource_path import resource_path

@contextmanager
def BlockSignals(widget):
    widget.blockSignals(True)
    try: yield
    finally: widget.blockSignals(False)

class LeftPanel(QWidget):
    PANEL_WIDTH = 600
    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = LeftPanelSignals(); self.connected_device_cache = []; self.package_history = []; self._user_selected_ip = False
        self._init_ui_settings(); self._create_ui(); self._connect_signals()

    def _init_ui_settings(self):
        self.setFixedWidth(self.PANEL_WIDTH); self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        self._create_fonts(); BaseStyles.theme_changed.connect(self._on_theme_changed)

    def _create_fonts(self):
        F = BaseStyles.DEFAULT_FONT_FAMILY
        self._font_sm = QFont(F, BaseStyles.SMALL_FONT_SIZE)
        self._font_mono = QFont("Courier New", BaseStyles.MONO_FONT_SIZE); self._font_mono.setStyleHint(QFont.Monospace)
        self._font_base = QFont(F, BaseStyles.DEFAULT_FONT_SIZE); self._font_tab = QFont(F, BaseStyles.TAB_FONT_SIZE)

    def _create_ui(self):
        lo = QVBoxLayout(self); lo.setContentsMargins(0,0,0,0); lo.setSpacing(0)
        self.tabs = QTabWidget(); self.tabs.setFont(self._font_tab); self._apply_tab_style()
        for maker, name in [(self._mk_devices,"Devices"),(self._mk_apps,"Apps"),
                            (self._mk_diag,"Input & Diag"),(self._mk_advanced,"Advanced")]:
            s = QScrollArea(); s.setWidgetResizable(True); s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            s.setStyleSheet("QScrollArea { border: none; background: transparent; }"); s.setWidget(maker())
            self.tabs.addTab(s, name)
        lo.addWidget(self.tabs)

    def _on_theme_changed(self, _):
        self._create_fonts(); self.tabs.setFont(self._font_tab); self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        self._apply_tab_style()
        for g in self.findChildren(QGroupBox): g.setStyleSheet(BaseStyles.GROUP_BOX_STYLE()); g.setFont(self._font_base)
        for b in self.findChildren(QPushButton):
            if not b.parent() or b.parent().objectName() != "toolbar": b.setFont(self._font_sm)
        for i in self.findChildren(QLineEdit): i.setFont(self._font_sm)
        for c in self.findChildren(QComboBox): c.setFont(self._font_sm)
        self._apply_device_list_style()
        if hasattr(self,'ip_entry'): self._apply_completer_style(self.ip_entry.completer())
        if hasattr(self,'completer'): self._apply_completer_style(self.completer)

    def _apply_tab_style(self):
        bs=BaseStyles
        self.tabs.setStyleSheet(f"""QTabWidget::pane{{border:1px solid {bs.color('BORDER_COLOR')};border-radius:{bs.RADIUS_MD}px;background:{bs.color('WINDOW_BG')};}}QTabBar::tab{{background:{bs.color('BUTTON_BG')};color:{bs.color('TEXT_PRIMARY')};border:1px solid {bs.color('BORDER_COLOR')};border-bottom:none;padding:3px 12px;font-size:{bs.TAB_FONT_SIZE}px;border-radius:{bs.RADIUS_SM}px {bs.RADIUS_SM}px 0 0;margin-right:1px;}}QTabBar::tab:selected{{background:{bs.color('WINDOW_BG')};border-bottom:2px solid {bs.color('BUTTON_ACCENT')};}}QTabBar::tab:hover{{background:{bs.color('BUTTON_HOVER')};}}""")

    def _apply_completer_style(self, c):
        if c is None: return
        p=c.popup()
        if p is None: return
        p.setFont(self._font_mono)
        bs=BaseStyles
        p.setStyleSheet(f"QListView{{background-color:{bs.color('INPUT_BG')};color:{bs.color('TEXT_PRIMARY')};border:1px solid {bs.color('BORDER_COLOR')};border-radius:{bs.RADIUS_SM}px;padding:2px;outline:none;font-family:'Courier New',monospace;}}QListView::item{{padding:4px 8px;}}QListView::item:selected{{background-color:{bs.color('SELECTION_BG')};color:{bs.color('SELECTION_TEXT')};}}QListView::item:hover{{background-color:{bs.color('BUTTON_HOVER')};}}")

    def _apply_device_list_style(self):
        bs=BaseStyles
        self.listbox_devices.setStyleSheet(f"""QListWidget#deviceList{{background-color:{bs.color('INPUT_BG')};color:{bs.color('TEXT_PRIMARY')};border:1px solid {bs.color('BORDER_COLOR')};border-radius:{bs.RADIUS_MD}px;padding:2px;font-family:'Courier New';font-size:{bs.MONO_FONT_SIZE}px;outline:none;}}QListWidget#deviceList::item{{padding:3px 6px;color:{bs.color('TEXT_PRIMARY')};}}QListWidget#deviceList::item:selected{{background-color:{bs.color('SELECTION_BG')};color:{bs.color('SELECTION_TEXT')};}}QListWidget#deviceList::item:hover{{background-color:{bs.color('BUTTON_HOVER')};}}QListWidget::indicator{{width:16px;height:16px;}}QListWidget::indicator:unchecked{{image:none;border:2px solid {bs.color('BORDER_COLOR')};border-radius:3px;background-color:{bs.color('INPUT_BG')};}}QListWidget::indicator:checked{{image:url(icons:Checkmark.svg);border:none;}}""")

    # ── 辅助方法 ──────────────────────────────────────────────────────────
    def _g(self,t): g=QGroupBox(t); g.setFont(self._font_base); g.setStyleSheet(BaseStyles.GROUP_BOX_STYLE()); g.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred); return g
    def _b(self,t,i,dc=False): b=DoubleClickButton(t) if dc else QPushButton(t); b.setFont(self._font_sm); b.setSizePolicy(QSizePolicy.Minimum,QSizePolicy.Fixed); b.setMinimumHeight(28); b.setIcon(QIcon(resource_path(f"resources/icons/{i}"))); b.setIconSize(QSize(14,14)); return b
    def _qb(self,t): b=QPushButton(t); b.setFont(self._font_sm); b.setSizePolicy(QSizePolicy.Minimum,QSizePolicy.Fixed); b.setMinimumHeight(28); return b
    def _in(self, p, w=0):
        i = QLineEdit(); i.setFont(self._font_sm); i.setPlaceholderText(p)
        i.setMaximumHeight(28); i.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if w: i.setMaximumWidth(w)
        return i
    def _sd(self): return self.selected_devices
    def _pg(self): return self.program_edit.currentText()
    def _sh(self,c): self.signals.shell_command_requested.emit(self._sd(),c)
    def _ke(self,c): self.signals.input_keyevent_requested.emit(self._sd(),c)

    # ═══ 标签页 1: 设备管理 ═══
    def _mk_devices(self):
        w=QWidget(); lo=QVBoxLayout(w); lo.setSpacing(3); lo.setContentsMargins(4,4,4,4)
        g1=self._g("Connection"); gl1=QVBoxLayout(g1); gl1.setSpacing(2)
        r=QHBoxLayout(); r.setSpacing(4)
        self.ip_entry=QComboBox(); self.ip_entry.setEditable(True); self.ip_entry.setFont(self._font_sm)
        self._refresh_device_combobox()
        self.ip_entry.currentIndexChanged.connect(self._on_ip_selected); self.ip_entry.editTextChanged.connect(self._on_ip_edited)
        self.btn_connect_devices=self._b("Connect","Connect.svg")
        r.addWidget(self.ip_entry,3); r.addWidget(self.btn_connect_devices,1); gl1.addLayout(r)
        r2=QHBoxLayout(); r2.setSpacing(4)
        self.pair_ip_input=self._in("Pair IP",80); self.pair_port_input=self._in("Port",45); self.pair_code_input=self._in("Code",50)
        self.btn_pair_device=self._b("Pair","Connect.svg")
        r2.addWidget(QLabel("Pair")); r2.addWidget(self.pair_ip_input,2); r2.addWidget(self.pair_port_input,1); r2.addWidget(self.pair_code_input,1); r2.addWidget(self.btn_pair_device,1)
        gl1.addLayout(r2); lo.addWidget(g1)

        g2=self._g("Devices"); gl2=QHBoxLayout(g2); gl2.setSpacing(4)
        self.listbox_devices=QListWidget(); self.listbox_devices.setObjectName("deviceList")
        self.listbox_devices.setEditTriggers(QListWidget.NoEditTriggers); self.listbox_devices.setSelectionBehavior(QListWidget.SelectRows)
        self.listbox_devices.setSelectionMode(QListWidget.MultiSelection); self.listbox_devices.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.listbox_devices.setMinimumHeight(130); self.listbox_devices.setFont(self._font_mono); self.listbox_devices.setDragDropMode(QAbstractItemView.NoDragDrop)
        self._apply_device_list_style()
        bp=QFrame(); bl=QVBoxLayout(bp); bl.setSpacing(2); bl.setContentsMargins(0,0,0,0)
        self.btn_refresh_devices=self._b("Refresh List","Refresh.svg"); self.btn_devices_Info=self._b("Device Info","Info.svg")
        self.btn_disconnect_devices=self._b("Disconnect","Disconnect.svg"); self.btn_restart_devices=self._b("Restart Device","Restart.svg")
        self.btn_restart_adb=self._b("Restart ADB","Restore.svg",dc=True); self.btn_restart_adb.setToolTip("Double-click to restart ADB")
        self.btn_batch_install=self._b("Batch Install APK","Install_app.svg")
        self.btn_sel_all=self._qb("Select All"); self.btn_sel_all.clicked.connect(lambda:[self.listbox_devices.item(i).setCheckState(Qt.Checked) for i in range(self.listbox_devices.count())])
        self.btn_sel_none=self._qb("Deselect All"); self.btn_sel_none.clicked.connect(lambda:[self.listbox_devices.item(i).setCheckState(Qt.Unchecked) for i in range(self.listbox_devices.count())])
        for b in (self.btn_refresh_devices,self.btn_devices_Info,self.btn_disconnect_devices,self.btn_restart_devices,self.btn_restart_adb,self.btn_batch_install,self.btn_sel_all,self.btn_sel_none): bl.addWidget(b)
        bl.addStretch(); gl2.addWidget(self.listbox_devices,3); gl2.addWidget(bp,1); lo.addWidget(g2)

        g3=self._g("Text Input"); gl3=QHBoxLayout(g3); gl3.setSpacing(4)
        self.btn_send_text=self._b("Send Text","Input.svg")
        self.input_text_edit=self._in("Type text and press Enter to send...")
        self.input_text_edit.returnPressed.connect(lambda:self.signals.send_text_requested.emit(self._sd(),self.input_text_edit.text()))
        gl3.addWidget(self.input_text_edit,3); gl3.addWidget(self.btn_send_text,1); lo.addWidget(g3)

        g4=self._g("Screen Capture"); gl4=QHBoxLayout(g4); gl4.setSpacing(4)
        self.btn_screenshot=self._b("Screenshot","Screenshot.svg")
        self.record_duration=QComboBox(); self.record_duration.addItems(["30s","60s","120s","180s","300s"]); self.record_duration.setCurrentText("180s"); self.record_duration.setFont(self._font_sm)
        self.btn_screen_record=self._b("Record Screen","Screenshot.svg"); self.btn_pull_recording=self._b("Pull Video","Save_alt.svg")
        gl4.addWidget(self.btn_screenshot,1); gl4.addWidget(self.record_duration,1); gl4.addWidget(self.btn_screen_record,1); gl4.addWidget(self.btn_pull_recording,1); lo.addWidget(g4)

        g5=self._g("Temp Email"); gl5=QHBoxLayout(g5); gl5.setSpacing(4)
        self.btn_generate_email=self._b("Get Email","Email.svg")
        self.email_text_sender=self._in("Email address"); self.verfication_text_sender=self._in("Verification code")
        gl5.addWidget(self.btn_generate_email,1); gl5.addWidget(self.email_text_sender,2); gl5.addWidget(self.verfication_text_sender,2); lo.addWidget(g5)
        return w

    # ═══ 标签页 2: 应用管理 ═══
    def _mk_apps(self):
        w=QWidget(); lo=QVBoxLayout(w); lo.setSpacing(3); lo.setContentsMargins(4,4,4,4)
        g0=self._g("Package Selector"); gl0=QHBoxLayout(g0); gl0.setSpacing(4)
        self.program_edit=QComboBox(); self.program_edit.setEditable(True); self.program_edit.setFont(self._font_sm)
        self.program_edit.lineEdit().setPlaceholderText("Package name")
        self.completer=QCompleter(self.package_history); self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._apply_completer_style(self.completer); self.program_edit.setCompleter(self.completer)
        self.btn_get_program=self._b("Get Package","Select_activity.svg")
        gl0.addWidget(self.program_edit,3); gl0.addWidget(self.btn_get_program,1); lo.addWidget(g0)

        g1=self._g("App Lifecycle"); gl1=QVBoxLayout(g1); gl1.setSpacing(2)
        r1=QHBoxLayout(); r1.setSpacing(4)
        self.btn_install_app=self._b("Install APK","Install_app.svg"); self.uninstall_btn=self._b("Uninstall App","Uninstall_app.svg")
        self.clear_app_data_btn=self._b("Clear Data","Clear_data.svg"); self.restart_app_btn=self._b("Restart App","Restart_app.svg")
        for b in (self.btn_install_app,self.uninstall_btn,self.clear_app_data_btn,self.restart_app_btn): r1.addWidget(b,1)
        gl1.addLayout(r1)
        r2=QHBoxLayout(); r2.setSpacing(4)
        self.print_activity_btn=self._b("Activity Info","Print.svg"); self.btn_force_stop=self._b("Force Stop App","Kill_monkey.svg")
        r2.addWidget(self.print_activity_btn,1); r2.addWidget(self.btn_force_stop,1); gl1.addLayout(r2); lo.addWidget(g1)

        g1b=self._g("Package Info"); gl1b=QHBoxLayout(g1b); gl1b.setSpacing(4)
        self.parse_apk_info_btn=self._b("Parse APK","Parse_APK.svg")
        self.btn_pm_path=self._qb("PM Path"); self.btn_pm_path.setToolTip("Get APK file path"); self.btn_pm_path.clicked.connect(lambda:self._sh(f"pm path {self._pg()}"))
        self.btn_pm_dump=self._qb("PM Dump"); self.btn_pm_dump.setToolTip("Dump package info"); self.btn_pm_dump.clicked.connect(lambda:self._sh(f"pm dump {self._pg()} | head -80"))
        self.btn_3rd_party=self._qb("3rd Party"); self.btn_3rd_party.setToolTip("Third-party packages"); self.btn_3rd_party.clicked.connect(lambda:self._sh("pm list packages -3"))
        self.btn_sys_pkg=self._qb("System"); self.btn_sys_pkg.setToolTip("System packages"); self.btn_sys_pkg.clicked.connect(lambda:self._sh("pm list packages -s"))
        for b in (self.parse_apk_info_btn,self.btn_pm_path,self.btn_pm_dump,self.btn_3rd_party,self.btn_sys_pkg): gl1b.addWidget(b,1)
        lo.addWidget(g1b)

        g2=self._g("Permissions"); gl2=QVBoxLayout(g2); gl2.setSpacing(2)
        rp1=QHBoxLayout(); rp1.setSpacing(4)
        self.perm_package=self._in("Package (blank = use selector)"); self.perm_name=self._in("Permission")
        rp1.addWidget(self.perm_package,1); rp1.addWidget(self.perm_name,2); gl2.addLayout(rp1)
        rp2=QHBoxLayout(); rp2.setSpacing(4)
        self.btn_grant_perm=self._b("Grant Permission","Install_app.svg"); self.btn_revoke_perm=self._b("Revoke Permission","Uninstall_app.svg")
        self.btn_list_perm=self._qb("List Perms"); self.btn_list_perm.clicked.connect(lambda:self._sh(f"pm dump {self.perm_package.text().strip() or self._pg()} | grep -A999 'requested permissions' | head -100"))
        rp2.addWidget(self.btn_grant_perm); rp2.addWidget(self.btn_revoke_perm); rp2.addWidget(self.btn_list_perm); gl2.addLayout(rp2); lo.addWidget(g2)

        g3=self._g("Package State"); gl3=QHBoxLayout(g3); gl3.setSpacing(4)
        self.btn_disable_app=self._b("Disable App","Kill_monkey.svg"); self.btn_enable_app=self._b("Enable App","Restart_app.svg")
        self.btn_disable_user=self._qb("Disable for User"); self.btn_disable_user.clicked.connect(lambda:self.signals.disable_app_requested.emit(self._sd(),self._pg()))
        gl3.addWidget(self.btn_disable_app,1); gl3.addWidget(self.btn_enable_app,1); gl3.addWidget(self.btn_disable_user,1); lo.addWidget(g3)

        g4=self._g("Broadcast & Intents"); gl4=QVBoxLayout(g4); gl4.setSpacing(2)
        rb=QHBoxLayout(); rb.setSpacing(4); self.broadcast_action=self._in("Broadcast action"); self.btn_broadcast=self._b("Send Broadcast","Input.svg")
        rb.addWidget(self.broadcast_action,2); rb.addWidget(self.btn_broadcast,1); gl4.addLayout(rb)
        ra=QHBoxLayout(); ra.setSpacing(4); self.activity_spec=self._in("Component (pkg/.Activity) or action")
        self.btn_start_activity=self._b("Start Activity","Select_activity.svg")
        ra.addWidget(self.activity_spec,2); ra.addWidget(self.btn_start_activity,1); gl4.addLayout(ra)
        rd_=QHBoxLayout(); rd_.setSpacing(4); self.deep_link_uri=self._in("Deep link URL"); self.btn_deep_link=self._b("Open Link","Connect.svg")
        rd_.addWidget(self.deep_link_uri,2); rd_.addWidget(self.btn_deep_link,1); gl4.addLayout(rd_); lo.addWidget(g4)
        lo.addStretch(); return w

    # ═══ 标签页 3: 输入与诊断 ═══
    def _mk_diag(self):
        w=QWidget(); lo=QVBoxLayout(w); lo.setSpacing(3); lo.setContentsMargins(4,4,4,4)

        g0=self._g("Reboot & Modes"); gl0=QHBoxLayout(g0); gl0.setSpacing(4)
        self.reboot_mode_combo=QComboBox(); self.reboot_mode_combo.addItems(["System","Bootloader","Recovery","Fastboot"]); self.reboot_mode_combo.setFont(self._font_sm)
        self.btn_reboot_mode=self._b("Reboot Mode","Restart.svg")
        self.tcpip_port_input=self._in("5555",45); self.btn_tcpip_mode=self._b("TCP/IP Mode","Connect.svg")
        gl0.addWidget(self.reboot_mode_combo,1); gl0.addWidget(self.btn_reboot_mode,1); gl0.addWidget(self.tcpip_port_input,1); gl0.addWidget(self.btn_tcpip_mode,1); lo.addWidget(g0)

        g4=self._g("Monkey Stress Test"); gl4=QVBoxLayout(g4); gl4.setSpacing(2)
        r4=QHBoxLayout(); r4.setSpacing(4)
        self.device_type=QComboBox(); self.device_type.addItems(["STB","Mobile"]); self.device_type.setFont(self._font_sm)
        self.select_times=QComboBox(); self.select_times.addItems(["100","10000","100000","500000"]); self.select_times.setFont(self._font_sm)
        self.start_monkey_btn=self._b("Start Monkey","Monkey.svg"); self.kill_monkey_btn=self._b("Kill Monkey","Kill_monkey.svg")
        r4.addWidget(self.device_type,1); r4.addWidget(self.select_times,1); r4.addWidget(self.start_monkey_btn,1); r4.addWidget(self.kill_monkey_btn,1); gl4.addLayout(r4); lo.addWidget(g4)

        g5=self._g("Reports & Logs"); gl5=QVBoxLayout(g5); gl5.setSpacing(2)
        r5a=QHBoxLayout(); r5a.setSpacing(4)
        self.list_package_btn=self._b("List Packages","format_list_bulleted.svg"); self.get_bugreport_btn=self._b("Bugreport","Bugreport.svg"); self.get_anr_file_btn=self._b("ANR Files","Get_ANR.svg")
        r5a.addWidget(self.list_package_btn); r5a.addWidget(self.get_bugreport_btn); r5a.addWidget(self.get_anr_file_btn); gl5.addLayout(r5a)
        r5b=QHBoxLayout(); r5b.setSpacing(4)
        self.btn_retrieve_devices_logs=self._b("Retrieve Logs","Save_alt.svg"); self.btn_cleanup_logs=self._b("Cleanup Logs","Cleaning_services.svg")
        r5b.addWidget(self.btn_retrieve_devices_logs); r5b.addWidget(self.btn_cleanup_logs); gl5.addLayout(r5b); lo.addWidget(g5)

        g6=self._g("Performance Diagnostics"); gl6=QVBoxLayout(g6); gl6.setSpacing(2)
        r6a=QHBoxLayout(); r6a.setSpacing(4)
        self.btn_meminfo=self._b("Memory","Info.svg"); self.btn_cpuinfo=self._b("CPU Load","Info.svg"); self.btn_battery_info=self._b("Battery","Info.svg"); self.btn_uptime=self._b("Uptime","Info.svg")
        for b in (self.btn_meminfo,self.btn_cpuinfo,self.btn_battery_info,self.btn_uptime): r6a.addWidget(b,1)
        gl6.addLayout(r6a)
        r6b=QHBoxLayout(); r6b.setSpacing(4)
        self.btn_top=self._qb("Top Snapshot"); self.btn_top.setToolTip("top -b -n 1"); self.btn_top.clicked.connect(lambda:self._sh("top -b -n 1 -m 20"))
        self.btn_gfx=self._qb("GFX Info"); self.btn_gfx.setToolTip("dumpsys gfxinfo"); self.btn_gfx.clicked.connect(lambda:self._sh(f"dumpsys gfxinfo {self._pg()} framestats | head -60"))
        self.btn_wakelock=self._qb("Wakelocks"); self.btn_wakelock.setToolTip("kernel wakelocks"); self.btn_wakelock.clicked.connect(lambda:self._sh("cat /proc/wakelocks | head -40"))
        self.btn_netstats=self._qb("Net Stats"); self.btn_netstats.setToolTip("dumpsys netstats"); self.btn_netstats.clicked.connect(lambda:self._sh("dumpsys netstats detail | head -60"))
        for b in (self.btn_top,self.btn_gfx,self.btn_wakelock,self.btn_netstats): r6b.addWidget(b,1)
        gl6.addLayout(r6b); lo.addWidget(g6)

        g3=self._g("All Key Events"); gl3=QHBoxLayout(g3); gl3.setSpacing(4)
        self.keyevent_combo=QComboBox(); self.keyevent_combo.setFont(self._font_sm)
        for lb,cd in [("HOME(3)","3"),("BACK(4)","4"),("POWER(26)","26"),("VOL_UP(24)","24"),("VOL_DOWN(25)","25"),("ENTER(66)","66"),("DEL(67)","67"),("MENU(82)","82"),("DPAD_UP(19)","19"),("DPAD_DOWN(20)","20"),("DPAD_LEFT(21)","21"),("DPAD_RIGHT(22)","22"),("DPAD_CENTER(23)","23"),("APP_SWITCH(187)","187"),("NOTIFICATION(83)","83"),("SETTINGS(176)","176"),("CAMERA(27)","27"),("SEARCH(84)","84"),("MEDIA_PLAY(85)","85"),("MEDIA_NEXT(87)","87"),("MEDIA_PREV(88)","88"),("CH_UP(166)","166"),("CH_DOWN(167)","167"),("SLEEP(223)","223"),("WAKEUP(224)","224"),("BRIGHT_UP(221)","221"),("BRIGHT_DOWN(220)","220")]: self.keyevent_combo.addItem(lb,cd)
        self.btn_keyevent=self._b("Send Key","Input.svg"); gl3.addWidget(self.keyevent_combo,2); gl3.addWidget(self.btn_keyevent,1); lo.addWidget(g3)

        g1=self._g("Touch Gestures"); gl1=QVBoxLayout(g1); gl1.setSpacing(2)
        rt=QHBoxLayout(); rt.setSpacing(4); self.tap_x=self._in("X",70); self.tap_y=self._in("Y",70); self.btn_tap=self._b("Tap","Screenshot.svg")
        rt.addWidget(QLabel("Tap")); rt.addWidget(self.tap_x,1); rt.addWidget(self.tap_y,1); rt.addWidget(self.btn_tap,1); gl1.addLayout(rt)
        rl=QHBoxLayout(); rl.setSpacing(4); self.long_x=self._in("X",55); self.long_y=self._in("Y",55); self.long_dur=self._in("ms",50); self.long_dur.setText("1000")
        self.btn_longpress=self._qb("Long Press"); self.btn_longpress.clicked.connect(lambda:self._sh(f"input swipe {self.long_x.text() or '0'} {self.long_y.text() or '0'} {self.long_x.text() or '0'} {self.long_y.text() or '0'} {self.long_dur.text() or '1000'}"))
        rl.addWidget(QLabel("Long")); rl.addWidget(self.long_x,1); rl.addWidget(self.long_y,1); rl.addWidget(self.long_dur,1); rl.addWidget(self.btn_longpress,1); gl1.addLayout(rl)
        rs1=QHBoxLayout(); rs1.setSpacing(2); self.swipe_x1=self._in("x1",48); self.swipe_y1=self._in("y1",48); self.swipe_x2=self._in("x2",48); self.swipe_y2=self._in("y2",48)
        rs1.addWidget(QLabel("From")); rs1.addWidget(self.swipe_x1,1); rs1.addWidget(self.swipe_y1,1); rs1.addWidget(QLabel("To")); rs1.addWidget(self.swipe_x2,1); rs1.addWidget(self.swipe_y2,1); gl1.addLayout(rs1)
        rs2=QHBoxLayout(); rs2.setSpacing(4); self.swipe_dur=self._in("ms",70); self.swipe_dur.setText("300"); self.btn_swipe=self._b("Swipe","Screenshot.svg")
        rs2.addWidget(QLabel("Swipe")); rs2.addWidget(self.swipe_dur,1); rs2.addWidget(self.btn_swipe,1); rs2.addStretch(3); gl1.addLayout(rs2)
        rd=QHBoxLayout(); rd.setSpacing(2); self.drag_x1=self._in("x1",48); self.drag_y1=self._in("y1",48); self.drag_x2=self._in("x2",48); self.drag_y2=self._in("y2",48); self.drag_dur=self._in("ms",50); self.drag_dur.setText("300")
        self.btn_drag=self._qb("Drag"); self.btn_drag.clicked.connect(lambda:self._sh(f"input draganddrop {self.drag_x1.text() or '0'} {self.drag_y1.text() or '0'} {self.drag_x2.text() or '0'} {self.drag_y2.text() or '0'} {self.drag_dur.text() or '300'}"))
        rd.addWidget(QLabel("Drag")); rd.addWidget(self.drag_x1,1); rd.addWidget(self.drag_y1,1); rd.addWidget(self.drag_x2,1); rd.addWidget(self.drag_y2,1); rd.addWidget(self.drag_dur,1); rd.addWidget(self.btn_drag,1); gl1.addLayout(rd); lo.addWidget(g1)

        g2=self._g("Quick Keys"); gl2=QVBoxLayout(g2); gl2.setSpacing(2)
        for keys in [[("HOME","3"),("BACK","4"),("POWER","26"),("APP SWITCH","187")],[("VOL +","24"),("VOL -","25"),("ENTER","66"),("DEL","67")],[("UP","19"),("DOWN","20"),("LEFT","21"),("RIGHT","22"),("CENTER","23")]]:
            rk=QHBoxLayout(); rk.setSpacing(3)
            for lb,cd in keys: kb=self._qb(lb); kb.clicked.connect(lambda _,c=cd:self._ke(c)); rk.addWidget(kb,1)
            gl2.addLayout(rk)
        lo.addWidget(g2)

        g7=self._g("Logcat Filter"); gl7=QVBoxLayout(g7); gl7.setSpacing(2)
        r7a=QHBoxLayout(); r7a.setSpacing(4)
        self.logcat_buffer=QComboBox(); self.logcat_buffer.addItems(["main","system","crash","events","radio"]); self.logcat_buffer.setFont(self._font_sm)
        self.logcat_priority=QComboBox(); self.logcat_priority.addItems(["V","D","I","W","E","F"]); self.logcat_priority.setCurrentText("V"); self.logcat_priority.setFont(self._font_sm)
        r7a.addWidget(QLabel("Buf")); r7a.addWidget(self.logcat_buffer,1); r7a.addWidget(QLabel("Prio")); r7a.addWidget(self.logcat_priority,1); gl7.addLayout(r7a)
        r7b=QHBoxLayout(); r7b.setSpacing(4)
        self.logcat_tag=self._in("Tag",70); self.logcat_regex=self._in("Regex",70); self.btn_logcat_filter=self._b("Fetch Logs","Save_alt.svg")
        r7b.addWidget(self.logcat_tag,1); r7b.addWidget(self.logcat_regex,1); r7b.addWidget(self.btn_logcat_filter,1); gl7.addLayout(r7b); lo.addWidget(g7)
        lo.addStretch(); return w

    # ═══ 标签页 4: 高级功能 ═══
    def _mk_advanced(self):
        w=QWidget(); lo=QVBoxLayout(w); lo.setSpacing(3); lo.setContentsMargins(4,4,4,4)
        g1=self._g("Shell Command"); gl1=QHBoxLayout(g1); gl1.setSpacing(4)
        self.shell_cmd_input=self._in("adb shell <command> ..."); self.shell_cmd_input.returnPressed.connect(lambda:self._sh(self.shell_cmd_input.text()))
        self.btn_shell_run=self._b("Run","Input.svg"); gl1.addWidget(self.shell_cmd_input,3); gl1.addWidget(self.btn_shell_run,1); lo.addWidget(g1)

        g2=self._g("File Operations"); gl2=QVBoxLayout(g2); gl2.setSpacing(2)
        rf=QHBoxLayout(); rf.setSpacing(4); self.file_path_input=self._in("Remote path (/sdcard/Download)"); self.btn_file_list=self._b("List Files","Save_alt.svg")
        rf.addWidget(self.file_path_input,2); rf.addWidget(self.btn_file_list,1); gl2.addLayout(rf)
        rf2=QHBoxLayout(); rf2.setSpacing(4); self.file_local_input=self._in("Local path"); self.btn_file_push=self._b("Push to Device","Install_app.svg"); self.btn_file_pull=self._b("Pull from Device","Save_alt.svg")
        rf2.addWidget(self.file_local_input,2); rf2.addWidget(self.btn_file_push,1); rf2.addWidget(self.btn_file_pull,1); gl2.addLayout(rf2); lo.addWidget(g2)

        g3=self._g("Port Forwarding"); gl3=QVBoxLayout(g3); gl3.setSpacing(2)
        r3a=QHBoxLayout(); r3a.setSpacing(4); self.fwd_local=self._in("Local port",90); self.fwd_remote=self._in("Remote port",90)
        self.btn_forward=self._b("Forward","Connect.svg"); self.btn_list_fwd=self._b("List","format_list_bulleted.svg"); self.btn_remove_fwd=self._b("Remove","Cleaning_services.svg")
        r3a.addWidget(self.fwd_local,1); r3a.addWidget(self.fwd_remote,1); r3a.addWidget(self.btn_forward,1); r3a.addWidget(self.btn_list_fwd,1); r3a.addWidget(self.btn_remove_fwd,1); gl3.addLayout(r3a)
        r3b=QHBoxLayout(); r3b.setSpacing(4); self.btn_reverse=self._b("Reverse","Connect.svg"); self.btn_list_rev=self._b("List Rev","format_list_bulleted.svg"); self.btn_remove_rev=self._b("Remove Rev","Cleaning_services.svg")
        r3b.addWidget(self.btn_reverse); r3b.addWidget(self.btn_list_rev); r3b.addWidget(self.btn_remove_rev); r3b.addStretch(2); gl3.addLayout(r3b); lo.addWidget(g3)

        gs=self._g("Service Toggles (svc)"); gsl=QVBoxLayout(gs); gsl.setSpacing(2)
        rs1=QHBoxLayout(); rs1.setSpacing(4)
        for n,cmd in [("WiFi ON","svc wifi enable"),("WiFi OFF","svc wifi disable"),("Data ON","svc data enable"),("Data OFF","svc data disable")]:
            b=self._qb(n); b.clicked.connect(lambda _,c=cmd:self._sh(c)); rs1.addWidget(b,1)
        gsl.addLayout(rs1)
        rs2=QHBoxLayout(); rs2.setSpacing(4)
        for n,cmd in [("BT ON","svc bluetooth enable"),("BT OFF","svc bluetooth disable"),("NFC ON","svc nfc enable"),("NFC OFF","svc nfc disable")]:
            b=self._qb(n); b.clicked.connect(lambda _,c=cmd:self._sh(c)); rs2.addWidget(b,1)
        gsl.addLayout(rs2); lo.addWidget(gs)

        g4=self._g("Android Settings"); gl4=QVBoxLayout(g4); gl4.setSpacing(2)
        r4a=QHBoxLayout(); r4a.setSpacing(4)
        self.settings_ns=QComboBox(); self.settings_ns.addItems(["system","global","secure"]); self.settings_ns.setFont(self._font_sm)
        self.settings_key=self._in("Key",70); self.settings_val=self._in("Value",70)
        r4a.addWidget(self.settings_ns,1); r4a.addWidget(self.settings_key,1); r4a.addWidget(self.settings_val,1); gl4.addLayout(r4a)
        r4b=QHBoxLayout(); r4b.setSpacing(4); self.btn_settings_list=self._b("List All","format_list_bulleted.svg"); self.btn_settings_get=self._b("Get Value","Info.svg"); self.btn_settings_put=self._b("Set Value","Input.svg")
        for b in (self.btn_settings_list,self.btn_settings_get,self.btn_settings_put): r4b.addWidget(b); gl4.addLayout(r4b); lo.addWidget(g4)

        g5=self._g("System Tools"); gl5=QVBoxLayout(g5); gl5.setSpacing(2)
        rc=QHBoxLayout(); rc.setSpacing(4); self.content_uri=self._in("Content URI"); self.btn_content_query=self._b("Query","Info.svg")
        rc.addWidget(self.content_uri,2); rc.addWidget(self.btn_content_query,1); gl5.addLayout(rc)
        rp=QHBoxLayout(); rp.setSpacing(4); self.btn_ps_list=self._b("Process List","format_list_bulleted.svg"); self.kill_pid_input=self._in("PID",55); self.btn_kill_pid=self._b("Kill PID","Kill_monkey.svg"); self.btn_pm_features=self._b("Features","Info.svg")
        rp.addWidget(self.btn_ps_list); rp.addWidget(self.kill_pid_input,1); rp.addWidget(self.btn_kill_pid); rp.addWidget(self.btn_pm_features); gl5.addLayout(rp)
        rs3=QHBoxLayout(); rs3.setSpacing(4)
        self.dumpsys_combo=QComboBox(); self.dumpsys_combo.setEditable(True); self.dumpsys_combo.setFont(self._font_sm)
        self.dumpsys_combo.addItems(["","package","activity","window","wifi","battery","power","alarm","usb","input","notification","connectivity","audio","display","meminfo","cpuinfo","netstats"])
        self.btn_dumpsys=self._qb("Dumpsys"); self.btn_dumpsys.clicked.connect(lambda:self._sh(f"dumpsys {self.dumpsys_combo.currentText().strip()} | head -80" if self.dumpsys_combo.currentText().strip() else "service list"))
        self.btn_kernel=self._qb("Kernel"); self.btn_kernel.setToolTip("cat /proc/version"); self.btn_kernel.clicked.connect(lambda:self._sh("cat /proc/version"))
        self.btn_cpuinfo_dev=self._qb("CPU Info"); self.btn_cpuinfo_dev.setToolTip("cat /proc/cpuinfo"); self.btn_cpuinfo_dev.clicked.connect(lambda:self._sh("cat /proc/cpuinfo | head -40"))
        rs3.addWidget(self.dumpsys_combo,2); rs3.addWidget(self.btn_dumpsys,1); rs3.addWidget(self.btn_kernel,1); rs3.addWidget(self.btn_cpuinfo_dev,1); gl5.addLayout(rs3); lo.addWidget(g5)

        g6=self._g("Battery & Quick Settings"); gl6=QVBoxLayout(g6); gl6.setSpacing(2)
        rb=QHBoxLayout(); rb.setSpacing(4); self.battery_param=QComboBox(); self.battery_param.addItems(["level","status"]); self.battery_param.setFont(self._font_sm); self.battery_val=self._in("Value",70)
        self.btn_battery_set=self._b("Set","Input.svg"); self.btn_battery_reset=self._b("Reset","Restore.svg")
        rb.addWidget(QLabel("Battery")); rb.addWidget(self.battery_param,1); rb.addWidget(self.battery_val,1); rb.addWidget(self.btn_battery_set,1); rb.addWidget(self.btn_battery_reset,1); gl6.addLayout(rb)
        rq=QHBoxLayout(); rq.setSpacing(4); self.quick_setting_combo=QComboBox(); self.quick_setting_combo.addItem("Disable Animations","anim_off"); self.quick_setting_combo.addItem("Enable Animations","anim_on"); self.quick_setting_combo.addItem("Stay Awake","stay_awake"); self.quick_setting_combo.setFont(self._font_sm)
        self.btn_quick_setting=self._b("Apply","Input.svg"); rq.addWidget(self.quick_setting_combo,2); rq.addWidget(self.btn_quick_setting,1); gl6.addLayout(rq); lo.addWidget(g6)

        g7=self._g("IME & Emulator Control"); gl7=QVBoxLayout(g7); gl7.setSpacing(2)
        ri=QHBoxLayout(); ri.setSpacing(4); self.btn_ime_list=self._b("List IME","format_list_bulleted.svg"); self.ime_id_input=self._in("IME ID"); self.btn_ime_set=self._b("Set IME","Input.svg")
        ri.addWidget(self.btn_ime_list); ri.addWidget(self.ime_id_input,2); ri.addWidget(self.btn_ime_set); gl7.addLayout(ri)
        re1=QHBoxLayout(); re1.setSpacing(3); self.emu_sms_sender=self._in("Sender",65); self.emu_sms_text=self._in("SMS text",70); self.btn_emu_sms=self._b("Send SMS","Email.svg")
        re1.addWidget(QLabel("Emu")); re1.addWidget(self.emu_sms_sender,1); re1.addWidget(self.emu_sms_text,1); re1.addWidget(self.btn_emu_sms,1); gl7.addLayout(re1)
        re2=QHBoxLayout(); re2.setSpacing(3); self.emu_call_num=self._in("Phone number"); self.btn_emu_call=self._b("Call","Input.svg"); self.emu_geo_lon=self._in("Lon",55); self.emu_geo_lat=self._in("Lat",55); self.btn_emu_geo=self._b("GPS","Input.svg")
        re2.addWidget(self.emu_call_num,1); re2.addWidget(self.btn_emu_call); re2.addWidget(self.emu_geo_lon,1); re2.addWidget(self.emu_geo_lat,1); re2.addWidget(self.btn_emu_geo); gl7.addLayout(re2); lo.addWidget(g7)
        lo.addStretch(); return w

    # ═══ 信号连接 ═══
    def _connect_signals(self):
        LP=self.signals; sd=self._sd; pg=self._pg
        self.btn_connect_devices.clicked.connect(lambda:LP.connect_requested.emit(self.ip_address))
        self.btn_refresh_devices.clicked.connect(lambda:LP.refresh_devices_requested.emit())
        self.btn_devices_Info.clicked.connect(lambda:LP.device_info_requested.emit(sd()))
        self.btn_disconnect_devices.clicked.connect(lambda:LP.disconnect_requested.emit(sd()))
        self.btn_restart_devices.clicked.connect(lambda:LP.restart_devices_requested.emit(sd()))
        self.btn_restart_adb.doubleClicked.connect(LP.restart_adb_requested.emit)
        self.btn_batch_install.clicked.connect(lambda:LP.batch_install_requested.emit(sd()))
        self.btn_screenshot.clicked.connect(lambda:LP.screenshot_requested.emit(sd()))
        self.btn_screen_record.clicked.connect(lambda:LP.screen_record_requested.emit(sd(),int(self.record_duration.currentText().replace("s",""))))
        self.btn_pull_recording.clicked.connect(lambda:LP.pull_recording_requested.emit(sd()))
        self.btn_reboot_mode.clicked.connect(lambda:LP.reboot_mode_requested.emit(sd(),self.reboot_mode_combo.currentText().lower()))
        self.btn_pair_device.clicked.connect(lambda:LP.pair_device_requested.emit(self.pair_ip_input.text().strip(),self.pair_port_input.text().strip() or "5555",self.pair_code_input.text().strip()))
        self.btn_tcpip_mode.clicked.connect(lambda:LP.tcpip_mode_requested.emit(sd(),self.tcpip_port_input.text().strip() or "5555"))
        self.btn_send_text.clicked.connect(lambda:LP.send_text_requested.emit(sd(),self.input_text_edit.text()))
        self.btn_tap.clicked.connect(lambda:LP.input_tap_requested.emit(sd(),int(self.tap_x.text() or "0"),int(self.tap_y.text() or "0")))
        self.btn_swipe.clicked.connect(lambda:LP.input_swipe_requested.emit(sd(),int(self.swipe_x1.text() or "0"),int(self.swipe_y1.text() or "0"),int(self.swipe_x2.text() or "0"),int(self.swipe_y2.text() or "0"),int(self.swipe_dur.text() or "300")))
        self.btn_keyevent.clicked.connect(lambda:LP.input_keyevent_requested.emit(sd(),self.keyevent_combo.currentData()))
        self.listbox_devices.itemDoubleClicked.connect(self._on_device_double_click)
        self.btn_get_program.clicked.connect(lambda:LP.get_program_requested.emit(sd()))
        self.btn_install_app.clicked.connect(lambda:LP.install_app_requested.emit(sd()))
        self.uninstall_btn.clicked.connect(lambda:LP.uninstall_app_requested.emit(sd(),pg()))
        self.clear_app_data_btn.clicked.connect(lambda:LP.clear_app_data_requested.emit(sd(),pg()))
        self.restart_app_btn.clicked.connect(lambda:LP.restart_app_requested.emit(sd(),pg()))
        self.print_activity_btn.clicked.connect(lambda:LP.print_activity_requested.emit(sd()))
        self.parse_apk_info_btn.clicked.connect(lambda:LP.parse_apk_info_requested.emit())
        self.btn_grant_perm.clicked.connect(lambda:LP.grant_permission_requested.emit(sd(),self.perm_package.text().strip() or pg(),self.perm_name.text().strip()))
        self.btn_revoke_perm.clicked.connect(lambda:LP.revoke_permission_requested.emit(sd(),self.perm_package.text().strip() or pg(),self.perm_name.text().strip()))
        self.btn_disable_app.clicked.connect(lambda:LP.disable_app_requested.emit(sd(),pg()))
        self.btn_enable_app.clicked.connect(lambda:LP.enable_app_requested.emit(sd(),pg()))
        self.btn_force_stop.clicked.connect(lambda:LP.force_stop_requested.emit(sd(),pg()))
        self.btn_broadcast.clicked.connect(lambda:LP.send_broadcast_requested.emit(sd(),self.broadcast_action.text().strip()))
        self.btn_start_activity.clicked.connect(lambda:LP.start_activity_requested.emit(sd(),self.activity_spec.text().strip()))
        self.btn_deep_link.clicked.connect(lambda:LP.open_deep_link_requested.emit(sd(),self.deep_link_uri.text().strip()))
        self.start_monkey_btn.clicked.connect(lambda:LP.start_monkey_requested.emit(sd(),self.device_type.currentText(),pg(),self.select_times.currentText()))
        self.kill_monkey_btn.clicked.connect(lambda:LP.kill_monkey_requested.emit(sd()))
        self.list_package_btn.clicked.connect(lambda:LP.list_installed_packages_requested.emit(sd()))
        self.get_bugreport_btn.clicked.connect(lambda:LP.capture_bugreport_requested.emit(sd()))
        self.get_anr_file_btn.clicked.connect(lambda:LP.pull_anr_file_requested.emit(sd()))
        self.btn_retrieve_devices_logs.clicked.connect(lambda:LP.retrieve_logs_requested.emit(sd()))
        self.btn_cleanup_logs.clicked.connect(lambda:LP.cleanup_logs_requested.emit(sd()))
        self.btn_meminfo.clicked.connect(lambda:LP.dumpsys_meminfo_requested.emit(sd(),pg()))
        self.btn_cpuinfo.clicked.connect(lambda:LP.dumpsys_cpuinfo_requested.emit(sd()))
        self.btn_battery_info.clicked.connect(lambda:LP.dumpsys_battery_requested.emit(sd()))
        self.btn_uptime.clicked.connect(lambda:LP.device_uptime_requested.emit(sd()))
        self.btn_logcat_filter.clicked.connect(lambda:LP.logcat_filtered_requested.emit(sd(),self.logcat_buffer.currentText(),self.logcat_priority.currentText(),self.logcat_tag.text().strip(),self.logcat_regex.text().strip()))
        self.btn_shell_run.clicked.connect(lambda:LP.shell_command_requested.emit(sd(),self.shell_cmd_input.text()))
        self.btn_file_list.clicked.connect(lambda:LP.file_list_requested.emit(sd(),self.file_path_input.text().strip() or "/sdcard"))
        self.btn_file_push.clicked.connect(lambda:LP.file_push_requested.emit(sd(),self.file_local_input.text().strip(),self.file_path_input.text().strip()))
        self.btn_file_pull.clicked.connect(lambda:LP.file_pull_requested.emit(sd(),self.file_path_input.text().strip()))
        self.btn_forward.clicked.connect(lambda:LP.forward_port_requested.emit(sd(),self.fwd_local.text().strip(),self.fwd_remote.text().strip()))
        self.btn_list_fwd.clicked.connect(lambda:LP.list_forwards_requested.emit(sd()))
        self.btn_remove_fwd.clicked.connect(lambda:LP.remove_forwards_requested.emit(sd()))
        self.btn_reverse.clicked.connect(lambda:LP.reverse_port_requested.emit(sd(),self.fwd_remote.text().strip(),self.fwd_local.text().strip()))
        self.btn_list_rev.clicked.connect(lambda:LP.list_reverse_requested.emit(sd()))
        self.btn_remove_rev.clicked.connect(lambda:LP.remove_reverse_requested.emit(sd()))
        self.btn_settings_list.clicked.connect(lambda:LP.settings_list_requested.emit(sd(),self.settings_ns.currentText()))
        self.btn_settings_get.clicked.connect(lambda:LP.settings_get_requested.emit(sd(),self.settings_ns.currentText(),self.settings_key.text().strip()))
        self.btn_settings_put.clicked.connect(lambda:LP.settings_put_requested.emit(sd(),self.settings_ns.currentText(),self.settings_key.text().strip(),self.settings_val.text().strip()))
        self.btn_content_query.clicked.connect(lambda:LP.content_query_requested.emit(sd(),self.content_uri.text().strip()))
        self.btn_ps_list.clicked.connect(lambda:LP.list_processes_requested.emit(sd()))
        self.btn_kill_pid.clicked.connect(lambda:LP.kill_process_requested.emit(sd(),self.kill_pid_input.text().strip()))
        self.btn_battery_set.clicked.connect(lambda:LP.battery_set_requested.emit(sd(),self.battery_param.currentText(),self.battery_val.text().strip()))
        self.btn_battery_reset.clicked.connect(lambda:LP.battery_reset_requested.emit(sd()))
        self.btn_quick_setting.clicked.connect(lambda:LP.quick_setting_requested.emit(sd(),self.quick_setting_combo.currentData()))
        self.btn_ime_list.clicked.connect(lambda:LP.ime_list_requested.emit(sd()))
        self.btn_ime_set.clicked.connect(lambda:LP.ime_set_requested.emit(sd(),self.ime_id_input.text().strip()))
        self.btn_pm_features.clicked.connect(lambda:LP.pm_features_requested.emit(sd()))
        self.btn_emu_sms.clicked.connect(lambda:LP.emu_sms_requested.emit(sd(),self.emu_sms_sender.text().strip(),self.emu_sms_text.text().strip()))
        self.btn_emu_call.clicked.connect(lambda:LP.emu_call_requested.emit(sd(),self.emu_call_num.text().strip()))
        self.btn_emu_geo.clicked.connect(lambda:LP.emu_geo_requested.emit(sd(),self.emu_geo_lon.text().strip(),self.emu_geo_lat.text().strip()))
        self.btn_generate_email.clicked.connect(lambda:LP.generate_email_requested.emit())
        self.email_text_sender.returnPressed.connect(lambda:LP.send_text_requested.emit(sd(),self.email_text_sender.text()))
        self.verfication_text_sender.returnPressed.connect(lambda:LP.send_text_requested.emit(sd(),self.verfication_text_sender.text()))

    # ═══ 设备列表 ═══
    def update_device_list(self, devices:List[str]=None):
        if devices is None: devices=ADBDevice.get_connected_devices_async();
        if not devices: return
        prev=set(self.selected_devices); self.listbox_devices.clear(); self.connected_device_cache=devices
        infos=DeviceStore.get_full_devices_info(devices)
        ml={'model':0,'brand':0,'version':0,'ip':0}
        for info in infos:
            for k in ml: ml[k]=max(ml[k],len(info.get({'model':'Model','brand':'Brand','version':'Aversion','ip':'ip'}[k],'Unknown')))
        for info in infos:
            m=info.get('Model','Unknown').ljust(ml['model']); b=info.get('Brand','Unknown').ljust(ml['brand'])
            v=info.get('Aversion','Unknown').ljust(ml['version']); ip=info.get('ip','').ljust(ml['ip'])
            txt=m+' | '+b+' | '+v+' | '+ip
            item=QListWidgetItem(txt); item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if info.get('ip') in prev else Qt.Unchecked); item.setFont(self._font_mono); item.setData(Qt.UserRole,info)
            self.listbox_devices.addItem(item)

    def _refresh_device_combobox(self):
        if not hasattr(self,"ip_entry"): return
        with BlockSignals(self.ip_entry):
            self.ip_entry.clear(); devs=DeviceStore.get_basic_devices_info()
            if not devs: self.ip_entry.lineEdit().setPlaceholderText("No devices"); return
            ip_list=[ip for _,_,ip in devs]
            ml={'brand':max(len(b) for b,_,_ in devs),'model':max(len(m) for _,m,_ in devs),'ip':max(len(ip) for _,_,ip in devs)}
            fmt='{brand:<'+str(ml['brand'])+'} | {model:<'+str(ml['model'])+'} | {ip:<'+str(ml['ip'])+'}'
            for brand,model,ip in devs: self.ip_entry.addItem(fmt.format(brand=brand,model=model,ip=ip),userData=ip)
            comp=QCompleter(ip_list,self); comp.setCaseSensitivity(Qt.CaseInsensitive); comp.setFilterMode(Qt.MatchContains)
            self._apply_completer_style(comp); self.ip_entry.setCompleter(comp)
            self.ip_entry.setCurrentIndex(-1); self.ip_entry.lineEdit().clear(); self.ip_entry.lineEdit().setPlaceholderText("Select or input IP:port")

    def _on_ip_selected(self,i):
        if i>=0:
            ip=self.ip_entry.itemData(i)
            if ip:
                with BlockSignals(self.ip_entry): self.ip_entry.setCurrentIndex(-1); self.ip_entry.setCurrentText(ip)
                self._user_selected_ip=True
    def _on_ip_edited(self,t): self._current_ip=t.strip()
    def _on_device_double_click(self,item):
        if not(item.flags()&Qt.ItemIsUserCheckable): item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked if item.checkState()==Qt.Checked else Qt.Checked)
    @property
    def selected_devices(self)->List[str]:
        return [self.listbox_devices.item(i).data(Qt.UserRole).get("ip","") for i in range(self.listbox_devices.count()) if self.listbox_devices.item(i).checkState()==Qt.Checked]
    @property
    def ip_address(self)->str:
        t=self.ip_entry.currentText().strip(); return t if self._user_selected_ip or t else ""
    def update_current_package(self,device_ip:str,package_name:str):
        def _up():
            for i in range(self.listbox_devices.count()):
                item=self.listbox_devices.item(i); info=item.data(Qt.UserRole)
                if info and info.get("ip")==device_ip:
                    item.setText(info.get('ip','')+' | '+package_name)
                    if package_name not in [self.program_edit.itemText(j) for j in range(self.program_edit.count())]: self.program_edit.addItem(package_name)
                    break
        QTimer.singleShot(0,_up)
    def update_email(self,t): self.email_text_sender.setText(t)
    def update_vercode(self,t): self.verfication_text_sender.setText(t)
