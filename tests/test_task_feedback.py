"""验证共享抽屉接线、后台状态与已读语义，不执行设备命令。"""

import importlib.util
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QWidget

from gui.pages.tasks_page import TaskCenterPage
from services.tasks.action_results import ActionItem, ActionResult, ActionSpec
from services.tasks.operations import OperationManager
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def task_feedback(qt_application):
    """保留真实页面、抽屉和导航，仅以普通窗口隔离原生无边框边界。"""
    instances = []

    def create(session_registry=None):
        assert importlib.util.find_spec("gui.task_feedback") is not None, (
            "共享任务抽屉协调器尚未实现"
        )
        from gui.task_feedback import TaskFeedbackCoordinator

        window = QWidget()
        window.resize(1000, 720)
        surface = QWidget(window)
        surface.setGeometry(0, 0, 1000, 720)
        manager = OperationManager()
        page = TaskCenterPage(manager, external_details=True, parent=surface)
        page.setGeometry(0, 0, 1000, 720)
        navigation_parent = QWidget(window)
        source_requests = []
        view = {"tasks": False}

        def show_center():
            view["tasks"] = True
            page.show()

        coordinator = TaskFeedbackCoordinator(
            page,
            surface,
            navigation_parent=navigation_parent,
            show_task_center=show_center,
            open_source=source_requests.append,
            is_task_center=lambda: view["tasks"],
            parent=window,
            session_registry=session_registry,
        )
        instances.append((coordinator, page, window))
        window.show()
        page.hide()
        coordinator.navigation_button.show()
        qt_application.processEvents()
        return coordinator, page, manager, view, source_requests

    yield create
    for coordinator, page, window in instances:
        coordinator.shutdown()
        page.shutdown()
        window.close()
        window.deleteLater()


def _result(request="fixture", *, state="running"):
    return ActionResult(
        request,
        ActionSpec("input_text", "apps.packages", "发送文本"),
        ("fixture-target",),
        1.0,
        state=state,
        items=(
            ActionItem("job", "fixture-target", "发送文本", state, "合成结果"),
        ) if state != "running" else (),
        finished_at=2.0 if state != "running" else None,
    )


@pytest.mark.parametrize("state,item_states,allowed", [
    ("running", (), False),
    ("running", ("failed",), False),
    ("succeeded", ("succeeded",), False),
    ("cancelled", ("cancelled",), False),
    ("warning", ("failed",), False),
    ("recorded", (), False),
    ("failed", (), True),
    ("failed", ("failed",), True),
    ("partial", ("succeeded", "failed"), True),
    ("partial", ("succeeded", "succeeded"), True),
    ("partial", ("succeeded", "cancelled"), False),
    ("partial", (), False),
])
def test_automatic_details_require_proven_terminal_failure_but_manual_details_remain(
    task_feedback, state, item_states, allowed,
):
    coordinator, page, _manager, _view, _sources = task_feedback()
    result = replace(_result(state=state), items=tuple(
        ActionItem(str(index), "fixture-target", "发送文本", item_state, "合成结果")
        for index, item_state in enumerate(item_states)
    ))
    page.present_action_result(result)
    key = "action:fixture"
    before = page.navigation_snapshot()
    assert coordinator.open_request("fixture", automatic=True) is allowed
    assert coordinator.drawer.opened is allowed
    assert page.selected_key == (key if allowed else "")
    assert page.navigation_snapshot() == before
    assert page.allows_automatic_details(key) is allowed
    assert not page.allows_automatic_details("action:missing")
    assert page.navigation_snapshot() == before
    assert coordinator.open_request("fixture")
    assert page.selected_key == key
    assert coordinator.drawer.opened
    assert page.navigation_snapshot().unread_count == 0


@pytest.mark.parametrize("latest,allowed", [
    ("error", True), ("success", False), ("info", False), ("warning", False),
])
def test_note_automatic_details_use_latest_event_without_consuming_old_failure(
    task_feedback, latest, allowed,
):
    from services.tasks.action_results import ActionResults

    coordinator, page, _manager, _view, _sources = task_feedback()
    store = ActionResults(page.present_action_result)
    spec = ActionSpec("notes:probe", "devices.remote", "远程控制", "notes")
    original = store.record_note(spec, (), "旧失败", "error")
    result = store.record_note(spec, (), "最新说明", latest)
    assert result.request_id == original.request_id
    assert page.navigation_snapshot().unread_count == 1
    assert coordinator.open_request(result.request_id, automatic=True) is allowed
    assert coordinator.drawer.opened is allowed
    assert page.allows_automatic_details(f"action:{result.request_id}") is allowed
    assert page.navigation_snapshot().unread_count == 1
    assert coordinator.open_request(result.request_id)
    assert page.navigation_snapshot().unread_count == 0
    assert "旧失败" in page.action_results.output.toPlainText()
    assert "最新说明" in page.action_results.output.toPlainText()


