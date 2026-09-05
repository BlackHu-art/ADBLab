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
        )
        assert apps.category_stack.current_key == "daily"
        assert apps.category_stack.page("monkey") is apps.category_stack.page("daily")
    finally:
        panel.deleteLater()
        qt_application.processEvents()


def test_app_panel_cards_belong_to_expected_categories(qt_application):
    panel, apps, _root = _build_apps_panel()
    try:
        expected = {
            "daily": ("应用包管理", "文本与屏幕", "Monkey", "报告与日志", "性能诊断"),
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


def test_app_action_tips_preserve_function_when_selection_changes(qt_application):
    """缺少设备或包名时仍说明按钮用途，恢复可用后清除过期阻塞原因。"""
    panel, apps, _root = _build_apps_panel()
    try:
        panel._devices_tab.set_selected_devices([])
        apps.program_edit.setText("")
        apps._update_action_states()
        actions = (apps.uninstall_btn, apps.clear_app_data_btn, apps.btn_screenshot)
        for button in actions:
            assert not button.isEnabled()
            assert button.property("functionalToolTip") in button.toolTip()
            assert "请先选择设备" in button.toolTip()
            assert button.accessibleDescription() == button.toolTip()
        assert len({button.toolTip() for button in actions}) == len(actions)

        panel._devices_tab.update_device_list(["demo-device"])
        panel._devices_tab.set_selected_devices(["demo-device"])
        apps._update_action_states()
        assert "请先输入应用包名" in apps.uninstall_btn.toolTip()
        assert "请先选择设备" not in apps.uninstall_btn.toolTip()
        assert apps.btn_screenshot.toolTip() == apps.btn_screenshot.property("functionalToolTip")

        apps.program_edit.setText("com.example.demo")
        apps._update_action_states()
        for button in actions:
            assert button.isEnabled()
            assert button.toolTip() == button.property("functionalToolTip")
            assert button.accessibleDescription() == button.toolTip()
    finally:
        panel.deleteLater()
        qt_application.processEvents()
