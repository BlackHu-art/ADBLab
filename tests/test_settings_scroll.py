"""设置页连续滚动的轨迹、输入归属及取消边界。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QSpinBox

from tests.test_settings_expand_animation import make_page as make_page

pytestmark = pytest.mark.ui


def _wheel(
    app, target, delta=-120, *, pixel=QPoint(), horizontal=0, modifiers=None,
    phase=Qt.ScrollPhase.NoScrollPhase, inverted=False,
):
    point = QPointF(target.rect().center())
    event = QWheelEvent(
        point, QPointF(target.mapToGlobal(point.toPoint())), pixel, QPoint(horizontal, delta),
        Qt.MouseButton.NoButton, modifiers or Qt.KeyboardModifier.NoModifier,
        phase, inverted,
    )
    app.sendEvent(target, event)


def _begin(app, page, value=180):
    bar = page.verticalScrollBar()
    bar.setValue(value)
    _wheel(app, page.viewport())
    assert bar.value() == value, "单刻度输入应保留首帧，随后逐帧移动"
    animation = page._wheel_scroll._animation
    animation.pause()
    return bar, animation


def test_single_notch_interpolates_and_keeps_qt_step(qt_application, make_page):
    page = make_page()
    bar, animation = _begin(qt_application, page)
    step = bar.singleStep() * QApplication.wheelScrollLines()
    values = [bar.value()]
    for elapsed in (30, 60, 90, animation.duration()):
        animation.setCurrentTime(elapsed)
        values.append(bar.value())
    assert values[0] < values[1] < values[2] < values[3] < values[4]
    assert values[-1] == values[0] + step


def test_reverse_starts_at_visible_position_without_following_old_target(
    qt_application, make_page,
):
    page = make_page()
    bar, animation = _begin(qt_application, page)
    animation.setCurrentTime(45)
    before = bar.value()
    _wheel(qt_application, page.viewport(), 120)
    assert bar.value() == before
    animation.pause()
    animation.setCurrentTime(animation.currentTime() + 30)
    assert bar.value() < before
    animation.setCurrentTime(animation.duration())
    assert bar.value() == before - bar.singleStep() * QApplication.wheelScrollLines()


def test_repeated_wheel_has_bounded_target_and_stops_at_content_edges(
    qt_application, make_page,
):
    page = make_page()
    bar, animation = _begin(qt_application, page)
    for _ in range(100):
        _wheel(qt_application, page.viewport())
        animation.pause()
    animation.setCurrentTime(animation.duration())
    assert bar.value() == min(bar.maximum(), 180 + bar.pageStep())
    for start, delta, end in (
        (bar.maximum() - 10, -120, bar.maximum()), (10, 120, bar.minimum()),
    ):
        bar.setValue(start)
        _wheel(qt_application, page.viewport(), delta)
        animation.pause()
        animation.setCurrentTime(animation.duration())
        assert bar.value() == end
        _wheel(qt_application, page.viewport(), delta)
        assert animation.state() == QAbstractAnimation.State.Stopped


@pytest.mark.parametrize("reason", ["program", "range", "drag", "hide", "close", "prepare"])
def test_external_scroll_or_lifecycle_change_cancels_pending_target(
    qt_application, make_page, reason,
):
    page = make_page()
    bar, animation = _begin(qt_application, page)
    animation.setCurrentTime(45)
    if reason == "program":
        bar.setValue(450)
    elif reason == "range":
        bar.setRange(0, bar.maximum() - 1)
    elif reason == "drag":
        page.scrollDelagate.vScrollBar.sliderPressed.emit()
    elif reason == "hide":
        page.hide()
    elif reason == "prepare":
        page.prepare_shutdown()
    else:
        page.close()
    before = bar.value()
    assert animation.state() == QAbstractAnimation.State.Stopped
    animation.setCurrentTime(animation.duration())
    assert bar.value() == before


def test_prepare_shutdown_stops_card_animations_and_rejects_late_wheel(
    qt_application, make_page,
):
    page = make_page()
    cards = (page.adb_client_card, page.adb_check_card)
    for card in cards:
        card.setExpand(True)
        card.expandAni.pause()
        card.card.expandButton.rotateAni.pause()
    qt_application.processEvents()
    bar, animation = _begin(qt_application, page)
    animation.setCurrentTime(45)
    page.prepare_shutdown()
    page.prepare_shutdown()
    before = bar.value()
    assert page.isVisible()
    assert page.adb_client_card._shutdown_requested.is_set()
    for card in cards:
        assert card.expandAni.state() == QAbstractAnimation.State.Stopped
        assert card.card.expandButton.rotateAni.state() == QAbstractAnimation.State.Stopped
    _wheel(qt_application, page.viewport())
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert bar.value() == before


@pytest.mark.parametrize("event_args", [
    {"pixel": QPoint(0, -14)}, {"delta": 0, "horizontal": -120},
    {"modifiers": Qt.KeyboardModifier.ShiftModifier}, {"delta": -30},
    {"phase": Qt.ScrollPhase.ScrollUpdate}, {"inverted": True},
])
def test_other_wheel_modes_cancel_animation_and_reach_native_handler(
    qt_application, make_page, monkeypatch, event_args,
):
    page = make_page()
    bar, animation = _begin(qt_application, page)
    animation.setCurrentTime(45)
    calls = []
    delegate = page.scrollDelagate
    if event_args.get("horizontal"):
        page.horizontalScrollBar().setRange(0, 200)
        page.horizontalScrollBar().setValue(60)
    for engine in (delegate.verticalSmoothScroll, delegate.horizonSmoothScroll):
        native = engine.wheelEvent

        def capture(event, native=native):
            calls.append(event)
            native(event)

        monkeypatch.setattr(engine, "wheelEvent", capture)
    _wheel(qt_application, page.viewport(), **event_args)
    assert len(calls) == 1
    assert animation.state() == QAbstractAnimation.State.Stopped
    after_native = bar.value()
    animation.setCurrentTime(animation.duration())
    assert bar.value() == after_native


def test_child_control_keeps_its_wheel_input(qt_application, make_page):
    page = make_page()
    control = QSpinBox(page.viewport())
    control.setRange(0, 100)
    control.setValue(10)
    control.show()
    bar = page.verticalScrollBar()
    before = bar.value()
    _wheel(qt_application, control, 120)
    assert control.value() == 11
    assert bar.value() == before


@pytest.mark.parametrize("retarget_ms", [48, 80, 112])
def test_continuous_wheel_does_not_restart_with_a_speed_spike(
    qt_application, make_page, retarget_ms,
):
    page = make_page()
    bar, animation = _begin(qt_application, page)
    animation.setCurrentTime(retarget_ms - 16)
    previous = bar.value()
    animation.setCurrentTime(retarget_ms)
    current = bar.value()
    previous_step = current - previous
    _wheel(qt_application, page.viewport())
    assert bar.value() == current
    animation.pause()
    animation.setCurrentTime(animation.currentTime() + 16)
    next_step = bar.value() - current
    # 比较输入前后可见位移，允许加速和像素取整，但不能再次冲到三四倍速度。
    assert 0 < next_step <= 2 * previous_step + 1, (previous_step, next_step)


def test_single_notch_accelerates_gently_then_settles_without_overshoot(
    qt_application, make_page,
):
    page = make_page()
    bar, animation = _begin(qt_application, page)
    start = bar.value()
    target = start + bar.singleStep() * QApplication.wheelScrollLines()
    values = [start]
    for elapsed in range(16, 369, 16):
        animation.setCurrentTime(elapsed)
        values.append(bar.value())
    assert 0 < values[1] - start < values[2] - values[1]
    assert values[8] < target, "一次滚轮应柔和收尾，不能在 120ms 内冲完并停住"
    assert values == sorted(values)
    assert max(values) == values[-1] == target


@pytest.mark.parametrize("interval_ms", [16, 48, 96])
def test_repeated_input_moves_continuously_and_finishes_at_requested_distance(
    qt_application, make_page, interval_ms,
):
    page = make_page()
    bar, animation = _begin(qt_application, page)
    start = bar.value()
    step = bar.singleStep() * QApplication.wheelScrollLines()
    values = [start]
    for _ in range(5):
        animation.setCurrentTime(animation.currentTime() + interval_ms)
        values.append(bar.value())
        _wheel(qt_application, page.viewport())
        assert bar.value() == values[-1]
        animation.pause()
    last_input_ms = animation.currentTime()
    for elapsed in range(16, 433, 16):
        animation.setCurrentTime(last_input_ms + elapsed)
        values.append(bar.value())
    assert values == sorted(values)
    assert max(values) == values[-1] == start + 6 * step
    assert animation.state() == QAbstractAnimation.State.Stopped


@pytest.mark.parametrize("reverse", [False, True])
def test_inputs_between_frames_keep_visible_position_and_new_direction(
    qt_application, make_page, reverse,
):
    page = make_page()
    bar, animation = _begin(qt_application, page, value=400)
    if reverse:
        animation.setCurrentTime(48)
        _wheel(qt_application, page.viewport(), 120)
        animation.pause()
    before = bar.value()
    direction = -1 if reverse else 1
    for _ in range(3):
        _wheel(qt_application, page.viewport(), direction * -120)
        assert bar.value() == before
        animation.pause()
    animation.setCurrentTime(animation.currentTime() + 16)
    moved = (bar.value() - before) * direction
    assert 0 < moved < bar.singleStep() * QApplication.wheelScrollLines()


def test_retarget_keeps_elapsed_clock_so_dense_input_cannot_starve_frames(
    qt_application, make_page,
):
    page = make_page()
    bar, animation = _begin(qt_application, page)
    animation.setCurrentTime(64)
    before = bar.value()
    for _ in range(3):
        _wheel(qt_application, page.viewport())
        animation.pause()
        assert animation.currentTime() == 64, "连续输入不能清掉等待下一帧的计时时间"
        assert bar.value() == before
    animation.setCurrentTime(80)
    assert bar.value() > before
