"""真实主窗口中的连接区过渡、滚动和配对生命周期契约。"""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, QObject, QPoint
from PySide6.QtTest import QTest

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from gui.widgets.responsive_primitives import ReflowReason
from tests.test_device_connection import qr_png
from tests.test_global_device_context import frame  # noqa: F401
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def connection_frame(request, qt_application):
    window = request.getfixturevalue("frame")
    window.resize(1120, 900)
    window.show()
    window._on_nav_requested("devices")
    window._on_devices_updated(["demo-a"])
    coordinator = window.left_panel._responsive_coordinator
    wait_until(qt_application, lambda: (
        window._page_transition.animation.state() == QAbstractAnimation.State.Stopped
        and coordinator.diagnostics.stable
    ))
    QTest.qWait(30)
    return window


def _open_paused(window):
    window._device_hub.connect_button.click()
    panel = window._connection_panel
    assert panel is not None and panel.is_expanded
    animation = panel._reveal_animation
    assert animation.state() == QAbstractAnimation.State.Running
    animation.pause()
    return panel, animation


def _advance(animation, fraction):
    animation.pause()
    animation.setCurrentTime(round(animation.duration() * fraction))
    # 不主动激活布局，真实绘制必须自行获得一致几何。
    QTest.qWait(35)


def _wait_finished(window, qt_application):
    panel = window._connection_panel
    wait_until(qt_application, lambda: (
        panel._reveal_animation.state() == QAbstractAnimation.State.Stopped
        and window.left_panel._responsive_coordinator.diagnostics.stable
    ))
    QTest.qWait(20)


def _rect_in(widget, ancestor):
    position = widget.mapTo(ancestor, QPoint())
    return position.x(), position.y(), widget.width(), widget.height()


class _PaintPositions(QObject):
    def __init__(self, ancestor, widgets):
        super().__init__(ancestor)
        self.ancestor = ancestor
        self.positions = {widget: [] for widget in widgets}
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.positions[watched].append(_rect_in(watched, self.ancestor))
        return False


def test_connection_frames_move_cards_without_extra_gap_or_workspace_planning(
    connection_frame, qt_application, monkeypatch,
):
    window = connection_frame
    hub = window._device_hub
    coordinator = window.left_panel._responsive_coordinator
    collect = Mock(wraps=coordinator._collect_candidates)
    monkeypatch.setattr(coordinator, "_collect_candidates", collect)
    collapsed_y = hub.cards_container.y()

    panel, animation = _open_paused(window)
    # 首次显示后的状态投影允许重定自然高度；首帧不占位应在事件循环前检查。
    assert panel.height() == 0
    assert hub.cards_container.y() == collapsed_y, "首帧不能额外跳出 14px 布局间距"
    opening = [collapsed_y]
    for fraction in (.2, .5, .8):
        _advance(animation, fraction)
        opening.append(hub.cards_container.y())
        assert opening[-1] - collapsed_y == panel.height()
    assert opening == sorted(set(opening)), opening
    collect.assert_not_called()
    assert not coordinator.diagnostics.stable

    # 局部高度不一定产生顶层 LayoutRequest；真实新请求仍应延后到终点处理。
    coordinator.request_reflow(ReflowReason.EXPLICIT)
    collect.assert_not_called()
    _advance(animation, 1)
    _wait_finished(window, qt_application)
    assert collect.call_count > 0
    collect.reset_mock()
    closing = [hub.cards_container.y()]
    hub.connect_button.click()
    animation.pause()
    for fraction in (.2, .5, .8):
        _advance(animation, fraction)
        closing.append(hub.cards_container.y())
        assert closing[-1] - collapsed_y == panel.height()
    assert closing == sorted(set(closing), reverse=True), closing
    collect.assert_not_called()
    _advance(animation, 1)
    _wait_finished(window, qt_application)
    assert panel.isHidden() and hub.cards_container.y() == collapsed_y


