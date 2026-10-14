"""远程侧栏只路由现有动作，窗口隐藏和释放必须同步收起更多面板。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QLabel, QPushButton, QScrollArea, QToolButton

pytestmark = pytest.mark.ui

EXPECTED_KEYS = {
    "BACK", "HOME", "RECENTS", "POWER", "MENU", "ENTER", "DEL", "SETTINGS",
    "CAMERA", "SEARCH", "VOL_DOWN", "VOL_UP", "MEDIA_PREV", "MEDIA_PLAY", "MEDIA_NEXT",
}
EXPECTED_ACTIONS = {
    "rotate_portrait", "rotate_landscape", "notif_expand", "notif_collapse",
    "swipe_up", "swipe_down", "swipe_left", "swipe_right",
}


def _buttons(toolbar):
    return [
        button for button in toolbar.findChildren(QAbstractButton)
        if button.property("remoteKey") or button.property("remoteAction")
    ]


def _more_button(toolbar):
    button = toolbar.findChild(QToolButton, "remoteToolbarMore")
    assert button is not None
    return button


def _show_more(toolbar, application):
    if not toolbar.popup_window.isVisible():
        _more_button(toolbar).click()
        application.processEvents()
    assert toolbar.popup_window.isVisible()


@pytest.mark.parametrize("available", [False, True])
def test_unchanged_availability_does_not_rewrite_button_state_or_tooltips(
    qt_application, monkeypatch, available,
):
    """窗口跟随轮询不重复刷新稳定的操作准入、提示和更多面板。"""
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar()
    try:
        toolbar.set_available(available)
        writes = []
        for button in (*_buttons(toolbar), _more_button(toolbar)):
            monkeypatch.setattr(button, "setEnabled", lambda value: writes.append(value))
        monkeypatch.setattr(toolbar, "_refresh_tooltips", lambda: writes.append("tooltip"))
        monkeypatch.setattr(toolbar, "dismiss_popup", lambda: writes.append("dismiss"))
        for _ in range(8):
            toolbar.set_available(available)
        assert writes == []
    finally:
        toolbar.dispose()


@pytest.mark.parametrize("portable", [False, True])
def test_popup_motion_reuses_measurement_until_font_or_screen_constraints_change(
    qt_application, monkeypatch, portable,
):
    """同屏移动仅更新位置；字体和可用区变化重新度量以保留完整操作行。"""
    from gui.styles import BaseStyles
    from gui.widgets.remote_toolbar import RemoteToolbar

    bounds = QRect(0, 0, 1600, 1000)
    screen = SimpleNamespace(availableGeometry=lambda: QRect(bounds))
    monkeypatch.setattr(RemoteToolbar, "screen", lambda _self: screen)
    toolbar = RemoteToolbar(portable=portable)
    try:
        toolbar.set_available(True)
        toolbar.show()
        _show_more(toolbar, qt_application)
        measurements = []
        original = toolbar._popup_content.sizeHint
        monkeypatch.setattr(toolbar._popup_content, "sizeHint", lambda: (
            measurements.append(True), original(),
        )[1])
        for x in range(100, 180, 10):
            toolbar.move(x, 80)
            toolbar._position_popup()
        assert measurements == []
        bounds.setHeight(330)
        toolbar._position_popup()
        assert measurements
        assert toolbar.popup_window.height() <= 330
        measurements.clear()
        BaseStyles.fonts_changed.emit(None)
        toolbar._position_popup()
        assert measurements
        measurements.clear()
        toolbar.windowHandle().screen().logicalDotsPerInchChanged.emit(120)
        assert measurements
        measurements.clear()
        toolbar.windowHandle().screen().availableGeometryChanged.emit(bounds)
        assert measurements
    finally:
        toolbar.dispose()


def test_all_23_actions_emit_the_existing_protocol_exactly_once(qt_application):
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar()
    toolbar.set_available(True)
    toolbar.show()
    qt_application.processEvents()
    keys, actions = [], []
    toolbar.key_requested.connect(keys.append)
    toolbar.action_requested.connect(actions.append)
    buttons = _buttons(toolbar)
    assert len(buttons) == 23
    assert {b.property("remoteKey") for b in buttons if b.property("remoteKey")} == EXPECTED_KEYS
    assert {
        b.property("remoteAction") for b in buttons if b.property("remoteAction")
    } == EXPECTED_ACTIONS
    _show_more(toolbar, qt_application)
    for button in buttons:
        assert button.isVisible()
        previous_count = len(keys) + len(actions)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert len(keys) + len(actions) == previous_count + 1
        assert toolbar.popup_window.isVisible()
    assert set(keys) == EXPECTED_KEYS and len(keys) == 15
    assert set(actions) == EXPECTED_ACTIONS and len(actions) == 8
    toolbar.dispose()


def test_unavailable_toolbar_rejects_actions_and_dismisses_popup(qt_application):
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar()
    toolbar.show()
    emitted = []
    toolbar.key_requested.connect(emitted.append)
    toolbar.action_requested.connect(emitted.append)
    assert all(not button.isEnabled() for button in _buttons(toolbar))
    toolbar.set_available(True)
    _show_more(toolbar, qt_application)
    toolbar.set_available(False)
    assert not toolbar.popup_window.isVisible()
    assert not _more_button(toolbar).isEnabled()
    for button in _buttons(toolbar):
        assert not button.isEnabled()
        button.click()
    assert emitted == []
    toolbar.dispose()


@pytest.mark.parametrize("operation", ["hide", "minimize", "dispose"])
def test_owner_visibility_and_dispose_close_the_owned_popup(qt_application, operation):
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar()
    toolbar.set_available(True)
    toolbar.show()
    _show_more(toolbar, qt_application)
    if operation == "hide":
        toolbar.hide()
    elif operation == "minimize":
        toolbar.showMinimized()
    else:
        toolbar.dispose()
        toolbar.dispose()
    qt_application.processEvents()
    assert not toolbar.popup_window.isVisible()
    assert not _more_button(toolbar).isChecked()
    if operation != "dispose":
        toolbar.showNormal()
        qt_application.processEvents()
        assert not toolbar.popup_window.isVisible()
    toolbar.dispose()


def test_collapsing_changes_width_and_dismisses_popup_without_dispatch(qt_application):
    from gui.styles.icon_loader import ResourceIcon
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar()
    toolbar.set_available(True)
    toolbar.show()
    _show_more(toolbar, qt_application)
    layouts, requests = [], []
    toolbar.layout_changed.connect(lambda: layouts.append(toolbar.width()))
    toolbar.key_requested.connect(requests.append)
    toolbar.action_requested.connect(requests.append)
    collapse = toolbar.findChild(QToolButton, "remoteToolbarCollapse")
    assert collapse is not None
    assert (collapse.iconSize().width(), collapse.iconSize().height()) == (20, 20)
    assert collapse.text() == ""
    assert collapse.icon().pixmap(20, 20).toImage() == (
        ResourceIcon("caret-double-up.svg").qicon().pixmap(20, 20).toImage()
    )
    collapse.click()
    qt_application.processEvents()
    assert toolbar.collapsed and toolbar.width() == 32
    assert not toolbar.popup_window.isVisible()
    assert collapse.icon().pixmap(20, 20).toImage() == (
        ResourceIcon("caret-double-down.svg").qicon().pixmap(20, 20).toImage()
    )
    collapse.click()
    qt_application.processEvents()
    assert not toolbar.collapsed and toolbar.width() == 56
    assert layouts == [32, 56] and requests == []
    toolbar.dispose()


def test_popup_keyboard_action_stays_open_and_escape_dismisses(qt_application):
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar()
    toolbar.set_available(True)
    toolbar.show()
    _show_more(toolbar, qt_application)
    QTest.keyClick(toolbar.popup_window, Qt.Key.Key_Escape)
    assert not toolbar.popup_window.isVisible()
    _show_more(toolbar, qt_application)
    button = next(b for b in _buttons(toolbar) if b.property("remoteAction") == "swipe_up")
    emitted = []
    toolbar.action_requested.connect(emitted.append)
    QTest.keyClick(button, Qt.Key.Key_Space)
    assert emitted == ["swipe_up"]
    assert toolbar.popup_window.isVisible()
    QTest.keyClick(button, Qt.Key.Key_Space)
    assert emitted == ["swipe_up", "swipe_up"]
    toolbar.dismiss_popup()
    assert not toolbar.popup_window.isVisible()
    toolbar.dispose()


def test_target_label_is_plain_text_and_buttons_keep_accessible_names(qt_application):
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar()
    toolbar.set_target_label("设备 A <b>演示</b>")
    toolbar.set_available(True)
    toolbar.show()
    _show_more(toolbar, qt_application)
    target = toolbar.popup_window.findChild(QLabel, "remoteToolbarTarget")
    assert target is not None
    assert target.text() == "设备 A <b>演示</b>"
    assert target.textFormat() == Qt.TextFormat.PlainText
    for button in _buttons(toolbar):
        assert button.accessibleName() and button.toolTip()
        assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert toolbar.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert not toolbar.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    toolbar.dispose()


@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("available_height", [330, 900])
def test_more_groups_keep_readable_rows_and_scroll_after_font_changes(
    qt_application, monkeypatch, font_size, available_height,
):
    from gui.styles import BaseStyles
    from gui.styles.fonts import FontMixin
    from gui.widgets.remote_toolbar import RemoteToolbar
    from tests.ui_geometry_helpers import wait_for_stable_geometry

    current_font_size = font_size
    monkeypatch.setattr(FontMixin, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Arial", size or current_font_size),
    ))
    bounds = QRect(0, 0, 1000, available_height)
    monkeypatch.setattr(RemoteToolbar, "screen", lambda _self: SimpleNamespace(
        availableGeometry=lambda: bounds,
    ))
    toolbar = RemoteToolbar()
    try:
        toolbar.set_available(True)
        toolbar.show()
        _show_more(toolbar, qt_application)
        popup = toolbar.popup_window
        scroll = popup.findChild(QScrollArea)
        assert scroll is not None
        content = scroll.widget()
        assert content is not None
        buttons = content.findChildren(QPushButton)
        assert len(buttons) == 17
        for next_font_size in (None, 22 if font_size == 12 else 12, font_size):
            if next_font_size is not None:
                current_font_size = next_font_size
                BaseStyles.fonts_changed.emit({})
            for button in buttons:
                assert button.height() >= button.fontMetrics().height() + 14, (
                    "first frame", button.objectName(), button.height(),
                    button.fontMetrics().height(),
                )
            wait_for_stable_geometry(qt_application, (popup, content, *buttons))
            assert popup.height() <= bounds.height()
            for button in buttons:
                assert button.font().pointSize() == current_font_size
                assert button.height() >= button.fontMetrics().height() + 14, (
                    button.objectName(), button.height(), button.fontMetrics().height(),
                )
            controls = [*buttons, *content.findChildren(QLabel)]
            rectangles = [QRect(widget.mapTo(content, QPoint()), widget.size())
                          for widget in controls]
            assert all(content.rect().contains(rectangle) for rectangle in rectangles)
            for index, rectangle in enumerate(rectangles):
                assert all(not rectangle.intersects(other)
                           for other in rectangles[index + 1:])
            if content.height() > scroll.viewport().height():
                assert scroll.verticalScrollBar().maximum() > 0
                scroll.ensureWidgetVisible(buttons[-1])
                qt_application.processEvents()
                last = QRect(buttons[-1].mapTo(scroll.viewport(), QPoint()), buttons[-1].size())
                assert scroll.viewport().rect().contains(last)
    finally:
        toolbar.dispose()


@pytest.mark.parametrize("code", sorted(
    (EXPECTED_KEYS - {"BACK", "HOME", "RECENTS", "VOL_UP", "VOL_DOWN", "POWER"})
    | EXPECTED_ACTIONS,
))
def test_more_mouse_click_stays_open_for_repeated_commands(qt_application, monkeypatch, code):
    from gui.widgets.remote_toolbar import RemoteToolbar

    monkeypatch.setattr(RemoteToolbar, "screen", lambda _self: SimpleNamespace(
        availableGeometry=lambda: QRect(0, 0, 1000, 330),
    ))
    toolbar = RemoteToolbar()
    try:
        toolbar.set_available(True)
        toolbar.show()
        qt_application.processEvents()
        QTest.mouseClick(_more_button(toolbar), Qt.MouseButton.LeftButton)
        qt_application.processEvents()
        popup = toolbar.popup_window
        assert popup.isVisible()
        button = next(button for button in _buttons(toolbar)
                      if (button.property("remoteKey") or button.property("remoteAction")) == code)
        scroll = popup.findChild(QScrollArea)
        assert scroll is not None
        scroll.ensureWidgetVisible(button)
        qt_application.processEvents()
        scroll_position = scroll.verticalScrollBar().value()
        pressed_visibility, requests = [], []
        button.pressed.connect(lambda: pressed_visibility.append(popup.isVisible()))
        toolbar.key_requested.connect(lambda value: requests.append(("key", value)))
        toolbar.action_requested.connect(lambda value: requests.append(("action", value)))

        expected = ("key" if code in EXPECTED_KEYS else "action", code)
        for count in (1, 2):
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            assert pressed_visibility == [True] * count
            assert requests == [expected] * count
            assert popup.isVisible(), "发送功能操作后保留面板，允许连续点击"
            assert scroll.verticalScrollBar().value() == scroll_position
    finally:
        toolbar.dispose()


def test_more_button_reflects_popup_visibility_with_icons_and_accessible_text(qt_application):
    from qfluentwidgets import FluentIcon

    from gui.i18n import tr
    from gui.styles.icon_loader import get_themed_icon
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar()
    try:
        toolbar.set_available(True)
        toolbar.show()
        qt_application.processEvents()
        more = _more_button(toolbar)

        def assert_state(opened):
            assert toolbar.popup_window.isVisible() is opened
            assert more.isChecked() is opened
            text = tr("关闭更多操作" if opened else "更多设备操作")
            assert more.toolTip() == more.accessibleName() == more.accessibleDescription() == text
            icon = get_themed_icon("x.svg") if opened else FluentIcon.MORE.qicon()
            assert more.icon().pixmap(20, 20).toImage() == icon.pixmap(20, 20).toImage()

        assert_state(False)
        QTest.mouseClick(more, Qt.MouseButton.LeftButton)
        assert_state(True)
        QTest.mouseClick(more, Qt.MouseButton.LeftButton)
        assert_state(False)
        QTest.mouseClick(more, Qt.MouseButton.LeftButton)
        assert_state(True)
        toolbar.dismiss_popup()
        assert_state(False)
    finally:
        toolbar.dispose()


@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.parametrize("code", ["MENU", "swipe_up"])
def test_command_receiver_can_synchronously_dispose_toolbar(qt_application, code, portable):
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar(portable=portable)
    toolbar.set_available(True)
    toolbar.show()
    _show_more(toolbar, qt_application)
    requests = []

    def dispose_on_request(value):
        requests.append(value)
        toolbar.dispose()

    toolbar.key_requested.connect(dispose_on_request)
    toolbar.action_requested.connect(dispose_on_request)
    button = next(button for button in _buttons(toolbar)
                  if (button.property("remoteKey") or button.property("remoteAction")) == code)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert requests == [code]
    assert not toolbar.isVisible()
    assert not toolbar.popup_window.isVisible()


def test_more_background_clicks_stay_open_and_external_click_still_dismisses(qt_application):
    from gui.widgets.remote_toolbar import RemoteToolbar

    outside = QPushButton("其他窗口")
    toolbar = RemoteToolbar()
    try:
        outside.show()
        toolbar.set_available(True)
        toolbar.show()
        _show_more(toolbar, qt_application)
        popup = toolbar.popup_window
        scroll = popup.findChild(QScrollArea)
        assert scroll is not None
        QTest.mouseClick(popup, Qt.MouseButton.LeftButton, pos=QPoint(6, 6))
        assert popup.isVisible()
        QTest.mouseClick(scroll.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        assert popup.isVisible()

        outside_clicks = []
        outside.clicked.connect(lambda: outside_clicks.append(True))
        QTest.mouseClick(outside, Qt.MouseButton.LeftButton)
        assert not popup.isVisible()
        assert outside_clicks == [True]

        _show_more(toolbar, qt_application)
        close_button = popup.findChild(QToolButton)
        assert close_button is not None
        QTest.mousePress(close_button, Qt.MouseButton.LeftButton)
        assert popup.isVisible()
        QTest.mouseRelease(close_button, Qt.MouseButton.LeftButton)
        assert not popup.isVisible()
    finally:
        toolbar.dispose()
        outside.close()


def _render_widget(widget):
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        widget.render(painter, QPoint())
    finally:
        painter.end()
    return image


def test_more_and_collapse_icons_remain_legible_across_theme_changes(qt_application):
    from gui.styles import BaseStyles
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar()
    try:
        toolbar.set_available(True)
        toolbar.show()
        collapse = toolbar.findChild(QToolButton, "remoteToolbarCollapse")
        assert collapse is not None
        for theme in ("Light", "Dark", "Light"):
            BaseStyles.switch_theme(theme)
            qt_application.processEvents()
            for button in (_more_button(toolbar), collapse):
                image = button.icon().pixmap(24, 24).toImage()
                colors = [image.pixelColor(x, y)
                          for x in range(image.width()) for y in range(image.height())
                          if image.pixelColor(x, y).alpha() >= 200]
                assert colors, button.objectName()
                brightness = sum(color.lightness() for color in colors) / len(colors)
                assert brightness > 200 if theme == "Dark" else brightness < 80, (
                    theme, button.objectName(), brightness,
                )
    finally:
        toolbar.dispose()


@pytest.mark.parametrize("code", ["BACK", "MENU", "MORE"])
def test_mouse_click_has_no_accent_outline_but_keyboard_focus_does(qt_application, code):
    from gui.styles import BaseStyles
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar()
    try:
        BaseStyles.switch_theme("Dark")
        toolbar.set_available(True)
        toolbar.show()
        if code == "MENU":
            _show_more(toolbar, qt_application)
            toolbar.popup_window.activateWindow()
        else:
            toolbar.activateWindow()
        qt_application.processEvents()
        button = _more_button(toolbar) if code == "MORE" else next(
            button for button in _buttons(toolbar) if button.property("remoteKey") == code
        )
        accent = QColor(BaseStyles.color("BORDER_FOCUS"))

        def outline():
            image = _render_widget(button)
            return image.pixelColor(image.width() // 2, 0)

        button.clearFocus()
        button.setFocus(Qt.FocusReason.MouseFocusReason)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert outline() != accent, "鼠标点击或展开状态不保留强调色边框"
        button.clearFocus()
        button.setFocus(Qt.FocusReason.TabFocusReason)
        assert button.hasFocus()
        assert outline() == accent, "键盘导航仍需清晰的焦点边框"
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert outline() != accent, "已获得键盘焦点的按钮再次鼠标点击后恢复普通反馈"
    finally:
        toolbar.dispose()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_floating_surfaces_have_four_transparent_corners_and_current_theme(qt_application, theme):
    from gui.styles import BaseStyles
    from gui.widgets.remote_toolbar import RemoteToolbar

    BaseStyles.switch_theme(theme)
    toolbar = RemoteToolbar()
    try:
        toolbar.set_available(True)
        toolbar.show()
        _show_more(toolbar, qt_application)
        for surface in (toolbar, toolbar.popup_window):
            image = _render_widget(surface)
            corners = ((0, 0), (image.width() - 1, 0),
                       (0, image.height() - 1), (image.width() - 1, image.height() - 1))
            assert [image.pixelColor(x, y).alpha() for x, y in corners] == [0, 0, 0, 0]
            assert image.pixelColor(image.width() // 2, 4) == QColor(BaseStyles.color("TOOLBAR_BG"))
    finally:
        toolbar.dispose()


def test_open_popup_updates_theme_accent_and_button_icons(qt_application):
    from gui.styles import BaseStyles
    from gui.widgets.remote_toolbar import RemoteToolbar

    original_accent = BaseStyles.accent_color()
    BaseStyles.switch_theme("Light")
    toolbar = RemoteToolbar()
    try:
        toolbar.set_available(True)
        toolbar.show()
        _show_more(toolbar, qt_application)
        button = next(button for button in _buttons(toolbar)
                      if button.property("remoteKey") == "BACK")
        light_icon = button.icon().pixmap(20, 20).toImage()
        close_button = toolbar.popup_window.findChild(QToolButton)
        assert close_button is not None
        light_close_icon = close_button.icon().pixmap(20, 20).toImage()
        light_disabled_icon = button.icon().pixmap(20, 20, QIcon.Mode.Disabled).toImage()
        BaseStyles.switch_theme("Dark")
        BaseStyles.set_accent_color("#D04080")
        qt_application.processEvents()
        assert toolbar.popup_window.isVisible()
        for surface in (toolbar, toolbar.popup_window):
            image = _render_widget(surface)
            assert image.pixelColor(image.width() // 2, 4) == QColor(BaseStyles.color("TOOLBAR_BG"))
        more = _render_widget(_more_button(toolbar))
        assert more.pixelColor(more.width() // 2, 0) != QColor(BaseStyles.color("BORDER_FOCUS"))
        indicator = toolbar.findChild(QLabel, "remoteToolbarIndicator")
        assert indicator is not None
        indicator_image = _render_widget(indicator)
        accent = QColor(BaseStyles.color("BORDER_FOCUS"))
        assert indicator.palette().color(QPalette.ColorRole.WindowText) == accent
        # 抗锯齿字形不保证存在完全不透明像素，但实际绘制的前景 RGB 必须跟随强调色。
        assert any(indicator_image.pixelColor(x, y).alpha() > 0
                   and indicator_image.pixelColor(x, y).getRgb()[:3] == accent.getRgb()[:3]
                   for x in range(indicator_image.width())
                   for y in range(indicator_image.height()))
        dark_icon = button.icon().pixmap(20, 20).toImage()
        assert dark_icon != light_icon
        assert close_button.icon().pixmap(20, 20).toImage() != light_close_icon
        disabled_icon = button.icon().pixmap(20, 20, QIcon.Mode.Disabled).toImage()
        assert disabled_icon != light_disabled_icon
        def alpha_sum(image):
            return sum(image.pixelColor(x, y).alpha()
                       for x in range(image.width()) for y in range(image.height()))

        assert 0 < alpha_sum(disabled_icon) < alpha_sum(dark_icon)
    finally:
        toolbar.dispose()
        BaseStyles.set_accent_color(original_accent)


@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_more_selection_tracks_accent_while_command_press_uses_theme_feedback(
    qt_application, theme, portable,
):
    from gui.styles import BaseStyles
    from gui.widgets.remote_toolbar import RemoteToolbar

    original_accent = BaseStyles.accent_color()
    BaseStyles.switch_theme(theme)
    toolbar = RemoteToolbar(portable=portable)
    try:
        toolbar.set_available(True)
        toolbar.show()
        _show_more(toolbar, qt_application)
        more = _more_button(toolbar)
        back = next(button for button in _buttons(toolbar)
                    if button.property("remoteKey") == "BACK")

        def background(button):
            position = button.mapTo(toolbar, QPoint(5, button.height() // 2))
            return _render_widget(toolbar).pixelColor(position)

        samples = []
        for accent in ("#D04080", "#087F5B"):
            BaseStyles.set_accent_color(accent)
            qt_application.processEvents()
            selected = background(more)
            samples.append(selected)
            assert toolbar.popup_window.isVisible() and more.isChecked()
            assert selected != QColor(BaseStyles.color("TOOLBAR_BG"))
            assert selected != QColor(BaseStyles.color("SELECTION_BG")), (
                "自定义强调色不能继续显示固定蓝色选中背景", theme, accent, selected.name(),
            )
            if accent == "#D04080":
                assert selected.red() > selected.green()
            else:
                assert selected.green() > selected.red()

            QTest.mousePress(back, Qt.MouseButton.LeftButton)
            assert background(back) == QColor(
                BaseStyles.color("BUTTON_PRESSED"),
            )
            QTest.mouseRelease(back, Qt.MouseButton.LeftButton)
            assert toolbar.popup_window.isVisible()
        assert samples[0] != samples[1]
        toolbar.set_available(False)
        assert not toolbar.popup_window.isVisible() and not more.isChecked()
        assert background(more) == QColor(
            BaseStyles.color("TOOLBAR_BG"),
        )
    finally:
        toolbar.dispose()
        BaseStyles.set_accent_color(original_accent)


@pytest.mark.parametrize("portable", [False, True])
def test_more_scrollbar_tracks_theme_and_remains_usable(qt_application, monkeypatch, portable):
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider

    from gui.styles import BaseStyles
    from gui.widgets.remote_toolbar import RemoteToolbar

    monkeypatch.setattr(RemoteToolbar, "screen", lambda _self: SimpleNamespace(
        availableGeometry=lambda: QRect(0, 0, 1000, 330),
    ))
    toolbar = RemoteToolbar(portable=portable)
    try:
        toolbar.set_available(True)
        toolbar.show()
        _show_more(toolbar, qt_application)
        popup = toolbar.popup_window
        scroll = popup.findChild(QScrollArea)
        assert scroll is not None
        scrollbar = scroll.verticalScrollBar()

        def subcontrol(control):
            option = QStyleOptionSlider()
            option.initFrom(scrollbar)
            option.orientation = Qt.Orientation.Vertical
            option.minimum = scrollbar.minimum()
            option.maximum = scrollbar.maximum()
            option.sliderPosition = scrollbar.sliderPosition()
            option.sliderValue = scrollbar.value()
            option.pageStep = scrollbar.pageStep()
            option.singleStep = scrollbar.singleStep()
            return scrollbar.style().subControlRect(
                QStyle.ComplexControl.CC_ScrollBar, option, control, scrollbar,
            )

        for theme in ("Dark", "Light", "Dark"):
            BaseStyles.switch_theme(theme)
            QTest.mouseMove(popup, QPoint(6, 6))
            qt_application.processEvents()
            assert scrollbar.isVisible() and scrollbar.maximum() > 0
            thumb = subcontrol(QStyle.SubControl.SC_ScrollBarSlider)
            track = subcontrol(QStyle.SubControl.SC_ScrollBarAddPage)
            assert not thumb.isEmpty() and not track.isEmpty()
            image = _render_widget(scrollbar)
            assert image.pixelColor(thumb.center()) == QColor(BaseStyles.color("SCROLLBAR_HANDLE"))
            assert image.pixelColor(track.center()) == QColor(BaseStyles.color("SCROLLBAR_BG"))
            QTest.mouseMove(scrollbar, thumb.center())
            qt_application.processEvents()
            assert _render_widget(scrollbar).pixelColor(thumb.center()) == QColor(
                BaseStyles.color("SCROLLBAR_HANDLE_HOVER"),
            )

        QTest.keyClick(scrollbar, Qt.Key.Key_End)
        qt_application.processEvents()
        assert scrollbar.value() == scrollbar.maximum()
        last = next(button for button in _buttons(toolbar)
                    if button.property("remoteKey") == "MEDIA_NEXT")
        last_rect = QRect(last.mapTo(scroll.viewport(), QPoint()), last.size())
        assert scroll.viewport().rect().contains(last_rect)
        requests = []
        toolbar.key_requested.connect(requests.append)
        QTest.mouseClick(last, Qt.MouseButton.LeftButton)
        assert requests == ["MEDIA_NEXT"]
        assert popup.isVisible()
    finally:
        toolbar.dispose()
