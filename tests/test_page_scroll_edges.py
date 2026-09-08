"""真实主窗口页面的滚动边界与正文留白回归。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, QSize

from core.settings_manager import AppSettings
from models.device_store import DeviceStore
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry, wait_until


def _animation_finished(frame):
    animation = frame.stackedWidget.view._ani
    return animation is None or animation.state() == QAbstractAnimation.State.Stopped


@pytest.fixture
def edge_frame(qt_application, monkeypatch):
    settings = _MainFrameSettings()
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda _devices: [])
    frame = build_main_frame(
        settings=settings,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("layout", QSize(1920, 1080))),
    )
    frame.show()
    yield frame
    frame._unbind_window_screen()
    frame._close_ready = True
    frame.close()


@pytest.mark.parametrize("size", [(1120, 720), (860, 500)])
@pytest.mark.parametrize("route", ["home", "settings", "tasks", "devices", "apps", "system"])
def test_page_scroll_reaches_content_right_and_bottom(edge_frame, qt_application, route, size):
    """页面外壳铺满材质面，正文留白不能将整根滚动条挤回页面内部。"""

    frame = edge_frame
    frame.resize(*size)
    frame._on_nav_requested(route)
    if route == "home":
        scroll = frame._home_page
    elif route == "settings":
        scroll = frame._settings_page
    elif route == "tasks":
        scroll = frame._task_page._scroll
    else:
        scroll = frame._workspace_feature_hosts[route].overview.body
    wait_until(qt_application, lambda: scroll.isVisibleTo(frame))
    wait_until(qt_application, lambda: _animation_finished(frame))
    surface = frame._content_surface
    wait_for_stable_geometry(qt_application, (surface, scroll, scroll.viewport()))
    rect = mapped_rect(scroll, surface)
    assert surface.width() - rect.right() - 1 == 0
    assert surface.height() - rect.bottom() - 1 == 0
    assert scroll.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize("route", ["settings", "devices"])
def test_reading_content_keeps_inset_while_scrollbar_reaches_edge(
    edge_frame, qt_application, route,
):
    """设置卡和设备工具栏共享阅读起点，滚动条显示不能改变该起点。"""

    frame = edge_frame
    frame.resize(1120, 640)
    frame._on_nav_requested(route)
    if route == "settings":
        scroll, content = frame._settings_page, frame._settings_page.save_card
    else:
        scroll, content = frame._device_scroll_area, frame._device_hub.toolbar
    wait_until(qt_application, lambda: content.isVisibleTo(frame))
    wait_until(qt_application, lambda: _animation_finished(frame))
    wait_for_stable_geometry(qt_application, (scroll, content))
    assert content.mapTo(scroll.viewport(), QPoint()).x() == 32
    assert mapped_rect(content, scroll.viewport()).right() < scroll.viewport().width() - 24


@pytest.mark.parametrize("closing", [False, True])
def test_session_state_card_keeps_reading_insets(edge_frame, qt_application, closing):
    """等待设备和关闭中的状态卡也保持阅读留白，按钮在短窗中仍可见。"""

    frame = edge_frame
    frame.resize(860, 500)
    assert frame._open_workspace_feature("devices", "files")
    host = frame._workspace_feature_hosts["devices"]
    state = host.closing_page if closing else host.no_device_page
    if closing:
        host.stack.setCurrentWidget(state)
    wait_until(qt_application, lambda: _animation_finished(frame))
    wait_for_stable_geometry(qt_application, (host.content_scroll, state))
    assert state.card.isVisibleTo(frame)
    rect = mapped_rect(state.card, host.content_scroll.viewport())
    assert rect.left() == 32
    assert host.content_scroll.viewport().width() - rect.right() - 1 == 32
    assert host.content_scroll.viewport().height() - rect.bottom() - 1 == 24
    button = state.back_button if closing else state.choose_button
    assert host.content_scroll.viewport().rect().contains(
        mapped_rect(button, host.content_scroll.viewport()),
    )
