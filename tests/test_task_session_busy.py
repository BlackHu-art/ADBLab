"""持续会话的资源活动和阶段忙碌分别投影，测试不启动进程或设备命令。"""

import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QSignalSpy, QTest

from gui.i18n import tr
from gui.pages.tasks_page import TaskCenterPage
from gui.panels.remote_panel import RemotePanel
from gui.panels.remote_panel_scrcpy import RemoteDeviceSession, RemotePanelScrcpy
from gui.session_tasks import SessionTaskRegistry, SessionTaskSnapshot
from gui.styles import BaseStyles
from gui.widgets.task_navigation import TaskNavigationButton, TaskNavigationSnapshot
from services.tasks.action_results import ActionResult, ActionSpec
from services.tasks.operations import OperationManager

pytestmark = pytest.mark.ui


class _RemoteHolder:
    """只承载实际只读投影所需的内存字段，不构造未初始化的 Qt 子类。"""

    task_snapshot = RemotePanel.task_snapshot
    _encoder_probe_owned = RemotePanel._encoder_probe_owned
    request_task_stop = RemotePanel.request_task_stop
    _SESSION_STOPPING = RemotePanel._SESSION_STOPPING

    def __init__(self):
        self._device_sessions = {}
        self._retiring_launch_worker = None
        self._launch_worker = None
        self._orphaned_launch_workers = []
        self._pending_launch_configs = []
        self._session_process_keys = ()
        self._scrcpy_threads = []
        self._warmup_threads = []
        self._warmup_threads_lock = threading.Lock()
        self._remote_futures_lock = threading.Lock()
        self._session_task_input_futures = set()
        self._scrcpy_service = SimpleNamespace(parse_fps=lambda _line: "")
        self._session_task_owned = False
        self._session_task_revision = 0
        self._session_task_members = {}
        self._session_task_labels = {}
        self._session_task_key = "opaque-remote"
        self._session_state = "running"
        self._closing = False
        self.btn_stop = SimpleNamespace(isEnabled=lambda: True)
        self._stop_scrcpy = Mock()

    def window(self):
        return None

    def add(self, device, state="connecting", *, owned=True):
        session = RemoteDeviceSession(
            SimpleNamespace(device=device, no_window=False), state=state,
            key=f"key-{device}", process=object(), resource_owned=owned,
        )
        self._device_sessions[device] = session
        return session


@pytest.fixture
def page(qt_application):
    widget = TaskCenterPage(external_details=True)
    yield widget
    widget.shutdown()
    widget.close()
    widget.deleteLater()


@pytest.fixture
def navigation(qt_application):
    widget = TaskNavigationButton()
    widget.show()
    qt_application.processEvents()
    widget.set_snapshot(TaskNavigationSnapshot())
    yield widget
    widget.shutdown()
    widget.close()
    widget.deleteLater()


def _session(kind="logcat", state="running", **kwargs):
    return SessionTaskSnapshot(kind, "revision", kind, state, True, True, ("设备 1",), **kwargs)


def test_legacy_positional_snapshots_append_optional_busy_fields():
    session = SessionTaskSnapshot(
        "key", "rev", "remote", "running", True, True, (), "detail", "run",
    )
    assert session.run_id == "run" and session.busy is False
    nav = TaskNavigationSnapshot(3, 2, "success")
    assert nav.success_event_id == "success" and nav.busy_count is None


def test_real_remote_connecting_ready_flows_through_registry_page_without_new_revision(page):
    owner = _RemoteHolder()
    member = owner.add("first")
    registry = SessionTaskRegistry(lambda: (owner,))
    updates = QSignalSpy(page.navigation_snapshot_changed)
    connecting = registry.collect()
    page.set_session_snapshots(connecting)
    first = page.navigation_snapshot()
    assert first.active_count == first.busy_count == 1
    member.state = "ready"
    ready = registry.collect()
    assert ready != connecting and ready[0].revision == connecting[0].revision
    page.set_session_snapshots(ready)
    final = page.navigation_snapshot()
    assert final.active_count == 1 and final.busy_count == 0
    assert final.success_event_id is None and updates.count() == 2
    assert registry.request_stop(ready[0].key, ready[0].revision)
    owner._stop_scrcpy.assert_called_once_with()
    assert page.navigation_snapshot().active_count == 1
    registry.shutdown()


