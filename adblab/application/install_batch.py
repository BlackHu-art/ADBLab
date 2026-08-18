"""以纯应用层操作状态协调安装任务扇出。"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import RLock

from .operations import (
    OperationManager,
    OperationSnapshot,
    OperationState,
    OperationTransitionError,
    OperationUnitResult,
)

_MISSING_OWNER = object()


@dataclass(frozen=True)
class InstallRequest:
    device_id: str
    apk_path: str
    apk_name: str

    def __post_init__(self) -> None:
        for name in ("device_id", "apk_path", "apk_name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class InstallUnit:
    unit_id: str
    index: int
    request: InstallRequest


@dataclass(frozen=True)
class InstallBatchOutcome:
    snapshot: OperationSnapshot
    units: tuple[InstallUnit, ...]

    @property
    def failed_units(self) -> tuple[InstallUnit, ...]:
        failed = {
            result.unit_id
            for result in self.snapshot.unit_results
            if result.state is OperationState.FAILED
        }
        return tuple(unit for unit in self.units if unit.unit_id in failed)


@dataclass(frozen=True)
class InstallBatchStart:
    operation_id: str
    units: tuple[InstallUnit, ...]
    terminal: InstallBatchOutcome | None = None


class InstallBatchUseCase:
    """持有安装批次身份，并把状态管理委托给 OperationManager。"""

    def __init__(
        self,
        manager: OperationManager,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._manager = manager
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._lock = RLock()
        self._active_units: dict[str, tuple[InstallUnit, ...]] = {}
        self._active_owner_tokens: dict[str, object | None] = {}
        self._active_kinds: dict[str, str] = {}
        self._active_generations: dict[str, object] = {}
        self._inactive_owner_tokens: dict[str, object | None] = {}
        self._starting_operations: set[str] = set()
        self._start_terminals: dict[str, InstallBatchOutcome] = {}
        self._inflight_units: dict[str, str] = {}

    def start(
        self,
        kind: str,
        requests: Iterable[InstallRequest],
        submit: Callable[[str, InstallUnit], None],
        *,
        parent_operation_id: str | None = None,
        operation_id: str | None = None,
        owner_token: object | None = None,
    ) -> InstallBatchStart:
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("kind must be a non-empty string")
        request_items = tuple(requests)
        if not request_items:
            raise ValueError("requests must not be empty")

        operation_id = (
            self._new_id("operation_id")
            if operation_id is None
            else self._validated_id(operation_id, "operation_id")
        )
        units = tuple(
            InstallUnit(self._new_id("unit_id"), index, request)
            for index, request in enumerate(request_items, start=1)
        )
        normalized_kind = kind.strip()
        generation_token = object()
        reserved = False
        try:
            with self._lock:
                if operation_id in self._active_units:
                    raise OperationTransitionError(f"Duplicate operation id: {operation_id}")
                self._inactive_owner_tokens.pop(operation_id, None)
                self._active_units[operation_id] = units
                self._active_owner_tokens[operation_id] = owner_token
                self._active_kinds[operation_id] = normalized_kind
                self._active_generations[operation_id] = generation_token
                self._starting_operations.add(operation_id)
                reserved = True
                operation = self._manager.begin(
                    normalized_kind,
                    unit_ids=(unit.unit_id for unit in units),
                    parent_operation_id=parent_operation_id,
                    operation_id=operation_id,
                    generation_token=generation_token,
                )
        except Exception as begin_error:
            if reserved:
                with self._lock:
                    self._drop_active_locked(operation_id, owner_token=owner_token)
                    self._starting_operations.discard(operation_id)
                    self._start_terminals.pop(operation_id, None)
            try:
                if reserved and (
                    self._manager.get(
                        operation_id,
                        expected_kind=normalized_kind,
                        expected_generation=generation_token,
                    )
                    is not None
                ):
                    self._manager.finish(
                        operation_id,
                        OperationState.FAILED,
                        message="Install batch begin failed",
                        expected_kind=normalized_kind,
                        expected_generation=generation_token,
                    )
            except Exception as cleanup_error:
                begin_error.add_note(f"Install batch begin cleanup failed: {cleanup_error}")
            raise
        try:
            if (
                self._manager.mark_running(
                    operation.operation_id,
                    expected_kind=normalized_kind,
                    expected_generation=generation_token,
                )
                is None
            ):
                with self._lock:
                    terminal = self._start_terminals.pop(operation.operation_id, None)
                    if terminal is None:
                        self._drop_manager_inactive_locked(
                            operation.operation_id,
                            owner_token,
                        )
                    self._starting_operations.discard(operation.operation_id)
                return InstallBatchStart(operation.operation_id, units, terminal)

            terminal = None
            try:
                for unit in units:
                    with self._lock:
                        reserved, handoff = self._reserve_submission_locked(
                            operation.operation_id,
                            unit.unit_id,
                            owner_token,
                        )
                    if not reserved:
                        terminal = handoff
                        break

                    try:
                        submit(operation.operation_id, unit)
                    except Exception:
                        completed = self.complete(
                            operation.operation_id,
                            unit.unit_id,
                            succeeded=False,
                            message="Install task submission failed",
                            owner_token=owner_token,
                        )
                        if completed is not None:
                            terminal = completed
                    finally:
                        with self._lock:
                            if self._inflight_units.get(operation.operation_id) == unit.unit_id:
                                self._inflight_units.pop(operation.operation_id, None)
                            deferred = self._finalize_cancel_locked(
                                operation.operation_id,
                                owner_token,
                            )
                            if terminal is None and deferred is not None:
                                terminal = deferred

                    with self._lock:
                        active, handoff = self._submission_status_locked(
                            operation.operation_id,
                            owner_token,
                        )
                    if terminal is None:
                        terminal = handoff
                    if terminal is not None or not active:
                        break
            finally:
                with self._lock:
                    if terminal is None:
                        terminal = self._start_terminals.pop(operation.operation_id, None)
                    else:
                        self._start_terminals.pop(operation.operation_id, None)
                    self._starting_operations.discard(operation.operation_id)
                    self._inflight_units.pop(operation.operation_id, None)
            return InstallBatchStart(operation.operation_id, units, terminal)
        except Exception as start_error:
            with self._lock:
                self._drop_active_locked(
                    operation.operation_id,
                    owner_token=owner_token,
                )
                self._starting_operations.discard(operation.operation_id)
                self._start_terminals.pop(operation.operation_id, None)
                self._inflight_units.pop(operation.operation_id, None)
            try:
                if (
                    self._manager.get(
                        operation.operation_id,
                        expected_kind=normalized_kind,
                        expected_generation=generation_token,
                    )
                    is not None
                ):
                    self._manager.finish(
                        operation.operation_id,
                        OperationState.FAILED,
                        message="Install batch start failed",
                        expected_kind=normalized_kind,
                        expected_generation=generation_token,
                    )
            except Exception as cleanup_error:
                start_error.add_note(f"Install batch start cleanup failed: {cleanup_error}")
            raise

    def complete(
        self,
        operation_id: str,
        unit_id: str,
        *,
        succeeded: bool,
        message: str,
        owner_token: object | None = None,
    ) -> InstallBatchOutcome | None:
        with self._lock:
            units = self._owned_units_locked(operation_id, owner_token)
            if units is None:
                return None
            expected_kind, expected_generation = self._manager_identity_locked(operation_id)
            snapshot = self._manager.get(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if snapshot is None:
                self._drop_manager_inactive_locked(operation_id, owner_token)
                return None
            if not any(unit.unit_id == unit_id for unit in units):
                raise ValueError(f"Unknown install unit: {unit_id}")
            if any(result.unit_id == unit_id for result in snapshot.unit_results):
                return None

            state = OperationState.SUCCEEDED if succeeded else OperationState.FAILED
            snapshot = self._manager.record_unit_result(
                operation_id,
                OperationUnitResult(unit_id, state, message),
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if snapshot is None:
                self._drop_manager_inactive_locked(operation_id, owner_token)
                return None
            if len(snapshot.unit_results) != len(units):
                return None
            terminal = self._manager.finish_from_unit_results(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if terminal is None:
                self._drop_manager_inactive_locked(operation_id, owner_token)
                return None
            return self._terminal_outcome_locked(
                operation_id,
                terminal,
                units,
                owner_token,
            )

    def active_unit(
        self,
        operation_id: str,
        unit_id: str,
        *,
        owner_token: object | None = None,
    ) -> InstallUnit | None:
        with self._lock:
            units = self._owned_units_locked(operation_id, owner_token)
            if units is None:
                return None
            expected_kind, expected_generation = self._manager_identity_locked(operation_id)
            if (
                self._manager.get(
                    operation_id,
                    expected_kind=expected_kind,
                    expected_generation=expected_generation,
                )
                is None
            ):
                self._drop_manager_inactive_locked(operation_id, owner_token)
                return None
            return next((unit for unit in units if unit.unit_id == unit_id), None)

    def active_snapshot(
        self,
        operation_id: str,
        *,
        owner_token: object | None = None,
    ) -> OperationSnapshot | None:
        with self._lock:
            if self._owned_units_locked(operation_id, owner_token) is None:
                return None
            expected_kind, expected_generation = self._manager_identity_locked(operation_id)
            snapshot = self._manager.get(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if snapshot is None:
                self._drop_manager_inactive_locked(operation_id, owner_token)
            return snapshot

    def fail(
        self,
        operation_id: str,
        message: str,
        *,
        owner_token: object | None = None,
    ) -> InstallBatchOutcome | None:
        with self._lock:
            units = self._owned_units_locked(operation_id, owner_token)
            if units is None:
                return None
            expected_kind, expected_generation = self._manager_identity_locked(operation_id)
            terminal = self._manager.finish(
                operation_id,
                OperationState.FAILED,
                message=message,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if terminal is None:
                self._drop_manager_inactive_locked(operation_id, owner_token)
                return None
            return self._terminal_outcome_locked(
                operation_id,
                terminal,
                units,
                owner_token,
            )

    def fail_snapshot(
        self,
        snapshot: OperationSnapshot,
        message: str,
    ) -> tuple[bool, object | None, InstallBatchOutcome | None]:
        with self._lock:
            operation_id = snapshot.operation_id
            units = self._active_units.get(operation_id)
            if units is None:
                return False, None, None
            expected_kind, expected_generation = self._manager_identity_locked(operation_id)
            if (
                snapshot.kind != expected_kind
                or snapshot.generation_token is not expected_generation
                or self._manager.get(
                    operation_id,
                    expected_kind=expected_kind,
                    expected_generation=expected_generation,
                )
                is None
            ):
                return False, None, None
            owner_token = self._active_owner_tokens.get(operation_id, _MISSING_OWNER)
            if owner_token is _MISSING_OWNER:
                return False, None, None
            terminal = self._manager.finish(
                operation_id,
                OperationState.FAILED,
                message=message,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if terminal is None:
                self._drop_manager_inactive_locked(operation_id, owner_token)
                return False, None, None
            return (
                True,
                owner_token,
                self._terminal_outcome_locked(
                    operation_id,
                    terminal,
                    units,
                    owner_token,
                ),
            )

    def cancel(
        self,
        operation_id: str,
        *,
        owner_token: object | None = None,
    ) -> InstallBatchOutcome | None:
        _accepted, terminal = self.cancel_owned(
            operation_id,
            owner_token=owner_token,
        )
        return terminal

    def cancel_owned(
        self,
        operation_id: str,
        *,
        owner_token: object,
    ) -> tuple[bool, InstallBatchOutcome | None]:
        with self._lock:
            units = self._owned_units_locked(operation_id, owner_token)
            if units is None:
                return False, None
            expected_kind, expected_generation = self._manager_identity_locked(operation_id)
            snapshot = self._manager.get(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if snapshot is None:
                self._drop_manager_inactive_locked(operation_id, owner_token)
                return False, None

            requested = self._manager.request_cancel(
                operation_id,
                expected_kind=expected_kind,
                expected_generation=expected_generation,
            )
            if not requested:
                snapshot = self._manager.get(
                    operation_id,
                    expected_kind=expected_kind,
                    expected_generation=expected_generation,
                )
                if snapshot is None:
                    self._drop_manager_inactive_locked(operation_id, owner_token)
                    return False, None
                if not snapshot.cancel_requested:
                    return False, None
            if operation_id in self._inflight_units:
                return True, None
            return True, self._finalize_cancel_locked(operation_id, owner_token)

    def retry_failed(
        self,
        outcome: InstallBatchOutcome,
        submit: Callable[[str, InstallUnit], None],
        *,
        operation_id: str | None = None,
        owner_token: object | None = None,
    ) -> InstallBatchStart | None:
        requests = tuple(unit.request for unit in outcome.failed_units)
        if not requests:
            return None
        return self.start(
            outcome.snapshot.kind,
            requests,
            submit,
            parent_operation_id=outcome.snapshot.operation_id,
            operation_id=operation_id,
            owner_token=owner_token,
        )

    def _reserve_submission_locked(
        self,
        operation_id: str,
        unit_id: str,
        owner_token: object | None,
    ) -> tuple[bool, InstallBatchOutcome | None]:
        terminal = self._start_terminals.pop(operation_id, None)
        if terminal is not None:
            return False, terminal
        if self._owned_units_locked(operation_id, owner_token) is None:
            return False, None
        expected_kind, expected_generation = self._manager_identity_locked(operation_id)
        snapshot = self._manager.get(
            operation_id,
            expected_kind=expected_kind,
            expected_generation=expected_generation,
        )
        if snapshot is None:
            self._drop_manager_inactive_locked(operation_id, owner_token)
            return False, None
        if snapshot.cancel_requested:
            return False, self._finalize_cancel_locked(operation_id, owner_token)
        self._inflight_units[operation_id] = unit_id
        return True, None

    def _submission_status_locked(
        self,
        operation_id: str,
        owner_token: object | None,
    ) -> tuple[bool, InstallBatchOutcome | None]:
        terminal = self._start_terminals.pop(operation_id, None)
        if terminal is not None:
            return False, terminal
        if self._owned_units_locked(operation_id, owner_token) is None:
            return False, None
        expected_kind, expected_generation = self._manager_identity_locked(operation_id)
        snapshot = self._manager.get(
            operation_id,
            expected_kind=expected_kind,
            expected_generation=expected_generation,
        )
        if snapshot is None:
            self._drop_manager_inactive_locked(operation_id, owner_token)
            return False, None
        if snapshot.cancel_requested:
            return False, self._finalize_cancel_locked(operation_id, owner_token)
        return True, None

    def _finalize_cancel_locked(
        self,
        operation_id: str,
        owner_token: object | None,
    ) -> InstallBatchOutcome | None:
        if operation_id in self._inflight_units:
            return None
        units = self._owned_units_locked(operation_id, owner_token)
        if units is None:
            return None
        expected_kind, expected_generation = self._manager_identity_locked(operation_id)
        snapshot = self._manager.get(
            operation_id,
            expected_kind=expected_kind,
            expected_generation=expected_generation,
        )
        if snapshot is None:
            self._drop_manager_inactive_locked(operation_id, owner_token)
            return None
        if not snapshot.cancel_requested:
            return None

        completed = {result.unit_id for result in snapshot.unit_results}
        for unit in units:
            if unit.unit_id not in completed:
                snapshot = self._manager.record_unit_result(
                    operation_id,
                    OperationUnitResult(
                        unit.unit_id,
                        OperationState.CANCELLED,
                        "Install batch cancelled",
                    ),
                    expected_kind=expected_kind,
                    expected_generation=expected_generation,
                )
                if snapshot is None:
                    self._drop_manager_inactive_locked(operation_id, owner_token)
                    return None
        terminal = self._manager.finish_from_unit_results(
            operation_id,
            expected_kind=expected_kind,
            expected_generation=expected_generation,
        )
        if terminal is None:
            self._drop_manager_inactive_locked(operation_id, owner_token)
            return None
        return self._terminal_outcome_locked(
            operation_id,
            terminal,
            units,
            owner_token,
        )

    def _terminal_outcome_locked(
        self,
        operation_id: str,
        terminal: OperationSnapshot,
        units: tuple[InstallUnit, ...],
        owner_token: object | None,
    ) -> InstallBatchOutcome:
        if not self._drop_active_locked(operation_id, owner_token=owner_token):
            raise RuntimeError("Install operation ownership changed before cleanup")
        outcome = InstallBatchOutcome(terminal, units)
        if operation_id in self._starting_operations:
            self._start_terminals[operation_id] = outcome
        return outcome

    def _owned_units_locked(
        self,
        operation_id: str,
        owner_token: object | None,
    ) -> tuple[InstallUnit, ...] | None:
        units = self._active_units.get(operation_id)
        if units is None:
            return None
        active_owner = self._active_owner_tokens.get(operation_id, _MISSING_OWNER)
        if active_owner is _MISSING_OWNER or active_owner is not owner_token:
            return None
        return units

    def reconcile_inactive(
        self,
        operation_id: str,
        *,
        owner_token: object | None = None,
    ) -> bool:
        """仅在缓存 generation 已不在 manager 中时回收安装身份。"""
        with self._lock:
            units = self._active_units.get(operation_id)
            if units is None:
                inactive_owner = self._inactive_owner_tokens.get(
                    operation_id,
                    _MISSING_OWNER,
                )
                if inactive_owner is _MISSING_OWNER or inactive_owner is not owner_token:
                    return False
                self._inactive_owner_tokens.pop(operation_id, None)
                return True
            if self._owned_units_locked(operation_id, owner_token) is None:
                return False
            expected_kind, expected_generation = self._manager_identity_locked(operation_id)
            if (
                self._manager.get(
                    operation_id,
                    expected_kind=expected_kind,
                    expected_generation=expected_generation,
                )
                is not None
            ):
                return False
            return self._drop_active_locked(operation_id, owner_token=owner_token)

    def _manager_identity_locked(self, operation_id: str) -> tuple[str, object]:
        return self._active_kinds[operation_id], self._active_generations[operation_id]

    def _drop_manager_inactive_locked(
        self,
        operation_id: str,
        owner_token: object | None,
    ) -> bool:
        if not self._drop_active_locked(operation_id, owner_token=owner_token):
            return False
        if owner_token is not None:
            self._inactive_owner_tokens[operation_id] = owner_token
        return True

    def _drop_active_locked(
        self,
        operation_id: str,
        *,
        owner_token: object | None = _MISSING_OWNER,
    ) -> bool:
        if owner_token is not _MISSING_OWNER:
            active_owner = self._active_owner_tokens.get(operation_id, _MISSING_OWNER)
            if active_owner is _MISSING_OWNER or active_owner is not owner_token:
                return False
        self._active_units.pop(operation_id, None)
        self._active_owner_tokens.pop(operation_id, None)
        self._active_kinds.pop(operation_id, None)
        self._active_generations.pop(operation_id, None)
        self._inactive_owner_tokens.pop(operation_id, None)
        return True

    def _new_id(self, field_name: str) -> str:
        return self._validated_id(self._id_factory(), field_name)

    @staticmethod
    def _validated_id(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()
