from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QMainWindow,
    QSizePolicy,
    QStyle,
    QStyleOptionGroupBox,
    QWidget,
)

from core.settings_manager import AppSettings
from gui.dialogs.settings_dialog import SettingsDialog
from gui.styles import BaseStyles


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
        "window_width": 1250,
        "window_height": 700,
        "left_panel_width": 400,
        "right_panel_width": 600,
        "panel_split_ratio": 0.4,
    }

    def __init__(self, **overrides):
        self.data = {**self.DEFAULTS, **overrides}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def update(self, values):
        self.data.update(values)

    def reset(self, key=None):
        if key is None:
            self.data = dict(self.DEFAULTS)
        else:
            self.data[key] = self.DEFAULTS.get(key, "")


class _MainWindowStub(QMainWindow):
    def __init__(self):
        super().__init__()
        self.snapshot = {"width": 1440, "height": 900, "panel_ratio": 0.35}
        self.actions = []

    @property
    def _panel_splitter(self):
        raise AssertionError("设置页不应访问主窗口私有分栏控件")

    def window_layout_snapshot(self):
        return dict(self.snapshot)

    def restore_default_window_size(self):
        self.actions.append("window")
        self.snapshot.update(width=1250, height=700)

    def reset_panel_split(self):
        self.actions.append("split")
        self.snapshot["panel_ratio"] = 0.4


def _install_fake_settings(monkeypatch, settings):
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))


def _grid_position(layout, widget):
    return layout.getItemPosition(layout.indexOf(widget))[:2]


def _group_title_gap(group: QGroupBox) -> int:
    option = QStyleOptionGroupBox()
    group.initStyleOption(option)
    title_rect = group.style().subControlRect(
        QStyle.ComplexControl.CC_GroupBox,
        option,
        QStyle.SubControl.SC_GroupBoxLabel,
        group,
    )
    children = [
        child
        for child in group.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
        if not child.isHidden()
    ]
    return min(child.geometry().top() for child in children) - title_rect.bottom() - 1


def test_window_section_uses_public_layout_api(monkeypatch, qt_application):
    _install_fake_settings(monkeypatch, _FakeSettings())
    main_window = _MainWindowStub()
    dialog = SettingsDialog(main_window)
    try:
        assert dialog._window_size_value.text() == "1440 × 900 px"
        assert dialog._panel_split_value.text() == "35% / 65%"
        assert not hasattr(dialog, "_inp_win_w")
        assert not hasattr(dialog, "_inp_left_w")
        assert not hasattr(SettingsDialog, "_OVERHEAD")

        dialog._btn_reset_window_size.click()
        dialog._btn_reset_panel_split.click()

        assert main_window.actions == ["window", "split"]
        assert dialog._window_size_value.text() == "1250 × 700 px"
        assert dialog._panel_split_value.text() == "40% / 60%"
    finally:
        dialog.close()
        main_window.close()


def test_settings_content_reflows_and_scrolls_at_narrow_width(
    monkeypatch,
    qt_application,
):
    _install_fake_settings(monkeypatch, _FakeSettings())
    dialog = SettingsDialog()
    dialog.resize(520, 350)
    dialog.show()
    qt_application.processEvents()
    try:
        assert not dialog.isModal()
        assert dialog._settings_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        # SmoothScrollArea 用自定义 SmoothScrollBar 承接滚动，原生垂直滚动条
        # 策略恒为 AlwaysOff（由委托隐藏），按需显隐交给 vScrollBar.setForceHidden。
        assert dialog._settings_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert dialog._settings_scroll.verticalScrollBar().maximum() > 0
        assert dialog._settings_scroll.horizontalScrollBar().maximum() == 0
        assert (
            dialog._settings_scroll.widget().width() <= dialog._settings_scroll.viewport().width()
        )
        assert dialog._appearance_compact is True
        assert dialog._window_compact is True
        assert dialog._general_compact is True
        assert _grid_position(dialog._appearance_grid, dialog._ui_font_label) == (2, 0)
        assert _grid_position(dialog._window_grid, dialog._btn_reset_window_size) == (2, 0)
        assert _grid_position(dialog._general_grid, dialog._max_log_label) == (3, 0)
        assert _grid_position(dialog._general_grid, dialog._btn_save) == (2, 0)
        assert dialog._btn_save.isVisible()

        assert not dialog._settings_scroll.isAncestorOf(dialog._btn_close)
    finally:
        dialog.close()