@pytest.mark.parametrize(
    "state,owned", [("preparing", False), ("connecting", True), ("stopping", True)],
)
def test_remote_mixed_batch_remains_busy_until_transition_member_released(state, owned):
    owner = _RemoteHolder()
    owner.add("first", "ready")
    second = owner.add("second", state, owned=owned)
    initial = owner.task_snapshot()
    assert initial.resource_owned and initial.busy
    second.state, second.resource_owned = "stopped", False
    settled = owner.task_snapshot()
    assert settled.resource_owned and not settled.busy
    assert settled.revision == initial.revision and settled.state == "running"


def test_remote_ready_launch_queue_preparation_and_drain_are_busy_but_live_reader_is_not():
    owner = _RemoteHolder()
    member = owner.add("first", "ready")
    owner._scrcpy_threads = [SimpleNamespace(is_alive=lambda: True)]
    stable = owner.task_snapshot()
    assert stable.resource_owned and not stable.busy
    owner._pending_launch_configs = [object()]
    assert owner.task_snapshot().busy
    owner._pending_launch_configs.clear()
    owner._launch_worker = object()
    assert owner.task_snapshot().busy
    owner._launch_worker = None
    assert not owner.task_snapshot().busy
    owner._scrcpy_service.encoder_probes_owned = lambda: True
    assert owner.task_snapshot().busy
    owner._scrcpy_service.encoder_probes_owned = lambda: False
    assert not owner.task_snapshot().busy
    owner._session_state = "stopping"
    member.state, member.stop_requested = "stopping", True
    assert owner.task_snapshot().busy
    member.resource_owned, member.state = False, "stopped"
    draining = owner.task_snapshot()
    assert draining.resource_owned and draining.busy
    owner._scrcpy_threads.clear()
    released = owner.task_snapshot()
    assert not released.resource_owned and not released.busy and released.state == "cancelled"


def test_remote_stop_failure_is_static_warning_but_new_preparation_remains_busy(page):
    owner = _RemoteHolder()
    member = owner.add("first", "connecting")
    member.error_type, member.stop_requested = "StopFailed", True
    failed = owner.task_snapshot()
    assert failed.resource_owned and failed.state == "failed" and not failed.busy
    page.set_session_snapshots((failed,))
    assert page.navigation_snapshot().unread_count == 1
    assert page.select_entry(f"session:{failed.key}")
    assert page.navigation_snapshot().unread_count == 0
    owner.add("second", "preparing", owned=False)
    pending = owner.task_snapshot()
    assert pending.busy and pending.revision == failed.revision
    assert page._session_version(pending) == page._session_version(failed)
    page.set_session_snapshots((pending,))
    assert page.navigation_snapshot().busy_count == 1
    assert page.navigation_snapshot().unread_count == 0
    assert page.navigation_snapshot().success_event_id is None


def test_original_process_readiness_rejects_stale_output_and_close_without_fake_ready():
    owner = _RemoteHolder()
    member = owner.add("first")
    controller = RemotePanelScrcpy(owner)
    controller._refresh_sessions = Mock()
    controller._on_scrcpy_output(object(), "INFO: Texture: 100x100")
    assert member.state == "connecting" and owner.task_snapshot().busy
    controller._on_scrcpy_output(member.process, "INFO: FPS: 60")
    assert member.state == "connecting"
    controller._on_scrcpy_output(member.process, "INFO: Texture: 100x100")
    assert member.state == "ready" and not owner.task_snapshot().busy
    member.state = "connecting"
    owner._closing = True
    controller._on_scrcpy_output(member.process, "INFO: Texture: 100x100")
    assert member.state == "connecting"


