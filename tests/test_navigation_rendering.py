"""验证导航折叠后仍绘制当前主题背景与图标。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, QSize
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy, QTest
from qfluentwidgets import NavigationDisplayMode

from core.settings_manager import AppSettings
from gui.styles import BaseStyles
from models.device_store import DeviceStore
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)
from tests.ui_geometry_helpers import wait_until


def _navigation_background_pixel(frame, panel_point=None):
    """取顶部空白边距，避免菜单回挂后水平滚动使原边距落入选中项高亮。"""
    point = frame.navigationInterface.panel.mapTo(frame, panel_point or QPoint(1, 5))
    image = frame.grab().toImage()
    scale = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * scale), round(point.y() * scale))


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("transition", ["resize", "menu"])
def test_navigation_collapse_preserves_theme_surface(qt_application, theme_name, transition):
    """缩窗和覆盖菜单关闭后，紧凑导航不能透明或残留旧主题底色。"""
    settings = _MainFrameSettings()
    settings.values.update(
        window_width=1440 if transition == "resize" else 900,
        window_height=960,
        mica_enabled=False,
    )
    adapter = _FakeScreenAdapter(_FakeScreen("navigation-test", QSize(1800, 1200)))
    BaseStyles.switch_theme(theme_name)
    frame = build_main_frame(screen_adapter=adapter, settings=settings)
    panel = frame.navigationInterface.panel
    try:
        frame.show()
        frame._on_nav_requested("apps")
        initial_mode = (
            NavigationDisplayMode.EXPAND
            if transition == "resize"
            else NavigationDisplayMode.COMPACT
        )
        wait_until(
            qt_application,
            lambda: panel.displayMode == initial_mode
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )
        background = _navigation_background_pixel(frame)
        assert background.alpha() == 255

        if transition == "resize":
            frame.resize(840, 640)
        else:
            frame._toggle_navigation_panel()
            wait_until(
                qt_application,
                lambda: panel.displayMode == NavigationDisplayMode.MENU
                and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
            )
            frame._toggle_navigation_panel()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.COMPACT
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )

        assert panel.width() == 48
        assert panel.parentWidget() is frame.navigationInterface
        assert panel.menuButton.isVisibleTo(frame)
        assert _navigation_background_pixel(frame) == background
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_wide_navigation_manual_collapse_waits_for_user_to_reopen(qt_application):
    """宽窗手动收起应保持紧凑，尾沿布局通知不能重新覆盖用户选择。"""
    settings = _MainFrameSettings()
    settings.values.update(window_width=1600, window_height=900, mica_enabled=False)
    adapter = _FakeScreenAdapter(_FakeScreen("navigation-test", QSize(1920, 1080)))
    frame = build_main_frame(screen_adapter=adapter, settings=settings)
    panel = frame.navigationInterface.panel
    try:
        frame.show()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )
        finished = QSignalSpy(panel.expandAni.finished)
        panel.menuButton.click()
        wait_until(qt_application, lambda: finished.count() == 1)
        # 消费动画结束后排队的布局事件，确认收起不是一帧过渡状态。
        QTest.qWait(panel.expandAni.duration() + 100)
        assert panel.displayMode == NavigationDisplayMode.COMPACT
        assert panel.width() == 48
        assert frame.width() == 1600

        panel.menuButton.click()
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )
        assert panel.width() == panel.expandWidth
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.fixture
def theme_probe_frame(qt_application, monkeypatch):
    """主题与导航探针隔离设置和设备快照，不触及真实用户配置。"""
    frames = []
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda _devices: [])

    def build(theme_name, mica, *, width=1320):
        settings = _MainFrameSettings()
        settings.values.update(
            theme="Light", mica_enabled=mica, window_width=width, window_height=860
        )
        monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
        BaseStyles.switch_theme("Light")
        frame = build_main_frame(
            settings=settings,
            screen_adapter=_FakeScreenAdapter(_FakeScreen("theme-probe", QSize(1920, 1080))),
        )
        frames.append(frame)
        frame.show()
        qt_application.processEvents()
        BaseStyles.switch_theme(theme_name)
        qt_application.processEvents()
        return frame

    yield build
    for frame in frames:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        frame.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _assert_stack_gap_matches_surface(frame, context):
    """整窗合成取顶部空白行，避开文字、控件和圆角的抗锯齿。"""
    image = frame.grab().toImage()
    scale = image.devicePixelRatio()
    expected = QColor(BaseStyles.color("WINDOW_BG"))
    for fraction in (0.25, 0.5, 0.75):
        point = frame.stackedWidget.mapTo(
            frame, QPoint(round(frame.stackedWidget.width() * fraction), 2)
        )
        actual = image.pixelColor(round(point.x() * scale), round(point.y() * scale))
        assert actual == expected, (context, point, actual.name(), actual.alpha(), expected.name())


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("mica", [False, True])
def test_route_animation_and_device_bar_visibility_keep_same_theme_surface(
    qt_application, theme_probe_frame, theme_name, mica
):
    frame = theme_probe_frame(theme_name, mica)
    for key in (
        "appsPage", "appManagerPage", "filesPage", "devicesPage", "settingsPage", "systemPage"
    ):
        previous = frame.stackedWidget.currentWidget()
        frame.navigationInterface.widget(key).click()
        assert frame._global_device_bar.isVisible() == (key not in {"devicesPage", "settingsPage"})
        assert frame.stackedWidget.isAnimationEnabled()
        animation = frame.stackedWidget.view._ani
        if frame.stackedWidget.currentWidget() is not previous:
            assert animation.state() == QAbstractAnimation.State.Running
            for time in (0, 30, 120):
                animation.setCurrentTime(time)
                assert frame.stackedWidget.currentWidget().y() > 0
                _assert_stack_gap_matches_surface(frame, (key, time))
            animation.setCurrentTime(animation.duration())
        _assert_stack_gap_matches_surface(frame, (key, "immediate"))
        qt_application.processEvents()
        _assert_stack_gap_matches_surface(frame, (key, "layout"))


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("mica", [False, True])
def test_rapid_route_replacement_keeps_animated_gap_in_current_theme(
    theme_probe_frame, theme_name, mica
):
    frame = theme_probe_frame(theme_name, mica)
    for key in ("appsPage", "settingsPage", "systemPage", "filesPage", "appsPage"):
        frame.navigationInterface.widget(key).click()
        animation = frame.stackedWidget.view._ani
        assert frame.stackedWidget.isAnimationEnabled()
        assert animation.state() == QAbstractAnimation.State.Running
        animation.setCurrentTime(30)
        _assert_stack_gap_matches_surface(frame, key)


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
def test_menu_collapse_style_reset_frame_preserves_opaque_theme(
    qt_application, monkeypatch, theme_probe_frame, theme_name
):
    frame = theme_probe_frame(theme_name, False, width=900)
    panel = frame.navigationInterface.panel
    frame._toggle_navigation_panel()
    wait_until(
        qt_application,
        lambda: panel.displayMode == NavigationDisplayMode.MENU
        and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
    )
    menu_point = QPoint(2, 20)
    menu_background = _navigation_background_pixel(frame, menu_point)
    captured = []
    original_set_style = panel.setStyle

    def capture_style_reset(style):
        original_set_style(style)
        captured.append(_navigation_background_pixel(frame, QPoint(1, 300)))

    monkeypatch.setattr(panel, "setStyle", capture_style_reset)
    frame._toggle_navigation_panel()
    assert panel.expandAni.state() == QAbstractAnimation.State.Running
    for time in (0, panel.expandAni.duration() // 2):
        panel.expandAni.setCurrentTime(time)
        assert panel.displayMode == NavigationDisplayMode.MENU
        assert panel.expandAni.state() == QAbstractAnimation.State.Running
        assert _navigation_background_pixel(frame, menu_point) == menu_background
    wait_until(
        qt_application,
        lambda: panel.displayMode == NavigationDisplayMode.COMPACT
        and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
    )
    assert captured, "必须采到上游收起尾沿 setStyle 后、主窗口恢复前的实际绘制"
    expected = QColor(BaseStyles.color("WINDOW_BG"))
    assert all(color == expected for color in captured), [
        (color.name(), color.alpha()) for color in captured
    ]
    assert _navigation_background_pixel(frame) == expected
