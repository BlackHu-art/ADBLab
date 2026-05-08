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
    QWidget,
)

from core.settings_manager import AppSettings
from gui.styles.base_styles import BaseStyles


class SettingsDialog(QDialog):
    settings_applied = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.s = AppSettings.instance()
        self.setWindowTitle("Settings")
        self.setMinimumSize(460, 420)
        self.setModal(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._build_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)

    # ── UI 构建 ────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(10)
        outer.setContentsMargins(20, 14, 20, 14)

        # ── Appearance ──
        g1 = QGroupBox("Appearance")
        g1l = QVBoxLayout(g1)
        g1l.setSpacing(8)
        r1 = QHBoxLayout()
        r1.setSpacing(10)
        r1.addWidget(QLabel("Theme"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(BaseStyles.theme_names())
        self.theme_combo.setCurrentText(BaseStyles.current_theme())
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        self.theme_combo.setFixedWidth(110)
        r1.addWidget(self.theme_combo)
        r1.addStretch()
        g1l.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(10)
        r2.addWidget(QLabel("Font Size"))
        self.spin_font = QSpinBox()
        self.spin_font.setRange(8, 22)
        self.spin_font.setValue(self.s.get("font_base_size", 12))
        self.spin_font.setSuffix(" px")
        self.spin_font.setFixedWidth(90)
        self.spin_font.valueChanged.connect(self._on_font_changed)
        r2.addWidget(self.spin_font)
        r2.addStretch()
        g1l.addLayout(r2)
        outer.addWidget(g1)

        # ── Panel Size ──
        g2 = QGroupBox("Panel Size")
        g2l = QVBoxLayout(g2)
        g2l.setSpacing(6)

        r2a = QHBoxLayout()
        r2a.setSpacing(6)
        r2a.addWidget(QLabel("Left Panel"))
        self.spin_left_w = QSpinBox()
        self.spin_left_w.setRange(200, 1200)
        self.spin_left_w.setSingleStep(10)
        self.spin_left_w.setSuffix(" px")
        self.spin_left_w.setFixedWidth(90)
        # 从当前窗口实际宽度读取面板尺寸
        pw = self.parent()
        if pw:
            for child in pw.findChildren(QWidget):
                if child.objectName() == "leftPanelWrapper":
                    self.spin_left_w.setValue(child.width())
                    break
            else:
                self.spin_left_w.setValue(self.s.get("left_panel_width", 400))
        else:
            self.spin_left_w.setValue(self.s.get("left_panel_width", 400))
        self.spin_left_w.valueChanged.connect(self._on_panel_size_changed)
        r2a.addWidget(self.spin_left_w)
        r2a.addStretch()
        g2l.addLayout(r2a)

        r2b = QHBoxLayout()
        r2b.setSpacing(6)
        r2b.addWidget(QLabel("Right Panel"))
        self.spin_right_w = QSpinBox()
        self.spin_right_w.setRange(300, 1600)
        self.spin_right_w.setSingleStep(10)
        self.spin_right_w.setSuffix(" px")
        self.spin_right_w.setFixedWidth(90)
        # 从当前窗口实际宽度读取面板尺寸
        if pw:
            for child in pw.findChildren(QWidget):
                if hasattr(child, "tabs"):
                    self.spin_right_w.setValue(child.width())
                    break
            else:
                self.spin_right_w.setValue(self.s.get("right_panel_width", 600))
        else:
            self.spin_right_w.setValue(self.s.get("right_panel_width", 600))
        self.spin_right_w.valueChanged.connect(self._on_panel_size_changed)
        r2b.addWidget(self.spin_right_w)
        r2b.addStretch()
        g2l.addLayout(r2b)
        outer.addWidget(g2)

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

    def _on_font_changed(self, v: int):
        self.s.set("font_base_size", v)
        self.s.set("font_small_size", v)
        self.s.set("font_tab_size", v)
        self.s.set("font_mono_size", max(8, v - 2))
        BaseStyles.reload_from_settings()

    def _on_panel_size_changed(self):
        left = self.spin_left_w.value()
        right = self.spin_right_w.value()
        self.s.set("left_panel_width", left)
        self.s.set("right_panel_width", right)
        # 实时应用到当前窗口面板
        pw = self.parent()
        if pw:
            for child in pw.findChildren(QWidget):
                if child.objectName() == "leftPanelWrapper":
                    child.setMinimumWidth(left)
                    child.setMaximumWidth(left)
                if isinstance(child, QWidget) and hasattr(child, "tabs"):
                    child.setMinimumWidth(right)

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
            QCheckBox              {{ color: {fg}; spacing: 8px; }}
            QCheckBox::indicator   {{ width: 16px; height: 16px; border: 2px solid {border}; border-radius: 3px; background: {ibg}; image: none; }}
            QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: none; }}
            QCheckBox::indicator:unchecked {{ image: none; }}
            QLineEdit              {{ background: {ibg}; color: {fg}; border: 1px solid {border}; border-radius: {r}px; padding: 4px 8px; }}
            QLineEdit:focus        {{ border-color: {accent}; }}
            QSpinBox               {{ background: {ibg}; color: {fg}; border: 1px solid {border}; border-radius: {r}px; padding: 3px 6px; padding-right: 20px; }}
            QSpinBox:focus         {{ border-color: {accent}; }}
            QSpinBox::up-button    {{ subcontrol-origin: border; subcontrol-position: top right; width: 18px; border: none; border-left: 1px solid {border}; border-bottom: 1px solid {border}; border-top-right-radius: {r-1}px; background: {btn}; }}
            QSpinBox::up-button:hover {{ background: {hov}; }}
            QSpinBox::down-button  {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border: none; border-left: 1px solid {border}; border-bottom-right-radius: {r-1}px; background: {btn}; }}
            QSpinBox::down-button:hover {{ background: {hov}; }}
            QComboBox              {{ background: {ibg}; color: {fg}; border: 1px solid {border}; border-radius: {r}px; padding: 3px 6px; }}
            QComboBox:focus        {{ border-color: {accent}; }}
            QComboBox::drop-down   {{ subcontrol-origin: padding; subcontrol-position: top right; width: 20px; border-left: 1px solid {border}; border-top-right-radius: {r}px; border-bottom-right-radius: {r}px; background: {btn}; }}
            QComboBox::drop-down:hover {{ background: {hov}; }}
            QComboBox QAbstractItemView {{ background: {ibg}; color: {fg}; selection-background-color: {sel_bg}; selection-color: {sel_fg}; border: 1px solid {border}; outline: none; }}
            QPushButton            {{ background: {btn}; color: {fg}; border: 1px solid {border}; border-radius: {r}px; padding: 4px 14px; }}
            QPushButton:hover      {{ background: {hov}; border-color: {accent}; }}
            QPushButton:pressed    {{ background: {prs}; }}
            QGroupBox              {{ font-weight: bold; color: {gt}; border: 1px solid {border}; border-radius: {r}px; margin-top: 10px; padding: 12px 14px 10px 14px; background: transparent; }}
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