@pytest.mark.parametrize("kind", ["logcat", "performance", "remote"])
def test_stable_sessions_active_transitions_busy_and_terminal_success_rules(page, kind):
    running = _session(kind)
    page.set_session_snapshots((running,))
    assert page.navigation_snapshot().active_count == 1
    assert page.navigation_snapshot().busy_count == 0
    for state in ("starting", "stopping", "finalizing"):
        page.set_session_snapshots((replace(running, state=state),))
        assert page.navigation_snapshot().active_count == page.navigation_snapshot().busy_count == 1
        assert page.navigation_snapshot().success_event_id is None
    page.set_session_snapshots((replace(running, resource_owned=False, state="succeeded"),))
    success = page.navigation_snapshot().success_event_id
    assert success is not None
    page.set_session_snapshots(())
    assert page.navigation_snapshot().success_event_id == success


def test_short_operations_and_actions_busy_while_stable_sessions_keep_active_count(page):
    manager = OperationManager()
    operation = manager.begin("install")
    manager.mark_running(operation.operation_id)
    page._operation_manager = manager
    page.set_session_snapshots((_session("logcat"), _session("performance")))
    result = ActionResult("request", ActionSpec("install", "apps", "安装"), (), 1,
                          operation_ids=(operation.operation_id,))
    page.present_action_result(result)
    nav = page.navigation_snapshot()
    assert nav.active_count == 3 and nav.busy_count == 1
    page.search_edit.setText("无匹配内容")
    assert page.navigation_snapshot() == nav
    page.present_action_result(ActionResult("other", ActionSpec("query", "system", "查询"), (), 2))
    assert page.navigation_snapshot().active_count == 4
    assert page.navigation_snapshot().busy_count == 2


def test_cancel_error_removal_and_ready_do_not_create_success(page):
    initial = _session("remote", busy=True)
    page.set_session_snapshots((initial,))
    for snapshot in (replace(initial, busy=False), replace(initial, state="failed", busy=False),
                     replace(initial, state="cancelled", resource_owned=False, busy=False)):
        page.set_session_snapshots((snapshot,))
        assert page.navigation_snapshot().success_event_id is None
    page.set_session_snapshots(())
    assert page.navigation_snapshot().success_event_id is None


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_stable_full_ring_pixels_count_and_moving_busy_frames(navigation, theme):
    previous = BaseStyles.current_theme()
    try:
        BaseStyles.switch_theme(theme)
        navigation.set_snapshot(TaskNavigationSnapshot(2, 1, "superseded", busy_count=0))
        stable = navigation.icon().pixmap(24, 24).toImage()
        navigation.set_snapshot(TaskNavigationSnapshot(3, 1, busy_count=0))
        assert stable != navigation.icon().pixmap(24, 24).toImage()
        navigation.set_snapshot(TaskNavigationSnapshot(2, 0, busy_count=0))
        assert stable != navigation.icon().pixmap(24, 24).toImage()
        navigation.set_snapshot(TaskNavigationSnapshot(2, 1, busy_count=0))
        QTest.qWait(120)
        assert stable == navigation.icon().pixmap(24, 24).toImage()
        assert not navigation._animation_timer.isActive()
        assert "2" in navigation.accessibleName() and tr("未读异常") in navigation.accessibleName()
        assert tr("已完成") not in navigation.accessibleName()
        navigation.set_snapshot(TaskNavigationSnapshot(2, 1, busy_count=1))
        busy = navigation.icon().pixmap(24, 24).toImage()
        assert stable != busy
        QTest.qWait(120)
        assert busy != navigation.icon().pixmap(24, 24).toImage()
        navigation.set_snapshot(TaskNavigationSnapshot(2, 1, busy_count=0))
        assert stable == navigation.icon().pixmap(24, 24).toImage()
    finally:
        BaseStyles.switch_theme(previous)


