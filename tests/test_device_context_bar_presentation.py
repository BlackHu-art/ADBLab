"""设备栏弹层的边界、定位和瞬态资源回归。"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, PushButton
from shiboken6 import isValid

from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceContextBar


@pytest.fixture
def bar_window(qt_application):
    window = QWidget()
    window.resize(730, 680)
    window.move(30, 20)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(12, 12, 12, 12)
    bar = DeviceContextBar(window)
    layout.addWidget(bar)
    layout.addStretch(1)
    bar.set_context(["demo-a"], ["demo-a", "demo-b"], "ready")
    window.show()
    qt_application.processEvents()
    yield window, bar
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("kind", ["picker", "connection"])
def test_device_popup_aligns_to_action_and_stays_in_content(bar_window, qt_application, kind):
    window, bar = bar_window
    if kind == "picker":
        bar.open_picker()
        view, anchor = bar._picker, bar.targets_button
    else:
        bar.open_connection([])
        view, anchor = bar._connection, bar.connect_button
    QTest.qWait(220)
    bounds = QRect(view.mapToGlobal(QPoint()), view.size())
    content = QRect(bar.mapToGlobal(QPoint()), bar.size())
    assert bounds.left() >= content.left()
    assert bounds.right() <= content.right()
    assert bounds.top() >= anchor.mapToGlobal(QPoint(0, anchor.height())).y()
    if kind == "picker":
        assert abs(bounds.left() - anchor.mapToGlobal(QPoint()).x()) <= 2
    else:
        anchor_right = anchor.mapToGlobal(QPoint(anchor.width() - 1, 0)).x()
        screen_right = window.screen().availableGeometry().right()
        if anchor_right > screen_right:
            # 缩放会缩小离屏屏幕的逻辑尺寸；窗口伸出屏幕时，弹层必须贴屏幕边界。
            popup = view.parentWidget()
            popup_bounds = QRect(popup.mapToGlobal(QPoint()), popup.size())
            assert popup_bounds.right() == screen_right
        else:
            assert abs(bounds.right() - anchor_right) <= 2
    assert 350 <= view.width() <= 420
    assert window.screen().availableGeometry().contains(bounds)


@pytest.mark.parametrize("kind", ["picker", "connection"])
def test_hiding_device_bar_releases_popup_and_allows_immediate_reopen(bar_window, kind):
    _window, bar = bar_window
    if kind == "picker":
        bar.open_picker()
        view = bar._picker
    else:
        bar.open_connection([])
        view = bar._connection
    destroyed = QSignalSpy(view.destroyed)
    bar.hide()
    assert not view.isVisible()
    bar.show()
    if kind == "picker":
        bar.open_picker()
        replacement = bar._picker
    else:
        bar.open_connection([])
        replacement = bar._connection
    assert replacement is not view and replacement.isVisible()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed.count() == 1
    assert not isValid(view)
    assert replacement.isVisible()


def test_connection_can_anchor_to_visible_overview_while_bar_hidden(bar_window, qt_application):
    window, bar = bar_window
    bar.hide()
    anchor = PushButton("连接设备", window)
    window.layout().insertWidget(1, anchor, 0, Qt.AlignmentFlag.AlignRight)
    qt_application.processEvents()
    bar.open_connection([], anchor=anchor)
    view = bar._connection
    assert view.isVisible()
    assert view.mapToGlobal(QPoint()).y() >= anchor.mapToGlobal(QPoint(0, anchor.height())).y()
    bar.dismiss_popups()
    assert not view.isVisible()


@pytest.mark.parametrize("kind", ["picker", "connection"])
def test_device_popup_escape_dismisses_and_releases_view(bar_window, kind):
    _window, bar = bar_window
    if kind == "picker":
        bar.open_picker()
        view = bar._picker
    else:
        bar.open_connection([])
        view = bar._connection
    destroyed = QSignalSpy(view.destroyed)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not view.isVisible()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed.count() == 1


@pytest.mark.parametrize("font_size", [12, 22])
def test_more_menu_fully_contains_actions_and_accepts_real_clicks(
    bar_window, qt_application, monkeypatch, font_size
):
    _window, bar = bar_window
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size)),
    )
    bar._apply_fonts()
    calls = [QSignalSpy(bar.info_requested), QSignalSpy(bar.disconnect_requested)]
    for row, (action, called) in enumerate(zip((bar.info_action, bar.disconnect_action), calls)):
        QTest.mouseClick(bar.more_button, Qt.MouseButton.LeftButton)
        QTest.qWait(220)
        menu = bar._more_menu
        viewport = menu.view.viewport()
        assert menu.isVisible() and action.isEnabled()
        item = menu.view.item(row)
        bounds = menu.view.visualItemRect(item)
        assert viewport.rect().contains(bounds)
        assert bounds.width() >= menu.view.fontMetrics().horizontalAdvance(action.text()) + 40
        assert bounds.height() >= menu.view.fontMetrics().height() + 14
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=bounds.center())
        assert called.count() == 1
        assert not menu.isVisible()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_device_bar_interior_uses_page_background_without_card_border(bar_window, theme):
    _window, bar = bar_window
    BaseStyles.switch_theme(theme)
    QTest.qWait(180)
    rendered = bar.grab().toImage()
    scale = rendered.devicePixelRatio()
    background = QColor(BaseStyles.color("WINDOW_BG"))
    for offset in (QPoint(1, 1), QPoint(4, 4), QPoint(4, bar._surface.height() // 2)):
        point = bar._surface.mapTo(bar, offset)
        assert rendered.pixelColor(round(point.x() * scale), round(point.y() * scale)) == background


@pytest.mark.parametrize("kind", ["picker", "connection"])
@pytest.mark.parametrize("font_size, width", [(12, 500), (22, 500), (22, 730)])
def test_popup_large_fonts_and_connection_error_fit_window(
    bar_window, qt_application, monkeypatch, kind, font_size, width
):
    window, bar = bar_window
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size)),
    )
    bar._apply_fonts()
    window.resize(width, 680)
    qt_application.processEvents()
    assert window.width() == width
    if kind == "picker":
        bar.open_picker()
        view = bar._picker
        controls = (view.description, view.device_list, view.select_all_button, view.clear_button)
    else:
        bar.open_connection([])
        view = bar._connection
        view.address.setText("not an address")
        view.connect_button.click()
        assert view.error_label.isVisible()
        controls = (view.address, view.error_label, view.connect_button)
    qt_application.processEvents()
    bounds = QRect(view.mapToGlobal(QPoint()), view.size())
    assert QRect(window.mapToGlobal(QPoint()), window.size()).contains(bounds)
    for control in controls:
        assert control.isVisible()
        assert view.rect().contains(QRect(control.mapTo(view, QPoint()), control.size()))
        assert control.font().pointSize() == font_size
        assert control.height() >= control.fontMetrics().height()


def test_existing_session_bar_can_shrink_after_increasing_font(
    bar_window, qt_application, monkeypatch
):
    window, bar = bar_window
    source = ComboBox()
    source.addItem("demo-a", userData="demo-a")
    close = PushButton("关闭会话")
    bar.set_session_context(source, close)
    window.resize(1080, 680)
    qt_application.processEvents()
    window.resize(500, 680)
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or 22)),
    )
    bar._apply_fonts()
    qt_application.processEvents()
    assert window.width() == 500
    for control in (bar.targets_button, bar.status_label, bar.session_combo, bar.close_button):
        assert bar.rect().contains(QRect(control.mapTo(bar, QPoint()), control.size()))


def test_first_dark_theme_switch_keeps_device_bar_dark_after_native_palette_update(
    qt_application, monkeypatch
):
    from PySide6.QtCore import QSize

    from core.settings_manager import AppSettings
    from models.device_store import DeviceStore
    from tests.test_main_window_layout import (
        _FakeScreen,
        _FakeScreenAdapter,
        _MainFrameSettings,
        build_main_frame,
    )

    settings = _MainFrameSettings()
    settings.values.update({"theme": "Light", "mica_enabled": False})
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", classmethod(lambda _cls: []))
    monkeypatch.setattr(
        DeviceStore, "get_full_devices_info", classmethod(lambda _cls, targets=None: [])
    )
    BaseStyles.switch_theme("Light")
    frame = build_main_frame(
        settings=settings,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("theme-probe", QSize(1600, 1100)))
    )
    try:
        frame.resize(1050, 800)
        frame.show()
        frame._on_devices_updated(["demo-a"])
        frame._on_nav_requested("apps")
        QTest.qWait(250)
        bar = frame._global_device_bar
        bar.open_picker()
        bar.dismiss_popups()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        BaseStyles.switch_theme("Dark")
        frame._on_nav_requested("system")
        QTest.qWait(250)
        background = QColor(BaseStyles.color("WINDOW_BG"))
        assert bar.palette().color(QPalette.ColorRole.Window) == background
        image = frame.grab().toImage()
        point = bar.mapTo(frame, QPoint(2, 2))
        scale = image.devicePixelRatio()
        assert image.pixelColor(round(point.x() * scale), round(point.y() * scale)) == background
        surface_point = bar._surface.mapTo(frame, QPoint(4, bar._surface.height() // 2))
        surface_color = image.pixelColor(
            round(surface_point.x() * scale), round(surface_point.y() * scale)
        )
        assert surface_color == background
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        frame.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
