"""文件页主列表贴边及工具行留白、预览断点的真实几何回归。"""

import pytest
from PySide6.QtGui import QFont

from gui.features.file_explorer import FileExplorerPage
from gui.styles import BaseStyles
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry, wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def scroll_page(qt_application, monkeypatch):
    def unexpected_start(_worker):
        pytest.fail("几何测试不应启动设备请求")

    monkeypatch.setattr("gui.workers.file_explorer.ADBWorker.start", unexpected_start)
    monkeypatch.setattr("gui.workers.file_explorer.TransferWorker.start", unexpected_start)
    page = FileExplorerPage(device_ip="synthetic-device")
    page._on_ls_result("\n".join(
        f"-rw-r--r-- 1 shell shell 1024 Sep 05 sample-{index:03}.txt"
        for index in range(100)
    ), False)
    try:
        yield page
    finally:
        page.close()
        qt_application.processEvents()


@pytest.mark.parametrize("width,font_size,theme", [
    (1120, 12, "light"), (700, 12, "dark"),
    (1120, 22, "dark"), (700, 22, "light"),
])
def test_embedded_file_list_scrollbar_reaches_page_edge_with_control_insets(
    scroll_page, qt_application, monkeypatch, width, font_size, theme,
):
    page = scroll_page
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda cls, role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    BaseStyles.switch_theme(theme)
    page._apply_theme()
    page.set_workspace_embedded(True)
    page.resize(width, 650)
    page.show()
    bar = page.table.scrollDelagate.vScrollBar
    wait_until(qt_application, lambda: bar.isVisible() and bar.maximum() > 0)
    wait_for_stable_geometry(qt_application, [page, page.table, bar, page.search_field])

    assert mapped_rect(page.table, page).left() == 32
    assert mapped_rect(page.table, page).right() == page.rect().right()
    for content in (page.table.viewport(), page.table.horizontalHeader()):
        assert page.rect().right() - mapped_rect(content, page).right() == 32
    assert 0 <= page.rect().right() - mapped_rect(bar, page).right() <= 2
    for control in (page.search_field, page.root_cb, page.status_bar):
        assert page.rect().right() - mapped_rect(control, page).right() == 32
    for control in (page._path_navigation, page.command_bar, page.status_bar):
        assert mapped_rect(control, page).left() == 32
    assert page.rect().bottom() - mapped_rect(page.status_bar, page).bottom() == 8
    assert min(mapped_rect(control, page).top() for control in (
        page._path_navigation, page.path_field, page.search_field,
    )) == 8
    assert page.table.columnWidth(page.NAME_COL) == 360
    if width == 700:
        page.table.setColumnWidth(page.NAME_COL, 960)
        horizontal = page.table.horizontalScrollBar()
        wait_until(qt_application, lambda: horizontal.maximum() > 0)
        horizontal.setValue(horizontal.maximum())
        assert horizontal.value() > 0
        assert page.table.columnWidth(page.NAME_COL) == 960


def test_file_list_embedding_is_idempotent_and_restores_standalone_insets(
    scroll_page, qt_application,
):
    page = scroll_page
    page.resize(1120, 650)
    page.show()
    for embedded in (False, True, True, False, False, True):
        page.set_workspace_embedded(embedded)
        wait_for_stable_geometry(qt_application, [page.table, page.search_field, page.status_bar])
        expected_left, expected_right = (32, 0) if embedded else (8, 8)
        assert mapped_rect(page.table, page).left() == expected_left
        assert page.rect().right() - mapped_rect(page.table, page).right() == expected_right
        for content in (page.table.viewport(), page.table.horizontalHeader()):
            assert page.rect().right() - mapped_rect(content, page).right() == (
                32 if embedded else 10
            )
        for control in (page.search_field, page.root_cb, page.status_bar):
            control_inset = page.rect().right() - mapped_rect(control, page).right()
            assert control_inset == (32 if embedded else 8)
        for control in (page._path_navigation, page.command_bar, page.status_bar):
            assert mapped_rect(control, page).left() == (32 if embedded else 8)
        assert page.rect().bottom() - mapped_rect(page.status_bar, page).bottom() == (
            8 if embedded else 6
        )
        assert page.header_card.isVisible() is (not embedded)


