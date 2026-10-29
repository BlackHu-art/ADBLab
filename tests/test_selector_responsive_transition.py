"""在真实主窗口验证设备列表过渡不会逐帧重新规划整个工作区。"""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QSize
from PySide6.QtGui import QResizeEvent
from PySide6.QtTest import QTest

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from tests.test_navigation_rendering import theme_probe_frame  # noqa: F401
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def selector_frame(request, monkeypatch):
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    frame = request.getfixturevalue("theme_probe_frame")("Dark", False, width=1120)
    frame._on_devices_updated(["demo-a", "demo-b"])
    return frame


@pytest.mark.parametrize("route,feature", [
    ("devices", "remote"), ("apps", "overview"), ("system", "overview"),
])
def test_selector_defers_workspace_planning_until_transition_finishes(
    selector_frame, qt_application, monkeypatch, route, feature,
):
    frame = selector_frame
    frame._open_workspace_feature(route, feature)
    coordinator = frame.left_panel._responsive_coordinator
    wait_until(qt_application, lambda: (
        frame._page_transition.animation.state() == QAbstractAnimation.State.Stopped
        and coordinator.diagnostics.stable
    ))
    collect = Mock(wraps=coordinator._collect_candidates)
    monkeypatch.setattr(coordinator, "_collect_candidates", collect)
    bar = frame._global_device_bar
    bar.open_picker()
    animation = bar._selector_animation
    animation.pause()
    positions = [frame.stackedWidget.y()]
    for fraction in (.2, .5, .8):
        animation.setCurrentTime(round(animation.duration() * fraction))
        QTest.qWait(50)
        positions.append(frame.stackedWidget.y())
    assert positions == sorted(set(positions)), positions
    assert collect.call_count == 0, "展开帧只分配高度，不应重算所有响应式网格"
    assert not coordinator.diagnostics.stable
    animation.setCurrentTime(animation.duration())
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    assert collect.call_count > 0
    assert coordinator.diagnostics.fallback_reason is None

    collect.reset_mock()
    apply = Mock(wraps=coordinator._apply_candidates)
    monkeypatch.setattr(coordinator, "_apply_candidates", apply)
    bar.collapse_selector()
    animation.pause()
    animation.setCurrentTime(round(animation.duration() * .4))
    QTest.qWait(50)
    assert collect.call_count == 0
    bar.open_picker()
    animation.pause()
    QTest.qWait(50)
    assert collect.call_count == 0, "反向点击不能在动画中途释放布局合并边界"
    bar.dismiss_popups()
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    assert collect.call_count == 1, "最终水平布局不变时只复核一次，不阻塞末帧绘制"
    apply.assert_not_called()
    assert not bar.is_selector_expanded


def test_viewport_height_only_resize_skips_horizontal_geometry_probe(
    selector_frame, qt_application, monkeypatch,
):
    frame = selector_frame
    panel = frame.left_panel
    frame._open_workspace_feature("devices", "remote")
    wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
    probe = Mock(return_value=True)
    monkeypatch.setattr(panel.remote_panel, "responsive_geometry_is_applied", probe)
    viewport = panel._tab_scroll_areas[2].viewport()
    size = viewport.size()
    QCoreApplication.sendEvent(viewport, QResizeEvent(
        QSize(size.width(), size.height() - 20), size,
    ))
    probe.assert_not_called()
    QCoreApplication.sendEvent(viewport, QResizeEvent(
        QSize(size.width() - 20, size.height()), size,
    ))
    probe.assert_called_once()


def test_transition_applies_final_width_font_and_theme_after_resume(
    selector_frame, qt_application, monkeypatch,
):
    frame = selector_frame
    frame._open_workspace_feature("devices", "remote")
    panel = frame.left_panel
    coordinator = panel._responsive_coordinator
    wait_until(qt_application, lambda: (
        frame._page_transition.animation.state() == QAbstractAnimation.State.Stopped
        and coordinator.diagnostics.stable
    ))
    collect = Mock(wraps=coordinator._collect_candidates)
    monkeypatch.setattr(coordinator, "_collect_candidates", collect)
    bar = frame._global_device_bar
    bar.open_picker()
    bar._selector_animation.pause()
    bar._selector_animation.setCurrentTime(70)
    frame.resize(1280, 800)
    config = replace(BaseStyles.current_font_config(), ui_size=22)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    BaseStyles.switch_theme("Light")
    bar._selector_animation.pause()
    QTest.qWait(60)
    assert collect.call_count == 0
    assert not coordinator.diagnostics.stable
    bar._selector_animation.setCurrentTime(bar._selector_animation.duration())
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    assert collect.call_count > 0
    assert panel.remote_panel.responsive_geometry_is_applied()
    assert bar.targets_button.font().pointSize() == 22
    assert coordinator.diagnostics.fallback_reason is None


def test_shutdown_finishes_selector_before_stopping_layout_timers(
    selector_frame, qt_application,
):
    frame = selector_frame
    frame._open_workspace_feature("devices", "remote")
    panel = frame.left_panel
    wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
    bar = frame._global_device_bar
    bar.open_picker()
    bar._selector_animation.pause()
    frame._prepare_ui_for_shutdown()
    assert bar._selector_animation.state() == QAbstractAnimation.State.Stopped
    assert not bar.is_selector_expanded
    assert not panel._responsive_settle_timer.isActive()
    bar._selector_animation.setCurrentTime(bar._selector_animation.duration())
    QTest.qWait(60)
    assert not panel._responsive_settle_timer.isActive()
