import os

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap, QShortcut
from PySide6.QtWidgets import QLabel, QPushButton, QToolButton
from qfluentwidgets import TransparentToolButton

from gui.dialogs.screenshot_viewer import ScreenshotViewer
from gui.dialogs.settings_dialog import SettingsDialog
from gui.main_frame import MainFrame
from gui.panels.side_panel import SidePanel
from gui.styles import BaseStyles
from gui.styles.theme import THEMES
from gui.widgets.fluent.focus_ring import FocusRing
from gui.widgets.preset_spin_box import PresetSpinBox
from tests.ui_geometry_helpers import wait_until


def _relative_luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    values = sorted((_relative_luminance(foreground), _relative_luminance(background)))
    return (values[1] + 0.05) / (values[0] + 0.05)


def test_shared_styles_expose_keyboard_focus(qt_application):
    # PANEL_BASE_STYLE 已由全局 QPalette 主题化取代并移除；键盘焦点改由
    # FocusRing（原生控件）或对话框级 QSS（file_explorer 表格）提供。
    assert not hasattr(BaseStyles, "PANEL_BASE_STYLE")
    ring = FocusRing(QToolButton(), selector="QToolButton")
    try:
        assert "QToolButton:focus" in ring.ring_style()
        assert BaseStyles.color("BORDER_FOCUS") in ring.ring_style()
    finally:
        ring.clear()


def test_theme_text_tokens_keep_readable_contrast():
    light = THEMES["Light"]
    dark = THEMES["Dark"]

    for token in ("LOG_INFO", "LOG_SUCCESS", "LOG_WARNING"):
        assert _contrast_ratio(light[token], light["LOG_BACKGROUND"]) >= 4.5
    assert _contrast_ratio(light["TEXT_PLACEHOLDER"], light["INPUT_BG"]) >= 4.5
    assert _contrast_ratio(dark["TEXT_PLACEHOLDER"], dark["INPUT_BG"]) >= 4.5
    assert _contrast_ratio("#ffffff", dark["BUTTON_ACCENT"]) >= 4.5
    assert _contrast_ratio("#ffffff", dark["BUTTON_DANGER"]) >= 4.5


def test_toolbar_icon_button_has_accessible_name(qt_application):
    button = MainFrame._create_toolbar_btn(
        None,
        "Settings",
        "resources/icons/gear.svg",
    )

    assert isinstance(button, QToolButton)
    assert button.text() == ""
    assert button.accessibleName() == "Settings"
    button.deleteLater()


def test_preset_icon_button_has_accessible_name_and_keyboard_focus(qt_application):
    field = PresetSpinBox(1, 100, 5, presets=(1, 5, 10))
    button = field.findChild(QToolButton, "presetMenuButton")

    assert button is not None
    assert button.text() == ""
    assert button.accessibleName().strip()
    assert button.focusPolicy() & Qt.FocusPolicy.TabFocus


@pytest.mark.parametrize(
    "configured_path",
    ["C:/a/complete/save/directory", "C:/R&D/results"],
    ids=["plain", "mnemonic-character"],
)
def test_toolbar_save_button_is_keyboard_reachable_and_keeps_path_context(
    qt_application,
    configured_path,
):
    from tests.test_main_window_layout import (
        _FakeScreen,
        _FakeScreenAdapter,
        _MainFrameSettings,
        build_main_frame,
    )

    settings = _MainFrameSettings()
    settings.save_directory = configured_path
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("large", QSize(1600, 900))),
        settings=settings,
    )
    try:
        frame.show()
        frame.resize(860, 420)
        wait_until(qt_application, lambda: frame._toolbar.width() == 860)

        assert frame.findChild(QToolButton, "toolbarMoreButton") is None
        assert not hasattr(frame, "_toolbar_more_menu")
        save_button = frame._tb_save_btn
        assert save_button.focusPolicy() & Qt.FocusPolicy.TabFocus
        save_button.setFocus(Qt.FocusReason.TabFocusReason)
        qt_application.processEvents()
        assert save_button.hasFocus()

        expected_path = os.path.normpath(settings.save_directory)
        save_action = frame._toolbar_actions["save_path"]
        action_label = "Change default save directory"
        escaped_path = expected_path.replace("&", "&&")
        # 动作文本保持简短（窄窗口 More 菜单不得溢出）；路径上下文经
        # toolTip/statusTip/accessibleDescription 可达，契约不变。
        assert save_action.text() == action_label
        assert expected_path in save_action.toolTip()
        assert expected_path in save_action.statusTip()
        assert expected_path in save_action.property("accessibleDescription")
        assert save_button.defaultAction() is save_action
        assert expected_path in save_button.toolTip()
        assert expected_path in save_button.accessibleDescription()
        if "&" in expected_path:
            for semantic_text in (
                save_action.toolTip(),
                save_action.statusTip(),
                save_action.property("accessibleDescription"),
                save_button.toolTip(),
                save_button.accessibleDescription(),
            ):
                assert escaped_path not in semantic_text
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_toolbar_uses_cardwidget_container():
    """工具栏已收敛为 CardWidget，不再依赖 TOOLBAR_STYLE QSS。"""

    assert not hasattr(BaseStyles, "TOOLBAR_STYLE")
    # 工具栏容器/标题/按钮均已收敛：CardWidget 自绘制背景圆角、FluentLabel 标题、
    # TransparentToolButton 按钮（透明/hover/focus 由 FluentStyleSheet 提供）。


