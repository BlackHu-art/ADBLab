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

pytestmark = pytest.mark.ui


def _assert_visible_track_at_window_edge(frame, scroll, qt_application):
    """检查用户看到的 Fluent 轨道，保留组件自身的 1px 边缘间隔。"""
    delegate = next(
        getattr(scroll, name) for name in ("scrollDelagate", "scrollDelegate", "delegate")
        if getattr(scroll, name, None) is not None
    )
    track = delegate.vScrollBar
    wait_until(qt_application, lambda: scroll.verticalScrollBar().maximum() > 0)
    wait_until(qt_application, lambda: track.isVisibleTo(frame))
    wait_for_stable_geometry(qt_application, (frame, scroll, track))
    assert mapped_rect(scroll, frame).right() == frame.rect().right()
    assert 0 <= frame.rect().right() - mapped_rect(track, frame).right() <= 2


def _animation_finished(frame):
    animation = frame._page_transition.animation
    return animation is None or animation.state() == QAbstractAnimation.State.Stopped


@pytest.fixture
def edge_frame(qt_application, monkeypatch):
    settings = _MainFrameSettings()
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda _devices: [])
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda self: None,
    )
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
    assert mapped_rect(surface, frame).right() == frame.rect().right()
    # 用真实正文制造纵向溢出，检查可见覆盖轨道而非隐藏的原生 QScrollBar。
    scroll.widget().setMinimumHeight(1400)
    _assert_visible_track_at_window_edge(frame, scroll, qt_application)


@pytest.mark.parametrize("size", [(1120, 720), (860, 500)])
@pytest.mark.parametrize("section,feature,view", [
    ("apps", "manager", "icons"),
    ("apps", "manager", "table"),
    ("devices", "files", "table"),
    ("devices", "remote", "page"),
    ("apps", "media", "page"),
    ("system", "logcat", "text"),
    ("system", "performance", "page"),
])
def test_feature_scroll_track_reaches_main_window_edge(
    edge_frame, qt_application, monkeypatch, section, feature, view, size,
):
    """真实路由和页面组成完整布局链，列表长内容不应使右侧轨道内缩。"""
    from gui.features.app_manager import AppManagerPage
    from gui.features.app_manager.icons import AppManagerIcons
    from gui.features.file_explorer import FileExplorerPage

    # 只截断设备 I/O，保留页面工厂、宿主、真实列表和全部布局逻辑。
    monkeypatch.setattr(AppManagerPage, "_load_apps", lambda self: None)
    monkeypatch.setattr(AppManagerPage, "_schedule_visible_detail_load", lambda self: None)
    monkeypatch.setattr(AppManagerIcons, "schedule", lambda self: None)
    monkeypatch.setattr(FileExplorerPage, "_refresh", lambda self: None)
    frame = edge_frame
    frame.resize(*size)
    host = frame._workspace_feature_hosts[section]
    requires_device = feature not in {"remote", "media"}
    if requires_device:
        host.set_device_context(["demo-edge"], ["demo-edge"])
    assert frame._open_workspace_feature(
        section, feature, device_id="demo-edge" if requires_device else "",
    )
    page = host.stack.currentWidget()
    wait_until(qt_application, lambda: page.isVisibleTo(frame))
    wait_until(qt_application, lambda: _animation_finished(frame))
    if feature == "manager":
        page._populate([
            (f"应用 {index}", f"com.example.edge{index}", "Enabled", "User")
            for index in range(100)
        ])
        if view == "table":
            page.view_toggle.click()
        scroll = page.icon_list if view == "icons" else page.tree
    elif feature == "files":
        page._on_ls_result("\n".join(
            f"-rw-r--r-- 1 shell shell 2048 Sep 05 file-{index}.txt"
            for index in range(100)
        ), False)
        scroll = page.table
    elif feature == "logcat":
        page.output.setPlainText("\n".join(f"日志记录 {index}" for index in range(100)))
        scroll = page.output
    else:
        scroll = page.body if feature == "remote" else host.content_scroll
        # 表单和画布使用宿主滚动；扩大真实内容以模拟超出短窗的阅读区域。
        scroll.widget().setMinimumHeight(1400)
    _assert_visible_track_at_window_edge(frame, scroll, qt_application)
    if feature in {"files", "manager"}:
        assert mapped_rect(scroll, frame._content_surface).left() == 32
        footer = page.status_bar if feature == "files" else page._command_bar
        assert frame.rect().bottom() - mapped_rect(footer, frame).bottom() == 8
        assert frame.rect().right() - mapped_rect(scroll.viewport(), frame).right() == 32
        header = scroll.horizontalHeader() if feature == "files" else scroll.header()
        assert frame.rect().right() - mapped_rect(header, frame).right() == 32
    if feature == "files":
        assert mapped_rect(page.status_bar, frame._content_surface).left() == 32


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
