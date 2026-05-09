"""Settings dialog -- immediate-apply, theme-aware."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from core.settings_manager import AppSettings
from gui.styles.base_styles import BaseStyles


class SettingsDialog(QDialog):
    settings_applied = Signal()

    _OVERHEAD = 13  # border(2) + margins(6) + splitter handle(5)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.s = AppSettings.instance()
        self.setWindowTitle("Settings")
        self.setFixedSize(440, 460)
        self.setModal(True)

        self._build_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        pw = self.parent()
        if pw and hasattr(pw, "_panel_splitter"):
            pw._panel_splitter.splitterMoved.connect(self._on_splitter_changed)

    # ── UI ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # ── Content area ──
        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 12)
        body.setSpacing(10)

        self._build_appearance(body)
        self._build_window(body)
        self._build_behavior(body)
        self._build_buttons(body)

        lo.addLayout(body)

    def _build_appearance(self, body):
        body.addWidget(self._section("Appearance"))

        card = self._card()
        cl = QVBoxLayout(card)
        cl.setSpacing(8)

        # Theme + Font family
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(self._lbl("Theme"))
        self.theme_combo = self._combo(BaseStyles.theme_names(), BaseStyles.current_theme())
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        r1.addWidget(self.theme_combo)
        r1.addSpacing(12)
        r1.addWidget(self._lbl("Font"))
        self.font_family_combo = self._combo(
            ["Segoe UI", "Microsoft YaHei", "Arial", "Consolas", "Tahoma", "Verdana"],
            self.s.get("font_family", "Segoe UI"),
        )
        self.font_family_combo.currentTextChanged.connect(self._on_font_family_changed)
        r1.addWidget(self.font_family_combo)
        cl.addLayout(r1)

        # UI size + Log size
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(self._lbl("UI Size"))
        self.spin_font = self._spin(8, 22, self.s.get("ui_font_size", 12))
        self.spin_font.valueChanged.connect(self._on_font_changed)
        r2.addWidget(self.spin_font)
        r2.addSpacing(12)
        r2.addWidget(self._lbl("Log Size"))
        self.spin_log_font = self._spin(7, 16, self.s.get("log_font_size", 9))
        self.spin_log_font.valueChanged.connect(self._on_log_font_changed)
        r2.addWidget(self.spin_log_font)
        r2.addStretch()
        cl.addLayout(r2)

        body.addWidget(card)

    def _build_window(self, body):
        body.addWidget(self._section("Window"))

        card = self._card()
        cl = QVBoxLayout(card)
        cl.setSpacing(8)

        pw = self.parent()
        cur_w = pw.width() if pw else self.s.get("window_width", 1200)
        cur_h = pw.height() if pw else self.s.get("window_height", 650)
        if pw and hasattr(pw, "_panel_splitter"):
            sizes = pw._panel_splitter.sizes()
            cur_left = sizes[0] if len(sizes) == 2 else self.s.get("left_panel_width", 595)
        else:
            cur_left = self.s.get("left_panel_width", 595)

        # Width + Height
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(self._lbl("Width"))
        self.spin_win_w = self._spin(860, 2560, cur_w, 20)
        self.spin_win_w.valueChanged.connect(self._on_window_size_changed)
        r1.addWidget(self.spin_win_w)
        r1.addSpacing(12)
        r1.addWidget(self._lbl("Height"))
        self.spin_win_h = self._spin(500, 1800, cur_h, 20)
        self.spin_win_h.valueChanged.connect(self._on_window_height_changed)
        r1.addWidget(self.spin_win_h)
        r1.addStretch()
        cl.addLayout(r1)

        # Left + Right panel
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(self._lbl("Left"))
        self.spin_left_w = self._spin(200, max(200, cur_w - 311), cur_left, 10)
        self.spin_left_w.valueChanged.connect(self._apply_panels)
        r2.addWidget(self.spin_left_w)
        r2.addSpacing(12)
        r2.addWidget(self._lbl("Right"))
        self.lbl_right_w = QLabel()
        self.lbl_right_w.setObjectName("rightLabel")
        self._update_right_label()
        r2.addWidget(self.lbl_right_w)
        r2.addStretch()
        cl.addLayout(r2)

        body.addWidget(card)

    def _build_behavior(self, body):
        body.addWidget(self._section("Behavior"))

        card = self._card()
        cl = QVBoxLayout(card)
        cl.setSpacing(4)

        self.chk_confirm = QCheckBox("Confirm before dangerous operations (reboot, uninstall)")
        self.chk_confirm.setChecked(self.s.get("confirm_dangerous_ops", True))
        self.chk_confirm.toggled.connect(lambda v: self.s.set("confirm_dangerous_ops", v))
        cl.addWidget(self.chk_confirm)

        self.chk_auto_refresh = QCheckBox("Auto-refresh device list after connect")
        self.chk_auto_refresh.setChecked(self.s.get("auto_refresh_on_connect", True))
        self.chk_auto_refresh.toggled.connect(lambda v: self.s.set("auto_refresh_on_connect", v))
        cl.addWidget(self.chk_auto_refresh)

        body.addWidget(card)

    def _build_buttons(self, body):
        body.addSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        btn_reset = QPushButton("Restore Defaults")
        btn_reset.setObjectName("resetBtn")
        btn_reset.clicked.connect(self._reset_all)
        row.addWidget(btn_reset)
        btn_close = QPushButton("Close")
        btn_close.setObjectName("closeBtn")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        body.addLayout(row)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setObjectName("sectionLabel")
        return lbl

    def _card(self) -> QFrame:
        f = QFrame()
        f.setObjectName("settingsCard")
        return f

    def _lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("fieldLabel")
        return lbl

    def _combo(self, items: list[str], current: str) -> QComboBox:
        c = QComboBox()
        c.addItems(items)
        c.setCurrentText(current)
        return c

    def _spin(self, lo: int, hi: int, val: int, step: int = 1) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setValue(val)
        s.setSuffix(" px")
        return s

    # ── Callbacks ───────────────────────────────────────────────────────

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
        right_w = self.spin_win_w.value() - self.spin_left_w.value() - self._OVERHEAD
        self.lbl_right_w.setText(f"{right_w} px")

    def _update_left_range(self):
        left_max = self.spin_win_w.value() - 311
        self.spin_left_w.setMaximum(max(200, left_max))

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
        if pw and hasattr(pw, "_panel_splitter"):
            sizes = pw._panel_splitter.sizes()
            if len(sizes) == 2:
                self.spin_left_w.blockSignals(True)
                self.spin_left_w.setValue(sizes[0])
                self.spin_left_w.blockSignals(False)
                self._update_right_label()

    def _apply_panels(self):
        left_w = self.spin_left_w.value()
        win_w = self.spin_win_w.value()
        right_w = win_w - left_w - self._OVERHEAD
        if right_w < 300:
            right_w = 300
            left_w = win_w - right_w - self._OVERHEAD
            self.spin_left_w.blockSignals(True)
            self.spin_left_w.setValue(left_w)
            self.spin_left_w.blockSignals(False)
        self.s.set("left_panel_width", left_w)
        self.s.set("right_panel_width", right_w)
        pw = self.parent()
        if pw and hasattr(pw, "apply_panel_sizes"):
            pw.apply_panel_sizes(left_w, right_w)
        self._update_right_label()

    # ── Theme ───────────────────────────────────────────────────────────

    def _apply_theme(self, _name: str = ""):
        c = lambda k: BaseStyles.color(k)
        r = BaseStyles.RADIUS_MD

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c('PANEL_BG')};
                font-family: '{BaseStyles.DEFAULT_FONT_FAMILY}';
            }}
            QLabel#sectionLabel {{
                font-size: 10px;
                font-weight: bold;
                color: {c('TEXT_SECONDARY')};
                padding: 0 2px;
                letter-spacing: 1px;
            }}
            QFrame#settingsCard {{
                background-color: {c('INPUT_BG')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r}px;
                padding: 10px;
            }}
            QLabel#fieldLabel {{
                font-size: 11px;
                color: {c('TEXT_PRIMARY')};
                min-width: 42px;
            }}
            QLabel#rightLabel {{
                font-size: 11px;
                color: {c('TEXT_SECONDARY')};
                padding-left: 4px;
            }}
            QComboBox {{
                background: {c('PANEL_BG')};
                color: {c('TEXT_PRIMARY')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 11px;
            }}
            QComboBox:focus {{ border-color: {c('BORDER_FOCUS')}; }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 18px;
                border-left: 1px solid {c('BORDER_COLOR')};
                border-top-right-radius: 3px;
                border-bottom-right-radius: 3px;
            }}
            QComboBox QAbstractItemView {{
                background: {c('PANEL_BG')};
                color: {c('TEXT_PRIMARY')};
                selection-background-color: {c('SELECTION_BG')};
                selection-color: {c('SELECTION_TEXT')};
                border: 1px solid {c('BORDER_COLOR')};
                outline: none;
            }}
            QSpinBox {{
                background: {c('PANEL_BG')};
                color: {c('TEXT_PRIMARY')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: 3px;
                padding: 2px 18px 2px 6px;
                font-size: 11px;
                max-width: 78px;
            }}
            QSpinBox:focus {{ border-color: {c('BORDER_FOCUS')}; }}
            QSpinBox::up-button {{
                subcontrol-origin: margin;
                subcontrol-position: top right;
                width: 14px;
                border: none;
                border-left: 1px solid {c('BORDER_COLOR')};
                border-bottom: 1px solid {c('BORDER_COLOR')};
                border-top-right-radius: 3px;
                margin: 1px;
            }}
            QSpinBox::down-button {{
                subcontrol-origin: margin;
                subcontrol-position: bottom right;
                width: 14px;
                border: none;
                border-left: 1px solid {c('BORDER_COLOR')};
                border-bottom-right-radius: 3px;
                margin: 1px;
            }}
            QCheckBox {{
                color: {c('TEXT_PRIMARY')};
                font-size: 11px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border: 2px solid {c('BORDER_COLOR')};
                border-radius: 3px;
                background: {c('PANEL_BG')};
            }}
            QCheckBox::indicator:checked {{
                background: {c('BUTTON_ACCENT')};
                border-color: {c('BUTTON_ACCENT')};
            }}
            QPushButton {{
                background: {c('BUTTON_BG')};
                color: {c('TEXT_PRIMARY')};
                border: 1px solid {c('BORDER_COLOR')};
                border-radius: {r}px;
                padding: 4px 16px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background: {c('BUTTON_HOVER')}; border-color: {c('BORDER_FOCUS')}; }}
            QPushButton:pressed {{ background: {c('BUTTON_PRESSED')}; }}
            QPushButton#closeBtn {{
                background: {c('BUTTON_ACCENT')};
                color: #ffffff;
                border: none;
                font-weight: bold;
            }}
            QPushButton#closeBtn:hover {{ background: {c('BUTTON_ACCENT_HOVER')}; }}
            QPushButton#closeBtn:pressed {{ background: {c('BUTTON_ACCENT_PRESSED')}; }}
        """)

    # ── Reset ────────────────────────────────────────────────────────────

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
