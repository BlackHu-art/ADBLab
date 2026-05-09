"""设置对话框 — 所有修改即时生效，无需确认。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from core.settings_manager import AppSettings
from gui.styles.base_styles import BaseStyles


class SettingsDialog(QDialog):
    settings_applied = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.s = AppSettings.instance()
        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 560)
        self.setModal(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._build_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        pw = self.parent()
        if pw and hasattr(pw, "_panel_splitter"):
            pw._panel_splitter.splitterMoved.connect(self._on_splitter_changed)

    # ── UI 构建 ────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(10)
        outer.setContentsMargins(20, 14, 20, 14)

        # ── Appearance ──
        g1 = QGroupBox("Appearance")
        g1l = QVBoxLayout(g1)
        g1l.setSpacing(6)

        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(QLabel("Theme"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(BaseStyles.theme_names())
        self.theme_combo.setCurrentText(BaseStyles.current_theme())
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        self.theme_combo.setFixedWidth(100)
        r1.addWidget(self.theme_combo)
        r1.addSpacing(16)
        r1.addWidget(QLabel("Font"))
        self.font_family_combo = QComboBox()
        self.font_family_combo.addItems(["Segoe UI", "Microsoft YaHei", "Arial", "Consolas", "Tahoma", "Verdana"])
        self.font_family_combo.setCurrentText(self.s.get("font_family", "Segoe UI"))
        self.font_family_combo.currentTextChanged.connect(self._on_font_family_changed)
        self.font_family_combo.setFixedWidth(140)
        r1.addWidget(self.font_family_combo)
        r1.addStretch()
        g1l.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(QLabel("UI Size"))
        self.spin_font = QSpinBox()
        self.spin_font.setRange(8, 22)
        self.spin_font.setValue(self.s.get("ui_font_size", 12))
        self.spin_font.setSuffix(" px")
        self.spin_font.setFixedWidth(80)
        self.spin_font.valueChanged.connect(self._on_font_changed)
        r2.addWidget(self.spin_font)
        r2.addSpacing(16)
        r2.addWidget(QLabel("Log Size"))
        self.spin_log_font = QSpinBox()
        self.spin_log_font.setRange(7, 16)
        self.spin_log_font.setValue(self.s.get("log_font_size", 9))
        self.spin_log_font.setSuffix(" px")
        self.spin_log_font.setFixedWidth(80)
        self.spin_log_font.valueChanged.connect(self._on_log_font_changed)
        r2.addWidget(self.spin_log_font)
        r2.addStretch()
        g1l.addLayout(r2)
        outer.addWidget(g1)

        # ── Window Size ──
        g_ws = QGroupBox("Window Size")
        g_ws_l = QVBoxLayout(g_ws)
        g_ws_l.setSpacing(4)
        pw = self.parent()
        cur_w = pw.width() if pw else self.s.get("window_width", 1200)
        cur_h = pw.height() if pw else self.s.get("window_height", 700)
        if pw and hasattr(pw, "panel_sizes"):
            sizes = pw.panel_sizes()
            cur_left = sizes[0] if len(sizes) == 2 else self.s.get("left_panel_width", 400)
        else:
            cur_left = self.s.get("left_panel_width", 400)

        r_ww = QHBoxLayout()
        r_ww.setSpacing(8)
        r_ww.addWidget(QLabel("Width"))
        self.spin_win_w = QSpinBox()
        self.spin_win_w.setRange(860, 2560)
        self.spin_win_w.setSingleStep(20)
        self.spin_win_w.setSuffix(" px")
        self.spin_win_w.setFixedWidth(100)
        self.spin_win_w.setValue(cur_w)
        r_ww.addWidget(self.spin_win_w)
        r_ww.addStretch()
        g_ws_l.addLayout(r_ww)

        r_wh = QHBoxLayout()
        r_wh.setSpacing(8)
        r_wh.addWidget(QLabel("Height"))
        self.spin_win_h = QSpinBox()
        self.spin_win_h.setRange(500, 1800)
        self.spin_win_h.setSingleStep(20)
        self.spin_win_h.setSuffix(" px")
        self.spin_win_h.setFixedWidth(100)
        self.spin_win_h.setValue(cur_h)
        r_wh.addWidget(self.spin_win_h)
        r_wh.addStretch()
        g_ws_l.addLayout(r_wh)

        self.spin_win_w.valueChanged.connect(self._on_window_size_changed)
        self.spin_win_h.valueChanged.connect(self._on_window_height_changed)
        outer.addWidget(g_ws)

        # ── Panel Size ──
        g_ps = QGroupBox("Panel Size")
        g_ps_l = QVBoxLayout(g_ps)
        g_ps_l.setSpacing(4)

        self._overhead = 13  # border(2) + margins(6) + splitter handle(5)

        r_lp = QHBoxLayout()
        r_lp.setSpacing(8)
        r_lp.addWidget(QLabel("Left Panel"))
        self.spin_left_w = QSpinBox()
        self.spin_left_w.setRange(200, max(200, cur_w - 311))
        self.spin_left_w.setSingleStep(10)
        self.spin_left_w.setSuffix(" px")
        self.spin_left_w.setFixedWidth(100)
        self.spin_left_w.setValue(cur_left)
        r_lp.addWidget(self.spin_left_w)
        r_lp.addStretch()
        g_ps_l.addLayout(r_lp)

        r_rp = QHBoxLayout()
        r_rp.setSpacing(8)
        r_rp.addWidget(QLabel("Right Panel"))
        self.lbl_right_w = QLabel()
        self._update_right_label()
        r_rp.addWidget(self.lbl_right_w)
        r_rp.addStretch()
        g_ps_l.addLayout(r_rp)

        self.spin_left_w.valueChanged.connect(self._apply_panels)
        outer.addWidget(g_ps)

        # ── Save Location ──
        g3 = QGroupBox("Default Save Location")
        g3l = QHBoxLayout(g3)
        g3l.setSpacing(8)
        self.save_dir_input = QLineEdit()
        self.save_dir_input.setText(self.s.save_directory)
        self.save_dir_input.setPlaceholderText("Select a folder...")
        self.save_dir_input.textChanged.connect(self._on_save_dir_changed)
        g3l.addWidget(self.save_dir_input, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.setAutoDefault(False)
        btn_browse.clicked.connect(self._browse_save_dir)
        g3l.addWidget(btn_browse)
        outer.addWidget(g3)

        # ── Behavior ──
        g4 = QGroupBox("Behavior")
        g4l = QVBoxLayout(g4)
        g4l.setSpacing(6)
        self.chk_confirm = QCheckBox("Confirm before dangerous operations (reboot, uninstall)")
        self.chk_confirm.setChecked(self.s.get("confirm_dangerous_ops", True))
        self.chk_confirm.toggled.connect(lambda v: self.s.set("confirm_dangerous_ops", v))
        g4l.addWidget(self.chk_confirm)
        self.chk_auto_refresh = QCheckBox("Auto-refresh device list after connect")
        self.chk_auto_refresh.setChecked(self.s.get("auto_refresh_on_connect", True))
        self.chk_auto_refresh.toggled.connect(lambda v: self.s.set("auto_refresh_on_connect", v))
        g4l.addWidget(self.chk_auto_refresh)
        outer.addWidget(g4)

        # ── Bottom ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        btn_reset = QPushButton("Restore Defaults")
        btn_reset.clicked.connect(self._reset_all)
        btn_row.addWidget(btn_reset)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        outer.addLayout(btn_row)

    # ── 即时生效回调 ────────────────────────────────────────────────────

    def _on_theme_changed(self, t: str):
        BaseStyles.switch_theme(t)
        self.s.set("theme", t)

    def _on_font_family_changed(self, f: str):
        self.s.set("font_family", f)
        BaseStyles.reload_from_settings()

    def _on_font_changed(self, v: int):
        self.s.set("ui_font_size", v)
        BaseStyles.reload_from_settings()

    def _on_log_font_changed(self, v: int):
        self.s.set("log_font_size", v)
        BaseStyles.reload_from_settings()

    def _update_right_label(self):
        right_w = self.spin_win_w.value() - self.spin_left_w.value() - self._overhead
        self.lbl_right_w.setText(f"{right_w} px")

    def _update_left_range(self):
        left_max = self.spin_win_w.value() - 311
        if left_max < 200:
            left_max = 200
        self.spin_left_w.setMaximum(left_max)

    def _on_window_size_changed(self):
        w = self.spin_win_w.value()
        h = self.spin_win_h.value()
        self.s.set("window_width", w)
        self.s.set("window_height", h)
        pw = self.parent()
        if pw and hasattr(pw, "apply_window_size"):
            pw.apply_window_size(w, h)
        self._update_left_range()
        self._apply_panels()

    def _on_window_height_changed(self):
        h = self.spin_win_h.value()
        self.s.set("window_height", h)
        pw = self.parent()
        if pw and hasattr(pw, "apply_window_size"):
            pw.apply_window_size(self.spin_win_w.value(), h)

    def _on_splitter_changed(self, _pos, _index):
        pw = self.parent()
        if pw and hasattr(pw, "panel_sizes"):
            sizes = pw.panel_sizes()
            if len(sizes) == 2:
                self.spin_left_w.blockSignals(True)
                self.spin_left_w.setValue(sizes[0])
                self.spin_left_w.blockSignals(False)
                self._update_right_label()

    def _apply_panels(self):
        left_w = self.spin_left_w.value()
        win_w = self.spin_win_w.value()
        right_w = win_w - left_w - self._overhead
        if right_w < 300:
            right_w = 300
            left_w = win_w - right_w - self._overhead
            self.spin_left_w.blockSignals(True)
            self.spin_left_w.setValue(left_w)
            self.spin_left_w.blockSignals(False)
        self.s.set("left_panel_width", left_w)
        self.s.set("right_panel_width", right_w)
        pw = self.parent()
        if pw and hasattr(pw, "apply_panel_sizes"):
            pw.apply_panel_sizes(left_w, right_w)
        self._update_right_label()

    def _on_save_dir_changed(self, t: str):
        self.s.set("save_directory", t.strip())

    def _browse_save_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Save Directory", self.save_dir_input.text()
        )
        if d:
            self.save_dir_input.setText(d)

    # ── 主题样式（统一设置在 Dialog 上，不分散到子控件）─────────────────

    def _apply_theme(self, _name: str = ""):
        r = BaseStyles.RADIUS_MD
        bg = BaseStyles.color("WINDOW_BG")
        fg = BaseStyles.color("TEXT_PRIMARY")
        ibg = BaseStyles.color("INPUT_BG")
        border = BaseStyles.color("BORDER_COLOR")
        accent = BaseStyles.color("BUTTON_ACCENT")
        hov = BaseStyles.color("BUTTON_HOVER")
        btn = BaseStyles.color("BUTTON_BG")
        prs = BaseStyles.color("BUTTON_PRESSED")
        sel_bg = BaseStyles.color("SELECTION_BG")
        sel_fg = BaseStyles.color("SELECTION_TEXT")
        gt = BaseStyles.color("GROUP_TITLE_COLOR")

        self.setStyleSheet(f"""
            QDialog                {{ background-color: {bg}; }}
            QLabel                 {{ color: {fg}; background: transparent; }}
            QCheckBox              {{ color: {fg}; spacing: 8px; background: transparent; }}
            QCheckBox::indicator   {{ width: 16px; height: 16px; border: 2px solid {border}; border-radius: 3px; background: {ibg}; image: none; }}
            QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: none; }}
            QCheckBox::indicator:unchecked {{ image: none; }}
            QLineEdit              {{ background: {ibg}; color: {fg}; border: 1px solid {border}; border-radius: {r}px; padding: 4px 8px; }}
            QLineEdit:focus        {{ border-color: {accent}; }}
            QSpinBox               {{ background: {ibg}; color: {fg}; border: 1px solid {border}; border-radius: {r}px; padding: 3px 20px 3px 6px; }}
            QSpinBox:hover         {{ border: 1px solid {accent}; }}
            QSpinBox:focus         {{ border: 1px solid {accent}; }}
            QSpinBox::up-button    {{ subcontrol-origin: margin; subcontrol-position: top right; width: 16px; border: none; border-left: 1px solid {border}; border-bottom: 1px solid {border}; border-top-right-radius: {r-1}px; background: transparent; margin: 1px; }}
            QSpinBox::up-button:hover {{ background: {hov}; border-left: 1px solid {accent}; border-bottom: 1px solid {accent}; border-top-right-radius: {r-1}px; }}
            QSpinBox::down-button  {{ subcontrol-origin: margin; subcontrol-position: bottom right; width: 16px; border: none; border-left: 1px solid {border}; border-bottom-right-radius: {r-1}px; background: transparent; margin: 1px; }}
            QSpinBox::down-button:hover {{ background: {hov}; border-left: 1px solid {accent}; border-bottom-right-radius: {r-1}px; }}
            QComboBox              {{ background: {ibg}; color: {fg}; border: 1px solid {border}; border-radius: {r}px; padding: 3px 6px; }}
            QComboBox:focus        {{ border-color: {accent}; }}
            QComboBox::drop-down   {{ subcontrol-origin: padding; subcontrol-position: top right; width: 20px; border-left: 1px solid {border}; border-top-right-radius: {r}px; border-bottom-right-radius: {r}px; background: {btn}; }}
            QComboBox::drop-down:hover {{ background: {hov}; }}
            QComboBox QAbstractItemView {{ background: {ibg}; color: {fg}; selection-background-color: {sel_bg}; selection-color: {sel_fg}; border: 1px solid {border}; outline: none; }}
            QPushButton            {{ background: {btn}; color: {fg}; border: 1px solid {border}; border-radius: {r}px; padding: 4px 14px; }}
            QPushButton:hover      {{ background: {hov}; border-color: {accent}; }}
            QPushButton:pressed    {{ background: {prs}; }}
            QGroupBox              {{ font-weight: bold; color: {gt}; border: 1px solid {border}; border-radius: {r}px; margin-top: 8px; padding: 8px 10px 6px 10px; background: transparent; }}
            QGroupBox::title       {{ subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; left: 10px; color: {gt}; background: transparent; }}
        """)

    # ── 重置 ────────────────────────────────────────────────────────────

    def _reset_all(self):
        if (
            QMessageBox.question(self, "Reset Settings", "Restore all settings to defaults?")
            == QMessageBox.StandardButton.Yes
        ):
            self.s.reset()
            BaseStyles.switch_theme("Light")
            self.theme_combo.setCurrentText("Light")
            self.spin_font.setValue(12)
            BaseStyles.reload_from_settings()
            self.accept()
