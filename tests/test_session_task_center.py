"""持续会话进入统一列表，但停止受理不能冒充资源已经退出。"""

from dataclasses import replace

import pytest
from PySide6.QtTest import QSignalSpy

from gui.i18n import tr
from gui.pages.tasks_page import TaskCenterPage

pytestmark = pytest.mark.ui


@pytest.fixture
def session_page(qt_application):
    page = TaskCenterPage(external_details=True)
    try:
        assert hasattr(page, "set_session_snapshots"), "任务中心尚未接入持续会话快照"
        yield page
    finally:
        page.shutdown()
        page.close()
        page.deleteLater()


def _session(key="opaque-owner", *, revision="run-1", kind="logcat", state="running",
             owned=True, stop_enabled=True, detail="正在读取日志"):
    from gui.session_tasks import SessionTaskSnapshot
    return SessionTaskSnapshot(
        key=key, revision=revision, kind=kind, state=state, resource_owned=owned,
        stop_enabled=stop_enabled, target_labels=("设备 1 · 测试手机",), detail=detail,
    )


def test_sessions_count_real_resources_independently_of_filters_and_failure(session_page):
    page = session_page
    running = _session()
    failed = _session("other-owner", kind="remote", state="failed", detail="停止失败")
    page.set_session_snapshots((running, failed))
    snapshot = page.navigation_snapshot()
    assert snapshot.active_count == 2
    assert snapshot.unread_count == 1
    page.search_edit.setText("没有匹配内容")
    assert not page.table.rows
    assert page.navigation_snapshot() == snapshot
    assert page.select_entry("session:other-owner", mark_read=False)
    assert page.navigation_snapshot().unread_count == 1
    assert page.select_entry("session:other-owner")
    assert page.navigation_snapshot().unread_count == 0
    page.set_session_snapshots((running, failed))
    assert page.navigation_snapshot().unread_count == 0
    page.set_session_snapshots((running, replace(failed, revision="run-2")))
    assert page.navigation_snapshot().unread_count == 1
    assert page.navigation_snapshot().active_count == 2


def test_stop_routes_exact_revision_and_waits_for_resource_release(session_page):
    page = session_page
    running = _session()
    page.set_session_snapshots((running,))
    requests = QSignalSpy(page.session_stop_requested)
    page.cancel_entry("session:opaque-owner")
    assert requests.count() == 1
    assert list(requests.at(0)) == ["opaque-owner", "run-1"]
    assert page.navigation_snapshot().active_count == 1
    stopping = replace(running, state="stopping", stop_enabled=False)
    page.set_session_snapshots((stopping,))
    page.cancel_entry("session:opaque-owner")
    assert requests.count() == 1
    row = page.detail_row("session:opaque-owner")
    assert row is not None and row.cancelling and row.stop_action
    assert page.navigation_snapshot().active_count == 1
    page.set_session_snapshots((replace(stopping, state="cancelled", resource_owned=False),))
    assert page.navigation_snapshot().active_count == 0
    assert page.navigation_snapshot().success_event_id is None


def test_session_sources_and_bounded_details_keep_original_target(session_page):
    page = session_page
    for kind, source in (("remote", "devices.remote"), ("logcat", "system.logcat"),
                         ("performance", "system.performance")):
        session = _session(kind=kind, detail="安全说明" * 20000)
        page.set_session_snapshots((session,))
        assert page.select_entry("session:opaque-owner")
        row = page.detail_row("session:opaque-owner")
        assert row is not None
        assert row.target == "设备 1 · 测试手机"
        assert row.scope == tr("持续会话")
        assert row.stop_action
        assert page.detail_source(row.key) == source
        assert page.operation_output.isVisibleTo(page.detail)
        assert not page.action_results.isVisibleTo(page.detail)
        assert 0 < len(page.operation_output.toPlainText()) <= 64000
        assert "设备 1 · 测试手机" in page.device_summary.text()


def test_session_disappearance_and_initial_success_do_not_create_completion(session_page):
    page = session_page
    page.set_session_snapshots((_session(state="succeeded", owned=False, stop_enabled=False),))
    assert page.navigation_snapshot().success_event_id is None
    page.set_session_snapshots((_session(),))
    assert page.select_entry("session:opaque-owner")
    page.set_session_snapshots(())
    assert page.navigation_snapshot().active_count == 0
    assert page.navigation_snapshot().success_event_id is None
    assert page.selected_key == ""
    page.shutdown()
    page.set_session_snapshots((_session(),))
    assert not page.recent_rows()