def test_settings_form_labels_have_buddies(monkeypatch, qt_application):
    monkeypatch.setattr(
        SettingsDialog,
        "_available_ui_font_families",
        classmethod(lambda _cls, _configured="": ["System Default"]),
    )
    dialog = SettingsDialog()
    try:
        labels = dialog.findChildren(QLabel, "settingsLabel")
        form_labels = [
            label
            for label in labels
            if label.text()
            in {
                "Theme",
                "Interface Font",
                "Interface Size",
                "Log Size",
                "Save Directory",
                "Visible Log Lines",
            }
        ]

        assert len(form_labels) == 6
        assert all(label.buddy() is not None for label in form_labels)
    finally:
        dialog.close()


def test_screenshot_icon_buttons_have_accessible_names(qt_application):
    viewer = ScreenshotViewer([])
    try:
        # 图标按钮已收敛为 qfluentwidgets TransparentToolButton（QToolButton 子类）；
        # SmoothScrollDelegate 的内部 ArrowButton 是滚动条子控件，不属于图标按钮，
        # 故按 TransparentToolButton 精确过滤而非 QToolButton。
        icon_only = [
            button for button in viewer.findChildren(TransparentToolButton) if not button.text()
        ]

        assert icon_only
        assert all(button.accessibleName().strip() for button in icon_only)
    finally:
        viewer.close()


def test_screenshot_controls_render_focus_indicators_in_dark_theme(qt_application, tmp_path):
    """A local dialog stylesheet must not hide the global keyboard-focus affordance."""
    image_paths = []
    for index, color in enumerate(("#ff0000", "#00ff00")):
        path = tmp_path / f"screenshot-{index}.png"
        image = QPixmap(24, 24)
        image.fill(color)
        assert image.save(str(path))
        image_paths.append(str(path))

    previous_theme = BaseStyles.current_theme()
    BaseStyles.switch_theme("Dark")
    viewer = ScreenshotViewer(image_paths)
    try:
        viewer.show()
        qt_application.processEvents()

        focus_color = BaseStyles.color("BORDER_FOCUS")
        button = viewer._zoom_in_btn
        thumbnail_strip = viewer._thumb_list

        for control in (button, thumbnail_strip):
            viewer._view.setFocus(Qt.OtherFocusReason)
            qt_application.processEvents()
            before = control.grab().toImage()

            control.setFocus(Qt.OtherFocusReason)
            qt_application.processEvents()
            after = control.grab().toImage()

            assert control.hasFocus()
            assert after != before
            assert after.pixelColor(0, control.height() // 2).name() == focus_color
    finally:
        viewer.close()
        BaseStyles.switch_theme(previous_theme)


def test_adb_server_action_is_keyboard_triggerable(qt_application):
    panel = SidePanel()
    try:
        button = panel._devices_tab.btn_restart_adb

        # qfluentwidgets PushButton 仍是 QPushButton 子类，保持键盘可触发契约。
        assert isinstance(button, QPushButton)
        assert button.toolTip() == "Restart the local ADB server"
        assert button.accessibleName() == "ADB Server"
    finally:
        panel.close()


def test_remote_shortcuts_are_unique_and_do_not_claim_application_quit(qt_application):
    panel = SidePanel()
    try:
        remote = panel._ensure_tab_loaded(2)
        shortcuts = [shortcut.key().toString() for shortcut in remote.findChildren(QShortcut)]

        assert len(shortcuts) == len(set(shortcuts))
        assert "Ctrl+Q" not in shortcuts
        assert "Ctrl+Return" in shortcuts
        assert "Ctrl+Shift+Return" in shortcuts
    finally:
        panel.shutdown()
        panel.close()
