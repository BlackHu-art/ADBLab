"""services.task_history 的有界历史 store 测试。"""

from __future__ import annotations

import threading

import pytest

from adblab.application.operations import OperationManager, OperationState
from services.task_history import TaskHistoryEntry, TaskHistoryStore


def test_record_and_recent_orders_newest_first():
    store = TaskHistoryStore(capacity=5)
    for i in range(3):
        store.record(
            TaskHistoryEntry(task_id=f"t{i}", kind="install", label=f"任务{i}", success=True)
        )
    entries = store.recent()
    assert [e.task_id for e in entries] == ["t2", "t1", "t0"]


def test_capacity_evicts_oldest_lru():
    store = TaskHistoryStore(capacity=2)
    store.record(TaskHistoryEntry(task_id="a", kind="install", label="A", success=True))
    store.record(TaskHistoryEntry(task_id="b", kind="monkey", label="B", success=False))
    store.record(TaskHistoryEntry(task_id="c", kind="record", label="C", success=True))
    assert [e.task_id for e in store.recent()] == ["c", "b"]
    assert len(store) == 2


def test_recent_limit():
    store = TaskHistoryStore(capacity=10)
    for i in range(5):
        store.record(TaskHistoryEntry(task_id=str(i), kind="k", label="L", success=True))
    assert len(store.recent(limit=2)) == 2


def test_clear_empties_store():
    store = TaskHistoryStore(capacity=10)
    store.record(TaskHistoryEntry(task_id="x", kind="k", label="L", success=True))
    store.clear()
    assert store.recent() == ()


def test_thread_safety_concurrent_records():
    store = TaskHistoryStore(capacity=50)
    errors = []

    def writer(offset):
        try:
            for i in range(100):
                store.record(
                    TaskHistoryEntry(
                        task_id=f"{offset}-{i}",
                        kind="k",
                        label="L",
                        success=True,
                    )
                )
        except Exception as exc:  # pragma: no cover - 仅测试线程安全兜底
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(store) == 50


def test_invalid_capacity_rejected():
    with pytest.raises(ValueError):
        TaskHistoryStore(capacity=0)


def test_terminal_snapshot_remains_readable_after_operation_deleted():
    manager = OperationManager(id_factory=lambda: "op-1")
    operation = manager.begin("install")
    manager.mark_running(operation.operation_id)
    terminal = manager.finish(operation.operation_id, OperationState.SUCCEEDED)
    assert terminal is not None

    assert manager.active_count == 0
    store = TaskHistoryStore()
    entry = store.record(terminal)

    assert store.recent() == (entry,)
    assert entry.task_id == operation.operation_id
    assert entry.state == OperationState.SUCCEEDED.value
    assert entry.success is True


def test_record_completed_consumes_compatibility_signal():
    store = TaskHistoryStore()

    entry = store.record_completed("install", False, "boom")

    assert entry.task_id == "install"
    assert entry.state == OperationState.FAILED.value
    assert entry.success is False


def test_record_rejects_non_terminal_snapshot():
    manager = OperationManager(id_factory=lambda: "op-1")
    operation = manager.begin("install")

    store = TaskHistoryStore()
    with pytest.raises(ValueError):
        store.record(operation)