def test_settings_content_keeps_existing_two_column_form_when_wide(
    monkeypatch,
    qt_application,
):
    _install_fake_settings(monkeypatch, _FakeSettings())
    dialog = SettingsDialog()
    dialog.resize(900, 650)
    dialog.show()
    qt_application.processEvents()
    try:
        assert dialog._appearance_compact is False
        assert dialog._window_compact is False
        assert dialog._general_compact is False
        assert _grid_position(dialog._appearance_grid, dialog._ui_font_label) == (0, 2)
        assert _grid_position(dialog._window_grid, dialog._btn_reset_window_size) == (0, 2)
        assert _grid_position(dialog._general_grid, dialog._btn_save) == (0, 2)
        assert _grid_position(dialog._general_grid, dialog._max_log_label) == (1, 0)
        assert dialog._settings_scroll.horizontalScrollBar().maximum() == 0
    finally:
        dialog.close()


def test_settings_default_size_is_compact_and_content_remains_scrollable(
    monkeypatch,
    qt_application,
):
    _install_fake_settings(monkeypatch, _FakeSettings())
    dialog = SettingsDialog()
    dialog.show()
    qt_application.processEvents()
    try:
        assert dialog.size().width() == 700
        assert dialog.size().height() == 600
        assert dialog._settings_scroll.horizontalScrollBar().maximum() == 0
        assert dialog._settings_scroll.verticalScrollBar().maximum() > 0
        assert dialog._btn_save.isVisible()
        assert dialog._btn_close.isVisible()
    finally:
        dialog.close()


def test_settings_comboboxes_use_compact_content_widths(
    monkeypatch,
    qt_application,
):
    _install_fake_settings(monkeypatch, _FakeSettings())
    dialog = SettingsDialog()
    dialog.show()
    qt_application.processEvents()
    try:
        assert dialog._theme_combo.maximumWidth() <= 180
        assert dialog._font_combo.maximumWidth() <= 260
        assert dialog._combo_font.maximumWidth() <= 100
        assert dialog._combo_log_font.maximumWidth() <= 100
        assert dialog._combo_log_lines.maximumWidth() <= 128
        assert all(
            combo.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Preferred
            for combo in (
                dialog._theme_combo,
                dialog._font_combo,
                dialog._combo_font,
                dialog._combo_log_font,
                dialog._combo_log_lines,
            )
        )
    finally:
        dialog.close()


def test_choose_save_directory_updates_setting_and_visible_path(
    monkeypatch,
    qt_application,
):
    settings = _FakeSettings()
    _install_fake_settings(monkeypatch, settings)
    selected = "D:/ADBLab/results"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: selected)
    dialog = SettingsDialog()
    try:
        dialog._btn_save.click()

        assert settings.get("save_directory") == selected
        assert dialog._lbl_save.text() == selected
        assert dialog._lbl_save.toolTip() == selected
    finally:
        dialog.close()


def test_settings_maximum_ui_font_keeps_compact_content_inside_viewport(
    monkeypatch,
    qt_application,
):
    _install_fake_settings(monkeypatch, _FakeSettings(ui_font_size=22))
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", 22)
    dialog = SettingsDialog()
    # 视觉重设计映射：分组导航栏（settingsNav，180px）常驻左侧，520px 对话框
    # 下内容视口只剩约 310px；宽度升到 720px 后内容视口约 510px，与重设计前
    # 520px 对话框的内容宽度等价。压缩形态、无水平溢出与几何边界不变式全部保留。
    dialog.resize(720, 420)
    dialog.show()
    qt_application.processEvents()
    try:
        viewport = dialog._settings_scroll.viewport()
        content = dialog._settings_scroll.widget()

        assert dialog.width() == 720
        assert dialog._appearance_compact is True
        assert dialog._window_compact is True
        assert dialog._general_compact is True
        assert dialog._settings_scroll.horizontalScrollBar().maximum() == 0
        assert content.width() <= viewport.width()
        assert dialog._btn_save.geometry().right() < dialog._btn_save.parentWidget().width()
        assert (
            dialog._btn_reset_window_size.geometry().right()
            < dialog._btn_reset_window_size.parentWidget().width()
        )
        assert all(
            _group_title_gap(group) >= 4
            for group in dialog.findChildren(QGroupBox, "settingsSection")
        )
    finally:
        dialog.close()
