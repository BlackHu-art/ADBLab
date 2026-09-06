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


@pytest.mark.parametrize(
    ("language", "file_title", "empty_title", "about_title", "project_link"),
    (
        ("en_US", "Files", "Select a device for Files", "About", "Project home"),
        ("zh_HK", "檔案管理", "檔案管理需要選擇裝置", "關於", "專案主頁"),
    ),
)
def test_translated_shell_keeps_navigation_routes_and_empty_state(
    qt_application, monkeypatch, language, file_title, empty_title, about_title, project_link,
):
    from core.settings_manager import AppSettings
    from gui.i18n import install_translators

    settings = _MainFrameSettings()
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    translators = install_translators(qt_application, language)
    window = None
    try:
        window = build_main_frame(settings=settings)
        window.show()
        qt_application.processEvents()

        item = window.navigationInterface.widget("filesPage")
        item.click()
        host = window._workspace_feature_hosts["devices"]
        assert window._devices_page.current_route == WorkspaceRoute("devices", "files")
        assert window._devices_page.header.title_label.text() == file_title
        assert item.accessibleName() == file_title
        assert item.toolTip() == file_title
        assert host.no_device_page.isVisible()
        assert host.no_device_page.title_label.text() == empty_title

        window.navigationInterface.widget("settingsPage").click()
        about = window._settings_page.about_panel
        window._settings_page.verticalScrollBar().setValue(
            window._settings_page.verticalScrollBar().maximum()
        )
        qt_application.processEvents()
        assert about.isVisible()
        assert about.titleLabel.text() == about_title
        assert about.project_button.text() == project_link
        assert "{version}" not in about.version_label.text()

        page = window._settings_page
        for mode in ("Light", "Dark"):
            page.theme_card.combo_box.setCurrentText(page.THEME_LABELS[mode])
            assert BaseStyles.current_theme() == mode
            assert settings.get("theme") == mode
    finally:
        if window is not None:
            window._unbind_window_screen()
            window._close_ready = True
            window.close()
            window.deleteLater()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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
    frame._global_device_bar.selection_requested.emit(["device-a"])
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