@pytest.mark.parametrize("width,narrow", [(927, True), (928, False)])
def test_embedded_file_preview_preserves_breakpoint_and_pane_scroll_boundary(
    scroll_page, qt_application, width, narrow,
):
    page = scroll_page
    page.set_workspace_embedded(True)
    page.resize(width, 650)
    page.show()
    page._show_text_preview("sample.txt", "line\n" * 100, "/synthetic/sample.txt")
    wait_for_stable_geometry(qt_application, [page, page.browser_panel, page.preview_panel])

    assert page.preview_panel.isVisible()
    assert page.preview_back_btn.isVisible() is narrow
    assert page.browser_panel.isVisible() is (not narrow)
    if narrow:
        assert mapped_rect(page.preview_text_edit, page).left() == 42
    if not narrow:
        bar = page.table.scrollDelagate.vScrollBar
        assert bar.isVisible() and bar.maximum() > 0
        pane_right = page.browser_panel.rect().right()
        assert mapped_rect(page.table, page.browser_panel).right() == pane_right
        assert 0 <= pane_right - mapped_rect(bar, page.browser_panel).right() <= 2
        assert mapped_rect(bar, page).right() < mapped_rect(page.preview_panel, page).left()
        assert mapped_rect(page.preview_text_edit, page.preview_panel).left() == 10


@pytest.mark.parametrize("width,search_row", [(783, 1), (784, 0)])
def test_embedded_file_search_reflow_uses_reading_width(
    scroll_page, qt_application, width, search_row,
):
    page = scroll_page
    page.set_workspace_embedded(True)
    page.resize(width, 650)
    page.show()
    wait_for_stable_geometry(qt_application, [page, page.path_field, page.search_field])

    path_rect = mapped_rect(page.path_field, page)
    search_rect = mapped_rect(page.search_field, page)
    if search_row:
        assert search_rect.top() > path_rect.bottom()
    else:
        assert search_rect.top() == path_rect.top()


@pytest.mark.parametrize("width", [700, 928, 1120])
def test_file_preview_keeps_reading_inset_when_embedding_changes(
    scroll_page, qt_application, width,
):
    page = scroll_page
    page.resize(width, 650)
    page.show()
    page._show_text_preview("sample.txt", "line\n" * 100, "/synthetic/sample.txt")

    for embedded in (False, True, True, False, False, True):
        page.set_workspace_embedded(embedded)
        wait_for_stable_geometry(qt_application, [
            page.preview_panel, page.preview_text_edit, page.preview_close_btn,
        ])
        expected_inset = 42 if embedded else 18
        assert page.preview_text_edit.isVisible()
        text_inset = page.rect().right() - mapped_rect(page.preview_text_edit, page).right()
        assert text_inset == expected_inset
        if page.browser_panel.isVisible():
            assert mapped_rect(page.preview_text_edit, page.preview_panel).left() == 10
        else:
            assert mapped_rect(page.preview_text_edit, page).left() == expected_inset
        if page.preview_close_btn.isVisible():
            button_inset = page.rect().right() - mapped_rect(page.preview_close_btn, page).right()
            assert button_inset == expected_inset

    page._close_preview()
    wait_for_stable_geometry(qt_application, [page.table, page.preview_panel])
    assert not page.preview_panel.isVisible()
    assert mapped_rect(page.table, page).left() == 32
    assert mapped_rect(page.table, page).right() == page.rect().right()


def test_embedded_file_preview_left_inset_follows_narrow_presentation(
    scroll_page, qt_application,
):
    page = scroll_page
    page.set_workspace_embedded(True)
    page.show()
    page._show_text_preview("sample.txt", "line\n" * 100, "/synthetic/sample.txt")
    for width in (1120, 927, 928, 700, 1120):
        page.resize(width, 650)
        wait_for_stable_geometry(qt_application, [page, page.preview_panel, page.preview_text_edit])
        if width < 928:
            assert not page.browser_panel.isVisible()
            assert mapped_rect(page.preview_text_edit, page).left() == 42
        else:
            assert page.browser_panel.isVisible()
            assert mapped_rect(page.preview_text_edit, page.preview_panel).left() == 10
        assert page.rect().right() - mapped_rect(page.preview_text_edit, page).right() == 42


@pytest.mark.parametrize("width", [700, 1120])
def test_embedded_file_bottom_inset_returns_space_to_list(
    scroll_page, qt_application, width,
):
    page = scroll_page
    page.set_workspace_embedded(True)
    page.resize(width, 650)
    page.show()
    layout = page.layout()
    margins = layout.contentsMargins()
    layout.setContentsMargins(margins.left(), margins.top(), margins.right(), 30)
    controls = (
        page._path_navigation, page.path_field, page.search_field, page.command_bar, page.root_cb,
    )
    wait_for_stable_geometry(qt_application, [page.table, page.status_bar, *controls])
    old_list_rect = mapped_rect(page.table, page)
    old_control_rects = [mapped_rect(control, page) for control in controls]

    page.set_workspace_embedded(True)
    wait_for_stable_geometry(qt_application, [page.table, page.status_bar, *controls])

    assert page.rect().bottom() - mapped_rect(page.status_bar, page).bottom() == 8
    assert mapped_rect(page.table, page).height() == old_list_rect.height() + 22
    assert mapped_rect(page.table, page).top() == old_list_rect.top()
    assert [mapped_rect(control, page) for control in controls] == old_control_rects
