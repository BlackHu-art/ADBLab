"""高刷局部时钟与原生设置卡、主窗口生命周期的集成回归。"""

import sys

import pytest
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtTest import QTest

from tests.test_connection_expansion_integration import connection_frame as connection_frame
from tests.test_device_details_integration import details_frame as details_frame
from tests.test_global_device_context import frame  # noqa: F401
from tests.test_settings_expand_animation import _settle
from tests.test_settings_expand_animation import make_page as make_page
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("card_name", ["adb_client_card", "adb_check_card"])
def test_collapse_configuration_does_not_write_terminal_property(make_page, card_name):
    page = make_page()
    card = getattr(page, card_name)
    card.setExpand(True)
    card.expandAni.setCurrentTime(card.expandAni.duration())
    button = card.card.expandButton
    button.rotateAni.setCurrentTime(button.rotateAni.duration())
    expanded_height = card.height()
    observed = []
    card.expandAni.valueChanged.connect(lambda _: observed.append(card.height()))
    card.setExpand(False)
    assert card.height() == expanded_height
    assert observed and set(observed) == {expanded_height}, observed
    assert button.angle == 180
    card.expandAni.pause()
    button.rotateAni.pause()
    card.expandAni.setCurrentTime(card.expandAni.duration() // 2)
    button.rotateAni.setCurrentTime(button.rotateAni.duration() // 2)
    assert card.height() < expanded_height
    assert 0 < button.angle < 180


@pytest.mark.parametrize("card_name", ["adb_client_card", "adb_check_card"])
def test_arrow_reversal_preserves_current_angle(make_page, card_name):
    card = getattr(make_page(), card_name)
    card.setExpand(True)
    card.expandAni.pause()
    button = card.card.expandButton
    button.rotateAni.pause()
    card.expandAni.setCurrentTime(80)
    button.rotateAni.setCurrentTime(80)
    before = button.angle
    assert 0 < before < 180
    observed = []
    button.rotateAni.valueChanged.connect(lambda _: observed.append(button.angle))
    card.setExpand(False)
    assert button.angle == before
    assert all(value == before for value in observed), observed
    button.rotateAni.pause()
    button.rotateAni.setCurrentTime(100)
    assert 0 < button.angle < before


@pytest.mark.parametrize("card_name", ["adb_client_card", "adb_check_card"])
@pytest.mark.parametrize("expanded", [True, False])
def test_hiding_settings_settles_card_and_arrow(qt_application, make_page, card_name, expanded):
    page = make_page()
    card = getattr(page, card_name)
    card.setExpand(True)
    if not expanded:
        card.expandAni.setCurrentTime(card.expandAni.duration())
        card.card.expandButton.rotateAni.setCurrentTime(200)
        card.setExpand(False)
    card.expandAni.pause()
    card.expandAni.setCurrentTime(80)
    page.hide()
    page.show()
    _settle(qt_application, page)
    assert card.expandAni.state() == QAbstractAnimation.State.Stopped
    assert card.card.expandButton.rotateAni.state() == QAbstractAnimation.State.Stopped
    assert card.isExpand is expanded
    assert card.card.expandButton.angle == (180 if expanded else 0)
    expected = card.viewportMargins().top()
    if expanded:
        expected += card.viewLayout.sizeHint().height()
    assert card.height() == expected
    QTest.qWait(30)
    assert card.height() == expected


@pytest.mark.parametrize("surface", ["overview", "selector", "settings"])
def test_minimize_finishes_transitions_and_releases_layout_gate(
    details_frame, qt_application, monkeypatch, surface,
):
    window = details_frame
    if sys.platform == "win32" and qt_application.platformName() == "offscreen":
        # 离屏句柄不是 HWND，仅替换原生外框查询；Qt 的最小化和子控件 Hide 仍真实执行。
        monkeypatch.setattr("qframelesswindow.windows.win_utils.isMaximized", lambda _: False)
    coordinator = window.left_panel._responsive_coordinator
    if surface == "overview":
        card = window._device_hub.device_cards[0]
        card.details_button.click()
        window._device_hub.connect_button.click()
        animations = [card._details_animation, window._connection_panel._reveal_animation]
    elif surface == "selector":
        window._open_workspace_feature("devices", "remote")
        wait_until(qt_application, lambda: (
            window._page_transition.animation.state() == QAbstractAnimation.State.Stopped
            and coordinator.diagnostics.stable
        ))
        window._global_device_bar.open_picker()
        animations = [window._global_device_bar._selector_animation]
    else:
        window._on_nav_requested("settings")
        wait_until(qt_application, lambda: (
            window._page_transition.animation.state() == QAbstractAnimation.State.Stopped
        ))
        card = window._settings_page.adb_client_card
        card.setExpand(True)
        animations = [card.expandAni, card.card.expandButton.rotateAni]
    for animation in animations:
        assert animation.state() == QAbstractAnimation.State.Running
        animation.pause()
        animation.setCurrentTime(animation.duration() // 3)
    window.showMinimized()
    qt_application.processEvents()
    assert all(animation.state() == QAbstractAnimation.State.Stopped for animation in animations)
    assert not coordinator._geometry_transition_active
    assert not window._connection_transition_active
    assert not window._device_details_transition_active
    window.showNormal()
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    if surface == "overview":
        assert card._details_clip.height() == card._details_target_height()
        assert not window._connection_panel.is_expanded
    elif surface == "selector":
        assert not window._global_device_bar.is_selector_expanded
    else:
        assert card.height() == card.viewportMargins().top() + card.viewLayout.sizeHint().height()
        assert card.card.expandButton.angle == 180