@pytest.fixture
def localized_tools(qt_application, monkeypatch, request):
    """真实翻译器驱动业务控件，设置、设备发现与控制器均由内存替身隔离。"""
    from core.exec import CommandRunner
    from core.settings_manager import DEFAULTS, AppSettings
    from gui.i18n import install_translators
    from gui.main_frame import MainFrame
    from models.device_store import DeviceStore

    language = getattr(request, "param", "en_US")
    settings = _MainFrameSettings()
    settings.values.update(DEFAULTS, language=language, continuous_device_scan=False)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr(MainFrame, "_start_scan_thread", lambda _self: None)
    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda _devices: [])

    def unexpected_command(*_args, **_kwargs):
        pytest.fail("语言控件测试不应执行外部命令")

    monkeypatch.setattr(CommandRunner, "run", unexpected_command)
    translators = install_translators(qt_application, language)
    window = None
    try:
        window = build_main_frame(settings=settings)
        window.show()
        qt_application.processEvents()
        yield window, settings
    finally:
        if window is not None:
            for host in window._workspace_feature_hosts.values():
                host.shutdown()
            window.left_panel.shutdown()
            window._task_page.shutdown()
            window._unbind_window_screen()
            window._close_ready = True
            window.close()
            window.deleteLater()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize(
    ("localized_tools", "quality", "default_size", "recovery"),
    [
        ("en_US", "Quality", "Default", "Recovery"),
        ("zh_CN", "画质优先", "默认", "恢复模式"),
        ("zh_HK", "畫質優先", "預設", "恢復模式"),
    ],
    indirect=["localized_tools"],
)
def test_localized_options_preserve_remote_settings_and_system_commands(
    localized_tools, quality, default_size, recovery,
):
    from services.remote.scrcpy_args import build_scrcpy_args

    window, settings = localized_tools
    window._on_devices_updated(["demo-a"])
    window._global_device_bar.selection_requested.emit(["demo-a"])
    window.navigationInterface.widget("remotePage").click()
    remote = window.left_panel._scrcpy_tab
    for preset, maximum, fps, bitrate, codec, buffer in (
        ("Smooth", "1024", "30", "4", "h264", "50"),
        ("Balanced", "1280", "30", "8", "h264", "20"),
        ("Quality", "1920", "60", "12", "h265", "50"),
        ("Low Latency", "720", "24", "2", "h264", "0"),
    ):
        remote.preset.setCurrentIndex(remote.preset.findData(preset))
        config = remote._scrcpy_config("scrcpy", "demo-a")
        assert all(getattr(remote, key).currentData() for key in (
            "maxsize", "fps", "bitrate", "codec", "buffer", "orientation",
        ))
        args = build_scrcpy_args(config)
        assert args[args.index("-m") + 1] == maximum
        assert (config.fps, config.bitrate, config.codec, config.buffer) == (
            fps, bitrate, codec, buffer,
        )
        assert settings.get("scrcpy_preset") == preset
        assert settings.get("scrcpy_maxsize") == config.maxsize
    remote.preset.setCurrentIndex(remote.preset.findData("Quality"))
    assert remote.preset.currentText() == quality
    assert settings.get("scrcpy_preset") == "Quality"
    assert settings.get("scrcpy_maxsize") == "1920"
    remote.maxsize.setCurrentIndex(remote.maxsize.findData("Default"))
    assert remote.maxsize.currentText() == default_size
    assert settings.get("scrcpy_maxsize") == "Default"
    assert settings.get("scrcpy_preset") == "Custom"
    config = remote._scrcpy_config("scrcpy", "demo-a")
    assert config.maxsize == "Default"
    assert config.device == "demo-a"
    assert config.codec == "h265"
    settings.values.update(scrcpy_preset="Quality", scrcpy_maxsize="1280")
    assert remote.reload_from_settings()
    assert remote.preset.currentText() == quality
    assert remote.maxsize.currentData() == "1280"
    settings.values["scrcpy_maxsize"] = "obsolete-size"
    assert remote.reload_from_settings()
    assert remote.maxsize.currentData() == "1280"

    window.navigationInterface.widget("systemPage").click()
    system = window.left_panel._advanced_tab
    reboot = QSignalSpy(window.left_panel.signals.reboot_mode_requested)
    system.reboot_mode_combo.setCurrentIndex(system.reboot_mode_combo.findData("Recovery"))
    assert system.reboot_mode_combo.currentText() == recovery
    system.btn_reboot_mode.click()
    assert reboot.count() == 1
    assert reboot.at(0) == [["demo-a"], "recovery"]
    system.battery_param.setCurrentIndex(system.battery_param.findData("status"))
    assert system.battery_val.validator().bottom() == 1
    assert system.battery_val.validator().top() == 5
    battery_changes = QSignalSpy(system.signals.battery_set_requested)
    system.battery_val.setText("3")
    system.btn_battery_set.click()
    assert battery_changes.count() == 1
    assert battery_changes.at(0) == [["demo-a"], "status", "3"]
    window.navigationInterface.widget("appsPage").click()
    apps = window.left_panel._apps_tab
    recordings = QSignalSpy(apps.signals.screen_record_batch_requested)
    apps.record_duration.setCurrentIndex(apps.record_duration.findData("60s"))
    apps._on_record_start()
    assert recordings.count() == 1
    assert recordings.at(0)[:2] == [["demo-a"], 60]
    apps.on_recording_target_finished(recordings.at(0)[2], "demo-a")


def test_english_monkey_errors_keep_target_index_and_raw_diagnostics(localized_tools):
    window, _settings = localized_tools
    window._on_devices_updated(["demo-a", "demo-b"])
    window._global_device_bar.selection_requested.emit(["demo-a", "demo-b"])
    window.navigationInterface.widget("appsPage").click()
    apps = window.left_panel._apps_tab
    apps.program_edit.setText("com.example.demo")
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    apps.monkey_get_package_btn.click()
    assert apps.monkey_package_info.text() == "Checking package information on 2 devices…"
    pending = apps._monkey_preparation
    apps.on_monkey_preparation_finished(
        pending.request_id,
        {"success": False, "error": "第 12 台设备未安装目标应用，请先安装后重试"},
    )
    assert apps.monkey_package_info.text() == (
        "The target app is not installed on device 12. Install it and retry"
    )
    assert starts.count() == 0
    assert apps.monkey_get_package_btn.isEnabled()
    apps.monkey_get_package_btn.click()
    pending = apps._monkey_preparation
    raw_message = "vendor-output: 错误原文 [synthetic]"
    apps.on_monkey_preparation_finished(
        pending.request_id, {"success": False, "error": raw_message},
    )
    assert apps.monkey_package_info.text() == raw_message


