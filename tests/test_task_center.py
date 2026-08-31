"""任务中心（P1-B）测试：有界历史 store 与 TaskCenterPage 轮询/取消/停表契约。"""

from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QPushButton

from adblab.application.operations import OperationManager, OperationState
from gui.pages.tasks_page import TaskCenterPage
from services.task_history import TaskHistoryStore

# ── services.task_history：有界 / LRU / 线程安全 / 终态消费 ──────────────


def test_history_store_bounded_lru_evicts_oldest():
    store = TaskHistoryStore(capacity=2)
    store.record_completed("a", True, "ok")
    store.record_completed("b", False, "fail")
    store.record_completed("c", True, "ok")

    assert len(store) == 2
    assert [entry.task_id for entry in store.recent()] == ["c", "b"]


def test_history_store_thread_safety_concurrent_records():
    store = TaskHistoryStore(capacity=100)
    errors: list[BaseException] = []

    def writer(offset: int) -> None:
        try:
            for index in range(50):
                store.record_completed(f"{offset}-{index}", True, "ok")
        except Exception as exc:  # pragma: no cover - 仅兜底捕获
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(store) == 100


def test_terminal_snapshot_remains_readable_after_operation_deleted():
    manager = OperationManager(id_factory=lambda: "op-1")
    operation = manager.begin("install")
    manager.mark_running(operation.operation_id)
    terminal = manager.finish(operation.operation_id, OperationState.SUCCEEDED)
    assert terminal is not None

    assert manager.active_count == 0  # 终态即删除
    store = TaskHistoryStore()
    entry = store.record(terminal)

    assert store.recent() == (entry,)
    assert entry.task_id == operation.operation_id
    assert entry.state == OperationState.SUCCEEDED.value
    assert entry.success is True


def test_record_completed_consumes_legacy_signal():
    store = TaskHistoryStore()

    entry = store.record_completed("install", False, "boom")

    assert entry.task_id == "install"
    assert entry.state == OperationState.FAILED.value
    assert entry.success is False


def test_record_rejects_non_terminal_snapshot():
    manager = OperationManager(id_factory=lambda: "op-1")
    operation = manager.begin("install")  # 仍为 QUEUED

    store = TaskHistoryStore()
    with pytest.raises(ValueError):
        store.record(operation)


def test_clear_empties_store():
    store = TaskHistoryStore()
    store.record_completed("a", True, "ok")

    store.clear()

    assert store.recent() == ()
    assert len(store) == 0


# ── TaskCenterPage：轮询 diff / 取消双路径 / 隐藏停表 ─────────────────────


def test_poll_diff_skips_rebuild_when_snapshot_unchanged():
    manager = OperationManager()
    page = TaskCenterPage(operation_manager=manager, history_store=TaskHistoryStore())
    spy = Mock(wraps=page._render_active_rows)
    page._render_active_rows = spy

    page.refresh()
    page.refresh()
    assert spy.call_count == 1  # 快照未变，不重建控件

    manager.begin("install")
    page.refresh()
    assert spy.call_count == 2  # 快照变化，才重建

    page.shutdown()


def test_cancel_dual_path_requests_cancel_and_calls_stop_hook():
    manager = OperationManager()
    operation = manager.begin("install")
    manager.mark_running(operation.operation_id)
    stop_hook = Mock()
    page = TaskCenterPage(operation_manager=manager, stop_hook=stop_hook)

    page._cancel(operation.operation_id)

    snapshot = manager.get(operation.operation_id)
    assert snapshot is not None
    assert snapshot.cancel_requested is True
    stop_hook.assert_called_once_with(operation.operation_id)
    page.shutdown()


def test_cancel_button_triggers_dual_path():
    manager = OperationManager()
    operation = manager.begin("install")
    manager.mark_running(operation.operation_id)
    stop_hook = Mock()
    page = TaskCenterPage(operation_manager=manager, stop_hook=stop_hook)
    page.refresh()

    cancel_buttons = [
        button for button in page.findChildren(QPushButton) if button.text() == "取消"
    ]
    assert len(cancel_buttons) == 1
    cancel_buttons[0].click()

    snapshot = manager.get(operation.operation_id)
    assert snapshot is not None
    assert snapshot.cancel_requested is True
    stop_hook.assert_called_once_with(operation.operation_id)
    page.shutdown()


def test_hide_stops_poll_timer_and_show_starts_it():
    page = TaskCenterPage(operation_manager=OperationManager())

    page.show()
    assert page._poll_timer.isActive()

    page.hide()
    assert not page._poll_timer.isActive()

    page.shutdown()
