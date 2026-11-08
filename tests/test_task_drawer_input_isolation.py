"""以真实宿主合成与命中验证任务侧栏，不创建原生主窗口或执行设备命令。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QAbstractAnimation, QAbstractEventDispatcher, QPoint, Qt
from PySide6.QtGui import QAccessible, QAccessibleActionInterface, QColor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from core.settings_manager import AppSettings
from gui.styles import BaseStyles
from gui.widgets.task_detail_drawer import TaskDetailDrawer
from gui.widgets.task_table import TaskRowData
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def _row(key="action:first", **changes):
    return replace(
        TaskRowData(key, "查询设备", "设备", "测试手机", "运行中", "accent", "刚刚", "本次",
                    cancellable=True),
        **changes,
    )


@pytest.fixture(params=[("Light", 12), ("Light", 22), ("Dark", 12), ("Dark", 22)],
                ids=["light-12", "light-22", "dark-12", "dark-22"])
def overlay(qt_application, monkeypatch, request):
    theme, size = request.param
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: {
        "font_family": "", "ui_font_size": size, "log_font_size": 11,
    }))
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    host = QWidget()
    host.setGeometry(0, 0, 700, 620)
    under = QPushButton("底层业务按钮", host)
    under.setGeometry(310, 0, 390, 620)
    under.setStyleSheet("background: #ff00ff; color: #000000;")
    outside = QPushButton("外侧业务按钮", host)
    outside.setGeometry(20, 520, 140, 80)
    panel = TaskDetailDrawer(host)
    panel.present(_row(), source_available=True, recent=(_row(), _row("action:other")))
    host.show()
    qt_application.processEvents()
    assert panel.close_button.font().pointSizeF() == size
    state = SimpleNamespace(host=host, panel=panel, under=under, outside=outside,
                            under_clicks=QSignalSpy(under.clicked),
                            outside_clicks=QSignalSpy(outside.clicked))
    yield state
    panel.shutdown()
    host.close()


def _closing_quarter(panel):
    panel.close_drawer()
    assert panel.animation.state() == QAbstractAnimation.State.Running
    panel.animation.pause()
    panel.animation.setCurrentTime(panel.animation.duration() // 4)
    assert panel.isVisible() and not panel.opened


def _click_at(host, point):
    """先按实际叠放命中，再向命中的对象投递，不绕过被测的遮挡边界。"""
    global_point = host.mapToGlobal(point)
    target = QApplication.widgetAt(global_point)
    assert target is not None
    assert target is host.childAt(point)
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFromGlobal(global_point))
    return target


@pytest.mark.parametrize("phase", ["open", "closing", "reverse", "resize"])
def test_host_composite_hides_underlying_controls_across_surfaces(overlay, qt_application, phase):
    host, panel = overlay.host, overlay.panel
    panel.open_drawer(animated=False)
    if phase in ("closing", "reverse"):
        _closing_quarter(panel)
        if phase == "reverse":
            panel.open_drawer()
            panel.animation.setCurrentTime(panel.animation.duration())
    elif phase == "resize":
        host.resize(300, 460)
        overlay.under.setGeometry(host.rect())
        qt_application.processEvents()
    image = host.grab().toImage()
    dpr = image.devicePixelRatio()
    # 正文左侧阅读留白避开文字与右侧真实滚动条，分别检查三块实际底板。
    body_y = panel.scroll_area.mapTo(host, panel.scroll_area.rect().center()).y()
    for y in (4, body_y, host.height() - 4):
        color = image.pixelColor(round((panel.x() + 8) * dpr), round(y * dpr))
        assert color == QColor(BaseStyles.color("CONTENT_BG")), (phase, y, color.name())


def test_visible_closing_pane_blocks_only_covered_area_then_restores_underlying(overlay):
    host, panel = overlay.host, overlay.panel
    panel.open_drawer(animated=False)
    covered = QPoint(host.width() - 20, host.height() - 20)
    outside = QPoint(70, 560)
    target = _click_at(host, covered)
    assert panel.isAncestorOf(target) or target is panel
    assert overlay.under_clicks.count() == 0
    _click_at(host, outside)
    assert overlay.outside_clicks.count() == 1
    _closing_quarter(panel)
    target = _click_at(host, covered)
    assert panel.isAncestorOf(target) or target is panel
    assert overlay.under_clicks.count() == 0
    assert panel.isEnabled() and panel.cancel_button.isEnabled()
    assert panel.cancel_button.focusPolicy() == Qt.FocusPolicy.NoFocus
    _click_at(host, outside)
    assert overlay.outside_clicks.count() == 2
    panel.animation.setCurrentTime(panel.animation.duration())
    assert panel.isHidden()
    assert _click_at(host, covered) is overlay.under
    assert overlay.under_clicks.count() == 1


def _activate(button, method):
    if method == "click":
        button.click()
    else:
        interface = QAccessible.queryAccessibleInterface(button)
        assert interface is not None
        actions = interface.actionInterface()
        assert actions is not None
        assert QAccessibleActionInterface.pressAction() in actions.actionNames()
        actions.doAction(QAccessibleActionInterface.pressAction())
        # Qt pressAction 通过 animateClick 延迟约 100ms 发 clicked；必须排空该真实时序。
        QTest.qWait(160)


def _start_accessible_press(button):
    interface = QAccessible.queryAccessibleInterface(button)
    assert interface is not None
    actions = interface.actionInterface()
    assert actions is not None
    actions.doAction(QAccessibleActionInterface.pressAction())


@pytest.mark.parametrize("method", ["click", "accessible"])
@pytest.mark.parametrize("action", ["cancel", "stop"])
def test_drawer_dispatch_requires_open_presentation_even_for_accessibility(overlay, method, action):
    panel = overlay.panel
    panel.present(_row(stop_action=action == "stop", stop_revision="revision-1"),
                  source_available=True, from_task_center=action == "source",
                  recent=(_row(), _row("action:other")))
    button, signal, payload = {
        "cancel": (panel.cancel_button, panel.cancel_requested, ["action:first"]),
        "stop": (panel.cancel_button, panel.stop_requested, ["action:first", "revision-1"]),
    }[action]
    spy = QSignalSpy(signal)
    panel.open_drawer(animated=False)
    _activate(button, method)
    assert spy.count() == 1
    assert spy.at(0) == payload
    _closing_quarter(panel)
    for phase in ("closing", "hidden", "shutdown"):
        if phase == "hidden":
            panel.animation.setCurrentTime(panel.animation.duration())
            assert panel.isHidden()
        elif phase == "shutdown":
            panel.shutdown()
        _activate(button, method)
        assert spy.count() == 1, phase


def test_accessible_press_started_open_cannot_dispatch_after_close(overlay):
    panel = overlay.panel
    panel.open_drawer(animated=False)
    spy = QSignalSpy(panel.cancel_requested)
    interface = QAccessible.queryAccessibleInterface(panel.cancel_button)
    assert interface is not None
    actions = interface.actionInterface()
    assert actions is not None
    actions.doAction(QAccessibleActionInterface.pressAction())
    _closing_quarter(panel)
    QTest.qWait(160)
    assert spy.count() == 0


@pytest.mark.parametrize("start_open", [False, True])
def test_accessible_stop_cannot_cross_close_and_reverse_open(overlay, start_open):
    panel = overlay.panel
    panel.present(_row(stop_action=True, stop_revision="first-revision"))
    panel.open_drawer(animated=False)
    spy = QSignalSpy(panel.stop_requested)
    if start_open:
        _start_accessible_press(panel.cancel_button)
        _closing_quarter(panel)
    else:
        _closing_quarter(panel)
        _start_accessible_press(panel.cancel_button)
    panel.open_drawer(animated=False)
    QTest.qWait(160)
    assert spy.count() == 0
    panel.cancel_button.click()
    assert spy.count() == 1
    assert spy.at(0) == ["action:first", "first-revision"]


@pytest.mark.parametrize("release_before_open", [False, True])
def test_close_discards_old_stop_gesture_before_fresh_click_on_other_task(
    overlay, release_before_open,
):
    panel = overlay.panel
    panel.present(_row(stop_action=True, stop_revision="1"))
    panel.open_drawer(animated=False)
    spy = QSignalSpy(panel.stop_requested)
    QTest.mousePress(panel.cancel_button, Qt.MouseButton.LeftButton)
    _closing_quarter(panel)
    if release_before_open:
        QTest.mouseRelease(panel.cancel_button, Qt.MouseButton.LeftButton)
    panel.present(_row("action:second", stop_action=True, stop_revision="2"))
    panel.open_drawer(animated=False)
    if not release_before_open:
        QTest.mouseRelease(panel.cancel_button, Qt.MouseButton.LeftButton)
    assert spy.count() == 0
    panel.cancel_button.click()
    assert spy.count() == 1
    assert spy.at(0) == ["action:second", "2"]


def test_valid_stop_gesture_keeps_original_identity_without_presentation_revocation(overlay):
    panel = overlay.panel
    panel.present(_row(stop_action=True, stop_revision="1"))
    panel.open_drawer(animated=False)
    spy = QSignalSpy(panel.stop_requested)
    QTest.mousePress(panel.cancel_button, Qt.MouseButton.LeftButton)
    panel.present(_row("action:second", stop_action=True, stop_revision="2"))
    QTest.mouseRelease(panel.cancel_button, Qt.MouseButton.LeftButton)
    assert spy.count() == 1
    assert spy.at(0) == ["action:first", "1"]


def test_old_accessible_timer_cannot_finish_new_physical_stop_before_release(overlay):
    panel = overlay.panel
    panel.present(_row(stop_action=True, stop_revision="1"))
    panel.open_drawer(animated=False)
    spy = QSignalSpy(panel.stop_requested)
    _start_accessible_press(panel.cancel_button)
    _closing_quarter(panel)
    panel.present(_row("action:second", stop_action=True, stop_revision="2"))
    panel.open_drawer(animated=False)
    QTest.mousePress(panel.cancel_button, Qt.MouseButton.LeftButton)
    QTest.qWait(160)
    assert spy.count() == 0
    QTest.mouseRelease(panel.cancel_button, Qt.MouseButton.LeftButton)
    assert spy.count() == 1
    assert spy.at(0) == ["action:second", "2"]


@pytest.mark.parametrize("start_open", [False, True])
@pytest.mark.parametrize("same_identity", [False, True])
def test_new_accessible_stop_after_reopen_is_not_swallowed_by_revoked_native_timer(
    overlay, start_open, same_identity,
):
    panel = overlay.panel
    panel.present(_row(stop_action=True, stop_revision="1"))
    panel.open_drawer(animated=False)
    spy = QSignalSpy(panel.stop_requested)
    if not start_open:
        _closing_quarter(panel)
    _start_accessible_press(panel.cancel_button)
    if start_open:
        _closing_quarter(panel)
    if not same_identity:
        panel.present(_row("action:second", stop_action=True, stop_revision="2"))
    panel.open_drawer(animated=False)
    _start_accessible_press(panel.cancel_button)
    QTest.qWait(170)
    assert spy.count() == 1
    assert spy.at(0) == (["action:first", "1"] if same_identity else ["action:second", "2"])


def test_native_cancel_keeps_toggle_state_and_unrelated_button_timer(overlay):
    panel = overlay.panel
    panel.open_drawer(animated=False)
    button = panel.cancel_button
    # 用当前可见动作复现可勾选按钮的原生定时器，验证撤销不会改变 checked。
    button.setCheckable(True)
    button.setChecked(True)
    assert button.isChecked()
    clicked = QSignalSpy(button.clicked)
    toggled = QSignalSpy(button.toggled)
    dispatcher = QAbstractEventDispatcher.instance(button.thread())
    assert dispatcher is not None
    custom_timer = button.startTimer(60000)
    try:
        _start_accessible_press(button)
        _closing_quarter(panel)
        assert button.isChecked()
        assert clicked.count() == 0
        assert toggled.count() == 0
        assert custom_timer in {timer.timerId for timer in dispatcher.registeredTimers(button)}
    finally:
        button.killTimer(custom_timer)


@pytest.mark.parametrize("boundary", ["hide", "minimize"])
def test_new_accessible_stop_after_host_resume_has_fresh_native_press(
    overlay, qt_application, boundary,
):
    host, panel = overlay.host, overlay.panel
    cocoa = QApplication.platformName() == "cocoa"
    panel.present(_row(stop_action=True, stop_revision="1"))
    panel.open_drawer(animated=False)
    spy = QSignalSpy(panel.stop_requested)
    if boundary == "hide":
        host.hide()
    else:
        host.showMinimized()
        # Cocoa 的 Qt 状态先于原生最小化完成；过早反向恢复会收到晚到最小化事件。
        wait_until(qt_application, lambda: host.isMinimized() and (
            not cocoa or host.windowHandle() is not None and not host.windowHandle().isExposed()
        ))
    assert panel.opened
    assert not panel.accepts_user_actions()
    _start_accessible_press(panel.cancel_button)
    if boundary == "hide":
        host.show()
    else:
        host.showNormal()
    # offscreen 不模拟原生曝光，仅 Cocoa 额外等待真实窗口映射完成。
    wait_until(qt_application, lambda: (
        host.isVisible() and not host.isMinimized() and panel.isVisible()
        and (not cocoa or host.windowHandle() is not None and host.windowHandle().isExposed())
    ))
    qt_application.processEvents()
    assert panel.opened
    assert panel.accepts_user_actions()
    _start_accessible_press(panel.cancel_button)
    QTest.qWait(170)
    assert spy.count() == 1
    assert spy.at(0) == ["action:first", "1"]
