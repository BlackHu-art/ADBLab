"""连接区的裁剪动画不得改变配对准入、秘密清理和二维码可见确认。"""

from dataclasses import replace

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from gui.widgets.device_connection import DeviceConnectionPanel
from tests.test_device_connection import PairingDouble, qr_png
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def animated_connection(qt_application):
    host = QWidget()
    host.resize(820, 950)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    button = QPushButton("连接设备", host)
    layout.addWidget(button)
    pairing = PairingDouble()
    panel = DeviceConnectionPanel(pairing, parent=host, animated=True)
    panel.setContentsMargins(0, 0, 0, 14)
    layout.addWidget(panel)
    body = QPushButton("设备卡片", host)
    layout.addWidget(body)
    layout.addStretch(1)
    host.show()
    host.activateWindow()
    qt_application.processEvents()
    yield host, panel, pairing, body
    panel.prepare_shutdown()
    pairing.busy = False
    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _advance(panel, app, fraction):
    animation = getattr(panel, "_reveal_animation", None)
    if animation is not None:
        if animation.state() == QAbstractAnimation.State.Running:
            animation.pause()
        animation.setCurrentTime(round(animation.duration() * fraction))
    app.processEvents()
    panel.window().layout().activate()
    app.processEvents()


def test_reveal_keeps_content_top_and_height_stable_while_moving_cards(
    animated_connection, qt_application,
):
    host, panel, _pairing, body = animated_connection
    collapsed = body.y()
    panel.expand()
    positions, content_positions, content_sizes = [], [], []
    for fraction in (.2, .6, 1):
        _advance(panel, qt_application, fraction)
        positions.append(body.y())
        content_positions.append(panel.navigation.mapTo(host, QPoint()).y())
        content_sizes.append(panel.stack.size())
    assert collapsed < positions[0] < positions[1] < positions[2]
    assert len(set(content_positions)) == 1
    assert content_sizes[0] == content_sizes[1] == content_sizes[2]
    assert panel.height() - panel.contentsMargins().bottom() > panel.stack.height()
    assert not panel.autoFillBackground()


def test_collapse_immediately_clears_secrets_and_cancels_before_visual_completion(
    animated_connection, qt_application,
):
    _host, panel, pairing, body = animated_connection
    panel.expand()
    _advance(panel, qt_application, 1)
    panel.pairing_code.setText("123456")
    pairing.qr_ready.emit(1, qr_png(), 29)
    qt_application.processEvents()
    expanded = body.y()
    panel.collapse()
    assert not panel.is_expanded
    assert panel.pairing_code.text() == "" and panel.qr_label.pixmap().isNull()
    assert pairing.calls[-1] == ("cancel",)
    assert panel.isVisible() and panel.height() > 0
    assert panel.progress_ring.aniGroup.state() == QAbstractAnimation.State.Stopped
    positions = []
    for fraction in (.2, .6, 1):
        _advance(panel, qt_application, fraction)
        positions.append(body.y())
    assert expanded > positions[0] > positions[1] > positions[2]
    assert panel.isHidden() and panel.height() == 0


def test_reversal_does_not_jump_or_restart_pairing_after_resource_idle(
    animated_connection, qt_application,
):
    _host, panel, pairing, body = animated_connection
    panel.expand()
    _advance(panel, qt_application, .55)
    before = body.y()
    synchronous_positions = []
    panel.reveal_geometry_changed.connect(lambda: synchronous_positions.append(body.y()))
    panel.collapse()
    assert body.y() == before
    assert all(position == before for position in synchronous_positions)
    _advance(panel, qt_application, .25)
    before = body.y()
    synchronous_positions.clear()
    panel.expand()
    assert body.y() == before
    assert all(position == before for position in synchronous_positions)
    pairing.qr_ready.emit(91, qr_png(), 29)
    pairing.finish()
    _advance(panel, qt_application, 1)
    assert panel.is_expanded and panel.isVisible()
    assert pairing.calls.count(("qr",)) == 1
    assert panel.qr_label.pixmap().isNull()
    assert ("ack", 91) not in pairing.calls


def test_qr_ack_waits_for_complete_reveal_then_delivers_exactly_once(
    animated_connection, qt_application,
):
    _host, panel, pairing, _body = animated_connection
    panel.expand()
    _advance(panel, qt_application, .2)
    pairing.qr_ready.emit(7, qr_png(), 29)
    qt_application.processEvents()
    assert ("ack", 7) not in pairing.calls
    _advance(panel, qt_application, 1)
    wait_until(qt_application, lambda: ("ack", 7) in pairing.calls)
    assert pairing.calls.count(("ack", 7)) == 1
    qt_application.processEvents()
    assert pairing.calls.count(("ack", 7)) == 1


