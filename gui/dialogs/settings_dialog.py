"""
Settings dialog — single-page configuration with live theme response.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox,
    QLineEdit, QCheckBox, QComboBox, QFileDialog, QGroupBox,
    QDialogButtonBox, QWidget, QMessageBox,
)
from gui.styles.base_styles import BaseStyles, get_default_font
from core.settings_manager import AppSettings


class SettingsDialog(QDialog):
    settings_applied = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = AppSettings.instance()
        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 500)
        self.setModal(True)
        self._init_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)

    def _init_ui(self):
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        outer.setContentsMargins(16, 12, 16, 12)

        # ── Appearance ──
        g1 = self._group("Appearance")
        g1l = QVBoxLayout(g1)
        g1l.setSpacing(6)

        r = QHBoxLayout()
        r.setSpacing(12)
        r.addWidget(QLabel("Theme"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(BaseStyles.theme_names())
        self.theme_combo.setCurrentText(self.settings.get("theme", "Light"))
        self.theme_combo.currentTextChanged.connect(lambda t: BaseStyles.switch_theme(t))
        self.theme_combo.setFixedWidth(120)
        r.addWidget(self.theme_combo)
        r.addStretch()
        g1l.addLayout(r)

        font_row = QHBoxLayout()
        font_row.setSpacing(12)
        self.spin_base = self._spin("UI Font", "font_base_size", 8, 24, font_row)
        self.spin_small = self._spin("Button Font", "font_small_size", 7, 22, font_row)
        self.spin_tab = self._spin("Tab Font", "font_tab_size", 7, 22, font_row)
        self.spin_mono = self._spin("Mono Font", "font_mono_size", 7, 18, font_row)
        g1l.addLayout(font_row)
        outer.addWidget(g1)

        # ── Window Size ──
        gw = self._group("Window Size")
        gwl = QHBoxLayout(gw)
        gwl.setSpacing(12)
        gwl.addWidget(QLabel("Width"))
        self.spin_win_w = QSpinBox()
        self.spin_win_w.setRange(800, 3840)
        self.spin_win_w.setSingleStep(20)
        gwl.addWidget(self.spin_win_w)
        gwl.addWidget(QLabel("×"))
        gwl.addWidget(QLabel("Height"))
        self.spin_win_h = QSpinBox()
        self.spin_win_h.setRange(500, 2160)
        self.spin_win_h.setSingleStep(20)
        gwl.addWidget(self.spin_win_h)
        gwl.addWidget(QLabel("px"))
        gwl.addStretch()
        outer.addWidget(gw)
        # Read live window size from parent, fallback to saved
        pw = self.parent()
        if pw:
            self.spin_win_w.setValue(pw.width())
            self.spin_win_h.setValue(pw.height())
        else:
            self.spin_win_w.setValue(self.settings.get("window_width", 1120))
            self.spin_win_h.setValue(self.settings.get("window_height", 640))

        # ── File Path ──
        g2 = self._group("Default Save Location")
        g2l = QHBoxLayout(g2)
        g2l.setSpacing(8)
        self.save_dir_input = QLineEdit()
        self.save_dir_input.setText(self.settings.save_directory)
        self.save_dir_input.setPlaceholderText("Click Browse to select a folder...")
        g2l.addWidget(self.save_dir_input, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_save_dir)
        g2l.addWidget(browse_btn)
        outer.addWidget(g2)

        # ── Behavior ──
        g3 = self._group("Behavior")
        g3l = QVBoxLayout(g3)
        g3l.setSpacing(5)

        self.chk_confirm = QCheckBox("Confirm before dangerous operations (reboot, uninstall)")
        self.chk_confirm.setChecked(self.settings.get("confirm_dangerous_ops", True))
        g3l.addWidget(self.chk_confirm)

        self.chk_auto_refresh = QCheckBox("Auto-refresh device list after connect")
        self.chk_auto_refresh.setChecked(self.settings.get("auto_refresh_on_connect", True))
        g3l.addWidget(self.chk_auto_refresh)

        outer.addWidget(g3)

        # ── Defaults ──
        g4 = self._group("Defaults")
        g4l = QVBoxLayout(g4)
        g4l.setSpacing(6)

        dr1 = QHBoxLayout()
        dr1.setSpacing(12)
        dr1.addWidget(QLabel("Log buffer lines"))
        self.spin_log_lines = QSpinBox()
        self.spin_log_lines.setRange(500, 50000)
        self.spin_log_lines.setSingleStep(500)
        self.spin_log_lines.setValue(self.settings.get("log_max_lines", 2000))
        self.spin_log_lines.setFixedWidth(100)
        dr1.addWidget(self.spin_log_lines)
        dr1.addStretch()
        g4l.addLayout(dr1)

        dr2 = QHBoxLayout()
        dr2.setSpacing(12)
        dr2.addWidget(QLabel("Monkey event count"))
        self.monkey_count_combo = QComboBox()
        self.monkey_count_combo.setEditable(True)
        self.monkey_count_combo.addItems(["100", "1000", "5000", "10000", "50000", "100000", "500000"])
        self.monkey_count_combo.setCurrentText(self.settings.get("monkey_default_count", "10000"))
        self.monkey_count_combo.setFixedWidth(120)
        dr2.addWidget(self.monkey_count_combo)
        dr2.addStretch()
        g4l.addLayout(dr2)

        dr3 = QHBoxLayout()
        dr3.setSpacing(12)
        dr3.addWidget(QLabel("Screen record duration (seconds)"))
        self.spin_rec_dur = QSpinBox()
        self.spin_rec_dur.setRange(10, 1800)
        self.spin_rec_dur.setSingleStep(30)
        self.spin_rec_dur.setValue(self.settings.get("screen_record_duration", 180))
        self.spin_rec_dur.setFixedWidth(100)
        dr3.addWidget(self.spin_rec_dur)
        dr3.addStretch()
        g4l.addLayout(dr3)

        outer.addWidget(g4)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        reset_btn = QPushButton("Restore Defaults")
        reset_btn.clicked.connect(self._reset_all)
        btn_row.addWidget(reset_btn)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                               QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        btn_row.addWidget(box)
        outer.addLayout(btn_row)

    def _group(self, title: str) -> QGroupBox:
        g = QGroupBox(title)
        g.setFont(QFont(BaseStyles.DEFAULT_FONT_FAMILY, BaseStyles.DEFAULT_FONT_SIZE))
        g.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {BaseStyles.color('GROUP_TITLE_COLOR')};
                border: 1px solid {BaseStyles.color('BORDER_COLOR')};
                border-radius: {BaseStyles.RADIUS_MD}px;
                margin-top: 8px;
                padding: 10px 12px 8px 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 10px;
                color: {BaseStyles.color('GROUP_TITLE_COLOR')};
            }}
        """)
        return g

    def _spin(self, label: str, key: str, lo: int, hi: int, parent) -> QSpinBox:
        parent.addWidget(QLabel(label))
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(self.settings.get(key))
        spin.setSuffix(" px")
        spin.setFixedWidth(80)
        parent.addWidget(spin)
        return spin

    def _browse_save_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Save Directory",
                                             self.save_dir_input.text())
        if d:
            self.save_dir_input.setText(d)

    def _apply_theme(self, _name: str = ""):
        bg = BaseStyles.color('PANEL_BG')
        fg = BaseStyles.color('TEXT_PRIMARY')
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg};
                color: {fg};
            }}
            {BaseStyles.BUTTON_STYLE()}
            {BaseStyles.INPUT_STYLE()}
            QCheckBox {{
                color: {fg};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
            }}
        """)

    def _on_accept(self):
        self._save_all()
        self.accept()

    def _apply_window_size(self):
        pw = self.parent()
        if pw and hasattr(pw, 'resize'):
            pw.resize(self.spin_win_w.value(), self.spin_win_h.value())

    def _save_all(self):
        s = self.settings
        s.set("font_base_size", self.spin_base.value())
        s.set("font_small_size", self.spin_small.value())
        s.set("font_tab_size", self.spin_tab.value())
        s.set("font_mono_size", self.spin_mono.value())
        s.set("save_directory", self.save_dir_input.text().strip())
        s.set("log_max_lines", self.spin_log_lines.value())
        s.set("monkey_default_count", self.monkey_count_combo.currentText())
        s.set("screen_record_duration", self.spin_rec_dur.value())
        s.set("confirm_dangerous_ops", self.chk_confirm.isChecked())
        s.set("auto_refresh_on_connect", self.chk_auto_refresh.isChecked())
        s.set("theme", self.theme_combo.currentText())
        s.set("window_width", self.spin_win_w.value())
        s.set("window_height", self.spin_win_h.value())
        from gui.styles.base_styles import BaseStyles as BS
        BS.reload_from_settings()
        self._apply_window_size()
        self.settings_applied.emit()

    def _on_apply(self):
        self._save_all()

    def _reset_all(self):
        if QMessageBox.question(self, "Reset Settings",
                                "Restore all settings to defaults?") == QMessageBox.StandardButton.Yes:
            self.settings.reset()
            self.accept()
