"""维护线程安全的业务操作状态和活动操作注册表。"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from threading import RLock

from .cancellation import CancellationToken


class OperationState(str, Enum):
    """定义业务操作从排队到终态的有限状态集合。"""

    QUEUED = "queued"
    RUNNING = "running"
    FINALIZING = "finalizing"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATES


TERMINAL_STATES = frozenset(
    {
        OperationState.SUCCEEDED,
        OperationState.PARTIAL,
        OperationState.FAILED,
        OperationState.CANCELLED,
    }
)

_UNIT_STATES = frozenset(
    {
        OperationState.SUCCEEDED,
        OperationState.FAILED,
        OperationState.CANCELLED,
    }
)


class OperationTransitionError(RuntimeError):
    """活动操作收到非法状态转换时抛出。"""


class IncompleteOperationError(OperationTransitionError):
    """扇出单元尚未全部上报就请求汇总时抛出。"""


class ConflictingOperationResultError(OperationTransitionError):
    """同一单元上报两个不同终态时抛出。"""


@dataclass(frozen=True)
class OperationUnitResult:
    """记录扇出操作中一个执行单元的不可变终态。"""

    unit_id: str
    state: OperationState
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.unit_id, str) or not self.unit_id.strip():
            raise ValueError("unit_id must be a non-empty string")
        if self.state not in _UNIT_STATES:
            raise ValueError("unit result must be succeeded, failed, or cancelled")


@dataclass(frozen=True)
class OperationArtifact:
    """记录操作产物及其可选的来源单元。"""

    path: str
    kind: str
    unit_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("artifact path must be a non-empty string")
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("artifact kind must be a non-empty string")


@dataclass(frozen=True)
class OperationSnapshot:
    """提供某一时刻可安全跨线程读取的业务操作快照。"""

    operation_id: str
    kind: str
    state: OperationState
    unit_ids: tuple[str, ...]
    unit_results: tuple[OperationUnitResult, ...]
    artifacts: tuple[OperationArtifact, ...]
    parent_operation_id: str | None
    cancel_requested: bool
    progress: float
    message: str
    created_at: float
    started_at: float | None
    updated_at: float
    finished_at: float | None
    generation_token: object = field(default_factory=object, repr=False, compare=False)

    @property
    def is_terminal(self) -> bool:
        return self.state.is_terminal


@dataclass
class _OperationEntry:
    snapshot: OperationSnapshot
    token: CancellationToken


class OperationManager:
    """管理业务操作状态，但不拥有线程、进程或 Qt 对象。"""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._lock = RLock()
        self._active: dict[str, _OperationEntry] = {}
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._clock = clock or time.monotonic

    def begin(
        self,
        kind: str,
        *,
        unit_ids: Iterable[str] = (),
        parent_operation_id: str | None = None,
        operation_id: str | None = None,
        generation_token: object | None = None,
    ) -> OperationSnapshot:
        """创建排队状态的活动操作，并拒绝重复标识和重复单元。"""
        normalized_kind = self._non_empty(kind, "kind")
        normalized_units = tuple(self._non_empty(unit, "unit_id") for unit in unit_ids)
        if len(set(normalized_units)) != len(normalized_units):
            raise ValueError("unit_ids must be unique")
        normalized_id = (
            self._non_empty(operation_id, "operation_id")
            if operation_id is not None
            else self._non_empty(self._id_factory(), "operation_id")
        )
        if parent_operation_id is not None:
            parent_operation_id = self._non_empty(
                parent_operation_id,
                "parent_operation_id",
            )
        now = self._clock()
        generation_token = object() if generation_token is None else generation_token
        snapshot = OperationSnapshot(
            operation_id=normalized_id,
            kind=normalized_kind,
            state=OperationState.QUEUED,
            unit_ids=normalized_units,
            unit_results=(),
            artifacts=(),
            parent_operation_id=parent_operation_id,
            cancel_requested=False,
            progress=0.0,
            message="",
            created_at=now,
            started_at=None,
            updated_at=now,
            finished_at=None,
            generation_token=generation_token,
        )
        with self._lock:
            if normalized_id in self._active:
                raise OperationTransitionError(f"Duplicate operation id: {normalized_id}")
            self._active[normalized_id] = _OperationEntry(snapshot, CancellationToken())
            return snapshot

    def get(
        self,
        operation_id: str,
        *,
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> OperationSnapshot | None:
        with self._lock:
            entry = self._matching_entry_locked(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            return entry.snapshot if entry else None

    def active_snapshot(self) -> tuple[OperationSnapshot, ...]:
        with self._lock:
            return tuple(entry.snapshot for entry in self._active.values())

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def token(
        self,
        operation_id: str,
        *,
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> CancellationToken | None:
        with self._lock:
            entry = self._matching_entry_locked(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            return entry.token if entry else None

    def mark_running(
        self,
        operation_id: str,
        *,
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> OperationSnapshot | None:
        return self._move(
            operation_id,
            OperationState.RUNNING,
            expected_kind=expected_kind,
            expected_generation=expected_generation,
        )

    def mark_finalizing(
        self,
        operation_id: str,
        *,
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> OperationSnapshot | None:
        return self._move(
            operation_id,
            OperationState.FINALIZING,
            expected_kind=expected_kind,
            expected_generation=expected_generation,
        )

    def request_cancel(
        self,
        operation_id: str,
        *,
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> bool:
        """设置协作式取消意图，仅首次有效请求返回 True。"""
        with self._lock:
            entry = self._matching_entry_locked(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if entry is None:
                return False
            first_request = entry.token.request()
            if first_request:
                now = self._clock()
                entry.snapshot = replace(
                    entry.snapshot,
                    cancel_requested=True,
                    updated_at=now,
                )
            return first_request

    def cancel_pending_units(
        self,
        operation_id: str,
        *,
        unit_message: str = "Operation cancelled",
        message: str = "",
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> OperationSnapshot | None:
        """原子取消未完成单元、汇总终态并移除活动操作。"""
        with self._lock:
            entry = self._matching_entry_locked(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if entry is None:
                return None
            current = entry.snapshot
            if not current.unit_ids:
                raise OperationTransitionError("operation has no fan-out units")
            entry.token.request()
            completed_units = {result.unit_id for result in current.unit_results}
            cancelled = tuple(
                OperationUnitResult(
                    unit_id,
                    OperationState.CANCELLED,
                    str(unit_message),
                )
                for unit_id in current.unit_ids
                if unit_id not in completed_units
            )
            entry.snapshot = replace(
                current,
                cancel_requested=True,
                unit_results=(*current.unit_results, *cancelled),
                updated_at=self._clock(),
            )
            return self._finish_from_unit_results_locked(entry, str(message))

    def update_progress(
        self,
        operation_id: str,
        progress: float,
        *,
        message: str | None = None,
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> OperationSnapshot | None:
        guarded = expected_kind is not None or expected_generation is not None
        if not guarded:
            value = float(progress)
            if not 0.0 <= value <= 100.0:
                raise ValueError("progress must be between 0 and 100")
        with self._lock:
            entry = self._matching_entry_locked(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if entry is None:
                return None
            if guarded:
                value = float(progress)
                if not 0.0 <= value <= 100.0:
                    raise ValueError("progress must be between 0 and 100")
            current = entry.snapshot
            if value < current.progress:
                raise OperationTransitionError("operation progress cannot move backwards")
            entry.snapshot = replace(
                current,
                progress=value,
                message=current.message if message is None else str(message),
                updated_at=self._clock(),
            )
            return entry.snapshot

    def record_unit_result(
        self,
        operation_id: str,
        result: OperationUnitResult,
        *,
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> OperationSnapshot | None:
        with self._lock:
            entry = self._matching_entry_locked(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if entry is None:
                return None
            current = entry.snapshot
            if result.unit_id not in current.unit_ids:
                raise ValueError(f"Unknown operation unit: {result.unit_id}")
            existing = {item.unit_id: item for item in current.unit_results}
            previous = existing.get(result.unit_id)
            if previous == result:
                return current
            if previous is not None:
                raise ConflictingOperationResultError(
                    f"Conflicting result for unit: {result.unit_id}"
                )
            entry.snapshot = replace(
                current,
                unit_results=(*current.unit_results, result),
                updated_at=self._clock(),
            )
            return entry.snapshot

    def add_artifact(
        self,
        operation_id: str,
        artifact: OperationArtifact,
        *,
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> OperationSnapshot | None:
        with self._lock:
            entry = self._matching_entry_locked(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if entry is None:
                return None
            current = entry.snapshot
            if artifact.unit_id is not None and artifact.unit_id not in current.unit_ids:
                raise ValueError(f"Unknown artifact unit: {artifact.unit_id}")
            if artifact in current.artifacts:
                return current
            entry.snapshot = replace(
                current,
                artifacts=(*current.artifacts, artifact),
                updated_at=self._clock(),
            )
            return entry.snapshot

    def finish(
        self,
        operation_id: str,
        state: OperationState,
        *,
        message: str = "",
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> OperationSnapshot | None:
        """完成非扇出操作，并从活动注册表中原子移除。"""
        guarded = expected_kind is not None or expected_generation is not None
        if not guarded and state not in TERMINAL_STATES:
            raise ValueError("finish state must be terminal")
        with self._lock:
            entry = self._matching_entry_locked(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if entry is None:
                return None
            if guarded and state not in TERMINAL_STATES:
                raise ValueError("finish state must be terminal")
            current = entry.snapshot
            self._validate_transition(current.state, state)
            if current.unit_ids and state in {
                OperationState.SUCCEEDED,
                OperationState.PARTIAL,
            }:
                raise OperationTransitionError(
                    "fan-out success/partial must use finish_from_unit_results"
                )
            return self._finish_locked(entry, state, message)

    def finish_from_unit_results(
        self,
        operation_id: str,
        *,
        message: str = "",
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> OperationSnapshot | None:
        """全部单元上报后汇总终态，并原子移除扇出操作。"""
        with self._lock:
            entry = self._matching_entry_locked(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if entry is None:
                return None
            return self._finish_from_unit_results_locked(entry, message)

    def _finish_from_unit_results_locked(
        self,
        entry: _OperationEntry,
        message: str,
    ) -> OperationSnapshot:
        current = entry.snapshot
        if not current.unit_ids:
            raise OperationTransitionError("operation has no fan-out units")
        if len(current.unit_results) != len(current.unit_ids):
            raise IncompleteOperationError("not all operation units have reported")
        states = {result.state for result in current.unit_results}
        if states == {OperationState.SUCCEEDED}:
            terminal = OperationState.SUCCEEDED
        elif states == {OperationState.CANCELLED}:
            terminal = OperationState.CANCELLED
        elif OperationState.SUCCEEDED in states:
            terminal = OperationState.PARTIAL
        else:
            terminal = OperationState.FAILED
        self._validate_transition(current.state, terminal)
        return self._finish_locked(entry, terminal, message)

    def _move(
        self,
        operation_id: str,
        state: OperationState,
        *,
        expected_kind: str | None = None,
        expected_generation: object | None = None,
    ) -> OperationSnapshot | None:
        with self._lock:
            entry = self._matching_entry_locked(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if entry is None:
                return None
            current = entry.snapshot
            self._validate_transition(current.state, state)
            now = self._clock()
            entry.snapshot = replace(
                current,
                state=state,
                started_at=now if state is OperationState.RUNNING else current.started_at,
                updated_at=now,
            )
            return entry.snapshot

    def _matching_entry_locked(
        self,
        operation_id: str,
        *,
        expected_kind: str | None,
        expected_generation: object | None,
    ) -> _OperationEntry | None:
        entry = self._active.get(operation_id)
        if entry is None:
            return None
        if expected_kind is not None and entry.snapshot.kind != expected_kind:
            return None
        if (
            expected_generation is not None
            and entry.snapshot.generation_token is not expected_generation
        ):
            return None
        return entry

    def _finish_locked(
        self,
        entry: _OperationEntry,
        state: OperationState,
        message: str,
    ) -> OperationSnapshot:
        current = entry.snapshot
        now = self._clock()
        progress = (
            100.0
            if state in {OperationState.SUCCEEDED, OperationState.PARTIAL}
            else current.progress
        )
        terminal = replace(
            current,
            state=state,
            progress=progress,
            message=str(message),
            updated_at=now,
            finished_at=now,
        )
        del self._active[current.operation_id]
        return terminal

    @staticmethod
    def _validate_transition(current: OperationState, target: OperationState) -> None:
        allowed = {
            OperationState.QUEUED: {
                OperationState.RUNNING,
                OperationState.FAILED,
                OperationState.CANCELLED,
            },
            OperationState.RUNNING: {
                OperationState.FINALIZING,
                OperationState.SUCCEEDED,
                OperationState.PARTIAL,
                OperationState.FAILED,
                OperationState.CANCELLED,
            },
            OperationState.FINALIZING: TERMINAL_STATES,
        }.get(current, frozenset())
        if target not in allowed:
            raise OperationTransitionError(
                f"Invalid operation transition: {current.value} -> {target.value}"
            )

    @staticmethod
    def _non_empty(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()
