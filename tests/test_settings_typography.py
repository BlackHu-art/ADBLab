from unittest.mock import Mock

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox

from core.settings_manager import AppSettings
from gui.dialogs.settings_dialog import SettingsDialog
from gui.styles import BaseStyles
from gui.styles.typography import FontRole


class _FakeSettings:
    DEFAULTS = {
        "theme": "Light",
        "font_family": "",
        "ui_font_size": 12,
        "log_font_size": 9,
        "confirm_dangerous_ops": True,
        "continuous_device_scan": True,
        "log_max_lines": 2000,
        "save_directory": "",
        "window_width": 1120,
        "window_height": 640,
        "left_panel_width": 400,
        "right_panel_width": 600,
    }

    def __init__(self, **overrides):
        self.data = {**self.DEFAULTS, **overrides}
        self.updates = []
        self.reset_count = 0

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.updates.append({key: value})

    def update(self, values):
        values = dict(values)
        self.data.update(values)
        self.updates.append(values)

    def reset(self, key=None):
        self.reset_count += 1
        if key is None:
            self.data = dict(self.DEFAULTS)
        else:
            self.data[key] = self.DEFAULTS.get(key, "")


def _install_fake_settings(monkeypatch, settings):
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))


def _set_combo_text_without_signal(combo, text):
    blocker = QSignalBlocker(combo)
    try:
        combo.setCurrentText(text)
    finally:
        blocker.unblock()


def test_settings_appearance_shows_system_fonts_and_previews(monkeypatch, qt_application):
    settings = _FakeSettings(font_family="Arial")
    _install_fake_settings(monkeypatch, settings)
    monkeypatch.setattr(
        SettingsDialog,
        "_available_ui_font_families",
        classmethod(lambda _cls, _configured="": ["System Default", "Arial", "Segoe UI"]),
    )

    dialog = SettingsDialog()
    try:
        labels = {label.text() for label in dialog.findChildren(QLabel)}
        families = [dialog._font_combo.itemText(i) for i in range(dialog._font_combo.count())]

        assert "Interface Font" in labels
        assert "UI Preview" in labels
        assert "Log Preview" in labels
        assert dialog._font_apply_hint.text() == "Changes apply immediately."
        assert families == ["System Default", "Arial", "Segoe UI"]
        assert dialog._font_combo.currentText() == "Arial"
        assert dialog._ui_font_preview.text() == "Aa 中文 123"
        assert "INFO" in dialog._log_font_preview.text()
    finally:
        dialog.close()


def test_settings_font_changes_apply_immediately_through_compatibility_entry(
    monkeypatch,
    qt_application,
):
    settings = _FakeSettings()
    _install_fake_settings(monkeypatch, settings)
    reload_fonts = Mock()
    monkeypatch.setattr(BaseStyles, "reload_from_settings", reload_fonts)
    monkeypatch.setattr(
        SettingsDialog,
        "_available_ui_font_families",
        classmethod(lambda _cls, _configured="": ["System Default", "Arial"]),
    )

    dialog = SettingsDialog()
    try:
        _set_combo_text_without_signal(dialog._font_combo, "Arial")
        dialog._on_font_family_changed("Arial")
        _set_combo_text_without_signal(dialog._combo_font, "16")
        dialog._on_font_changed("16")
        _set_combo_text_without_signal(dialog._combo_log_font, "12")
        dialog._on_log_font_changed("12")
        _set_combo_text_without_signal(dialog._font_combo, "System Default")
        dialog._on_font_family_changed("System Default")

        assert settings.updates == [
            {"font_family": "Arial", "ui_font_size": 12},
            {"font_family": "Arial", "ui_font_size": 16},
            {"log_font_size": 12},
            {"font_family": "", "ui_font_size": 16},
        ]
        assert reload_fonts.call_count == 4
    finally:
        dialog.close()


def test_settings_log_limit_change_is_emitted_immediately(monkeypatch, qt_application):
    settings = _FakeSettings()
    _install_fake_settings(monkeypatch, settings)
    dialog = SettingsDialog()
    values = []
    dialog.log_max_lines_changed.connect(values.append)
    try:
        dialog._combo_log_lines.setCurrentText("5000")

        assert settings.data["log_max_lines"] == 5000
        assert values == [5000]
    finally:
        dialog.close()


