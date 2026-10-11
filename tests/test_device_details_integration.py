"""真实主窗口中详情动画的滚动、正文移动和重叠过渡归属。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtTest import QTest

from tests.test_connection_expansion_integration import connection_frame as connection_frame
from tests.test_device_hub_page import _rich_metadata
from tests.test_global_device_context import frame  # noqa: F401
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def details_frame(connection_frame, qt_application):
    window = connection_frame
    records = _rich_metadata()
    window._on_devices_updated([record["ip"] for record in records])
    for record in records:
        window._on_device_info_updated(record["ip"], record)
    wait_until(qt_application, lambda: window.left_panel._responsive_coordinator.diagnostics.stable)
    QTest.qWait(30)
    return window


def _advance(animation, fraction):
    animation.pause()
    animation.setCurrentTime(round(animation.duration() * fraction))
    QTest.qWait(30)


def _wait_settled(window, application):
    wait_until(application, lambda: (
        not window._device_details_transition_active
        and not window._connection_transition_active
        and window.left_panel._responsive_coordinator.diagnostics.stable
    ))


def test_details_move_following_cards_without_per_frame_workspace_planning(
    details_frame, qt_application, monkeypatch,
):
    window = details_frame
    first, second = window._device_hub.device_cards
    coordinator = window.left_panel._responsive_coordinator
    collect = Mock(wraps=coordinator._collect_candidates)
    monkeypatch.setattr(coordinator, "_collect_candidates", collect)
    collapsed_y = second.y()
    first.details_button.click()
    animation = first._details_animation
    assert animation.state() == QAbstractAnimation.State.Running
    animation.pause()
    assert second.y() == collapsed_y, "首次展开不能先跳出布局间距"
    for opening in (True, False):
        if not opening:
            first.details_button.click()
            animation.pause()
        positions = [second.y()]
        for fraction in (.2, .5, .8):
            _advance(animation, fraction)
            positions.append(second.y())
            assert second.y() - collapsed_y == first._details_clip.height()
        assert positions == sorted(set(positions), reverse=not opening), positions
        collect.assert_not_called()
        _advance(animation, 1)
        _wait_settled(window, qt_application)
        collect.reset_mock()
    assert second.y() == collapsed_y


def test_details_growth_keeps_reading_position_instead_of_following_bottom(
    details_frame, qt_application,
):
    window = details_frame
    window.resize(1120, 640)
    window._on_devices_updated([f"demo-{index}" for index in range(8)])
    wait_until(qt_application, lambda: window.left_panel._responsive_coordinator.diagnostics.stable)
    QTest.qWait(40)
    bar = window._device_scroll_area.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    before_value, before_maximum = bar.value(), bar.maximum()
    card = window._device_hub.device_cards[-1]
    card.details_button.click()
    animation = card._details_animation
    animation.pause()
    for fraction in (.2, .5, .8):
        _advance(animation, fraction)
        assert bar.value() == before_value, "详情增高不能逐帧拖动阅读位置"
        assert bar.maximum() > before_maximum
    _advance(animation, 1)
    _wait_settled(window, qt_application)
    assert bar.value() == before_value


def test_connection_and_multiple_details_release_gate_after_last_transition(
    details_frame, qt_application,
):
    window = details_frame
    cards = window._device_hub.device_cards
    coordinator = window.left_panel._responsive_coordinator
    for card in cards:
        card.details_button.click()
        _advance(card._details_animation, .25)
    window._device_hub.connect_button.click()
    connection = window._connection_panel
    _advance(connection._reveal_animation, .4)
    assert coordinator._geometry_transition_active
    _advance(connection._reveal_animation, 1)
    wait_until(qt_application, lambda: not window._connection_transition_active)
    assert coordinator._geometry_transition_active
    _advance(cards[0]._details_animation, 1)
    assert coordinator._geometry_transition_active
    _advance(cards[1]._details_animation, 1)
    _wait_settled(window, qt_application)
    assert not coordinator._geometry_transition_active


def test_leaving_device_page_stops_details_and_releases_layout_gate(
    details_frame, qt_application,
):
    window = details_frame
    cards = window._device_hub.device_cards
    for card in cards:
        card.details_button.click()
        _advance(card._details_animation, .4)
    window._on_nav_requested("settings")
    wait_until(qt_application, lambda: (
        window.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped
    ))
    _wait_settled(window, qt_application)
    assert not window.left_panel._responsive_coordinator._geometry_transition_active
    for card in cards:
        assert card._details_animation.state() == QAbstractAnimation.State.Stopped
        assert not card._details_transition_active


def test_shutdown_finishes_details_before_responsive_coordinator_stops(
    details_frame, qt_application, monkeypatch,
):
    window = details_frame
    cards = window._device_hub.device_cards
    for card in cards:
        card.details_button.click()
        _advance(card._details_animation, .4)
        card._copy_feedback_timer.start(1800)
    shutdown = window.left_panel.shutdown
    observed = []

    def stop_panel():
        observed.append(window.left_panel._responsive_coordinator._geometry_transition_active)
        for card in cards:
            assert card._details_animation.state() == QAbstractAnimation.State.Stopped
            assert not card._copy_feedback_timer.isActive()
        shutdown()

    monkeypatch.setattr(window.left_panel, "shutdown", stop_panel)
    window._closing = True
    window._prepare_ui_for_shutdown()
    assert observed == [False]
    assert not window._device_details_transition_active
    QTest.qWait(230)
    assert not window.left_panel._responsive_coordinator._geometry_transition_active