@pytest.mark.parametrize("state,allowed", [
    ("starting", False), ("running", False), ("stopping", False),
    ("finalizing", False), ("succeeded", False), ("cancelled", False),
    ("warning", False), ("partial", False), ("failed", True),
])
def test_session_automatic_details_only_accept_explicit_failed_state(
    task_feedback, state, allowed,
):
    from gui.session_tasks import SessionTaskSnapshot

    coordinator, page, _manager, _view, _sources = task_feedback()
    page.set_session_snapshots((SessionTaskSnapshot(
        "owner", "revision", "logcat", state, False, False, ("设备",), "合成会话",
    ),))
    before = page.navigation_snapshot()
    assert coordinator.open_entry("session:owner", automatic=True) is allowed
    assert page.navigation_snapshot() == before
    assert coordinator.open_entry("session:owner")
    assert page.navigation_snapshot().unread_count == 0


def test_hidden_page_refreshes_unlinked_operations_for_global_navigation(
    task_feedback, qt_application,
):
    coordinator, page, manager, _view, _sources = task_feedback()
    assert not page.isVisible()
    operation = manager.begin("batch_install")
    manager.mark_running(operation.operation_id)
    wait_until(qt_application, lambda: page.navigation_snapshot().active_count == 1)
    assert "1" in coordinator.navigation_button.accessibleName()
    assert not coordinator.drawer.opened
    assert not page.isVisible()


def test_auto_open_does_not_acknowledge_failure_and_dismissal_blocks_late_reopen(
    task_feedback, qt_application,
):
    coordinator, page, _manager, _view, _sources = task_feedback()
    failed = _result(state="failed")
    page.present_action_result(failed)
    assert page.navigation_snapshot().unread_count == 1
    assert coordinator.open_request(failed.request_id, automatic=True)
    assert coordinator.drawer.opened
    assert page.navigation_snapshot().unread_count == 1
    coordinator.dismiss()
    assert not coordinator.drawer.opened
    # 动画尚未结束时也不得被同请求晚到终态反向打开。
    assert not coordinator.open_request(failed.request_id, automatic=True)
    wait_until(qt_application, lambda: not coordinator.drawer.isVisible())
    assert coordinator.open_request(failed.request_id)
    assert page.navigation_snapshot().unread_count == 0
    assert page.detail_row("action:fixture") is not None


def test_background_result_does_not_replace_other_selected_reader(task_feedback):
    coordinator, page, _manager, _view, _sources = task_feedback()
    first = _result("first", state="succeeded")
    second = _result("second")
    page.present_action_result(first)
    assert coordinator.open_request("first")
    reader = page.action_results
    page.present_action_result(second)
    assert not coordinator.open_request("second", automatic=True)
    page.present_action_result(replace(second, state="failed", finished_at=3.0))
    assert page.selected_key == "action:first"
    assert page.action_results is reader
    assert coordinator.drawer.selected_key == "action:first"
    assert page.navigation_snapshot().unread_count == 1


def test_drawer_location_clears_filters_without_changing_task_or_targets(task_feedback):
    coordinator, page, _manager, view, _sources = task_feedback()
    result = _result(state="succeeded")
    page.present_action_result(result)
    coordinator.open_request(result.request_id)
    page.search_edit.setText("没有匹配的任务")
    coordinator.drawer.locate_requested.emit("action:fixture")
    assert view["tasks"]
    assert page.search_edit.text() == ""
    assert page.selected_key == "action:fixture"
    assert coordinator.drawer.opened
    assert page.action_results.records_snapshot()[0].targets == ("fixture-target",)


def test_shutdown_stops_background_refresh_and_rejects_late_requests(task_feedback):
    coordinator, page, _manager, _view, _sources = task_feedback()
    page.present_action_result(_result())
    coordinator.open_request("fixture")
    coordinator.shutdown()
    coordinator.shutdown()
    assert not coordinator.refresh_timer.isActive()
    assert not coordinator.drawer.isVisible()
    assert not coordinator.open_request("fixture")


def test_native_mainframe_uses_one_overlay_without_navigating_or_resizing_content(
    qt_application, monkeypatch,
):
    """主窗共享阅读器覆盖正文，打开详情不能改路由或把正文挤窄。"""
    from tests.test_main_window_layout import build_main_frame
    from tests.ui_geometry_helpers import wait_for_stable_geometry
    from tests.ui_lifecycle_helpers import cleanup_ui_windows

    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    frame = build_main_frame()
    try:
        frame.show()
        wait_for_stable_geometry(qt_application, (frame, frame._content_surface))
        coordinator = getattr(frame, "_task_feedback", None)
        assert coordinator is not None, "主窗口尚未安装共享任务抽屉"
        before_page = frame.stackedWidget.currentWidget()
        before_geometry = frame.stackedWidget.geometry()
        frame._task_page.present_action_result(_result(state="failed"))
        frame._action_feedback.open_task("fixture")
        assert coordinator.drawer.opened
        assert coordinator.drawer.parentWidget() is frame._content_surface
        assert coordinator.drawer.isAncestorOf(frame._task_page.detail)
        assert frame.stackedWidget.currentWidget() is before_page
        assert frame.stackedWidget.geometry() == before_geometry
        coordinator.dismiss()
        wait_until(qt_application, lambda: not coordinator.drawer.isVisible())
        assert frame._task_page.selected_key == ""
        assert frame.stackedWidget.geometry() == before_geometry
    finally:
        assert not cleanup_ui_windows((frame,), cleanup_records={})