def test_explicit_busy_hidden_minimized_resume_shutdown_and_legacy_animation(
    navigation, qt_application,
):
    navigation.set_snapshot(TaskNavigationSnapshot(1))
    assert navigation._animation_timer.isActive()
    navigation.set_snapshot(TaskNavigationSnapshot(1, busy_count=0))
    navigation.hide()
    navigation.show()
    qt_application.processEvents()
    assert not navigation._animation_timer.isActive()
    navigation.set_snapshot(TaskNavigationSnapshot(1, busy_count=1))
    navigation.set_presentation_enabled(False)
    assert not any(timer.isActive() for timer in navigation.findChildren(QTimer))
    navigation.set_snapshot(TaskNavigationSnapshot(1, busy_count=0))
    navigation.set_presentation_enabled(True)
    assert not navigation._animation_timer.isActive()
    navigation.set_snapshot(TaskNavigationSnapshot(1, busy_count=1))
    assert navigation._animation_timer.isActive()
    navigation.shutdown()
    navigation.set_snapshot(TaskNavigationSnapshot(5, busy_count=5))
    assert not any(timer.isActive() for timer in navigation.findChildren(QTimer))


def test_stop_failed_callback_and_watchdog_remain_static_until_new_work(page):
    owner = _RemoteHolder()
    member = owner.add("first", "stopping")
    member.stop_requested = member.stop_inflight = True
    member.process = SimpleNamespace(poll=lambda: 0)
    owner._scrcpy_service.is_active = lambda _key: True
    controller = RemotePanelScrcpy(owner)
    controller._refresh_sessions = Mock()
    controller._on_device_stop_completed("first", member, False)
    failed = owner.task_snapshot()
    assert member.state == "connecting" and member.error_type == "StopFailed"
    assert not member.stop_inflight and not failed.busy
    page.set_session_snapshots((failed,))
    assert page.navigation_snapshot().active_count == page.navigation_snapshot().unread_count == 1
    for _ in range(2):
        controller._poll_process()
        passive = owner.task_snapshot()
        assert member.state == "stopping" and member.resource_owned
        assert passive.state == "failed" and passive.resource_owned and not passive.busy
        assert passive.revision == failed.revision
        assert page._session_version(passive) == page._session_version(failed)
        page.set_session_snapshots((passive,))
        nav = page.navigation_snapshot()
        assert nav.active_count == nav.unread_count == 1 and nav.busy_count == 0
        assert nav.success_event_id is None
    member.stop_inflight = True
    assert owner.task_snapshot().busy
    member.stop_inflight = False
    owner._session_state = "stopping"
    assert owner.task_snapshot().busy
    owner._session_state = "running"
    other = owner.add("second", "preparing", owned=False)
    assert owner.task_snapshot().busy
    other.state = "stopped"
    owner._pending_launch_configs = [object()]
    assert owner.task_snapshot().busy
    owner._pending_launch_configs.clear()
    assert not owner.task_snapshot().busy
    member.resource_owned = False
    owner._scrcpy_threads = [SimpleNamespace(is_alive=lambda: True)]
    assert owner.task_snapshot().resource_owned and owner.task_snapshot().busy
    owner._scrcpy_threads.clear()
    assert not owner.task_snapshot().resource_owned and not owner.task_snapshot().busy


def test_static_failed_activity_does_not_claim_running_in_accessibility(page, navigation):
    failure = _session("remote", "failed")
    page.set_session_snapshots((failure,))
    navigation.set_snapshot(page.navigation_snapshot())
    assert tr("未读异常") in navigation.accessibleName()
    assert page.select_entry("session:remote")
    navigation.set_snapshot(page.navigation_snapshot())
    expected = f"{tr('任务中心')} · {tr('进行中 {count} 项').format(count=1)}"
    assert navigation.accessibleName() == navigation.toolTip() == expected
    assert not navigation._animation_timer.isActive()
