"""无外部窗口定位能力的平台仍提供同一会话的完整操作和安全清理。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QScrollArea, QToolButton

from tests.test_remote_toolbar import EXPECTED_ACTIONS, EXPECTED_KEYS, _more_button, _show_more

pytestmark = pytest.mark.ui


def test_portable_more_uses_one_window_and_keeps_all_commands(qt_application, monkeypatch):
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar(portable=True)
    try:
        monkeypatch.setattr(toolbar.popup_window, "move", lambda *_args: pytest.fail(
            "嵌入更多操作不能依赖 Wayland 不支持的全局窗口定位",
        ))
        toolbar.set_available(True)
        toolbar.show()
        qt_application.processEvents()
        assert not toolbar.popup_window.isVisible()
        narrow_width = toolbar.width()
        _show_more(toolbar, qt_application)
        assert toolbar.popup_window.window() is toolbar
        assert toolbar.width() > narrow_width
        keys, actions = [], []
        toolbar.key_requested.connect(keys.append)
        toolbar.action_requested.connect(actions.append)
        buttons = [button for button in toolbar.findChildren(QAbstractButton)
                   if button.property("remoteKey") or button.property("remoteAction")]
        assert len(buttons) == 23
        for button in buttons:
            assert button.window() is toolbar
            scroll = toolbar.popup_window.findChild(QScrollArea)
            if button.property("remoteKey") not in {
                "BACK", "HOME", "RECENTS", "VOL_UP", "VOL_DOWN", "POWER",
            }:
                scroll.ensureWidgetVisible(button)
                qt_application.processEvents()
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            assert toolbar.popup_window.isVisible()
        assert set(keys) == EXPECTED_KEYS and len(keys) == 15
        assert set(actions) == EXPECTED_ACTIONS and len(actions) == 8
        toolbar.dismiss_popup()
        qt_application.processEvents()
        assert toolbar.width() == narrow_width
    finally:
        toolbar.dispose()


def test_portable_drag_handle_requests_system_move_and_keeps_friendly_target(
    qt_application, monkeypatch,
):
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar(portable=True)
    try:
        toolbar.set_target_label("演示设备 <b>A</b>")
        toolbar.set_available(True)
        toolbar.show()
        qt_application.processEvents()
        handle = toolbar.findChild(QLabel, "remoteToolbarIndicator")
        assert handle is not None
        assert "演示设备 <b>A</b>" in handle.toolTip()
        native_window = toolbar.windowHandle()
        calls = []
        with monkeypatch.context() as native_patch:
            native_patch.setattr(
                native_window, "startSystemMove", lambda: calls.append(True) or True,
            )
            QTest.mouseClick(handle, Qt.MouseButton.LeftButton)
            assert calls == [True]
            QTest.mouseClick(handle, Qt.MouseButton.RightButton)
            _more_button(toolbar).click()
            assert calls == [True]
            toolbar.findChild(QToolButton, "remoteToolbarCollapse").click()
            assert toolbar.collapsed and handle.isVisible()
            QTest.mouseClick(handle, Qt.MouseButton.LeftButton)
            assert calls == [True, True]
    finally:
        toolbar.dispose()


def test_portable_escape_close_and_collapse_leave_recoverable_controls(qt_application):
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar(portable=True)
    try:
        toolbar.set_available(True)
        toolbar.show()
        qt_application.processEvents()
        assert toolbar.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        assert not toolbar.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
        _show_more(toolbar, qt_application)
        button = toolbar.findChild(QAbstractButton, "remoteToolbarCommand_MENU")
        assert QTest.qWaitForWindowExposed(toolbar)
        # 模拟用户已点击浮窗、合成器已授予焦点的前提；Wayland 不接受主动激活请求。
        QApplication.setActiveWindow(toolbar)
        button.setFocus(Qt.FocusReason.TabFocusReason)
        qt_application.processEvents()
        assert button.hasFocus()
        QTest.keyClick(button, Qt.Key.Key_Escape)
        assert not toolbar.popup_window.isVisible()
        _show_more(toolbar, qt_application)
        toolbar.close()
        qt_application.processEvents()
        assert toolbar.isVisible() and toolbar.collapsed
        assert not toolbar.popup_window.isVisible()
        collapse = toolbar.findChild(QToolButton, "remoteToolbarCollapse")
        QTest.mouseClick(collapse, Qt.MouseButton.LeftButton)
        assert not toolbar.collapsed
        assert _more_button(toolbar).isVisible()
    finally:
        toolbar.dispose()


@pytest.mark.parametrize("operation", ["hide", "showMinimized", "unavailable", "dispose"])
def test_portable_withdrawal_closes_more_and_removes_application_filter(qt_application, operation):
    from gui.widgets.remote_toolbar import RemoteToolbar

    toolbar = RemoteToolbar(portable=True)
    try:
        toolbar.set_available(True)
        toolbar.show()
        _show_more(toolbar, qt_application)
        if operation == "unavailable":
            toolbar.set_available(False)
        else:
            getattr(toolbar, operation)()
        qt_application.processEvents()
        assert not toolbar.popup_window.isVisible()
        assert not _more_button(toolbar).isChecked()
        assert not toolbar._watching_application
        if operation == "dispose":
            assert not toolbar.isVisible()
        toolbar.dispose()
        toolbar.dispose()
        assert not toolbar.isVisible()
    finally:
        toolbar.dispose()


@pytest.mark.parametrize("font_size", [12, 22])
def test_portable_more_keeps_readable_scrollable_rows_during_theme_changes(
    qt_application, monkeypatch, font_size,
):
    from gui.styles import BaseStyles
    from gui.styles.fonts import FontMixin
    from gui.widgets.remote_toolbar import RemoteToolbar
    from tests.ui_geometry_helpers import wait_for_stable_geometry

    monkeypatch.setattr(FontMixin, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Arial", size or font_size),
    ))
    monkeypatch.setattr(RemoteToolbar, "screen", lambda _self: SimpleNamespace(
        availableGeometry=lambda: QRect(0, 0, 1000, 600),
    ))
    toolbar = RemoteToolbar(portable=True)
    try:
        toolbar.set_available(True)
        toolbar.show()
        _show_more(toolbar, qt_application)
        popup = toolbar.popup_window
        scroll = popup.findChild(QScrollArea)
        for theme in ("Dark", "Light"):
            BaseStyles.switch_theme(theme)
            wait_for_stable_geometry(qt_application, (toolbar, popup, scroll.widget()))
            assert toolbar.height() <= 600
            assert popup.isVisible() and popup.window() is toolbar
            buttons = popup.findChildren(QAbstractButton)
            for button in buttons:
                if button.property("remoteKey") or button.property("remoteAction"):
                    assert button.height() >= button.fontMetrics().height() + 12
            last = popup.findChild(QAbstractButton, "remoteToolbarCommand_MEDIA_NEXT")
            scroll.ensureWidgetVisible(last)
            qt_application.processEvents()
            rect = QRect(last.mapTo(scroll.viewport(), QPoint()), last.size())
            assert scroll.viewport().rect().contains(rect)
            assert _more_button(toolbar).isChecked()
    finally:
        toolbar.dispose()
