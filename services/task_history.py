"""任务中心历史视图的有界、线程安全存储（P1-B）。

本模块属于纯服务层（ADR-0004）：不依赖 Qt，可独立单测。历史 store 把两类终态
来源归一为不可变的 :class:`TaskHistoryEntry`：

* vNext 终态快照（:class:`~adblab.application.operations.OperationSnapshot`），
  经 :meth:`TaskHistoryStore.record` 记录；
* 旧版 ``operation_completed(operation, success, message)`` 信号，经
  :meth:`TaskHistoryStore.record_completed` 记录；
* 已构造的 :class:`TaskHistoryEntry` 也可直接经 ``record`` 写入（兼容 P1-A 的
  组合根订阅终态事件的注入路径）。

两类来源共用同一个有界 LRU 缓存：超过容量时淘汰最久未记录（最早插入）的条目，
所有读写都由同一把重入锁保护，可从业务线程与 GUI 线程同时调用。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import RLock

from adblab.application.operations import OperationSnapshot, OperationState

DEFAULT_CAPACITY = 200


@dataclass(frozen=True)
class TaskHistoryEntry:
    """任务中心历史列表中的一条不可变终态记录。

    属性：
    * ``task_id``：操作标识；vNext 快照取 ``operation_id``，旧版信号以操作名作为标识；
    * ``kind``：业务操作种类；
    * ``label``：人类可读标签（旧版信号以操作名回填）；
    * ``success``：是否完全成功（仅 ``succeeded`` 为 True，``partial`` 为 False，
      与旧版 ``operation_completed`` 的 ``success=False`` 语义一致）；
    * ``detail``：终态附加说明（对应快照的 ``message``）；
    * ``state``：终态状态值（:class:`OperationState` 的 ``value``），空串表示未归一；
    * ``finished_at``：写入历史的墙钟时间（epoch 秒）。
    """

    task_id: str
    kind: str
    label: str
    success: bool
    detail: str = ""
    state: str = ""
    finished_at: float = field(default_factory=time.time)


class TaskHistoryStore:
    """维护任务终态历史的有界 LRU 缓存，容量与读写均线程安全。

    不变量：
    * 任意时刻条目数不超过 ``capacity``；
    * 超过容量时淘汰最久未记录（最早插入）的条目（LRU）；
    * :meth:`recent` 返回按写入时间从新到旧的不可变序列，且不改变淘汰顺序；
    * 所有读写都由同一把重入锁保护，可跨线程调用。
    """

    def __init__(
        self,
        capacity: int = DEFAULT_CAPACITY,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self._capacity = int(capacity)
        self._clock = clock or time.time
        self._lock = RLock()
        # 键为单调递增序号：插入顺序即“最近记录”顺序，淘汰时 popitem(last=False)。
        self._entries: OrderedDict[int, TaskHistoryEntry] = OrderedDict()
        self._sequence = 0

    @property
    def capacity(self) -> int:
        """返回当前容量上限。"""

        return self._capacity

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def record(self, item: OperationSnapshot | TaskHistoryEntry) -> TaskHistoryEntry:
        """记录一条终态：接受 vNext 终态快照或已构造的历史条目。

        非终态快照直接拒绝并抛 ``ValueError``；历史条目原样入列。
        """

        if isinstance(item, TaskHistoryEntry):
            return self._append(item)
        return self._append(self._from_snapshot(item))

    def record_completed(
        self,
        operation: str,
        success: bool,
        message: str,
    ) -> TaskHistoryEntry:
        """记录旧版 ``operation_completed`` 信号（无快照身份，kind 即操作名）。"""

        operation = self._non_empty(operation, "operation")
        return self._append(
            TaskHistoryEntry(
                task_id=operation,
                kind=operation,
                label=operation,
                success=bool(success),
                detail=str(message),
                state=(
                    OperationState.SUCCEEDED.value
                    if success
                    else OperationState.FAILED.value
                ),
                finished_at=self._clock(),
            )
        )

    def recent(self, limit: int | None = None) -> tuple[TaskHistoryEntry, ...]:
        """返回从新到旧的最近 ``limit`` 条记录；``limit=None`` 返回全部。"""

        with self._lock:
            items = [self._entries[key] for key in reversed(self._entries)]
            if limit is None:
                return tuple(items)
            count = max(0, int(limit))
            return tuple(items[:count])

    def clear(self) -> None:
        """清空全部历史记录。"""

        with self._lock:
            self._entries.clear()

    def _from_snapshot(self, snapshot: OperationSnapshot) -> TaskHistoryEntry:
        """把 vNext 终态快照归一为历史条目；非终态拒绝。"""

        if not snapshot.is_terminal:
            raise ValueError("task history only accepts terminal snapshots")
        return TaskHistoryEntry(
            task_id=snapshot.operation_id,
            kind=snapshot.kind,
            label=snapshot.kind,
            success=snapshot.state is OperationState.SUCCEEDED,
            detail=snapshot.message,
            state=snapshot.state.value,
            finished_at=self._clock(),
        )

    def _append(self, entry: TaskHistoryEntry) -> TaskHistoryEntry:
        """把条目记为最新，并淘汰超出容量的最旧条目。"""

        with self._lock:
            self._entries[self._sequence] = entry
            self._sequence += 1
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)
            return entry

    @staticmethod
    def _non_empty(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()


__all__ = ["DEFAULT_CAPACITY", "TaskHistoryEntry", "TaskHistoryStore"]
