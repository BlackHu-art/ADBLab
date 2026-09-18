"""应用数量与操作状态并入筛选栏，不再独占底部行。"""

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont

from gui.dialogs.app_manager import AppManagerPage
from gui.styles import BaseStyles
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("width,font_size", [(1040, 12), (540, 12), (720, 22), (340, 22)])
def test_application_status_shares_filter_area_and_releases_bottom_row(
    qt_application, monkeypatch, width, font_size,
):
    monkeypatch.setattr(
        BaseStyles, "font_for_role",
        classmethod(lambda cls, role, size=None: QFont("Arial", size or font_size)),
    )
    page = AppManagerPage(device_ip="status-demo")
    try:
        page._populate([("示例应用", "com.example.demo", "Enabled", "User")])
        page.resize(width, 900)
        page.show()
        wait_for_stable_geometry(qt_application, (*page._top_controls, page.stack))
        status = mapped_rect(page.status_bar, page)
        selection = mapped_rect(page.selection_label, page)
        assert status.bottom() < mapped_rect(page.stack, page).top()
        assert abs(status.center().y() - selection.center().y()) <= 2
        assert status.right() < selection.left()
        assert selection.width() >= page.selection_label.minimumSizeHint().width()
        layout = page._master_panel.layout()
        assert layout.itemAt(layout.count() - 1).widget() is page._command_bar
        assert "1" in page.status_bar.text()
        assert page.status_bar.isVisibleTo(page)
        for control in page._top_controls:
            assert page.rect().contains(mapped_rect(control, page))
    finally:
        page.close()


def test_long_status_retains_full_tooltip_without_changing_filter_geometry(qt_application):
    page = AppManagerPage(device_ip="status-demo")
    try:
        page.resize(1040, 800)
        page.show()
        wait_for_stable_geometry(qt_application, (*page._top_controls, page.stack))
        before = page.stack.mapTo(page, QPoint())
        height = page.status_bar.height()
        message = "设备已离线，仍可查看缓存的应用列表。" * 8
        page.status_bar.setText(message)
        wait_for_stable_geometry(qt_application, (*page._top_controls, page.stack))
        assert page.status_bar.text() == message
        assert page.status_bar.toolTip() == message
        assert page.status_bar.accessibleDescription() == message
        assert not page.status_bar.wordWrap()
        assert page.status_bar.height() == height
        assert page.stack.mapTo(page, QPoint()) == before
        assert page.status_bar.width() < page.status_bar.fontMetrics().horizontalAdvance(message)
    finally:
        page.close()