@pytest.mark.parametrize("font_size,width", [(12, 1120), (22, 860)])
def test_connection_text_stays_fixed_in_actual_paints_while_cards_slide(
    connection_frame, qt_application, font_size, width,
):
    window = connection_frame
    hub = window._device_hub
    # 必须在主窗口已显示、导航稳定后改变真实字体和宽度，覆盖工具栏转为纵排。
    window.resize(width, 900)
    config = replace(BaseStyles.current_font_config(), ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    wait_until(qt_application, lambda: window.left_panel._responsive_coordinator.diagnostics.stable)
    QTest.qWait(30)
    assert window.width() == width
    assert hub.summary.font().pointSize() == font_size
    chrome = (hub.toolbar, hub.summary)
    chrome_expected = {widget: _rect_in(widget, hub) for widget in chrome}
    chrome_positions = {widget: [] for widget in chrome}
    hub.connect_button.click()
    panel = window._connection_panel
    assert panel._reveal_animation.state() == QAbstractAnimation.State.Running
    labels = [panel.qr_text_layout.itemAt(index).widget() for index in (0, 1)]
    card = hub.device_cards[0]
    observer = _PaintPositions(hub, [*labels, card])

    def record_chrome():
        for widget in chrome:
            chrome_positions[widget].append(_rect_in(widget, hub))

    panel.reveal_geometry_changed.connect(record_chrome)
    for opening in (True, False):
        if not opening:
            for positions in observer.positions.values():
                positions.clear()
            for positions in chrome_positions.values():
                positions.clear()
            hub.connect_button.click()
        _wait_finished(window, qt_application)
        for widget in chrome:
            positions = chrome_positions[widget]
            assert len(positions) >= 2, (opening, widget, positions)
            assert set(positions) == {chrome_expected[widget]}, (opening, positions)
        for label in labels:
            positions = observer.positions[label]
            assert len(positions) >= 2, (opening, label.text(), positions)
            assert set(positions) == {_rect_in(label, hub)}, (opening, positions)
        card_positions = [rect[1] for rect in observer.positions[card]]
        assert len(set(card_positions)) >= 2, (opening, card_positions)
        assert card_positions == sorted(card_positions, reverse=not opening), card_positions


def test_connection_expansion_does_not_follow_the_previous_scroll_bottom(
    connection_frame, qt_application,
):
    window = connection_frame
    window.resize(1120, 640)
    window._on_devices_updated([f"demo-{index}" for index in range(8)])
    coordinator = window.left_panel._responsive_coordinator
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    QTest.qWait(30)
    scroll = window._device_scroll_area.verticalScrollBar()
    assert scroll.maximum() > 0
    scroll.setValue(scroll.maximum())
    initial_value, initial_maximum = scroll.value(), scroll.maximum()

    _panel, animation = _open_paused(window)
    maxima = []
    for fraction in (.2, .5, .8):
        _advance(animation, fraction)
        maxima.append(scroll.maximum())
        assert scroll.value() == initial_value, "连接区增高不能逐帧把页面拖到新底部"
    assert initial_maximum < maxima[0] < maxima[-1], maxima
    _advance(animation, 1)
    _wait_finished(window, qt_application)
    assert scroll.value() == initial_value


def test_qr_ack_waits_until_connection_is_fully_revealed(
    connection_frame, qt_application, monkeypatch,
):
    window = connection_frame
    panel, animation = _open_paused(window)
    _advance(animation, .1)
    pairing = window._adb_pairing
    acknowledged_states = []
    acknowledge = pairing.acknowledge_qr

    def record_ack(request_id):
        acknowledged_states.append(animation.state())
        acknowledge(request_id)

    monkeypatch.setattr(pairing, "acknowledge_qr", record_ack)
    scroll = window._device_scroll_area.verticalScrollBar()
    initial_scroll = scroll.value()
    pairing.qr_ready.emit(1, qr_png(), 29)
    QTest.qWait(60)
    assert ("ack", 1) not in pairing.calls
    assert scroll.value() == initial_scroll
    _advance(animation, .6)
    assert ("ack", 1) not in pairing.calls

    _advance(animation, 1)
    wait_until(qt_application, lambda: ("ack", 1) in pairing.calls)
    assert acknowledged_states == [QAbstractAnimation.State.Stopped]
    assert panel.is_expanded and not panel.qr_label.pixmap().isNull()


def test_fast_reverse_then_leave_clears_secrets_and_releases_transition(
    connection_frame, qt_application,
):
    window = connection_frame
    panel, animation = _open_paused(window)
    _advance(animation, .5)
    partial_height = panel.height()
    pairing = window._adb_pairing
    panel.pairing_code.setText("012345")

    window._device_hub.connect_button.click()
    assert panel.height() == partial_height
    assert not panel.is_expanded and panel.pairing_code.text() == ""
    assert pairing.calls.count(("cancel",)) == 1
    animation.pause()
    _advance(animation, .35)
    closing_height = panel.height()
    window._device_hub.connect_button.click()
    assert panel.is_expanded and panel.height() == closing_height
    animation.pause()
    assert pairing.calls.count(("qr",)) == 1, "资源清理完成前不能启动第二轮配对"

    window._on_nav_requested("apps")
    wait_until(qt_application, lambda: (
        not panel.is_expanded and window.left_panel._responsive_coordinator.diagnostics.stable
    ))
    assert panel.isHidden() and panel.height() == 0
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert not window.left_panel._responsive_coordinator._geometry_transition_active
    pairing.qr_ready.emit(1, qr_png(), 29)
    pairing.finish()
    window._on_nav_requested("devices")
    QTest.qWait(50)
    assert panel.isHidden() and not window._device_hub.connect_button.isChecked()
    assert ("ack", 1) not in pairing.calls and pairing.calls.count(("qr",)) == 1


def test_shutdown_finishes_connection_before_layout_timers_stop(
    connection_frame, monkeypatch,
):
    window = connection_frame
    panel, animation = _open_paused(window)
    _advance(animation, .5)
    # 原配对替身只覆盖连接交互；主窗口退出还会通知资源协调器准备停止。
    monkeypatch.setattr(window._adb_pairing, "prepare_shutdown", Mock(), raising=False)
    window._prepare_ui_for_shutdown()

    assert animation.state() == QAbstractAnimation.State.Stopped
    assert not window.left_panel._responsive_coordinator._geometry_transition_active
    assert not window.left_panel._responsive_settle_timer.isActive()
    animation.setCurrentTime(animation.duration())
    QTest.qWait(60)
    assert panel.qr_label.pixmap().isNull()
    assert not window.left_panel._responsive_settle_timer.isActive()
