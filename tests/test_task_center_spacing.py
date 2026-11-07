"""任务中心与工作区正文对齐，字号增大时仍按内容自然排布。"""

import pytest
from PySide6.QtCore import QPoint

from core.settings_manager import AppSettings
from gui.pages.device_hub import DeviceHubPage
from gui.pages.tasks_page import TaskCenterPage
from gui.pages.workspace_containers import WorkspaceSectionPage
from gui.styles import BaseStyles
from services.tasks.operations import OperationManager
from tests.ui_geometry_helpers import wait_for_stable_geometry


@pytest.mark.parametrize("width,font_size", [(360, 12), (360, 22), (900, 12), (900, 22)])
@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_task_header_aligns_with_workspace_without_clipping(
    qt_application, monkeypatch, width, font_size, theme,
):
    settings = {"ui_font_size": font_size, "font_family": "Arial", "log_font_size": 11}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    device_hub = DeviceHubPage()
    reference_page = WorkspaceSectionPage("deviceSpacingReference", device_hub)
    reference_page.resize(width, 650)
    reference_page.show()
    manager = OperationManager()
    manager.begin("install")
    page = TaskCenterPage(manager)
    page.resize(width, 650)
    page.show()
    try:
        wait_for_stable_geometry(
            qt_application,
            (page, page.filters, page.table, reference_page, device_hub.toolbar),
        )
        filters_origin = page.filters.mapTo(page._scroll.viewport(), QPoint())
        toolbar_origin = device_hub.toolbar.mapTo(reference_page, QPoint())
        assert filters_origin == toolbar_origin == QPoint(32, 8)
        filters_bottom = page.filters.mapTo(page, page.filters.rect().bottomLeft()).y()
        count_top = page.count_label.mapTo(page, QPoint()).y()
        count_bottom = page.count_label.mapTo(page, page.count_label.rect().bottomLeft()).y()
        table_top = page.table.mapTo(page, QPoint()).y()
        assert 0 < count_top - filters_bottom <= 9
        assert 0 < table_top - count_bottom <= 9
        for control in (page.search_edit, page.kind_combo, page.state_combo):
            assert page.filters.rect().contains(control.geometry())
            assert control.height() >= control.fontMetrics().height()
        assert page._scroll.horizontalScrollBar().maximum() == 0
    finally:
        page.shutdown()
        page.close()
        reference_page.close()
