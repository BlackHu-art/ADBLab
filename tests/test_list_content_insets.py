"""列表内容留白在样式刷新和真实交互后保持，覆盖滚动条仍位于页面边缘。"""

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from gui.dialogs.app_manager import AppManagerPage
from gui.features.file_explorer import FileExplorerPage
from gui.styles import BaseStyles
from gui.styles.fluent import refresh_fluent_widget_style
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry, wait_until

pytestmark = pytest.mark.ui


@pytest.fixture(params=["files", "application_icons", "application_table"])
def content_page(request, qt_application, monkeypatch):
    def unexpected_start(_worker):
        pytest.fail("布局回归不应发起真实设备请求")

    monkeypatch.setattr("gui.workers.file_explorer.ADBWorker.start", unexpected_start)
    monkeypatch.setattr("gui.workers.file_explorer.TransferWorker.start", unexpected_start)
    if request.param == "files":
        page = FileExplorerPage(device_ip="synthetic-device")
        page._on_ls_result("\n".join(
            f"-rw-r--r-- 1 shell shell 1024 Sep 05 sample-{row:03}.txt"
            for row in range(80)
        ), False)
        page.set_workspace_embedded(True)
        view = page.table
        header = view.horizontalHeader()
    else:
        page = AppManagerPage(device_ip="synthetic-device")
        monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
        monkeypatch.setattr(page._icons_controller, "schedule", lambda *args, **kwargs: None)
        monkeypatch.setattr(page.details_page, "activate", lambda *args, **kwargs: None)
        page._populate([
            (f"示例应用 {row}", f"com.example.app{row}", "Enabled", "User")
            for row in range(80)
        ])
        page.prepare_for_workspace()
        if request.param == "application_table":
            page.view_toggle.click()
        view = page.tree if request.param == "application_table" else page.icon_list
        header = view.header()
    page.resize(1040, 760)
    page.show()
    page.activateWindow()
    try:
        yield page, view, header
    finally:
        assert page.request_dispose("test")
        page.close()
        page.deleteLater()
        qt_application.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _assert_reading_edge(page, view, header, qt_application):
    bar = view.scrollDelagate.vScrollBar
    wait_until(qt_application, lambda: bar.isVisible() and bar.maximum() > 0)
    wait_for_stable_geometry(qt_application, (page, view, view.viewport(), header, bar))
    assert mapped_rect(view, page).right() == page.rect().right()
    for content in (view.viewport(), header):
        assert page.rect().right() - mapped_rect(content, page).right() == 32
    assert page.rect().right() - mapped_rect(bar, page).right() == 1


def test_content_inset_survives_style_refresh_focus_and_manual_column_resize(
    content_page, qt_application, monkeypatch,
):
    """检查实际表头、视口及可见轨道，不以 QSS 文本或隐藏滚条作为结果。"""
    page, view, header = content_page
    _assert_reading_edge(page, view, header, qt_application)
    header.resizeSection(1, 960)
    horizontal = view.horizontalScrollBar()
    wait_until(qt_application, lambda: horizontal.maximum() > 0)
    original_accent = BaseStyles.accent_color()
    font_size = [12]
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda cls, role, size=None: QFont("Microsoft YaHei", size or font_size[0]),
    ))
    try:
        for theme, size, width, accent in (
            ("Dark", 12, 1040, "#8B5CF6"),
            ("Light", 20, 820, "#C239B3"),
            ("Dark", 12, 1040, "#0F6CBD"),
        ):
            BaseStyles.switch_theme(theme)
            font_size[0] = size
            BaseStyles.fonts_changed.emit(None)
            BaseStyles.set_accent_color(accent)
            # 与主窗口强调色更新一致，逐个后代刷新，不借页面主题槽修补遗漏。
            for widget in page.findChildren(QWidget):
                refresh_fluent_widget_style(widget)
            page.resize(width, 760)
            _assert_reading_edge(page, view, header, qt_application)
            assert view.font().pointSize() == size
            assert header.sectionSize(1) == 960

            view.clearFocus()
            view.setFocus(Qt.FocusReason.TabFocusReason)
            qt_application.processEvents()
            assert view.hasFocus()
            _assert_reading_edge(page, view, header, qt_application)
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
            _assert_reading_edge(page, view, header, qt_application)
            QTest.keyClick(view, Qt.Key.Key_Down)
            _assert_reading_edge(page, view, header, qt_application)

            assert horizontal.maximum() > 0
            horizontal.setValue(horizontal.maximum())
            qt_application.processEvents()
            last = header.count() - 1
            assert header.sectionViewportPosition(last) >= 0
            assert (
                header.sectionViewportPosition(last) + header.sectionSize(last)
                <= view.viewport().width()
            )
            assert header.sectionSize(1) == 960
            _assert_reading_edge(page, view, header, qt_application)
    finally:
        BaseStyles.set_accent_color(original_accent)
