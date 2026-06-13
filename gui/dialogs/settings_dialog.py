"""Settings dialog — immediate-apply, theme-aware, with full settings coverage."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.settings_manager import AppSettings
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar


class SettingsDialog(QDialog):
    settings_applied = Signal()
    continuous_scan_toggled = Signal(bool)

    _OVERHEAD = 13

    def __init__(self, parent=None):
        super().__init__(parent)
        self.s = AppSettings.instance()
        self.setWindowTitle("Settings")
        self.setWindowIcon(get_themed_icon("gear.svg"))
        self.setMinimumWidth(520)
        self.setModal(True)

        self._build_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        pw = self.parent()
        if pw and hasattr(pw, "_panel_splitter"):
            pw._panel_splitter.splitterMoved.connect(self._on_splitter_changed)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QVBoxLayout()
        content.setContentsMargins(2, 2, 2, 2)
        content.setSpacing(6)

        self._build_appearance(content)
        self._build_window(content)
        self._build_behavior(content)
        self._build_general(content)
        content.addStretch()
        self._build_footer(content)
        root.addLayout(content)

    # ── Appearance ──────────────────────────────────────────────────────

    def _build_appearance(self, body):
        g = self._section("Appearance")
        self._theme_combo = self._combo(
            BaseStyles.theme_names(), BaseStyles.current_theme()
        )
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        self._font_combo = self._combo(
            ["Segoe UI", "Microsoft YaHei", "Arial", "Consolas", "Tahoma", "Verdana"],
            self.s.get("font_family", "Segoe UI"),
        )
        self._font_combo.currentTextChanged.connect(self._on_font_family_changed)
        self._combo_font = self._combo(
            ["8", "9", "10", "11", "12", "13", "14", "15", "16", "18", "20", "22"],
            str(self.s.get("ui_font_size", 12)),
        )
        self._combo_font.currentTextChanged.connect(self._on_font_changed)
        self._combo_log_font = self._combo(
            ["7", "8", "9", "10", "11", "12", "13", "14", "15", "16"],
            str(self.s.get("log_font_size", 9)),
        )
        self._combo_log_font.currentTextChanged.connect(self._on_log_font_changed)

        gg = QGridLayout(g)
        gg.setContentsMargins(8, 12, 8, 8)
        gg.setHorizontalSpacing(8)
        gg.setVerticalSpacing(6)
        gg.addWidget(self._label("Theme"), 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        gg.addWidget(self._theme_combo, 0, 1)
        gg.addWidget(self._label("Font"), 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        gg.addWidget(self._font_combo, 0, 3)
        gg.addWidget(self._label("UI Size"), 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        gg.addWidget(self._combo_font, 1, 1)
        gg.addWidget(self._label("Log Size"), 1, 2, Qt.AlignRight | Qt.AlignVCenter)
        gg.addWidget(self._combo_log_font, 1, 3)
        gg.setColumnStretch(1, 1)
        gg.setColumnStretch(3, 1)
        body.addWidget(g)

    # ── Window ──────────────────────────────────────────────────────────

    def _build_window(self, body):
        g = self._section("Window")
        pw = self.parent()
        cur_w = pw.width() if pw else self.s.get("window_width", 1120)
        cur_h = pw.height() if pw else self.s.get("window_height", 640)
        if pw and hasattr(pw, "_panel_splitter"):
            sizes = pw._panel_splitter.sizes()
            cur_left = sizes[0] if len(sizes) == 2 else self.s.get("left_panel_width", 400)
        else:
            cur_left = self.s.get("left_panel_width", 400)

        self._inp_win_w = self._int_input(cur_w, 860, 2560)
        self._inp_win_w.textChanged.connect(lambda inp=self._inp_win_w: self._on_int_changed(inp, None, self._on_window_size_changed))
        self._inp_win_h = self._int_input(cur_h, 500, 1800)
        self._inp_win_h.textChanged.connect(lambda inp=self._inp_win_h: self._on_int_changed(inp, None, self._on_window_height_changed))
        self._inp_left_w = self._int_input(cur_left, 200, max(200, cur_w - 311))
        self._inp_left_w.textChanged.connect(lambda inp=self._inp_left_w: self._on_int_changed(inp, None, self._apply_panels))
        self._lbl_right_w = QLabel()
        self._lbl_right_w.setObjectName("hintLabel")
        self._update_right_label()

        gg = QGridLayout(g)
        gg.setContentsMargins(8, 12, 8, 8)
        gg.setHorizontalSpacing(8)
        gg.setVerticalSpacing(6)
        gg.addWidget(self._label("Width"), 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        gg.addLayout(self._with_unit(self._inp_win_w, "px"), 0, 1)
        gg.addWidget(self._label("Height"), 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        gg.addLayout(self._with_unit(self._inp_win_h, "px"), 0, 3)
        gg.addWidget(self._label("Left"), 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        gg.addLayout(self._with_unit(self._inp_left_w, "px"), 1, 1)
        gg.addWidget(self._label("Right"), 1, 2, Qt.AlignRight | Qt.AlignVCenter)
        gg.addWidget(self._lbl_right_w, 1, 3)
        gg.setColumnStretch(1, 1)
        gg.setColumnStretch(3, 1)
        body.addWidget(g)

    # ── Behavior ────────────────────────────────────────────────────────

    def _build_behavior(self, body):
        g = self._section("Behavior")

        self._chk_confirm = self._checkbox(
            "Confirm before dangerous operations (reboot, uninstall)"
        )
        self._chk_confirm.setChecked(self.s.get("confirm_dangerous_ops", True))
        self._chk_confirm.toggled.connect(lambda v: self.s.set("confirm_dangerous_ops", v))

        self._chk_continuous_scan = self._checkbox(
            "Continuously scan for new devices (every 3s)"
        )
        self._chk_continuous_scan.setChecked(self.s.get("continuous_device_scan", True))
        self._chk_continuous_scan.toggled.connect(self._on_continuous_scan_toggled)

        vl = QVBoxLayout(g)
        vl.setContentsMargins(8, 12, 8, 8)
        vl.setSpacing(4)
        vl.addWidget(self._chk_confirm)
        vl.addWidget(self._chk_continuous_scan)
        body.addWidget(g)

    # ── General ─────────────────────────────────────────────────────────

    def _build_general(self, body):
        g = self._section("General")
        gg = QGridLayout(g)
        gg.setContentsMargins(8, 12, 8, 8)
        gg.setHorizontalSpacing(8)
        gg.setVerticalSpacing(6)

        save_dir = self.s.get("save_directory", "")
        self._lbl_save = QLabel(save_dir if save_dir else "~/ADBLab (default)")
        self._lbl_save.setObjectName("hintLabel")
        self._lbl_save.setWordWrap(True)
        self._btn_save = self._icon_button("folder.svg", "Choose...")
        self._btn_save.clicked.connect(self._on_pick_save_dir)
        gg.addWidget(self._label("Save Dir"), 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        gg.addWidget(self._lbl_save, 0, 1,)

        # Log max lines
        self._combo_log_lines = self._combo(
            ["1000", "2000", "3000", "5000", "10000"],
            str(self.s.get("log_max_lines", 2000)),
        )
        self._combo_log_lines.currentTextChanged.connect(
            lambda t: self.s.set("log_max_lines", int(t))
        )
        gg.addWidget(self._label("Max Log"), 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        gg.addWidget(self._combo_log_lines, 0, 3)


        gg.setColumnStretch(1, 2)
        body.addWidget(g)

    # ── Footer ──────────────────────────────────────────────────────────

    def _build_footer(self, body):
        body.addSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(2, 0, 2, 0)
        row.addStretch()
        btn_reset = QPushButton("Restore Defaults")
        btn_reset.setIcon(get_themed_icon("arrow-u-up-left.svg"))
        btn_reset.setIconSize(QSize(16, 16))
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setAutoDefault(False)
        btn_reset.clicked.connect(self._reset_all)
        row.addWidget(btn_reset)
        btn_close = QPushButton("Close")
        btn_close.setIcon(get_themed_icon("x.svg"))
        btn_close.setIconSize(QSize(16, 16))
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setObjectName("accentBtn")
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        body.addLayout(row)

    # ── Widget helpers ──────────────────────────────────────────────────

    def _section(self, title: str) -> QGroupBox:
        g = QGroupBox(title)
        g.setObjectName("settingsSection")
        return g

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("settingsLabel")
        return lbl

    def _combo(self, items: list, current: str) -> QComboBox:
        c = QComboBox()
        c.addItems(items)
        c.setCurrentText(current)
        return c

    def _int_input(self, val: int, lo: int, hi: int) -> QLineEdit:
        inp = QLineEdit()
        inp.setValidator(QIntValidator(lo, hi))
        inp.setText(str(val))
        inp.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        inp.setObjectName("numInput")
        return inp

    def _with_unit(self, widget: QLineEdit, unit: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(widget, 1)
        lbl = QLabel(unit)
        lbl.setObjectName("unitLabel")
        row.addWidget(lbl)
        return row

    def _checkbox(self, text: str) -> QCheckBox:
        cb = QCheckBox(text)
        cb.setObjectName("settingsCheck")
        return cb

    def _icon_button(self, icon: str, text: str = "") -> QPushButton:
        btn = QPushButton(text)
        if icon:
            btn.setIcon(get_themed_icon(icon))
            btn.setIconSize(QSize(14, 14))
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _read_int(self, inp: QLineEdit) -> int:
        t = inp.text()
        try:
            return int(t) if t else 0
        except ValueError:
            return 0

    # ── Callback helpers ────────────────────────────────────────────────

    def _on_int_changed(self, inp: QLineEdit, setting_key: str | None, after=None):
        if setting_key:
            self.s.set(setting_key, self._read_int(inp))
        if after:
            after()

    # ── Callbacks ───────────────────────────────────────────────────────

    def _on_theme_changed(self, t: str):
        BaseStyles.switch_theme(t)
        self.s.set("theme", t)

    def _on_font_family_changed(self, f: str):
        self.s.set("font_family", f)
        BaseStyles.reload_from_settings()

    def _on_font_changed(self, t: str):
        self.s.set("ui_font_size", int(t))
        BaseStyles.reload_from_settings()

    def _on_log_font_changed(self, t: str):
        self.s.set("log_font_size", int(t))
        BaseStyles.reload_from_settings()

    def _on_continuous_scan_toggled(self, checked: bool):
        self.s.set("continuous_device_scan", checked)
        self.continuous_scan_toggled.emit(checked)

    def _on_pick_save_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select default save directory")
        if d:
            self.s.set("save_directory", d)
            self._lbl_save.setText(d)

    def _update_right_label(self):
        right_w = self._read_int(self._inp_win_w) - self._read_int(self._inp_left_w) - self._OVERHEAD
        self._lbl_right_w.setText(f"{right_w} px")

    def _update_left_range(self):
        left_max = self._read_int(self._inp_win_w) - 311
        self._inp_left_w.validator().setRange(200, max(200, left_max))
        cur = self._read_int(self._inp_left_w)
        if cur > left_max:
            self._inp_left_w.setText(str(left_max))

    def _on_window_size_changed(self):
        w = self._read_int(self._inp_win_w)
        h = self._read_int(self._inp_win_h)
        self.s.set("window_width", w)
        self.s.set("window_height", h)
        pw = self.parent()
        if pw and hasattr(pw, "apply_window_size"):
            pw.apply_window_size(w, h)
        self._update_left_range()
        self._apply_panels()

    def _on_window_height_changed(self):
        h = self._read_int(self._inp_win_h)
        self.s.set("window_height", h)
        pw = self.parent()
        if pw and hasattr(pw, "apply_window_size"):
            pw.apply_window_size(self._read_int(self._inp_win_w), h)

    def _on_splitter_changed(self, _pos, _index):
        pw = self.parent()
        if pw and hasattr(pw, "_panel_splitter"):
            sizes = pw._panel_splitter.sizes()
            if len(sizes) == 2:
                self._inp_left_w.blockSignals(True)
                self._inp_left_w.setText(str(sizes[0]))
                self._inp_left_w.blockSignals(False)
                self._update_right_label()

    def _apply_panels(self):
        left_w = self._read_int(self._inp_left_w)
        win_w = self._read_int(self._inp_win_w)
        right_w = win_w - left_w - self._OVERHEAD
        if right_w < 300:
            right_w = 300
            left_w = win_w - right_w - self._OVERHEAD
            self._inp_left_w.blockSignals(True)
            self._inp_left_w.setText(str(left_w))
            self._inp_left_w.blockSignals(False)
        self.s.set("left_panel_width", left_w)
        self.s.set("right_panel_width", right_w)
        pw = self.parent()
        if pw and hasattr(pw, "apply_panel_sizes"):
            pw.apply_panel_sizes(left_w, right_w)
        self._update_right_label()

    # ── Theme ───────────────────────────────────────────────────────────

    def closeEvent(self, event):
        BaseStyles.theme_changed.disconnect(self._apply_theme)
        super().closeEvent(event)

    def _apply_theme(self, _name: str = ""):
        apply_dark_title_bar(self)
        c = BaseStyles.color
        r = BaseStyles.RADIUS_MD
        ui_size = BaseStyles.DEFAULT_FONT_SIZE
        label_size = max(10, ui_size - 1)
        hint_size = max(9, ui_size - 2)

        self.setFont(BaseStyles.get_default_font())
        self.setStyleSheet(
            BaseStyles.INPUT_STYLE()
            + BaseStyles.BUTTON_QSS()
            + BaseStyles.SCROLLBAR_STYLE()
            + f"""
            QDialog {{
                background-color: {c('WINDOW_BG')};
                color: {c('TEXT_PRIMARY')};
                font-family: '{BaseStyles.DEFAULT_FONT_FAMILY}';
                font-size: {ui_size}px;
            }}
            QDialog QLabel,
            QDialog QLineEdit,
            QDialog QComboBox,
            QDialog QComboBox QAbstractItemView,
            QDialog QCheckBox,
            QDialog QPushButton {{
                font-family: '{BaseStyles.DEFAULT_FONT_FAMILY}';
                font-size: {ui_size}px;
            }}
            QGroupBox#settingsSection {{
                background-color: {c('PANEL_BG')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r}px;
                margin-top: 5px;
                font-family: '{BaseStyles.DEFAULT_FONT_FAMILY}';
                font-size: {ui_size}px;
                font-weight: bold;
                color: {c('TEXT_PRIMARY')};
            }}
            QLabel#settingsLabel {{
                font-size: {label_size}px;
                font-weight: bold;
                color: {c('TEXT_PRIMARY')};
                min-width: 64px;
            }}
            QLabel#hintLabel {{
                font-size: {hint_size}px;
                color: {c('TEXT_SECONDARY')};
                padding: 3px 4px;
            }}
            QLabel#unitLabel {{
                font-size: {label_size}px;
                color: {c('TEXT_SECONDARY')};
                min-width: 34px;
            }}
            QComboBox {{
                min-height: 26px;
            }}
            QLineEdit#numInput {{
                background-color: {c('INPUT_BG')};
                color: {c('TEXT_PRIMARY')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r}px;
                min-height: 24px;
                padding: 3px 8px;
                font-family: '{BaseStyles.DEFAULT_FONT_FAMILY}';
                font-size: {ui_size}px;
            }}
            QLineEdit#numInput:focus {{ border-color: {c('BORDER_FOCUS')}; }}
            QCheckBox#settingsCheck {{
                color: {c('TEXT_PRIMARY')};
                spacing: 8px;
                padding: 2px 0;
            }}
            QPushButton {{
                min-height: 26px;
                padding: 4px 12px;
            }}
            QPushButton#accentBtn {{
                background-color: {c('BUTTON_ACCENT')};
                color: #ffffff;
                border: none;
                border-radius: {r}px;
                min-height: 26px;
                padding: 4px 18px;
                font-weight: bold;
            }}
            QPushButton#accentBtn:hover {{ background-color: {c('BUTTON_ACCENT_HOVER')}; }}
            QPushButton#accentBtn:pressed {{ background-color: {c('BUTTON_ACCENT_PRESSED')}; }}
        """)

    # ── Reset ───────────────────────────────────────────────────────────

    def _reset_all(self):
        if (
            QMessageBox.question(self, "Reset Settings", "Restore all settings to defaults?")
            == QMessageBox.StandardButton.Yes
        ):
            self.s.reset()
            BaseStyles.switch_theme("Light")
            self._theme_combo.setCurrentText("Light")
            self._combo_font.setCurrentText("12")
            self._combo_log_font.setCurrentText("9")
            self._font_combo.setCurrentText("Segoe UI")
            self._chk_confirm.setChecked(True)
            self._chk_continuous_scan.setChecked(True)
            self._combo_log_lines.setCurrentText("2000")
            self._lbl_save.setText("~/ADBLab (default)")
            BaseStyles.reload_from_settings()
            self.accept()
