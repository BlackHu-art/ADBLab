"""设备栏弹层的边界、定位和瞬态资源回归。"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox, PushButton
from shiboken6 import isValid

from gui.pages.device_hub import DeviceHubPage
from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceContextBar
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until


@pytest.fixture
def native_window_api():
    """原生激活和键盘路由只能由 Windows 平台验证，离屏事件不能替代。"""
    if QApplication.platformName() != "windows":
        pytest.skip("需要 Windows 原生窗口验证激活与键盘路由")
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("user32")
    for name in ("GetActiveWindow", "GetFocus"):
        function = getattr(api, name)
        function.argtypes = []
        function.restype = wintypes.HWND
    api.PostMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    api.PostMessageW.restype = wintypes.BOOL
    return api


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


@pytest.fixture
def connection_anchor(bar_window, qt_application):
    window, _bar = bar_window
    surface = QWidget(window)
    layout = QHBoxLayout(surface)
    layout.setContentsMargins(28, 0, 28, 0)
    layout.addStretch(1)
    anchor = PushButton("连接设备", surface)
    layout.addWidget(anchor)
    window.layout().insertWidget(1, surface)
    qt_application.processEvents()
    return anchor


@pytest.mark.parametrize("kind", ["picker", "connection"])
def test_native_device_popup_keeps_owner_active(
    bar_window, connection_anchor, qt_application, native_window_api, kind,
):
    """设备弹层不得抢走主 HWND 的激活，否则 DWM 会把主窗口云母退回实色。"""
    window, bar = bar_window
    window.raise_()
    window.activateWindow()
    hwnd = int(window.winId())
    wait_until(qt_application, lambda: native_window_api.GetActiveWindow() == hwnd)
    if kind == "picker":
        bar.open_picker()
        popup = bar._picker_flyout
    else:
        bar.open_connection([], connection_anchor)
        popup = bar._connection_flyout
    wait_until(qt_application, lambda: popup.isVisible())
    qt_application.processEvents()

    assert QApplication.activePopupWidget() is popup
    assert native_window_api.GetActiveWindow() == hwnd
    bar.dismiss_popups()
    qt_application.processEvents()
    assert native_window_api.GetActiveWindow() == hwnd
    assert bar._picker_flyout is None and bar._connection_flyout is None


@pytest.mark.parametrize("kind", ["picker", "connection"])
def test_native_device_popup_routes_keyboard_without_activating(
    bar_window, connection_anchor, qt_application, native_window_api, kind,
):
    """从主 HWND 投递键盘消息，确保保留云母时复选、输入和关闭仍由弹层消费。"""
    window, bar = bar_window
    window.raise_()
    window.activateWindow()
    hwnd = int(window.winId())
    wait_until(qt_application, lambda: native_window_api.GetActiveWindow() == hwnd)
    if kind == "picker":
        bar.open_picker()
        popup = bar._picker_flyout
        field = bar._picker.device_list
        field.setCurrentRow(1)
        field.setFocus()
        changed = QSignalSpy(bar.selection_requested)
    else:
        bar.open_connection([], connection_anchor)
        popup = bar._connection_flyout
        field = bar._connection.address
        changed = QSignalSpy(bar.connect_requested)
    wait_until(qt_application, field.hasFocus)
    # Qt Popup 应在保留主原生焦点的同时，把输入路由给弹层内的焦点控件。
    assert native_window_api.GetFocus() == hwnd
    if kind == "picker":
        assert native_window_api.PostMessageW(hwnd, 0x0100, 0x20, 1)  # WM_KEYDOWN / Space
        assert native_window_api.PostMessageW(hwnd, 0x0101, 0x20, 1)  # WM_KEYUP / Space
        wait_until(qt_application, lambda: changed.count() == 1)
        assert changed.at(0)[0] == ["demo-a", "demo-b"]
        key = 0x1B  # Escape
    else:
        for char in "192.0.2.1:5555":
            assert native_window_api.PostMessageW(hwnd, 0x0102, ord(char), 1)  # WM_CHAR
        wait_until(qt_application, lambda: field.text() == "192.0.2.1:5555")
        key = 0x0D  # Return
    assert native_window_api.PostMessageW(hwnd, 0x0100, key, 1)
    assert native_window_api.PostMessageW(hwnd, 0x0101, key, 1)
    wait_until(qt_application, lambda: not isValid(popup) or not popup.isVisible())
    if kind == "connection":
        assert changed.count() == 1 and changed.at(0)[0] == "192.0.2.1:5555"
    assert native_window_api.GetActiveWindow() == hwnd


def test_native_connection_history_menu_keeps_outer_popup_and_owner_active(
    bar_window, connection_anchor, qt_application, native_window_api,
):
    """内层历史菜单选择与 Esc 只关闭当前层，连接表单继续持有输入。"""
    window, bar = bar_window
    window.activateWindow()
    hwnd = int(window.winId())
    wait_until(qt_application, lambda: native_window_api.GetActiveWindow() == hwnd)
    bar.open_connection([("演示连接", "192.0.2.2:5555")], connection_anchor)
    form, popup = bar._connection, bar._connection_flyout
    field = form.address
    field.dropButton.click()
    menu = field.dropMenu
    wait_until(qt_application, lambda: menu.isVisible())
    viewport = menu.view.viewport()
    QTest.mouseClick(
        viewport, Qt.MouseButton.LeftButton,
        pos=menu.view.visualItemRect(menu.view.item(0)).center(),
    )
    wait_until(qt_application, lambda: field.text() == "192.0.2.2:5555")
    assert popup.isVisible() and bar._connection is form
    assert native_window_api.GetActiveWindow() == hwnd

    field.dropButton.click()
    wait_until(qt_application, lambda: field.dropMenu is not None and field.dropMenu.isVisible())
    assert native_window_api.PostMessageW(hwnd, 0x0100, 0x1B, 1)
    assert native_window_api.PostMessageW(hwnd, 0x0101, 0x1B, 1)
    wait_until(qt_application, lambda: field.dropMenu is None)
    assert popup.isVisible()
    assert native_window_api.PostMessageW(hwnd, 0x0100, 0x1B, 1)
    assert native_window_api.PostMessageW(hwnd, 0x0101, 0x1B, 1)
    wait_until(qt_application, lambda: bar._connection_flyout is None)
    assert native_window_api.GetActiveWindow() == hwnd


@pytest.mark.parametrize("kind", ["picker", "connection"])
def test_native_outside_click_closes_device_popup_and_allows_reopen(
    bar_window, connection_anchor, qt_application, native_window_api, kind,
):
    """从主 HWND 分发弹层外点击，关闭后清理引用并允许立即再次打开。"""
    window, bar = bar_window
    window.activateWindow()
    hwnd = int(window.winId())
    wait_until(qt_application, lambda: native_window_api.GetActiveWindow() == hwnd)

    def open_popup():
        if kind == "picker":
            bar.open_picker()
            return bar._picker_flyout
        bar.open_connection([], connection_anchor)
        return bar._connection_flyout

    popup = open_popup()
    point = QPoint(window.width() - 20, window.height() - 20)
    assert not popup.geometry().contains(window.mapToGlobal(point))
    coordinates = point.x() | (point.y() << 16)
    assert native_window_api.PostMessageW(hwnd, 0x0201, 1, coordinates)  # WM_LBUTTONDOWN
    assert native_window_api.PostMessageW(hwnd, 0x0202, 0, coordinates)  # WM_LBUTTONUP
    wait_until(
        qt_application, lambda: bar._picker_flyout is None and bar._connection_flyout is None,
    )
    replacement = open_popup()
    assert replacement is not popup and replacement.isVisible()
    assert native_window_api.GetActiveWindow() == hwnd


@pytest.mark.parametrize("kind", ["picker", "connection"])
def test_device_popup_aligns_to_action_and_stays_in_content(
    bar_window, connection_anchor, qt_application, kind
):
    window, bar = bar_window
    if kind == "picker":
        bar.open_picker()
        view, anchor = bar._picker, bar.targets_button
    else:
        bar.open_connection([], anchor=connection_anchor)
        view, anchor = bar._connection, connection_anchor
    QTest.qWait(220)
    bounds = QRect(view.mapToGlobal(QPoint()), view.size())
    content = QRect(bar.mapToGlobal(QPoint()), bar.size())
    assert bounds.left() >= content.left()
    assert bounds.right() <= content.right()
    assert bounds.top() >= anchor.mapToGlobal(QPoint(0, anchor.height())).y()
    if kind == "picker":
        assert abs(bounds.right() - anchor.mapToGlobal(QPoint(anchor.width() - 1, 0)).x()) <= 2
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
def test_hiding_device_bar_releases_popup_and_allows_immediate_reopen(
    bar_window, connection_anchor, kind
):
    _window, bar = bar_window
    if kind == "picker":
        bar.open_picker()
        view = bar._picker
    else:
        bar.open_connection([], anchor=connection_anchor)
        view = bar._connection
    destroyed = QSignalSpy(view.destroyed)
    bar.hide()
    assert not view.isVisible()
    bar.show()
    if kind == "picker":
        bar.open_picker()
        replacement = bar._picker
    else:
        bar.open_connection([], anchor=connection_anchor)
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
def test_device_popup_escape_dismisses_and_releases_view(bar_window, connection_anchor, kind):
    _window, bar = bar_window
    if kind == "picker":
        bar.open_picker()
        view = bar._picker
    else:
        bar.open_connection([], anchor=connection_anchor)
        view = bar._connection
    destroyed = QSignalSpy(view.destroyed)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not view.isVisible()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed.count() == 1


@pytest.mark.parametrize("font_size", [12, 22])
def test_overview_toolbar_fully_contains_disconnect_and_accepts_real_clicks(
    bar_window, qt_application, monkeypatch, font_size
):
    window, bar = bar_window
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size)),
    )
    bar.hide()
    hub = DeviceHubPage(window)
    window.layout().insertWidget(1, hub)
    hub.set_device_context(["demo-a"], ["demo-a"], "ready")
    hub._apply_fonts()
    qt_application.processEvents()
    called = QSignalSpy(hub.disconnect_requested)
    button = hub.disconnect_button
    assert button.isVisible() and button.isEnabled()
    bounds = QRect(button.mapTo(hub.toolbar, QPoint()), button.size())
    assert hub.toolbar.rect().contains(bounds)
    assert button.width() >= button.sizeHint().width()
    assert button.height() >= button.fontMetrics().height() + 14
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert called.count() == 1


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
    bar_window, connection_anchor, qt_application, monkeypatch, kind, font_size, width
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
        bar.open_connection([], anchor=connection_anchor)
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
    assert bar.targets_button.isVisible()
    assert bar.rect().contains(
        QRect(bar.targets_button.mapTo(bar, QPoint()), bar.targets_button.size())
    )
    bar.open_picker()
    picker = bar._picker
    assert picker.session_box.isHidden()
    assert picker.device_list.isVisible()
    assert picker.select_all_button.isHidden()
    assert picker.close_button.isVisible()
    assert picker.rect().contains(QRect(picker.close_button.mapTo(picker, QPoint()),
                                       picker.close_button.size()))
    source.deleteLater()
    close.deleteLater()


def test_global_labels_survive_discovery_reorder_offline_and_selection_changes(bar_window):
    _window, bar = bar_window
    bar.set_context(["demo-c"], ["demo-a", "demo-b", "demo-c"], "ready")
    bar.set_device_labels({"demo-c": "Phone"})
    assert bar.device_label("demo-c") == "设备 3 · Phone"
    bar.set_context(["demo-c"], ["demo-c", "demo-a"], "ready")
    bar.open_picker()
    assert bar._picker.device_list.item(0).text() == "设备 3 · Phone"
    bar.set_context([], [], "empty")
    assert bar.device_label("demo-c") == "设备 3 · Phone"
    bar.set_context(["demo-c"], ["demo-c"], "ready")
    assert bar._picker.device_list.item(0).text() == "设备 3 · Phone"


@pytest.mark.parametrize("width,font_size", [(400, 12), (730, 12), (650, 22)])
def test_single_device_header_keeps_normal_name_fully_visible(
    bar_window, qt_application, monkeypatch, width, font_size,
):
    """普通型号不应被重复前缀或按钮样式额外省略，完整归属仍可辅助读取。"""
    window, bar = bar_window
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    bar._apply_fonts()
    source = ComboBox(window)
    source.addItem("demo-a", userData="demo-a")
    bar.set_device_labels({"demo-a": "Redmi 23113RKC6C"})
    bar.set_session_context(source, None)
    window.resize(width, 680)
    wait_for_stable_geometry(qt_application, (window, bar, bar.targets_button))

    button = bar.targets_button
    assert "Redmi 23113RKC6C" in button.text()
    assert "设备 1" in button.text()
    assert button.width() >= button.sizeHint().width()
    assert "当前设备 · 设备 1 · Redmi 23113RKC6C" in button.toolTip()
    assert "当前设备 · 设备 1 · Redmi 23113RKC6C" == button.accessibleName()
    assert bar.rect().contains(QRect(button.mapTo(bar, QPoint()), button.size()))
    assert bar.session_combo.currentData() == "demo-a"


@pytest.mark.parametrize("family", ["Microsoft YaHei", "Segoe UI"])
@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("letter_spacing", [0.0, 1 / 32])
def test_batch_device_header_does_not_elide_text_that_fits(
    bar_window, qt_application, monkeypatch, family, font_size, letter_spacing,
):
    """字体的小数宽度不能被取整截短；常规短名称必须完整交给真实按钮绘制。"""
    window, bar = bar_window
    font = QFont(family, font_size)
    # 原生 DirectWrite 默认返回小数宽度，额外字距让离屏字体也覆盖同一边界。
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: font,
    ))
    bar._apply_fonts()
    bar.set_context(["demo-a"], ["demo-a"], "ready")
    wait_for_stable_geometry(qt_application, (window, bar, bar.targets_button))

    button = bar.targets_button
    expected = "操作设备 · 1 台"
    assert button.text() == expected
    option = QStyleOptionButton()
    button.initStyleOption(option)
    content_rect = button.style().subElementRect(
        QStyle.SubElement.SE_PushButtonContents, option, button,
    )
    assert content_rect.width() >= QFontMetricsF(button.font()).horizontalAdvance(expected)
    assert expected in button.toolTip()
    assert bar.rect().contains(QRect(button.mapTo(bar, QPoint()), button.size()))


def test_single_page_header_and_picker_show_only_current_operation_target(bar_window):
    _window, bar = bar_window
    source = ComboBox()
    source.addItem("demo-b", userData="demo-b")
    bar.set_context(["demo-a", "demo-b"], ["demo-a", "demo-b"], "ready")
    bar.set_session_context(source, None)
    assert bar.targets_button.accessibleName() == "当前设备 · 设备 2"
    bar.open_picker()
    assert bar._picker.batch_heading.isHidden()
    assert "请选择一台操作设备" in bar._picker.description.text()
    assert bar._picker.device_list.item(0).checkState() == Qt.CheckState.Unchecked
    assert bar._picker.device_list.item(1).checkState() == Qt.CheckState.Checked
    bar.set_context(["demo-a"], ["demo-a", "demo-b"], "ready")
    assert "未勾选" in bar.targets_button.accessibleName()
    assert all(bar._picker.device_list.item(index).checkState() == Qt.CheckState.Unchecked
               for index in range(bar._picker.device_list.count()))
    bar.set_context(["demo-a"], ["demo-a"], "ready")
    assert "离线" in bar.targets_button.accessibleName()
    bar.set_session_context(None, None)
    assert bar.targets_button.accessibleName() == "操作设备 · 1 台"
    assert not bar._picker.batch_heading.isVisible()
    source.deleteLater()


@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("with_close", [False, True])
def test_single_device_popup_keeps_actions_inside_narrow_window(
    bar_window, qt_application, monkeypatch, font_size, with_close,
):
    window, bar = bar_window
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    bar._apply_fonts()
    window.resize(500, 500)
    devices = [f"demo-{index}" for index in range(8)]
    bar.set_context(devices, devices, "ready")
    source = ComboBox(window)
    for device in devices:
        source.addItem(device, userData=device)
    close = PushButton("关闭文件管理", window) if with_close else None
    bar.set_session_context(source, close)
    qt_application.processEvents()
    assert (window.width(), window.height()) == (500, 500)
    bar.open_picker()
    QTest.qWait(220)
    picker = bar._picker
    bounds = QRect(picker.mapToGlobal(QPoint()), picker.size())
    assert QRect(window.mapToGlobal(QPoint()), window.size()).contains(bounds)
    controls = [picker.device_list, picker.clear_button]
    assert picker.close_button.isVisible() is with_close
    assert picker.close_section.isVisible() is with_close
    if with_close:
        controls.append(picker.close_button)
    for control in controls:
        assert control.isVisible()
        assert picker.rect().contains(QRect(control.mapTo(picker, QPoint()), control.size()))
        assert control.height() >= control.fontMetrics().height()
    picker.device_list.scrollToBottom()
    last = picker.device_list.item(picker.device_list.count() - 1)
    assert picker.device_list.viewport().rect().contains(picker.device_list.visualItemRect(last))
    if with_close:
        requested = QSignalSpy(bar.close_session_requested)
        QTest.mouseClick(picker.close_button, Qt.MouseButton.LeftButton)
        assert requested.count() == 1


def test_picker_close_action_updates_and_hides_with_session_context(bar_window, qt_application):
    window, bar = bar_window
    source = ComboBox(window)
    source.addItem("demo-a", userData="demo-a")
    bar.set_session_context(source, None)
    bar.open_picker()
    picker = bar._picker
    assert picker.close_section.isHidden()
    assert not picker.close_button.isVisible()

    close = PushButton("关闭应用管理", window)
    bar.set_session_context(source, close)
    qt_application.processEvents()
    assert picker.close_section.isVisible()
    assert picker.close_button.isVisible()
    assert picker.close_button.text() == "关闭应用管理"
    assert picker.close_button.accessibleName() == "关闭应用管理"
    assert picker.close_button.isEnabled()

    close.setEnabled(False)
    bar.set_session_context(source, close)
    assert picker.close_button.text() == "正在关闭"
    assert picker.close_button.accessibleName() == "正在关闭"
    assert not picker.close_button.isEnabled()
    requested = QSignalSpy(bar.close_session_requested)
    QTest.mouseClick(picker.close_button, Qt.MouseButton.LeftButton)
    assert requested.count() == 0

    bar.set_session_context(None, None)
    assert picker.close_section.isHidden()
    assert not picker.close_button.isVisible()


def test_picker_close_action_supports_keyboard_and_releases_after_completion(
    bar_window, qt_application,
):
    window, bar = bar_window
    source = ComboBox(window)
    source.addItem("demo-a", userData="demo-a")
    close = PushButton("清除截图结果", window)
    bar.set_session_context(source, close)
    bar.open_picker()
    picker = bar._picker
    popup = bar._picker_flyout
    requested = QSignalSpy(bar.close_session_requested)
    destroyed = QSignalSpy(picker.destroyed)
    picker.clear_button.setFocus(Qt.FocusReason.TabFocusReason)
    wait_until(qt_application, picker.clear_button.hasFocus)
    QTest.keyClick(picker.clear_button, Qt.Key.Key_Tab)
    assert picker.close_button.hasFocus()
    QTest.keyClick(picker.close_button, Qt.Key.Key_Space)
    assert requested.count() == 1
    assert popup.isVisible()
    assert picker.close_button.text() == "正在关闭"
    assert not picker.close_button.isEnabled()
    QTest.keyClick(picker.close_button, Qt.Key.Key_Space)
    assert requested.count() == 1
    bar.set_session_context(None, None)
    assert not popup.isVisible()
    assert bar._picker is None and bar._picker_flyout is None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed.count() == 1
    assert not isValid(picker)


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
    from tests.test_navigation_rendering import _native_content_color

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
        # 顶栏加入页面标题后，左侧中点会命中文字笔画；采样顶部留白验证材质。
        surface_point = bar._surface.mapTo(frame, QPoint(4, 0))
        surface_color = image.pixelColor(
            round(surface_point.x() * scale), round(surface_point.y() * scale)
        )
        # 内层沿用原生 Fluent 内容遮罩，关闭云母仍保留相对于根背景的层次。
        assert surface_color == _native_content_color(frame.backgroundColor)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        frame.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
