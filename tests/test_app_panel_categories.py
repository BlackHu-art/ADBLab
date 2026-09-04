"""验证 Apps 面板分类布局不会改变既有卡片和控件对象。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from qfluentwidgets import HeaderCardWidget

from gui.panels.side_panel import SidePanel

pytestmark = pytest.mark.ui


def _build_apps_panel():
    panel = SidePanel()
    apps = panel._ensure_tab_loaded(0)
    root = panel._tab_scroll_areas[0].widget()
    assert apps is not None
    assert root is not None
    return panel, apps, root


def _direct_card_titles(page) -> tuple[str, ...]:
    return tuple(
        card.title
        for card in page.findChildren(
            HeaderCardWidget,
            options=Qt.FindChildOption.FindDirectChildrenOnly,
        )
    )


def test_app_panel_exposes_stable_category_keys(qt_application):
    panel, apps, root = _build_apps_panel()
    try:
        root.show()
        qt_application.processEvents()

        assert apps.category_stack.category_keys == (
            "daily",
            "packages",
            "monkey",
            "diagnostics",
        )
        assert apps.category_stack.current_key == "daily"
    finally:
        panel.deleteLater()
        qt_application.processEvents()


def test_app_panel_cards_belong_to_expected_categories(qt_application):
    panel, apps, _root = _build_apps_panel()
    try:
        expected = {
            "daily": ("文本与屏幕",),
            "packages": ("应用包管理",),
            "monkey": ("Monkey",),
            "diagnostics": ("报告与日志", "性能诊断"),
        }

        assert {
            key: _direct_card_titles(apps.category_stack.page(key))
            for key in apps.category_stack.category_keys
        } == expected
    finally:
        panel.deleteLater()
        qt_application.processEvents()


def test_app_panel_category_switch_shows_only_selected_page(qt_application):
    panel, apps, root = _build_apps_panel()
    try:
        root.resize(900, 700)
        root.show()
        qt_application.processEvents()

        for selected_key in apps.category_stack.category_keys:
            assert apps.category_stack.set_current(selected_key) is True
            qt_application.processEvents()

            assert apps.category_stack.current_key == selected_key
            assert (
                apps.category_stack.stack.currentWidget()
                is apps.category_stack.page(selected_key)
            )
            for key in apps.category_stack.category_keys:
                page = apps.category_stack.page(key)
                assert page is not None
                assert page.isVisibleTo(apps.category_stack) is (key == selected_key)
    finally:
        panel.deleteLater()
        qt_application.processEvents()
