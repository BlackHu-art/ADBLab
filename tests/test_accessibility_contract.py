import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap, QShortcut
from PySide6.QtWidgets import QPushButton
from qfluentwidgets import CardWidget, TransparentToolButton

from gui.features.media import ScreenshotPage
from gui.pages.fluent_pages import ActionCard
from gui.panels.side_panel import SidePanel
from gui.styles import BaseStyles
from gui.styles.fluent import apply_focus_indicator
from gui.styles.theme import THEMES
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
    # PANEL_BASE_STYLE 已移除；直接使用参考控件并为项目动作按钮补齐清晰焦点态。
    assert not hasattr(BaseStyles, "PANEL_BASE_STYLE")
    button = TransparentToolButton()
    apply_focus_indicator(button, selector="TransparentToolButton")
    assert "TransparentToolButton:focus" in button.styleSheet()
    assert BaseStyles.color("BORDER_FOCUS") in button.styleSheet()


def test_theme_text_tokens_keep_readable_contrast():
    light = THEMES["Light"]
    dark = THEMES["Dark"]

    for token in ("LOG_INFO", "LOG_SUCCESS", "LOG_WARNING"):
        assert _contrast_ratio(light[token], light["LOG_BACKGROUND"]) >= 4.5
    assert _contrast_ratio(light["TEXT_PLACEHOLDER"], light["INPUT_BG"]) >= 4.5
    assert _contrast_ratio(dark["TEXT_PLACEHOLDER"], dark["INPUT_BG"]) >= 4.5
    assert _contrast_ratio("#ffffff", dark["BUTTON_ACCENT"]) >= 4.5
    assert _contrast_ratio("#ffffff", dark["BUTTON_DANGER"]) >= 4.5


def test_home_action_card_has_accessible_name_and_keyboard_focus(qt_application):
    card = ActionCard("", "Settings", "Configure application preferences", lambda: None)

    assert card.accessibleName() == "Settings"
    assert card.accessibleDescription() == "Configure application preferences"
    assert card.focusPolicy() & Qt.FocusPolicy.TabFocus
    card.deleteLater()


@pytest.mark.parametrize(
    "configured_path",
    ["C:/a/complete/save/directory", "C:/R&D/results"],
    ids=["plain", "mnemonic-character"],
)
def test_settings_save_action_is_keyboard_reachable_and_keeps_path_context(
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
        frame._on_nav_requested("settings")
        save_button = frame._settings_page.save_card.button
        wait_until(qt_application, lambda: save_button.isVisibleTo(frame))

        assert not hasattr(frame, "_toolbar")
        assert save_button.focusPolicy() & Qt.FocusPolicy.TabFocus
        save_button.setFocus(Qt.FocusReason.TabFocusReason)
        qt_application.processEvents()
        assert save_button.hasFocus()

        assert frame._settings_page.save_card.contentLabel.text() == configured_path
        home_card = frame._home_page.tool_cards["save_path"]
        assert home_card.focusPolicy() & Qt.FocusPolicy.TabFocus
        assert "输出" in home_card.accessibleName()
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_home_actions_use_gallery_cardwidget_container(qt_application):
    """主动作已收敛为 Gallery CardWidget，不再存在顶部工具栏。"""

    assert not hasattr(BaseStyles, "TOOLBAR_STYLE")
    module = __import__("tests.test_main_window_layout", fromlist=["build_main_frame"])
    frame = module.build_main_frame()
    try:
        assert not hasattr(frame, "_toolbar")
        assert all(isinstance(card, CardWidget) for card in frame._home_page.tool_cards.values())
    finally:
        frame._close_ready = True
        frame.close()


def test_screenshot_icon_buttons_have_accessible_names(qt_application):
    viewer = ScreenshotPage([])
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
    """截图页局部样式不得遮蔽全局键盘焦点提示。"""
    image_paths = []
    for index, color in enumerate(("#ff0000", "#00ff00")):
        path = tmp_path / f"screenshot-{index}.png"
        image = QPixmap(24, 24)
        image.fill(color)
        assert image.save(str(path))
        image_paths.append(str(path))

    previous_theme = BaseStyles.current_theme()
    BaseStyles.switch_theme("Dark")
    viewer = ScreenshotPage(image_paths)
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
        assert button.toolTip() == "重启本机 ADB 服务"
        assert button.accessibleName() == "重启 ADB"
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
