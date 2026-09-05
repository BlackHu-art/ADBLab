"""验证一级功能导航、共享应用工具和设备工作台的集成行为。"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSize
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QPushButton
from shiboken6 import isValid

from gui.features.app_manager import AppManagerPage
from gui.pages.workspace_features import WorkspaceRoute
from gui.styles import BaseStyles, FontRole
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)
from tests.ui_geometry_helpers import assert_scroll_target_reachable, wait_for_stable_geometry


@pytest.fixture
def frame(qt_application):
    window = build_main_frame()
    window.show()
    qt_application.processEvents()
    yield window
    window._unbind_window_screen()
    window._close_ready = True
    window.close()


@pytest.mark.parametrize(
    ("section", "feature", "key", "title"),
    (
        ("devices", "overview", "devicesPage", "设备概览"),
        ("devices", "files", "filesPage", "文件管理"),
        ("devices", "remote", "remotePage", "远程控制"),
        ("apps", "manager", "appManagerPage", "应用管理"),
        ("apps", "overview", "appsPage", "截图与诊断"),
        ("apps", "media", "screenshotsPage", "截图结果"),
        ("system", "overview", "systemPage", "系统工具"),
        ("system", "logcat", "logcatPage", "实时 Logcat"),
        ("system", "performance", "performancePage", "性能采集"),
    ),
)
def test_sidebar_directly_selects_feature_and_page_title(frame, section, feature, key, title):
    item = frame.navigationInterface.widget(key)
    assert item.treeParent is None
    item.click()
    page = frame._workspace_pages[section]
    assert frame.stackedWidget.currentWidget() is page
    assert page.current_route == WorkspaceRoute(section, feature)
    assert page.header.title_label.text() == title
    assert frame.navigationInterface.panel.currentItem() is item
    host = frame._workspace_feature_hosts[section]
    assert host.feature_pivot.isHidden()
    assert host.feature_combo.isHidden()
    assert frame._global_device_bar.isVisible() == ((section, feature) != ("devices", "overview"))


def test_package_tools_stay_expanded_at_top_of_diagnostics_across_routes(frame):
    apps = frame.left_panel._apps_tab
    frame.navigationInterface.widget("appsPage").click()
    daily = apps.category_stack.page("daily")
    assert daily.layout().itemAt(0).widget() is apps.package_tools_card
    assert apps.package_tools_card.headerLabel.text() == "应用包管理"
    assert apps.program_edit.isVisible()
    assert apps.btn_batch_install.isVisible()
    assert apps.package_tools_card.isAncestorOf(apps.program_edit)
    assert apps.package_tools_card.isAncestorOf(apps.btn_batch_install)
    apps.program_edit.setText("org.example.app")

    frame.navigationInterface.widget("appManagerPage").click()
    assert not apps.program_edit.isVisible()
    assert not apps.btn_batch_install.isVisible()
    frame.navigationInterface.widget("appsPage").click()
    assert apps.program_edit.isVisible()
    assert apps.package_text == "org.example.app"
    assert apps.package_tools_card.parentWidget() is daily


def test_system_legacy_routes_resolve_to_one_page_without_losing_controls(frame):
    system = frame.left_panel._advanced_tab
    for alias in ("settings", "device", "connectivity"):
        assert frame._open_workspace_feature("system", alias)
        assert frame._system_page.current_route == WorkspaceRoute("system", "overview")
        assert system.category_stack.stack.currentWidget() is system.category_stack.page("commands")
        assert frame.navigationInterface.panel.currentItem() is (
            frame.navigationInterface.widget("systemPage")
        )
    assert len(system._system_section_groups) == 9


def test_device_workbench_selection_commits_once_through_device_manager(frame):
    manager = frame.left_panel._devices_tab
    manager.update_device_list(["device-a", "device-b"])
    changes = QSignalSpy(frame.left_panel.selected_devices_changed)
    frame._device_hub.selection_requested.emit(["device-a", "device-b"])
    assert frame.left_panel.selected_devices == ["device-a", "device-b"]
    assert changes.count() == 1


def test_package_alias_and_semantic_back_restore_manager(frame, qt_application):
    assert frame._open_workspace_feature("apps", "packages")
    assert frame._apps_page.current_route.feature == "manager"
    frame.navigationInterface.widget("appsPage").click()
    assert frame._apps_page.current_route.feature == "overview"
    frame.navigationInterface.panel.returnButton.click()
    qt_application.processEvents()
    assert frame._apps_page.current_route.feature == "manager"
    assert frame.navigationInterface.panel.currentItem() is (
        frame.navigationInterface.widget("appManagerPage")
    )


def test_package_tools_preserve_batch_targets_across_device_action_and_close(
    frame, qt_application, monkeypatch
):
    monkeypatch.setattr(AppManagerPage, "_load_apps", lambda _self: None)
    frame._on_devices_updated(["device-a", "device-b"])
    frame._global_device_bar.selection_requested.emit(["device-a", "device-b"])
    apps = frame.left_panel._apps_tab
    frame.navigationInterface.widget("appsPage").click()
    apps.program_edit.setText("org.example.retained")
    frame._device_hub.device_action_requested.emit("apps", "manager", "device-b")
    assert frame._apps_page.current_route == WorkspaceRoute("apps", "manager", "device-b")
    assert frame.left_panel.selected_devices == ["device-a", "device-b"]
    assert not apps.program_edit.isVisible()
    host = frame._workspace_feature_hosts["apps"]
    key = host.registry.current_key
    host.close_current_session()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert host.registry.get(key) is None
    assert isValid(apps.package_tools_card)
    assert isValid(apps.program_edit)
    frame.navigationInterface.widget("appsPage").click()
    assert apps.program_edit.currentText() == "org.example.retained"
    assert apps.btn_batch_install.isVisible()
    calls = QSignalSpy(frame.left_panel.signals.batch_install_requested)
    apps.btn_batch_install.click()
    assert calls.count() == 1
    assert calls.at(0) == [["device-a", "device-b"]]
    assert frame.left_panel.selected_devices == ["device-a", "device-b"]


def test_manager_contains_its_session_and_diagnostics_owns_package_controls(frame, monkeypatch):
    from gui.widgets.collapsible_tools import CollapsibleTools

    monkeypatch.setattr(AppManagerPage, "_load_apps", lambda _self: None)
    frame._on_devices_updated(["device-a"])
    frame.navigationInterface.widget("appManagerPage").click()
    host = frame._workspace_feature_hosts["apps"]
    assert host.registry.get(host.registry.current_key) is host.stack.currentWidget()
    assert isinstance(host.stack.currentWidget(), AppManagerPage)
    apps = frame.left_panel._apps_tab
    assert not host.stack.currentWidget().isAncestorOf(apps.program_edit)
    frame.navigationInterface.widget("appsPage").click()
    assert apps.program_edit.isVisible()
    daily = apps.category_stack.page("daily")
    assert not daily.findChildren(CollapsibleTools)
    titles = [daily.layout().itemAt(i).widget().headerLabel.text() for i in range(5)]
    assert titles == ["应用包管理", "文本与屏幕", "Monkey", "报告与日志", "性能诊断"]


def test_package_tools_follow_live_font_changes_and_keep_unique_history(frame, monkeypatch):
    apps = frame.left_panel._apps_tab
    for package in ("org.example.first", "org.example.second", "org.example.first"):
        apps.add_package_to_history(package)
    assert [apps.program_edit.itemText(i) for i in range(2)] == [
        "org.example.first", "org.example.second",
    ]
    assert apps.program_edit.count() == 2
    assert apps.package_text == "org.example.first"

    from core.settings_manager import AppSettings
    settings = _MainFrameSettings()
    settings.values["ui_font_size"] = 22
    monkeypatch.setattr(AppSettings, "instance", lambda: settings)
    BaseStyles.reload_from_settings()
    assert apps.program_edit.font() == BaseStyles.font_for_role(FontRole.MONO)
    assert apps.btn_batch_install.font() == BaseStyles.font_for_role(FontRole.UI)
    assert apps.package_tools_card.headerLabel.font() == BaseStyles.font_for_role(FontRole.TITLE)
    frame.navigationInterface.widget("appManagerPage").click()
    frame.navigationInterface.widget("appsPage").click()
    assert apps.program_edit.isVisible()
    assert apps.package_text == "org.example.first"


def test_large_font_package_controls_remain_reachable_on_small_screen(
    qt_application, monkeypatch
):
    from core.settings_manager import AppSettings

    settings = _MainFrameSettings()
    settings.values.update(ui_font_size=22, window_width=500, window_height=700)
    monkeypatch.setattr(AppSettings, "instance", lambda: settings)
    BaseStyles.reload_from_settings()
    window = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("small", QSize(500, 700))),
        settings=settings,
    )
    window.show()
    try:
        window.navigationInterface.widget("appsPage").click()
        apps = window.left_panel._apps_tab
        scroll = window.left_panel._tab_scroll_areas[0]
        wait_for_stable_geometry(qt_application, (window, scroll, apps.package_tools_card))
        assert apps.package_tools_card.isVisible()
        for target in (
            apps.program_edit,
            *apps.package_tools_card.findChildren(QPushButton),
            apps.btn_netstats,
        ):
            assert_scroll_target_reachable(scroll, target)
    finally:
        window._unbind_window_screen()
        window._close_ready = True
        window.close()
