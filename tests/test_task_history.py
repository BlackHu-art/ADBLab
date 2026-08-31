"""services.task_history 的有界历史 store 测试。"""

from __future__ import annotations

import threading

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
    import pytest

    with pytest.raises(ValueError):
        TaskHistoryStore(capacity=0)
