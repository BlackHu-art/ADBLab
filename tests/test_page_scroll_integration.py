"""主窗口各滚动入口与异步关闭共用局部滚轮控制器的集成契约。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QPlainTextEdit
from qfluentwidgets import ExpandGroupSettingCard

from gui.widgets.settings_scroll import SettingsWheelScroll
from tests.test_global_device_context import frame as frame
from tests.test_settings_scroll import _wheel
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("section,feature", [
    ("home", None), ("devices", "overview"), ("apps", "overview"),
    ("system", "overview"), ("devices", "remote"), ("settings", None), ("tasks", None),
])
def test_visible_page_pixel_scroll_uses_one_controller(frame, qt_application, section, feature):
    frame.resize(1000, 620)
    frame.show()
    if feature is None:
        frame._on_nav_requested(section)
    else:
        frame._open_workspace_feature(section, feature)
    wait_until(qt_application, lambda: (
        frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped
        and frame.left_panel._responsive_coordinator.diagnostics.stable
    ))
    areas = [area for area in frame.findChildren(QAbstractScrollArea)
             if area.isVisibleTo(frame) and frame._content_surface.isAncestorOf(area)
             and area.width() > 200
             and not isinstance(area, (QPlainTextEdit, ExpandGroupSettingCard))]
    assert areas
    for area in areas:
        assert len(area.findChildren(SettingsWheelScroll, "adblabWheelScroll",
                                     Qt.FindChildOption.FindDirectChildrenOnly)) == 1, (
            section, feature, type(area).__name__, area.objectName(),
        )


def test_application_shutdown_rejects_late_input_on_all_installed_scrolls(frame, qt_application):
    frame.resize(1000, 620)
    frame.show()
    frame._on_nav_requested("home")
    wait_until(qt_application, lambda: (
        frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped
    ))
    area = frame._home_page
    _wheel(qt_application, area.viewport())
    assert area._wheel_scroll._animation.state() == QAbstractAnimation.State.Running
    frame._close_controller._prepare_ui_for_shutdown()
    controllers = frame.findChildren(SettingsWheelScroll)
    assert len(controllers) > 1
    assert all(controller._shutdown for controller in controllers)
    assert all(controller._animation.state() == QAbstractAnimation.State.Stopped
               for controller in controllers)
    before = area.verticalScrollBar().value()
    _wheel(qt_application, area.viewport())
    assert area.verticalScrollBar().value() == before
    assert area._wheel_scroll._animation.state() == QAbstractAnimation.State.Stopped
