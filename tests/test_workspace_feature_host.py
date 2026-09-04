"""验证工作台二级页面和设备会话生命周期。"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QWidget
from qfluentwidgets import ComboBox, FluentIcon

from gui.features import FeatureSessionKey, FeatureSessionRegistry
from gui.pages.fluent_pages import WorkspaceAreaPage, WorkspaceSectionPage
from gui.pages.workspace_features import WorkspaceFeatureHost, WorkspaceRoute


class _LifecyclePage(QWidget):
    dispose_ready = Signal(object)

    def __init__(self, key: FeatureSessionKey) -> None:
        super().__init__()
        self.key = key
        self.activations = []
        self.deactivations = []
        self.dispose_reasons = []
        self.dispose_immediately = True

    def activate(self, payload=None) -> None:
        self.activations.append(payload)

    def deactivate(self, reason: str) -> None:
        self.deactivations.append(reason)

    def request_dispose(self, reason: str) -> bool:
        self.dispose_reasons.append(reason)
        return self.dispose_immediately

    def register_shutdown_tasks(self, supervisor, *, owner_id: str, task_prefix: str):
        supervisor(owner_id, task_prefix, self.key)
        return (f"{task_prefix}-worker",)


class _TallLifecyclePage(_LifecyclePage):
    def minimumSizeHint(self) -> QSize:
        return QSize(700, 500)


class _AdaptiveLifecyclePage(_LifecyclePage):
    def __init__(self, key: FeatureSessionKey) -> None:
        super().__init__(key)
        self.required_size = QSize(300, 200)

    def workspace_content_minimum_size(self) -> QSize:
        return QSize(self.required_size)


def test_feature_session_key_normalizes_and_rejects_invalid_values():
    assert FeatureSessionKey(" files ", " device-1 ") == FeatureSessionKey(
        "files",
        "device-1",
    )
    with pytest.raises(ValueError):
        FeatureSessionKey(" ")
    with pytest.raises(ValueError):
        FeatureSessionKey("files", generation=-1)


def test_registry_reuses_stable_session_and_deactivates_previous(qt_application):
    registry = FeatureSessionRegistry()
    created = []

    def factory(key):
        page = _LifecyclePage(key)
        created.append(page)
        return page

    first_key = FeatureSessionKey("files", "device-1")
    second_key = FeatureSessionKey("files", "device-2")
    first, first_created = registry.get_or_create(first_key, factory)
    again, again_created = registry.get_or_create(first_key, factory)
    second, _ = registry.get_or_create(second_key, factory)

    assert first_created is True
    assert again_created is False
    assert again is first
    registry.activate(first_key, {"path": "/sdcard"})
    registry.activate(second_key)

    assert first.activations == [{"path": "/sdcard"}]
    assert first.deactivations == ["navigation"]
    assert second.activations == [None]
    assert len(created) == 2


def test_registry_forwards_shutdown_registration_and_disposal(qt_application):
    registry = FeatureSessionRegistry()
    key = FeatureSessionKey("logcat", "device-1")
    page, _ = registry.get_or_create(key, _LifecyclePage)
    supervisor = Mock()

    task_ids = registry.register_shutdown_tasks(
        supervisor,
        owner_id="application",
        task_prefix="feature",
    )
    assert task_ids == ("feature-logcat-0-worker",)
    supervisor.assert_called_once_with("application", "feature-logcat-0", key)

    page.dispose_immediately = False
    assert registry.request_dispose(key, "user") is False
    assert registry.is_disposing(key) is True
    assert registry.get(key) is page
    with pytest.raises(RuntimeError, match="disposing"):
        registry.get_or_create(key, _LifecyclePage)
    page.dispose_ready.emit(key.generation)
    assert registry.get(key) is None


def test_workspace_host_uses_inline_lazy_device_sessions(qt_application):
    overview = QWidget()
    host = WorkspaceFeatureHost("system", "系统工具", overview)
    created = []

    def factory(key):
        page = _LifecyclePage(key)
        created.append(page)
        return page

    host.register_feature("logcat", "实时日志", FluentIcon.SCROLL, factory)
    host.set_device_context([], ["device-1", "device-2"])
    assert host.open_feature("logcat") is True
    assert host.stack.currentWidget() is host.no_device_page
    assert created == []
    assert host.close_session_button.isHidden()
    assert host.session_badge.text() == "等待选择设备"
    assert host.device_combo.count() == 3
    assert host.device_combo.currentData() == ""

    host.set_device_context(["device-1", "device-2"], ["device-1", "device-2"])
    assert host.open_feature("logcat", preferred_device="device-1") is True
    first = host.stack.currentWidget()
    assert isinstance(first, _LifecyclePage)
    assert first.isWindow() is False
    assert first.key.device_id == "device-1"

    assert host.open_feature("logcat", preferred_device="device-2") is True
    second = host.stack.currentWidget()
    assert isinstance(second, _LifecyclePage)
    assert second is not first
    assert first.deactivations == ["navigation"]

    host.open_feature("logcat", preferred_device="device-1", payload="again")
    assert host.stack.currentWidget() is first
    assert first.activations[-1] == "again"
    assert len(created) == 2


def test_host_exposes_navigation_catalog_without_a_local_feature_selector(
    qt_application,
):
    overview = QWidget()
    remote_page = QWidget()
    activated = []
    routes = []
    host = WorkspaceFeatureHost("devices", "连接与选择", overview)
    host.register_overview_category(
        "remote",
        "屏幕镜像",
        FluentIcon.PROJECTOR,
        page=remote_page,
        requires_device=True,
        activate=lambda device_id: activated.append(device_id),
    )
    host.route_changed.connect(routes.append)
    host.set_device_context(
        ["device-1", "device-2"],
        ["device-1", "device-2"],
    )

    assert [
        (item.feature, item.label)
        for item in host.navigation_items()
    ] == [
        ("overview", "连接与选择"),
        ("remote", "屏幕镜像"),
    ]
    assert host.findChildren(ComboBox) == [host.device_combo]
    assert host.open_route(WorkspaceRoute("devices", "remote")) is True
    assert host.stack.currentWidget() is host.no_device_page
    assert activated == []

    host.device_combo.setCurrentIndex(2)
    assert host.stack.currentWidget() is remote_page
    assert activated == ["device-2"]
    assert routes[-1] == WorkspaceRoute("devices", "remote", "device-2")

    assert host.show_overview() is True
    assert host.stack.currentWidget() is overview
    assert host.session_badge.text() == "操作目标：2 台"


def test_overview_category_switch_resets_inner_scroll_position(qt_application):
    content = QWidget()
    overview = WorkspaceSectionPage("appsOverview", content)
    host = WorkspaceFeatureHost("apps", "日常操作", overview)
    host.register_overview_category(
        "packages",
        "应用包",
        FluentIcon.APPLICATION,
    )
    scrollbar = overview.body.verticalScrollBar()
    scrollbar.setRange(0, 500)
    scrollbar.setValue(180)

    assert host.show_overview("packages") is True
    assert scrollbar.value() == 0


def test_small_workspace_state_messages_wrap_without_clipping(qt_application):
    """无设备和关闭屏障在低高度宿主中仍完整显示两行说明。"""

    host = WorkspaceFeatureHost("apps", "快捷操作", QWidget())
    for page, button in (
        (host.no_device_page, host.no_device_page.choose_button),
        (host.closing_page, host.closing_page.back_button),
    ):
        page.resize(623, 149)
        page.show()
        qt_application.processEvents()

        label = page.message_label
        required_height = label.heightForWidth(label.width())
        assert required_height > 0
        assert label.height() >= required_height
        assert button.isVisibleTo(page)
        assert button.focusPolicy() != Qt.FocusPolicy.NoFocus
        page.hide()


def test_small_workspace_scrolls_deep_feature_without_compressing_it(qt_application):
    """深层功能页在短屏上保留完整布局，由宿主提供双向滚动。"""

    host = WorkspaceFeatureHost("system", "系统工具", QWidget())
    host.register_feature("large", "大型页面", FluentIcon.SCROLL, _TallLifecyclePage)
    host.set_device_context(["device-1"], ["device-1"])
    host.resize(650, 320)
    host.show()
    assert host.open_feature("large") is True
    qt_application.processEvents()

    page = host.stack.currentWidget()
    assert isinstance(page, _TallLifecyclePage)
    assert page.width() >= 700
    assert page.height() >= 500
    assert host.content_scroll.horizontalScrollBar().maximum() > 0
    assert host.content_scroll.verticalScrollBar().maximum() > 0

    host.show_overview()
    qt_application.processEvents()
    assert host.stack.currentWidget() is host.overview
    assert host.content_scroll.horizontalScrollBar().maximum() == 0
    assert host.content_scroll.verticalScrollBar().maximum() == 0


def test_workspace_scroll_extent_tracks_current_page_layout_changes(qt_application):
    host = WorkspaceFeatureHost("apps", "快捷操作", QWidget())
    host.register_feature("adaptive", "自适应页面", FluentIcon.APPLICATION, _AdaptiveLifecyclePage)
    host.set_device_context(["device-1"], ["device-1"])
    host.resize(650, 320)
    host.show()
    host.open_feature("adaptive")
    qt_application.processEvents()

    page = host.stack.currentWidget()
    assert isinstance(page, _AdaptiveLifecyclePage)
    initial_maximum = host.content_scroll.verticalScrollBar().maximum()
    page.required_size = QSize(300, 600)
    page.updateGeometry()
    qt_application.processEvents()
    qt_application.processEvents()

    assert host.stack.minimumHeight() == 600
    assert host.content_scroll.verticalScrollBar().maximum() > initial_maximum


def test_workspace_route_rejects_wrong_host_and_back_does_not_dispose(qt_application):
    host = WorkspaceFeatureHost("apps", "快捷操作", QWidget())
    host.register_feature(
        "manager",
        "应用管理",
        FluentIcon.APPLICATION,
        _LifecyclePage,
    )
    host.set_device_context(["device-1"], ["device-1"])

    assert host.open_route(WorkspaceRoute("system", "manager", "device-1")) is False
    assert host.open_route(WorkspaceRoute("apps", "manager", "device-1")) is True
    page = host.stack.currentWidget()
    host.show_overview()

    assert host.stack.currentWidget() is host.overview
    assert page.deactivations == ["overview"]
    assert page.dispose_reasons == []


def test_closing_inline_session_increments_generation(qt_application):
    host = WorkspaceFeatureHost("devices", "设备概览", QWidget())
    host.register_feature("files", "文件管理", FluentIcon.FOLDER, _LifecyclePage)
    host.set_device_context(["device-1"], ["device-1"])
    host.open_feature("files")
    first = host.stack.currentWidget()

    host.close_current_session()
    host.open_feature("files")
    second = host.stack.currentWidget()

    assert isinstance(first, _LifecyclePage)
    assert isinstance(second, _LifecyclePage)
    assert second is not first
    assert first.dispose_reasons == ["user"]
    assert second.key.generation == 1


def test_closed_offline_session_is_not_silently_recreated(qt_application):
    host = WorkspaceFeatureHost("devices", "设备概览", QWidget())
    host.register_feature("files", "文件管理", FluentIcon.FOLDER, _LifecyclePage)
    host.set_device_context(["device-1"], ["device-1"])
    host.open_feature("files")
    host.set_device_context([], [])

    host.close_current_session()
    host.open_feature("files")

    assert host.stack.currentWidget() is host.no_device_page
    assert all(key.device_id != "device-1" for key in host.registry.keys())


def test_host_preserves_all_device_sessions_and_marks_offline_candidate(qt_application):
    host = WorkspaceFeatureHost("devices", "设备概览", QWidget())
    host.register_feature("files", "文件管理", FluentIcon.FOLDER, _LifecyclePage)
    host.set_device_context(["device-1", "device-2"], ["device-1", "device-2"])
    host.open_feature("files", preferred_device="device-1")
    first = host.stack.currentWidget()
    host.open_feature("files", preferred_device="device-2")

    host.set_device_context(["device-2"], ["device-2"])
    candidates = [host.device_combo.itemData(index) for index in range(host.device_combo.count())]
    labels = [host.device_combo.itemText(index) for index in range(host.device_combo.count())]

    assert candidates == ["device-2", "device-1"]
    assert labels[1].endswith("（离线会话）")
    host.open_feature("files", preferred_device="device-1")
    assert host.stack.currentWidget() is first


def test_host_lists_online_devices_outside_batch_selection(qt_application):
    host = WorkspaceFeatureHost("devices", "连接与选择", QWidget())
    host.register_feature("files", "文件管理", FluentIcon.FOLDER, _LifecyclePage)
    host.set_device_context(["device-1"], ["device-1", "device-2"])

    assert host.open_feature("files") is True
    candidates = [
        host.device_combo.itemData(index)
        for index in range(host.device_combo.count())
    ]

    assert candidates == ["device-1", "device-2"]
    host.device_combo.setCurrentIndex(1)
    assert host.current_device_id == "device-2"
    assert host.stack.currentWidget().key.device_id == "device-2"


def test_batch_selection_growth_does_not_preselect_single_device_session(
    qt_application,
):
    host = WorkspaceFeatureHost("apps", "日常操作", QWidget())
    host.register_feature(
        "manager",
        "应用管理",
        FluentIcon.APPLICATION,
        _LifecyclePage,
    )
    host.set_device_context(["device-1"], ["device-1", "device-2"])
    host.set_device_context(
        ["device-1", "device-2"],
        ["device-1", "device-2"],
    )

    assert host.open_feature("manager") is True
    assert host.stack.currentWidget() is host.no_device_page
    assert host.current_device_id == ""
    assert host.device_combo.currentData() == ""


def test_idle_overview_adopts_new_unique_batch_target_until_user_chooses(
    qt_application,
):
    overview = QWidget()
    remote_page = QWidget()
    host = WorkspaceFeatureHost("devices", "连接与选择", overview)
    host.register_overview_category(
        "remote",
        "屏幕镜像",
        FluentIcon.PROJECTOR,
        page=remote_page,
        requires_device=True,
    )
    host.set_device_context(["device-a"], ["device-a", "device-b"])
    host.show_overview("remote")
    assert host.current_device_id == "device-a"

    host.show_overview()
    host.set_device_context(["device-b"], ["device-a", "device-b"])
    host.show_overview("remote")
    assert host.current_device_id == "device-b"

    host.show_overview("remote", preferred_device="device-a")
    host.show_overview()
    host.set_device_context(["device-b"], ["device-a", "device-b"])
    host.show_overview("remote")
    assert host.current_device_id == "device-a"


def test_workspace_suspends_and_resumes_feature_across_navigation(qt_application):
    devices_host = WorkspaceFeatureHost("devices", "设备概览", QWidget())
    apps_host = WorkspaceFeatureHost("apps", "快捷操作", QWidget())
    devices_host.register_feature("files", "文件管理", FluentIcon.FOLDER, _LifecyclePage)
    apps_host.register_feature("manager", "应用管理", FluentIcon.APPLICATION, _LifecyclePage)
    devices_host.set_device_context(["device-1"], ["device-1"])
    apps_host.set_device_context(["device-1"], ["device-1"])
    devices_page = WorkspaceAreaPage(
        "devicesPage",
        "devices",
        "设备与连接",
        "设备概览",
        devices_host,
        feature_host=devices_host,
    )
    apps_page = WorkspaceAreaPage(
        "appsPage",
        "apps",
        "应用与自动化",
        "应用概览",
        apps_host,
        feature_host=apps_host,
    )

    devices_page.activate()
    devices_page.open_route(WorkspaceRoute("devices", "files", "device-1"))
    files_page = devices_host.stack.currentWidget()
    devices_page.deactivate()
    apps_page.activate()
    apps_page.open_route(WorkspaceRoute("apps", "manager", "device-1"))
    manager_page = apps_host.stack.currentWidget()

    assert files_page.deactivations[-1] == "top_level_navigation"
    apps_page.deactivate()
    assert manager_page.deactivations[-1] == "top_level_navigation"
    activation_count = len(manager_page.activations)
    apps_page.activate()
    assert len(manager_page.activations) == activation_count + 1


def test_activate_route_replaces_hidden_session_without_restoring_old_page(qt_application):
    host = WorkspaceFeatureHost("system", "系统工具", QWidget())
    host.register_feature("logcat", "实时日志", FluentIcon.SCROLL, _LifecyclePage)
    host.register_feature(
        "performance",
        "性能采集",
        FluentIcon.SPEED_HIGH,
        _LifecyclePage,
    )
    host.set_device_context(["device-1"], ["device-1"])
    host.open_feature("logcat")
    logcat_page = host.stack.currentWidget()
    host.deactivate("top_level_navigation")

    assert host.activate_route(
        WorkspaceRoute("system", "performance", "device-1")
    )
    performance_page = host.stack.currentWidget()
    assert isinstance(logcat_page, _LifecyclePage)
    assert isinstance(performance_page, _LifecyclePage)
    assert logcat_page.activations == [None]
    assert logcat_page.deactivations == ["top_level_navigation"]
    assert performance_page.activations == [None]

    host.deactivate("top_level_navigation")
    assert host.activate_route(
        WorkspaceRoute("system", "performance", "device-1")
    )
    assert performance_page.activations == [None, None]


def test_deep_route_back_to_existing_session_activates_page_only_once(qt_application):
    devices_host = WorkspaceFeatureHost("devices", "设备概览", QWidget())
    apps_host = WorkspaceFeatureHost("apps", "快捷操作", QWidget())
    devices_host.register_feature("files", "文件管理", FluentIcon.FOLDER, _LifecyclePage)
    apps_host.register_feature("manager", "应用管理", FluentIcon.APPLICATION, _LifecyclePage)
    for host in (devices_host, apps_host):
        host.set_device_context(["device-1"], ["device-1"])
    devices_page = WorkspaceAreaPage(
        "devicesPage",
        "devices",
        "设备与连接",
        "设备概览",
        devices_host,
        feature_host=devices_host,
    )
    apps_page = WorkspaceAreaPage(
        "appsPage",
        "apps",
        "应用与自动化",
        "应用概览",
        apps_host,
        feature_host=apps_host,
    )
    apps_page.activate()
    apps_page.open_route(WorkspaceRoute("apps", "manager", "device-1"))
    manager_page = apps_host.stack.currentWidget()
    apps_page.deactivate()
    devices_page.activate()
    devices_page.open_route(WorkspaceRoute("devices", "files", "device-1"))
    activation_count = len(manager_page.activations)

    devices_page.deactivate()
    apps_page.activate()
    apps_page.open_route(WorkspaceRoute("apps", "manager", "device-1"))

    assert len(manager_page.activations) == activation_count + 1


def test_inactive_deep_route_activates_target_without_resuming_old_session(
    qt_application,
):
    host = WorkspaceFeatureHost("apps", "快捷操作", QWidget())
    host.register_feature("manager", "应用管理", FluentIcon.APPLICATION, _LifecyclePage)
    host.register_feature("media", "截图结果", FluentIcon.PHOTO, _LifecyclePage)
    host.set_device_context(["device-1"], ["device-1"])
    page = WorkspaceAreaPage(
        "appsPage",
        "apps",
        "应用与自动化",
        "应用概览",
        host,
        feature_host=host,
    )
    page.activate()
    page.open_route(WorkspaceRoute("apps", "manager", "device-1"))
    manager_page = host.stack.currentWidget()
    page.deactivate()
    target_route = WorkspaceRoute(
        "apps",
        "media",
        "device-1",
        {"focus_new": True},
    )

    assert page.open_route(target_route) is True
    assert page.current_route == WorkspaceRoute("apps", "media", "device-1")
    assert manager_page.activations == [None]
    assert all(key.feature != "media" for key in host.registry.keys())

    page.activate()
    media_page = host.stack.currentWidget()

    assert isinstance(media_page, _LifecyclePage)
    assert media_page.key.feature == "media"
    assert manager_page.activations == [None]
    assert manager_page.deactivations == ["top_level_navigation"]
    assert media_page.activations == [{"focus_new": True}]


def test_unknown_workspace_feature_does_not_change_section_or_route(qt_application):
    apps_host = WorkspaceFeatureHost("apps", "快捷操作", QWidget())
    apps_page = WorkspaceAreaPage(
        "appsPage",
        "apps",
        "应用与自动化",
        "应用概览",
        apps_host,
        feature_host=apps_host,
    )
    original_widget = apps_host.stack.currentWidget()
    original_route = apps_page.current_route

    assert apps_page.open_route(WorkspaceRoute("apps", "missing")) is False
    assert apps_host.stack.currentWidget() is original_widget
    assert apps_page.current_route == original_route


def test_no_device_page_retains_route_payload_for_resume(qt_application):
    host = WorkspaceFeatureHost("system", "系统工具", QWidget())
    host.register_feature("logcat", "实时日志", FluentIcon.SCROLL, _LifecyclePage)
    payload = {"package_name": "example.package"}

    assert host.open_feature("logcat", payload=payload) is True
    assert host.pending_route == WorkspaceRoute("system", "logcat", payload=payload)
    callback = Mock()
    host.choose_device_requested.connect(callback)
    host.no_device_page.choose_button.click()
    callback.assert_called_once_with()


def test_async_disposal_cannot_reactivate_closing_session(qt_application):
    host = WorkspaceFeatureHost("system", "系统工具", QWidget())
    host.register_feature("logcat", "实时日志", FluentIcon.SCROLL, _LifecyclePage)
    host.set_device_context(["device-1"], ["device-1"])
    host.open_feature("logcat")
    page = host.stack.currentWidget()
    page.dispose_immediately = False

    host.close_current_session()
    host.show_overview()
    host.open_feature("logcat")

    assert host.stack.currentWidget() is host.closing_page
    assert page.activations == [None]
    assert host.close_session_button.isEnabled() is False
    page.dispose_ready.emit(page.key)
    host.open_feature("logcat")
    reopened = host.stack.currentWidget()
    assert isinstance(reopened, _LifecyclePage)
    assert reopened is not page
    assert reopened.key.generation == 1


def test_shutdown_registration_failure_does_not_skip_later_sessions(qt_application):
    registry = FeatureSessionRegistry()
    first_key = FeatureSessionKey("files", "device-1")
    second_key = FeatureSessionKey("files", "device-2")
    first, _ = registry.get_or_create(first_key, _LifecyclePage)
    second, _ = registry.get_or_create(second_key, _LifecyclePage)
    supervisor = Mock()
    first.register_shutdown_tasks = Mock(side_effect=ValueError("broken"))
    second.register_shutdown_tasks = Mock(return_value=("second-task",))

    with pytest.raises(RuntimeError, match="1 session"):
        registry.register_shutdown_tasks(
            supervisor,
            owner_id="application",
            task_prefix="feature",
        )

    first.register_shutdown_tasks.assert_called_once()
    second.register_shutdown_tasks.assert_called_once()


def test_narrow_workspace_keeps_only_the_session_device_combo(qt_application):
    host = WorkspaceFeatureHost("system", "系统工具", QWidget())
    host.register_feature("logcat", "实时 Logcat", FluentIcon.SCROLL, _LifecyclePage)
    host.register_feature(
        "performance",
        "性能采集",
        FluentIcon.SPEED_HIGH,
        _LifecyclePage,
    )
    host.set_device_context(["device-1"], ["device-1"])
    host.open_feature("performance")
    host.resize(650, 480)
    host.show()
    qt_application.processEvents()

    assert host.findChildren(ComboBox) == [host.device_combo]
    assert host.device_combo.isVisibleTo(host)
    assert host.session_toolbar.minimumSizeHint().width() <= 650


def test_wide_workspace_keeps_session_toolbar_inside_content(qt_application):
    host = WorkspaceFeatureHost("system", "命令与启动", QWidget())
    host.register_feature(
        "performance",
        "性能采集",
        FluentIcon.SPEED_HIGH,
        _LifecyclePage,
    )
    host.set_device_context(["device-1"], ["device-1"])
    host.open_feature("performance")
    host.resize(1100, 480)
    host.show()
    qt_application.processEvents()

    assert host.findChildren(ComboBox) == [host.device_combo]
    assert host.device_combo.isVisibleTo(host)
    assert host.content_column.width() >= 1000
    combo_rect = host.device_combo.geometry()
    assert combo_rect.right() <= host.session_toolbar.contentsRect().right()
    assert host.close_session_button.geometry().right() <= (
        host.session_toolbar.contentsRect().right()
    )