@pytest.mark.parametrize("ending", ["hide", "close", "shutdown"])
def test_interrupted_reveal_finishes_immediately_and_cannot_ack_late_qr(
    animated_connection, qt_application, ending,
):
    host, panel, pairing, _body = animated_connection
    panel.expand()
    _advance(panel, qt_application, .35)
    pairing.qr_ready.emit(8, qr_png(), 29)
    before = list(pairing.calls)
    if ending == "hide":
        host.hide()
    elif ending == "close":
        panel.close()
    else:
        panel.prepare_shutdown()
    assert panel.height() == 0 and not panel.is_expanded
    assert panel._reveal_animation.state() == QAbstractAnimation.State.Stopped
    qt_application.processEvents()
    assert panel.qr_label.pixmap().isNull() and ("ack", 8) not in pairing.calls
    if ending == "shutdown":
        assert pairing.calls == before
    else:
        assert pairing.calls.count(("cancel",)) == before.count(("cancel",)) + 1


def test_keyboard_entry_completes_reveal_and_collapsing_controls_leave_focus_chain(
    animated_connection, qt_application,
):
    _host, panel, _pairing, _body = animated_connection
    panel.expand()
    _advance(panel, qt_application, .2)
    intermediate = panel.height()
    panel.code_button.setFocus(Qt.FocusReason.TabFocusReason)
    qt_application.processEvents()
    assert panel.height() > intermediate
    assert panel._reveal_animation.state() == QAbstractAnimation.State.Stopped
    panel.collapse()
    _advance(panel, qt_application, .35)
    for _ in range(6):
        focus = QApplication.focusWidget()
        assert focus is None or not panel.isAncestorOf(focus)
        if focus is not None:
            QTest.keyClick(focus, Qt.Key.Key_Tab)


def test_font_and_width_change_retarget_without_squashing_natural_content(
    animated_connection, qt_application,
):
    host, panel, _pairing, body = animated_connection
    panel.expand()
    _advance(panel, qt_application, .25)
    config = replace(BaseStyles.current_font_config(), ui_size=22)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    host.resize(650, 1100)
    _advance(panel, qt_application, 1)
    _advance(panel, qt_application, 1)
    assert panel.isVisible() and panel.is_expanded
    assert panel.stack.height() >= panel.stack.heightForWidth(panel.width())
    assert body.y() == panel.y() + panel.height()
    assert panel.pairing_code.height() >= panel.pairing_code.fontMetrics().height() + 16


def test_collapse_releases_transition_only_after_parent_paints_terminal_geometry(
    animated_connection, qt_application,
):
    host, panel, _pairing, body = animated_connection
    panel.expand()
    _advance(panel, qt_application, 1)
    events = []

    class PaintProbe(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Paint:
                events.append(("paint", body.y()))
            return False

    probe = PaintProbe(host)
    host.installEventFilter(probe)
    panel.transition_changed.connect(lambda active: events.append(("transition", active)))
    panel.collapse()
    _advance(panel, qt_application, .6)
    events.clear()
    _advance(panel, qt_application, 1)
    assert ("transition", False) in events
    terminal_paint = events.index(("paint", body.y()))
    assert terminal_paint < events.index(("transition", False))


def test_height_only_frames_do_not_reflow_content_or_move_painted_text(
    animated_connection, qt_application, monkeypatch,
):
    host, panel, _pairing, body = animated_connection
    panel.expand()
    _advance(panel, qt_application, .3)
    reflows, paints = [], []
    original = panel._reflow

    def reflow():
        reflows.append(panel.height())
        original()

    monkeypatch.setattr(panel, "_reflow", reflow)

    class PaintProbe(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Paint:
                paints.append((panel.navigation.mapTo(host, QPoint()).y(), body.y()))
            return False

    probe = PaintProbe(panel.navigation)
    panel.navigation.installEventFilter(probe)
    for fraction in (.4, .55, .7, .85):
        panel.navigation.update()
        _advance(panel, qt_application, fraction)
    assert reflows == []
    assert len(paints) >= 3
    assert len({position[0] for position in paints}) == 1
    assert len({position[1] for position in paints}) >= 3


def test_new_reveal_invalidates_queued_release_from_previous_terminal_paint(
    animated_connection, qt_application,
):
    host, panel, _pairing, _body = animated_connection
    panel.expand()
    _advance(panel, qt_application, 1)
    wait_until(qt_application, lambda: not panel._transition_active)
    transitions = []
    panel.transition_changed.connect(transitions.append)
    panel.collapse()
    panel._reveal_animation.pause()
    panel._reveal_animation.setCurrentTime(panel._reveal_animation.duration())
    # 把终点父级绘制送入过滤器，但暂不处理已排队的释放计时器。
    host.repaint()
    panel.expand()
    _advance(panel, qt_application, .3)
    assert transitions == [True]
    assert panel.is_expanded and panel._transition_active
    _advance(panel, qt_application, 1)
    wait_until(qt_application, lambda: not panel._transition_active)
    assert transitions == [True, False]


def test_reopening_ignores_destroyed_controls_from_saved_focus_policies(
    animated_connection, qt_application,
):
    _host, panel, _pairing, _body = animated_connection
    panel.expand()
    _advance(panel, qt_application, 1)
    transient = QPushButton("历史地址", panel._content)
    panel.collapse()
    _advance(panel, qt_application, 1)
    transient.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    panel.expand()
    _advance(panel, qt_application, 1)
    assert panel.is_expanded and panel.isVisible()
