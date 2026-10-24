"""窄窗导航收起时保留真实输入来源，不把重挂父控件伪装成 Tab。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from qfluentwidgets import NavigationDisplayMode

from core.settings_manager import AppSettings
from gui.styles import BaseStyles
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def navigation_frame(qt_application, monkeypatch):
    settings = _MainFrameSettings()
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda self: None,
    )
    frame = build_main_frame(
        settings=settings,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("focus", QSize(1920, 1080))),
    )
    frame.show()
    frame.activateWindow()
    frame.resize(860, 640)
    yield frame
    frame._unbind_window_screen()
    frame._close_ready = True
    frame.close()


def _open_navigation(frame, qt_application):
    panel = frame.navigationInterface.panel
    wait_until(qt_application, lambda: panel.displayMode == NavigationDisplayMode.COMPACT)
    QTest.mouseClick(panel.menuButton, Qt.MouseButton.LeftButton)
    wait_until(qt_application, lambda: (
        panel.displayMode == NavigationDisplayMode.MENU
        and panel.expandAni.state() == QAbstractAnimation.State.Stopped
    ))
    return panel


def _focus_border(button):
    image = button.grab().toImage()
    return image.pixelColor(image.width() // 2, round(image.devicePixelRatio()))


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_mouse_navigation_does_not_paint_device_focus_frame(
    navigation_frame, qt_application, theme,
):
    frame = navigation_frame
    BaseStyles.switch_theme(theme)
    for route in ("remotePage", "screenshotsPage", "appsPage"):
        panel = _open_navigation(frame, qt_application)
        item = frame.navigationInterface.widget(route)
        if route == "appsPage":
            panel.scrollArea.setFocus(Qt.FocusReason.TabFocusReason)
            QTest.keyClick(panel.scrollArea, Qt.Key.Key_Down)
            assert panel.scrollArea.hasFocus()
        # Fluent 的树容器不消费鼠标释放，实际可点击区域是其可见 itemWidget。
        QTest.mouseClick(item.itemWidget, Qt.MouseButton.LeftButton)
        wait_until(qt_application, lambda: (
            panel.displayMode == NavigationDisplayMode.COMPACT and panel.width() == 48
        ))
        QTest.mouseMove(frame, QPoint(frame.width() - 1, frame.height() - 1))
        button = frame._global_device_bar.targets_button
        assert panel.currentItem().property("routeKey") == route
        assert button.hasFocus()
        assert _focus_border(button) != QColor(BaseStyles.color("BORDER_FOCUS")), (
            route, button.property("adblabKeyboardFocus"),
            frame.testAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange),
        )
        assert button.focusPolicy() & Qt.FocusPolicy.TabFocus
        # 键盘仍能从返回的设备入口继续导航，并在实际 Tab 返回时显示提示。
        QTest.keyClick(button, Qt.Key.Key_Tab)
        QTest.keyClick(frame.focusWidget(), Qt.Key.Key_Backtab)
        assert button.hasFocus()
        assert _focus_border(button) == QColor(BaseStyles.color("BORDER_FOCUS"))


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_keyboard_navigation_retains_device_focus_frame(
    navigation_frame, qt_application, theme,
):
    frame = navigation_frame
    BaseStyles.switch_theme(theme)
    panel = _open_navigation(frame, qt_application)
    # 真正的 Tab 先建立窗口键盘来源，再模拟快捷导航命令；不伪造全局标志。
    QTest.keyClick(panel.menuButton, Qt.Key.Key_Tab)
    panel.scrollArea.setFocus(Qt.FocusReason.TabFocusReason)
    assert panel.scrollArea.hasFocus()
    frame.navigationInterface.widget("appsPage").click()
    wait_until(qt_application, lambda: (
        panel.displayMode == NavigationDisplayMode.COMPACT and panel.width() == 48
    ))
    button = frame._global_device_bar.targets_button
    assert button.hasFocus()
    assert _focus_border(button) == QColor(BaseStyles.color("BORDER_FOCUS"))