def test_english_device_states_translate_around_original_metadata(localized_tools):
    window, _settings = localized_tools
    window.navigationInterface.widget("appsPage").click()
    bar = window._global_device_bar
    assert bar.targets_button.isVisible()
    assert bar.targets_button.text() == "Target devices · None selected"
    assert not window.left_panel._apps_tab.monkey_get_package_btn.isEnabled()
    window._on_devices_updated(["demo-a"])
    window._global_device_bar.selection_requested.emit(["demo-a"])
    assert bar.targets_button.text() == "Target devices · 1"
    window.navigationInterface.widget("devicesPage").click()
    metadata = {
        "ip": "demo-a", "name": "原始设备别名", "Battery Level": "82%",
        "Battery Status": "充电中", "Resolution": "1080x1920",
    }
    window._device_hub.set_device_metadata([metadata])
    card = window._device_hub.device_cards[0]
    assert card.isVisible()
    assert card.name_label.text() == "原始设备别名"
    assert card.battery_label.text() == "Battery 82% · Charging"
    assert card.screen_label.text() == "1080x1920"
    assert metadata["Battery Status"] == "充电中"
    window._device_hub.set_device_metadata([dict(metadata, **{"Battery Status": "厂商原值"})])
    assert card.battery_label.text() == "Battery 82% · 厂商原值"


def test_english_task_states_and_cancel_preserve_operation_identity(
    localized_tools, qt_application,
):
    from qfluentwidgets import BodyLabel

    from adblab.application.operations import OperationManager
    from gui.pages.tasks_page import _StatusBadge
    from services.task_history import TaskHistoryEntry

    window, _settings = localized_tools
    manager = OperationManager()
    operation = manager.begin("install")
    manager.mark_running(operation.operation_id)
    page = window._task_page
    page._operation_manager = manager
    raw_detail = "device-output: 原始诊断"
    page._history_store.record(TaskHistoryEntry(
        "known-task", "screenshot", "screenshot", True, state="succeeded",
    ))
    page._history_store.record(TaskHistoryEntry(
        "plugin-task", "plugin_extension", "plugin_extension", False,
        detail=raw_detail, state="failed",
    ))
    window.navigationInterface.widget("tasksPage").click()
    wait_for_stable_geometry(qt_application, (window, page))
    badges = page._active_card.findChildren(_StatusBadge)
    assert [badge.text() for badge in badges if badge.isVisible()] == ["Running"]
    active_labels = page._active_card.findChildren(BodyLabel)
    assert any(label.text().startswith("Install app · ") for label in active_labels)
    history_labels = page._history_card.findChildren(BodyLabel)
    assert any(label.text().startswith("Screenshot · ") for label in history_labels)
    unknown = next(
        label for label in history_labels if label.text().startswith("plugin_extension · ")
    )
    assert unknown.toolTip() == raw_detail
    assert manager.get(operation.operation_id).kind == "install"
    buttons = [button for button in page.findChildren(QPushButton) if button.text() == "Cancel"]
    assert len(buttons) == 1
    assert buttons[0].isVisible()
    buttons[0].click()
    assert manager.get(operation.operation_id).cancel_requested


@pytest.mark.parametrize(
    ("localized_tools", "missing_address"),
    [
        ("en_US", "Please enter IP and port, e.g. 192.168.1.10:5555"),
        ("zh_CN", "请输入 IP 地址和端口，例如 192.168.1.10:5555"),
    ],
    indirect=["localized_tools"],
)
def test_device_connection_errors_translate_and_valid_address_stays_original(
    localized_tools, missing_address,
):
    from gui.widgets.device_context_bar import DeviceConnectionForm

    window, _settings = localized_tools
    form = DeviceConnectionForm([], window)
    form.show()
    connections = QSignalSpy(form.connect_requested)
    form.connect_button.click()
    assert form.error_label.isVisible()
    assert form.error_label.text() == missing_address
    assert connections.count() == 0
    form.address.setText("192.0.2.20:5555")
    form.connect_button.click()
    assert not form.error_label.isVisible()
    assert connections.count() == 1
    assert connections.at(0) == ["192.0.2.20:5555"]