def test_settings_font_previews_use_distinct_typography_roles(monkeypatch, qt_application):
    settings = _FakeSettings()
    _install_fake_settings(monkeypatch, settings)
    ui_font = QFont("Arial", 15)
    small_font = QFont("Arial", 13)
    log_font = QFont("Consolas", 11)
    requested_roles = []

    def font_for_role(_cls, role, size=None):
        del size
        role = FontRole(role)
        requested_roles.append(role)
        if role is FontRole.LOG:
            return log_font
        if role is FontRole.UI_SMALL:
            return small_font
        return ui_font

    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(font_for_role))

    dialog = SettingsDialog()
    try:
        # ScalableGroupBox 构造时会额外请求 UI 角色（group_box_title_margin），
        # 首两个请求的顺序不再固定；改断言首个请求为 UI 且集合覆盖全部角色。
        assert requested_roles[0] == FontRole.UI
        assert requested_roles[-2:] == [FontRole.UI, FontRole.LOG]
        assert set(requested_roles) == {FontRole.UI, FontRole.UI_SMALL, FontRole.LOG}
        assert "font-family: 'Arial'" in dialog._ui_font_preview.styleSheet()
        assert "font-family: 'Consolas'" in dialog._log_font_preview.styleSheet()
        assert "font-size: 15pt" in dialog._ui_font_preview.styleSheet()
        assert "font-size: 11pt" in dialog._log_font_preview.styleSheet()
        assert all(
            label.font().pointSize() == 15 for label in dialog.findChildren(QLabel, "settingsLabel")
        )
        assert all(
            hint.font().pointSize() == 13 for hint in dialog.findChildren(QLabel, "hintLabel")
        )
        assert all(
            description.font().pointSize() == 13
            for description in dialog.findChildren(QLabel, "settingsDescription")
        )
    finally:
        dialog.close()


def test_settings_restore_defaults_blocks_control_callbacks_and_stays_open(
    monkeypatch,
    qt_application,
):
    settings = _FakeSettings(
        theme="Dark",
        font_family="Arial",
        ui_font_size=18,
        log_font_size=14,
        confirm_dangerous_ops=False,
        continuous_device_scan=False,
        log_max_lines=5000,
        save_directory="D:/results",
        window_width=1440,
        window_height=900,
        left_panel_width=520,
        right_panel_width=900,
    )
    _install_fake_settings(monkeypatch, settings)
    monkeypatch.setattr(
        SettingsDialog,
        "_available_ui_font_families",
        classmethod(lambda _cls, _configured="": ["System Default", "Arial"]),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    switch_theme = Mock()
    reload_fonts = Mock()
    monkeypatch.setattr(BaseStyles, "switch_theme", switch_theme)
    monkeypatch.setattr(BaseStyles, "reload_from_settings", reload_fonts)

    dialog = SettingsDialog()
    applied = []
    scan_values = []
    log_limit_values = []
    save_directory_values = []
    dialog.settings_applied.connect(lambda: applied.append(True))
    dialog.continuous_scan_toggled.connect(scan_values.append)
    dialog.log_max_lines_changed.connect(log_limit_values.append)
    dialog.save_directory_changed.connect(save_directory_values.append)
    dialog.show()
    try:
        dialog._reset_all()

        assert settings.reset_count == 1
        assert settings.updates == []
        assert switch_theme.call_args.args == ("Light",)
        reload_fonts.assert_called_once_with()
        assert dialog._font_combo.currentText() == "System Default"
        assert dialog._combo_font.currentText() == "12"
        assert dialog._combo_log_font.currentText() == "9"
        assert dialog._chk_confirm.isChecked() is True
        assert dialog._chk_continuous_scan.isChecked() is True
        assert dialog._combo_log_lines.currentText() == "2000"
        assert dialog._lbl_save.text() == "~/ADBLab (default)"
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert dialog.isVisible()
        assert applied == [True]
        assert scan_values == [True]
        assert log_limit_values == [2000]
        assert save_directory_values == [""]
    finally:
        dialog.close()
