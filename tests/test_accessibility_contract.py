from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt
from PySide6.QtGui import QPixmap, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, TransparentToolButton
from shiboken6 import isValid

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

    for token in (
        "LOG_TEXT_COLOR", "LOG_DEBUG", "LOG_INFO", "LOG_SUCCESS", "LOG_WARNING",
        "LOG_ERROR", "LOG_CRITICAL", "LOG_TIMESTAMP",
    ):
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
        controls = (
            *viewer._command_bar.commandButtons, viewer._command_bar.moreButton,
            viewer._view.preButton, viewer._view.nextButton,
            viewer._pager.preButton, viewer._pager.nextButton,
        )
        assert controls
        assert all(button.accessibleName().strip() for button in controls)
        assert viewer._view.accessibleName().strip()
        assert viewer._pager.accessibleName().strip()
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
        viewer.resize(1100, 700)
        viewer.show()
        qt_application.processEvents()

        focus_color = BaseStyles.color("BORDER_FOCUS")
        button = next(
            button for button in viewer._command_bar.commandButtons
            if button.action() is viewer._zoom_in_action
        )
        pager = viewer._pager

        for control in (button, pager):
            assert control.isVisibleTo(viewer)
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


@pytest.fixture
def visible_remote_shortcuts(qt_application, monkeypatch):
    from core.settings_manager import AppSettings
    from gui.panels.remote_panel import RemotePanel
    from tests.test_main_window_layout import _MainFrameSettings

    settings = _MainFrameSettings()
    monkeypatch.setattr(AppSettings, "instance", lambda: settings)
    monkeypatch.setattr("models.device_store.DeviceStore.get_basic_devices_info", lambda: [])
    start, stop = Mock(), Mock()
    monkeypatch.setattr(RemotePanel, "_start_scrcpy", start)
    monkeypatch.setattr(RemotePanel, "_stop_scrcpy", stop)
    panel = SidePanel()
    remote = panel._ensure_tab_loaded(2)
    remote.set_target_devices(["demo-remote"])
    view = panel._tab_scroll_areas[2].takeWidget()
    window = QWidget()
    stack = QStackedWidget(window)
    QVBoxLayout(window).addWidget(stack)
    stack.addWidget(view)
    other = QPushButton("Other page")
    stack.addWidget(other)
    window.resize(1000, 800)
    window.show()
    window.activateWindow()
    remote.btn_start.setFocus()
    wait_until(qt_application, lambda: remote.btn_start.hasFocus())
    try:
        yield remote, view, stack, other, start, stop
    finally:
        panel.shutdown()
        window.close()
        window.deleteLater()
        panel.close()
        panel.deleteLater()


def test_remote_shortcuts_are_unique_and_do_not_claim_application_quit(visible_remote_shortcuts):
    _remote, view, _stack, _other, _start, _stop = visible_remote_shortcuts
    shortcuts = [shortcut.key().toString() for shortcut in view.findChildren(QShortcut)]

    assert len(shortcuts) == len(set(shortcuts))
    assert "Ctrl+Q" not in shortcuts
    assert "Ctrl+Return" in shortcuts
    assert "Ctrl+Shift+Return" in shortcuts


def test_remote_stop_shortcut_remains_available_when_start_is_disabled(
    qt_application, visible_remote_shortcuts,
):
    remote, _view, _stack, _other, start, stop = visible_remote_shortcuts
    remote.btn_start.setEnabled(False)
    remote.btn_stop.setEnabled(True)
    remote.btn_stop.setFocus()
    wait_until(qt_application, remote.btn_stop.hasFocus)
    QTest.keyClick(
        remote.btn_stop, Qt.Key.Key_Return,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    stop.assert_called_once_with()
    start.assert_not_called()


def test_remote_shortcuts_dispatch_only_while_the_real_page_is_visible(
    qt_application, visible_remote_shortcuts,
):
    remote, view, stack, other, start, stop = visible_remote_shortcuts
    assert remote.isHidden() and view.isVisible()

    def press_both(target):
        QTest.keyClick(target, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(
            target, Qt.Key.Key_Return,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        qt_application.processEvents()

    press_both(remote.btn_start)
    start.assert_called_once_with()
    stop.assert_called_once_with()
    stack.setCurrentWidget(other)
    other.setFocus()
    wait_until(qt_application, other.hasFocus)
    press_both(other)
    assert start.call_count == stop.call_count == 1
    stack.setCurrentWidget(view)
    remote.btn_start.setFocus()
    wait_until(qt_application, remote.btn_start.hasFocus)
    press_both(remote.btn_start)
    assert start.call_count == stop.call_count == 2

    shortcuts = view.findChildren(QShortcut)
    stack.setCurrentWidget(other)
    stack.removeWidget(view)
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert all(not isValid(shortcut) for shortcut in shortcuts)
    other.setFocus()
    press_both(other)
    assert start.call_count == stop.call_count == 2
