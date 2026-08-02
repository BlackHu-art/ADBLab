"""通过旧 Qt 信号传递操作身份的兼容信封。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OperationMetadata:
    """描述一次兼容信号所关联的操作、任务和预期产物。"""

    version: int
    operation_id: str
    operation_kind: str
    method_name: str
    task_id: str
    unit_id: str | None = None
    target_id: str | None = None
    expected_artifact_path: str | None = None

    def __post_init__(self) -> None:
        if self.version != 1:
            raise ValueError("unsupported operation metadata version")
        if not isinstance(self.operation_id, str) or not self.operation_id.strip():
            raise ValueError("operation_id must be a non-empty string")
        for field_name in ("operation_kind", "method_name", "task_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.unit_id is not None and (
            not isinstance(self.unit_id, str) or not self.unit_id.strip()
        ):
            raise ValueError("unit_id must be a non-empty string when provided")
        for field_name in ("target_id", "expected_artifact_path"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be a non-empty string when provided")


@dataclass(frozen=True)
class OperationEnvelope:
    """将原始业务结果与内部操作元数据放入同一信号载荷。"""

    payload: Any
    metadata: OperationMetadata


def attach_operation_metadata(
    result: Any,
    metadata: OperationMetadata | None,
) -> Any:
    """仅在存在内部操作元数据时包装业务结果。"""
    if metadata is None:
        return result
    return OperationEnvelope(result, metadata)


def split_operation_metadata(result: Any) -> tuple[Any, OperationMetadata | None]:
    """在旧业务处理器运行前拆分操作元数据。"""
    if not isinstance(result, OperationEnvelope):
        return result, None
    return result.payload, result.metadata
