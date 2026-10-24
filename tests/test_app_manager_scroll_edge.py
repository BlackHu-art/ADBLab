"""应用管理主列表贴边，阅读控件与详情分栏保留各自边界。"""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from gui.dialogs.app_manager import AppManagerPage
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry, wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def manager_page(qt_application, monkeypatch):
    page = AppManagerPage(device_ip="scroll-demo")
    monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
    monkeypatch.setattr(page._icons_controller, "schedule", lambda *args, **kwargs: None)
    monkeypatch.setattr(page.details_page, "activate", lambda *args, **kwargs: None)
    page._populate([
        (f"示例应用 {row}", f"com.example.app{row}", "Enabled", "User")
        for row in range(80)
    ])
    yield page
    page.close()


@pytest.mark.parametrize("width", [1040, 540])
@pytest.mark.parametrize("embedded", [False, True])
@pytest.mark.parametrize("icon_mode", [False, True])
def test_main_application_scrollbar_reaches_its_right_edge(
    qt_application, manager_page, width, embedded, icon_mode,
):
    page = manager_page
    if embedded:
        page.prepare_for_workspace()
        page.prepare_for_workspace()
    page.resize(width, 720)
    page.show()
    if not icon_mode:
        QTest.mouseClick(page.view_toggle, Qt.MouseButton.LeftButton)
    view = page.icon_list if icon_mode else page.tree
    bar = view.scrollDelagate.vScrollBar
    wait_until(qt_application, lambda: view.isVisible() and bar.isVisible() and bar.maximum() > 0)
    wait_for_stable_geometry(qt_application, (page, view, bar))
    right_gap = 0 if embedded else 8
    assert page.rect().right() - mapped_rect(view, page).right() == right_gap
    assert 0 <= page.rect().right() - mapped_rect(bar, page).right() - right_gap <= 2
    assert mapped_rect(view, page).left() == (32 if embedded else 8)
    if embedded:
        for content in (view.viewport(), view.header()):
            assert page.rect().right() - mapped_rect(content, page).right() == 32

    # 在真实覆盖滚条手柄上拖动，避免只检测隐藏的原生 QScrollBar 几何。
    point = bar.handle.rect().center()
    assert page.childAt(bar.handle.mapTo(page, point)) is bar.handle
    before = bar.value()
    QTest.mousePress(bar.handle, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(bar.handle, point + QPoint(0, 60))
    QTest.mouseRelease(bar.handle, Qt.MouseButton.LeftButton, pos=point + QPoint(0, 60))
    assert bar.value() > before


@pytest.mark.parametrize("width", [1040, 540])
def test_embedded_application_controls_retain_reading_insets(
    qt_application, manager_page, width,
):
    page = manager_page
    page.prepare_for_workspace()
    page.resize(width, 720)
    page.show()
    page._set_load_state("error", "无法加载应用列表，请重试。")
    wait_for_stable_geometry(qt_application, (*page._top_controls, page._command_bar))
    for control in page._top_controls:
        rect = mapped_rect(control, page)
        assert rect.left() >= 32
        assert rect.right() <= page.rect().right() - 32
    assert page._action_layout_available_width() == page.width() - 64
    assert mapped_rect(page._command_bar, page).left() == 32
    assert page.rect().right() - mapped_rect(page._command_bar, page).right() == 32
    assert mapped_rect(page.load_error_label, page).left() == 40
    assert page.rect().right() - mapped_rect(page.retry_btn, page).right() == 40


@pytest.mark.parametrize("width,expected_mode", [
    (1300, "split"), (1228, "split"), (1227, "stack"), (1216, "stack"), (900, "stack"),
])
def test_embedded_application_details_keep_pane_scroll_and_breakpoint(
    qt_application, manager_page, width, expected_mode,
):
    page = manager_page
    page.prepare_for_workspace()
    page.set_device_selected(True)
    page.resize(width, 800)
    page.show()
    assert page.open_details("com.example.app0") is page.details_page
    wait_for_stable_geometry(qt_application, (page._master_panel, page.details_page))
    assert page.master_detail_mode == expected_mode
    assert page.details_page.isVisible()
    assert page._master_panel.isVisible() == (expected_mode == "split")
    if expected_mode == "split":
        bar = page.icon_list.scrollDelagate.vScrollBar
        wait_until(qt_application, lambda: bar.isVisible() and bar.maximum() > 0)
        pane_right = page._master_panel.rect().right()
        assert mapped_rect(page.icon_list, page._master_panel).right() == pane_right
        assert 0 <= pane_right - mapped_rect(bar, page._master_panel).right() <= 2
        assert mapped_rect(bar, page).right() < mapped_rect(page.details_page, page).left()
    page.close_details()
    wait_for_stable_geometry(qt_application, (page._master_panel, page.icon_list))
    assert page._master_panel.isVisible()
    assert not page.details_page.isVisible()
    assert mapped_rect(page.icon_list, page).left() == 32
    assert mapped_rect(page.icon_list, page).right() == page.rect().right()


def test_application_detail_width_round_trips_keep_local_reading_edges(
    qt_application, manager_page,
):
    page = manager_page
    page.prepare_for_workspace()
    page.prepare_for_workspace()
    page.set_device_selected(True)
    page.show()
    assert page.open_details("com.example.app0") is page.details_page
    for width, expected_mode in ((1227, "stack"), (1228, "split"), (900, "stack"), (1300, "split")):
        page.resize(width, 800)
        for _ in range(2):
            page._update_master_detail_layout()
            wait_for_stable_geometry(qt_application, (page._master_panel, page.details_page))
            assert page.master_detail_mode == expected_mode
            detail_left = mapped_rect(page.details_page, page).left()
            back_left = mapped_rect(page.details_page.back_btn, page).left()
            assert back_left - detail_left == 8
            if expected_mode == "stack":
                assert back_left == 32
            package_right = mapped_rect(page.details_page.package_label, page).right()
            assert page.rect().right() - package_right == 32
            if expected_mode == "split":
                assert mapped_rect(page.icon_list, page._master_panel).left() == 8
                assert page._action_layout_available_width() == page._master_panel.width() - 40
    page.close_details()
    wait_for_stable_geometry(qt_application, (page._master_panel, page.icon_list))
    assert mapped_rect(page.icon_list, page).left() == 32
    assert page._action_layout_available_width() == page.width() - 64


@pytest.mark.parametrize("icon_mode", [False, True])
def test_application_bottom_inset_releases_height_to_list(
    qt_application, manager_page, icon_mode,
):
    page = manager_page
    page.prepare_for_workspace()
    page.resize(1040, 720)
    page.show()
    if not icon_mode:
        QTest.mouseClick(page.view_toggle, Qt.MouseButton.LeftButton)
    view = page.icon_list if icon_mode else page.tree
    wait_for_stable_geometry(qt_application, (view, page._command_bar))
    assert page.rect().bottom() - mapped_rect(page._command_bar, page).bottom() == 8
    assert min(mapped_rect(control, page).top() for control in page._top_controls) == 8
    current_height = view.height()
    control_rects = [mapped_rect(control, page) for control in page._top_controls]
    command_rect = mapped_rect(page._command_bar, page)

    # 在同一窗口复现原有 24+6px 底部外距，比较释放的高度确实回到列表。
    margins = page._page_layout.contentsMargins()
    master_layout = page._master_panel.layout()
    master_margins = master_layout.contentsMargins()
    master_layout.setContentsMargins(
        master_margins.left(), master_margins.top(), master_margins.right(), 6,
    )
    page._page_layout.setContentsMargins(margins.left(), margins.top(), margins.right(), 24)
    wait_for_stable_geometry(qt_application, (view, page._command_bar))
    assert current_height - view.height() == 22
    assert [mapped_rect(control, page) for control in page._top_controls] == control_rects
    previous_command = mapped_rect(page._command_bar, page)
    assert previous_command.left() == command_rect.left() == 32
    assert previous_command.right() == command_rect.right() == page.rect().right() - 32
    page._page_layout.setContentsMargins(margins)
    master_layout.setContentsMargins(master_margins)
    wait_for_stable_geometry(qt_application, (view, page._command_bar))
    assert view.height() == current_height
    assert page.rect().bottom() - mapped_rect(page._command_bar, page).bottom() == 8
