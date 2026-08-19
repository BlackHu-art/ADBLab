"""以纯应用层操作状态协调多设备批次操作的收口。"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import RLock

from .operations import (
    IncompleteOperationError,
    OperationManager,
    OperationSnapshot,
    OperationState,
    OperationTransitionError,
    OperationUnitResult,
)


@dataclass(frozen=True)
class DeviceBatchUnit:
    """记录批次中单个设备执行单元的身份。"""

    unit_id: str
    device: str

    def __post_init__(self) -> None:
        if not isinstance(self.unit_id, str) or not self.unit_id.strip():
            raise ValueError("unit_id must be a non-empty string")
        if not isinstance(self.device, str) or not self.device.strip():
            raise ValueError("device must be a non-empty string")


@dataclass(frozen=True)
class DeviceBatchStart:
    """记录已创建批次的操作标识、类型与执行单元。"""

    operation_id: str
    kind: str
    units: tuple[DeviceBatchUnit, ...]


@dataclass(frozen=True)
class DeviceBatchOutcome:
    """汇总批次终态，暴露成功标记、用户文案与失败设备列表。"""

    snapshot: OperationSnapshot
    kind: str
    label: str
    units: tuple[DeviceBatchUnit, ...]

    @property
    def failed_units(self) -> tuple[DeviceBatchUnit, ...]:
        """返回上报失败结果的执行单元。"""
        failed = {
            result.unit_id
            for result in self.snapshot.unit_results
            if result.state is OperationState.FAILED
        }
        return tuple(unit for unit in self.units if unit.unit_id in failed)

    @property
    def failed_devices(self) -> tuple[str, ...]:
        """返回失败设备标识列表，顺序与批次注册顺序一致。"""
        return tuple(unit.device for unit in self.failed_units)

    @property
    def succeeded_count(self) -> int:
        """返回成功单元数量。"""
        return sum(
            1
            for result in self.snapshot.unit_results
            if result.state is OperationState.SUCCEEDED
        )

    @property
    def failed_count(self) -> int:
        """返回失败单元数量。"""
        return len(self.snapshot.unit_results) - self.succeeded_count

    @property
    def success(self) -> bool:
        """全设备成功时返回 True，存在失败设备时返回 False。"""
        return self.failed_count == 0

    @property
    def message(self) -> str:
        """复刻旧 BatchOperationTracker 的汇总文案。"""
        return (
            f"🎯 {self.label} completed; ✅ Success: {self.succeeded_count}; "
            f"❌ Failed: {self.failed_count}"
        )


class DeviceBatchUseCase:
    """把多设备批次的计数与汇总委托给 OperationManager。"""

    def __init__(
        self,
        manager: OperationManager,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._manager = manager
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._lock = RLock()
        self._active_units: dict[str, tuple[DeviceBatchUnit, ...]] = {}
        self._unit_index: dict[str, str] = {}
        self._active_kinds: dict[str, str] = {}
        self._active_labels: dict[str, str] = {}
        self._active_generations: dict[str, object] = {}

    def start(
        self,
        kind: str,
        devices: Iterable[str],
        *,
        label: str | None = None,
        operation_id: str | None = None,
    ) -> DeviceBatchStart:
        """创建多设备批次，并为每个设备登记一个执行单元。"""
        normalized_kind = self._non_empty(kind, "kind")
        normalized_label = self._non_empty(label or kind, "label")
        device_items = tuple(devices)
        if not device_items:
            raise ValueError("devices must not be empty")
        normalized_devices = tuple(
            self._non_empty(device, "device") for device in device_items
        )
        resolved_operation_id = (
            self._new_id("operation_id")
            if operation_id is None
            else self._non_empty(operation_id, "operation_id")
        )
        units = tuple(
            DeviceBatchUnit(self._new_id("unit_id"), device)
            for device in normalized_devices
        )
        generation_token = object()
        with self._lock:
            if resolved_operation_id in self._active_units:
                raise OperationTransitionError(
                    f"Duplicate operation id: {resolved_operation_id}"
                )
            self._active_units[resolved_operation_id] = units
            self._active_kinds[resolved_operation_id] = normalized_kind
            self._active_labels[resolved_operation_id] = normalized_label
            self._active_generations[resolved_operation_id] = generation_token
            for unit in units:
                self._unit_index[unit.unit_id] = resolved_operation_id
            try:
                self._manager.begin(
                    normalized_kind,
                    unit_ids=(unit.unit_id for unit in units),
                    operation_id=resolved_operation_id,
                    generation_token=generation_token,
                )
                self._manager.mark_running(
                    resolved_operation_id,
                    expected_kind=normalized_kind,
                    expected_generation=generation_token,
                )
            except Exception as start_error:
                self._drop_active_locked(resolved_operation_id)
                try:
                    if (
                        self._manager.get(
                            resolved_operation_id,
                            expected_kind=normalized_kind,
                            expected_generation=generation_token,
                        )
                        is not None
                    ):
                        self._manager.finish(
                            resolved_operation_id,
                            OperationState.FAILED,
                            message="Device batch start failed",
                            expected_kind=normalized_kind,
                            expected_generation=generation_token,
                        )
                except Exception as cleanup_error:
                    start_error.add_note(
                        f"Device batch start cleanup failed: {cleanup_error}"
                    )
                raise
        return DeviceBatchStart(resolved_operation_id, normalized_kind, units)

    def active_start(self, operation_id: str) -> DeviceBatchStart | None:
        """返回仍在活动中的批次身份，未知或已收口返回 None。"""
        with self._lock:
            units = self._active_units.get(operation_id)
            if units is None:
                return None
            return DeviceBatchStart(
                operation_id,
                self._active_kinds[operation_id],
                units,
            )

    def progress(self, operation_id: str) -> str:
        """返回与旧 BatchOperationTracker 一致的进度字符串，如 "(1/2)"。"""
        with self._lock:
            units = self._active_units.get(operation_id)
            if units is None:
                return ""
            snapshot = self._manager.get(
                operation_id,
                expected_kind=self._active_kinds[operation_id],
                expected_generation=self._active_generations[operation_id],
            )
            if snapshot is None:
                return ""
            return f"({len(snapshot.unit_results)}/{len(units)})"

    def record_unit_result(
        self,
        unit_id: str,
        device: str,
        success: bool,
        message: str = "",
    ) -> DeviceBatchOutcome | None:
        """记录单设备结果；重复或终态后的晚到结果被忽略。"""
        with self._lock:
            operation_id = self._unit_index.get(unit_id)
            if operation_id is None:
                return None
            units = self._active_units[operation_id]
            kind = self._active_kinds[operation_id]
            generation = self._active_generations[operation_id]
            snapshot = self._manager.get(
                operation_id,
                expected_kind=kind,
                expected_generation=generation,
            )
            if snapshot is None:
                self._drop_active_locked(operation_id)
                return None
            if snapshot.is_terminal:
                return None
            if any(result.unit_id == unit_id for result in snapshot.unit_results):
                return None
            state = OperationState.SUCCEEDED if success else OperationState.FAILED
            recorded = self._manager.record_unit_result(
                operation_id,
                OperationUnitResult(unit_id, state, str(message)),
                expected_kind=kind,
                expected_generation=generation,
            )
            if recorded is None:
                self._drop_active_locked(operation_id)
                return None
            if len(recorded.unit_results) != len(units):
                return None
            return self._finish_locked(operation_id)

    def finish(self, operation_id: str) -> DeviceBatchOutcome:
        """全部单元收口后汇总终态；未收口或未知操作时抛出异常。"""
        with self._lock:
            units = self._active_units.get(operation_id)
            if units is None:
                raise OperationTransitionError(f"Unknown operation id: {operation_id}")
            snapshot = self._manager.get(
                operation_id,
                expected_kind=self._active_kinds[operation_id],
                expected_generation=self._active_generations[operation_id],
            )
            if snapshot is None:
                self._drop_active_locked(operation_id)
                raise OperationTransitionError(f"Unknown operation id: {operation_id}")
            if len(snapshot.unit_results) != len(units):
                raise IncompleteOperationError("not all operation units have reported")
            outcome = self._finish_locked(operation_id)
            if outcome is None:
                raise OperationTransitionError(
                    f"Device batch finalize failed: {operation_id}"
                )
            return outcome

    def _finish_locked(self, operation_id: str) -> DeviceBatchOutcome | None:
        units = self._active_units[operation_id]
        kind = self._active_kinds[operation_id]
        label = self._active_labels[operation_id]
        generation = self._active_generations[operation_id]
        terminal = self._manager.finish_from_unit_results(
            operation_id,
            expected_kind=kind,
            expected_generation=generation,
        )
        if terminal is None:
            self._drop_active_locked(operation_id)
            return None
        self._drop_active_locked(operation_id)
        return DeviceBatchOutcome(terminal, kind, label, units)

    def _drop_active_locked(self, operation_id: str) -> None:
        units = self._active_units.pop(operation_id, ())
        for unit in units:
            self._unit_index.pop(unit.unit_id, None)
        self._active_kinds.pop(operation_id, None)
        self._active_labels.pop(operation_id, None)
        self._active_generations.pop(operation_id, None)

    def _new_id(self, field_name: str) -> str:
        return self._non_empty(self._id_factory(), field_name)

    @staticmethod
    def _non_empty(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()