def test_native_navigation_keeps_global_status_after_route_and_accessibility_sync(
    qt_application, monkeypatch,
):
    """切页及主导航重同步不能把动态任务提示覆盖成静态名称。"""
    from gui.i18n import tr
    from tests.test_main_window_layout import build_main_frame
    from tests.ui_lifecycle_helpers import cleanup_ui_windows

    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    frame = build_main_frame()
    try:
        frame.show()
        qt_application.processEvents()
        coordinator = getattr(frame, "_task_feedback", None)
        assert coordinator is not None, "主窗口尚未安装共享任务状态导航"
        frame._task_page.present_action_result(_result())
        frame._on_nav_requested("tasks")
        frame._sync_navigation_accessibility()
        assert tr("进行中 {count} 项").format(count=1) in (
            coordinator.navigation_button.accessibleName()
        )
        frame._on_nav_requested("apps")
        assert frame._task_page.navigation_snapshot().active_count == 1
        frame._task_page.present_action_result(_result(state="cancelled"))
        assert tr("进行中 {count} 项").format(count=1) not in (
            coordinator.navigation_button.accessibleName()
        )
    finally:
        assert not cleanup_ui_windows((frame,), cleanup_records={})


def test_persistent_owner_updates_while_hidden_and_stops_original_revision(task_feedback):
    from gui.session_tasks import SessionTaskRegistry, SessionTaskSnapshot

    class Owner(QWidget):
        def __init__(self):
            super().__init__()
            self.snapshot = SessionTaskSnapshot(
                "owner", "revision", "logcat", "running", True, True, ("原设备",),
            )
            self.requests = []

        def task_snapshot(self):
            return self.snapshot

        def request_task_stop(self, revision):
            self.requests.append(revision)
            self.snapshot = replace(self.snapshot, state="stopping", stop_enabled=False)
            return True

    owner = Owner()
    registry = SessionTaskRegistry(lambda: (owner,))
    coordinator, page, _manager, _view, _sources = task_feedback(registry)
    coordinator._refresh_hidden_page()
    assert not page.isVisible()
    assert page.navigation_snapshot().active_count == 1
    assert coordinator.open_entry("session:owner")
    assert coordinator.drawer.cancel_button.text() == "停止会话"
    coordinator.drawer.cancel_requested.emit("session:owner")
    assert owner.requests == ["revision"]
    assert page.navigation_snapshot().active_count == 1
    assert coordinator.drawer.cancel_button.text() == "正在停止"
    assert not coordinator.drawer.cancel_button.isEnabled()
    owner.snapshot = replace(owner.snapshot, state="cancelled", resource_owned=False)
    coordinator._refresh_hidden_page()
    assert page.navigation_snapshot().active_count == 0
    assert page.navigation_snapshot().success_event_id is None
    coordinator.shutdown()
    assert registry.collect() == ()
    assert not registry.request_stop("owner", "revision")
    owner.close()


def test_native_all_hidden_sessions_keep_safe_labels_and_original_stop_owner(
    qt_application, monkeypatch,
):
    from gui.features.base import FeatureSessionKey
    from gui.session_tasks import SessionTaskSnapshot
    from tests.test_main_window_layout import build_main_frame
    from tests.ui_lifecycle_helpers import cleanup_ui_windows

    class Owner(QWidget):
        def __init__(self):
            super().__init__()
            self.snapshot = SessionTaskSnapshot(
                "hidden-owner", "original-run", "logcat", "running", True, True,
                ("通用标签",),
            )
            self.requests = []

        def task_snapshot(self):
            return self.snapshot

        def request_task_stop(self, revision):
            self.requests.append(revision)
            self.snapshot = replace(self.snapshot, state="stopping", stop_enabled=False)
            return True

    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    frame = build_main_frame()
    try:
        frame.show()
        host = frame._workspace_feature_hosts["system"]
        key = FeatureSessionKey("logcat", "synthetic-offline-device", 7)
        owner, _created = host.registry.get_or_create(key, lambda _key: Owner())
        assert not owner.isVisible()
        before_keys = host.registry.keys()
        # 全局没有勾选或在线设备；已存在的隐藏 owner 仍须在任务中心保持原归属。
        frame._global_device_bar.set_context([], [], "ready")
        frame._task_feedback._refresh_hidden_page()
        row = frame._task_page.detail_row("session:hidden-owner")
        assert row is not None
        assert row.target == frame._global_device_bar.device_label(key.device_id)
        assert key.device_id not in row.target
        assert frame._task_page.navigation_snapshot().active_count == 1
        assert host.registry.keys() == before_keys
        frame._task_page.cancel_entry(row.key)
        assert owner.requests == ["original-run"]
        assert frame._task_page.navigation_snapshot().active_count == 1
        assert frame._task_page.detail_row(row.key).cancelling
        assert host.registry.keys() == before_keys
    finally:
        assert not cleanup_ui_windows((frame,), cleanup_records={})
