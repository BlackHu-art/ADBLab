"""验证电源短按与长按互斥，失去操作条件后不会迟到发送。"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton
from shiboken6 import isValid

from gui.widgets.remote_toolbar import RemoteToolbar
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture(params=[False, True], ids=["native", "portable"])
def power_toolbar(qt_application, request):
    toolbar = RemoteToolbar(portable=request.param)
    toolbar.set_available(True)
    toolbar.show()
    qt_application.processEvents()
    keys, actions = [], []
    toolbar.key_requested.connect(keys.append)
    toolbar.action_requested.connect(actions.append)
    button = toolbar.findChild(QAbstractButton, "remoteToolbarCommand_POWER")
    yield toolbar, button, keys, actions
    if isValid(toolbar):
        toolbar.dispose()
        toolbar.deleteLater()


@pytest.mark.parametrize("input_kind", ["mouse", "keyboard"])
def test_power_hold_sends_once_and_release_does_not_toggle_screen(
    qt_application, power_toolbar, input_kind,
):
    toolbar, button, keys, actions = power_toolbar
    press = QTest.mousePress if input_kind == "mouse" else QTest.keyPress
    release = QTest.mouseRelease if input_kind == "mouse" else QTest.keyRelease
    key = Qt.MouseButton.LeftButton if input_kind == "mouse" else Qt.Key.Key_Space
    press(button, key)
    QTest.qWait(100)
    assert keys == actions == [], "短按应在松开时发送，长按不能提前触发"
    if input_kind == "keyboard":
        for event_type in (QEvent.Type.KeyRelease, QEvent.Type.KeyPress):
            QCoreApplication.sendEvent(button, QKeyEvent(
                event_type, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ", True,
            ))
    wait_until(qt_application, lambda: actions == ["power_long_press"], timeout_ms=1500)
    QTest.qWait(650)
    assert actions == ["power_long_press"] and keys == []
    release(button, key)
    assert actions == ["power_long_press"] and keys == []
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert keys == ["POWER"], "下一次独立短按必须恢复"
    assert toolbar.isVisible()


@pytest.mark.parametrize("interruption", [
    "leave", "move_out_and_back", "disable", "hide", "collapse", "focus", "dispose",
])
def test_power_hold_is_cancelled_when_button_is_no_longer_available(power_toolbar, interruption):
    toolbar, button, keys, actions = power_toolbar
    QTest.mousePress(button, Qt.MouseButton.LeftButton)
    if interruption == "leave":
        QCoreApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
    elif interruption == "move_out_and_back":
        QTest.mouseMove(button, QPoint(-10, -10))
        QTest.mouseMove(button, button.rect().center())
    elif interruption == "disable":
        toolbar.set_available(False)
        toolbar.set_available(True)
    elif interruption == "hide":
        toolbar.hide()
        toolbar.show()
    elif interruption == "collapse":
        toolbar._collapse_button.click()
    elif interruption == "focus":
        QCoreApplication.sendEvent(button, QFocusEvent(QEvent.Type.FocusOut))
    else:
        toolbar.dispose()
    QTest.qWait(750)
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    assert keys == actions == []
    assert all(not timer.isActive() for timer in button.findChildren(QTimer))


def test_long_power_receiver_can_destroy_toolbar_synchronously(qt_application, power_toolbar):
    from shiboken6 import delete

    toolbar, button, keys, actions = power_toolbar
    toolbar.action_requested.connect(lambda _action: delete(toolbar))
    QTest.mousePress(button, Qt.MouseButton.LeftButton)
    wait_until(qt_application, lambda: not isValid(toolbar), timeout_ms=1500)
    assert actions == ["power_long_press"] and keys == []
