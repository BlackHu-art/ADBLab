"""集中管理 Monkey 业务批次、停止屏障与一次性归档交付，不拥有模型进程资源。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class MonkeyRunSnapshot:
    """排队前固定归档身份和标量参数，避免页面后续修改污染本次运行。"""

    batch_id: str
    index: int
    parameters: Mapping[str, Any]
    started_at: float
    device_label: str
    app_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class MonkeyTargetCompletion:
    """已释放的设备批次及最终结果，只交付一次给 Controller 发布归档。"""

    device: str
    snapshot: MonkeyRunSnapshot
    result: dict


@dataclass
class _MonkeyTargetState:
    """单台设备的唯一业务状态；无快照表示兼容入口发出的独立停止请求。"""

    batch_id: str
    snapshot: MonkeyRunSnapshot | None = None
    result: dict | None = None
    stop_requested: bool = False
    stop_acknowledged: bool = False


class MonkeyBatchCoordinator:
    """由 GUI 线程独占批次状态，Controller 组合锁保护登记与交付临界区。

    运行终态与停止确认顺序无关；停止失败撤除停止屏障，但仍须等待运行终态。
    模型进程、取消条件和资源锁保持原有归属，不由本对象启动、停止或等待。
    """

    def __init__(self) -> None:
        self._targets: dict[str, _MonkeyTargetState] = {}

    def reserve(self, snapshots: Mapping[str, MonkeyRunSnapshot]) -> tuple[str, ...]:
        """整批占位；存在活动设备时返回冲突设备，且不登记任何新目标。"""
        conflicts = tuple(
            device for device in snapshots
            if (state := self._targets.get(device)) is not None and state.snapshot is not None
        )
        if conflicts:
            return conflicts
        for device, snapshot in snapshots.items():
            self._targets[device] = _MonkeyTargetState(snapshot.batch_id, snapshot)
        return ()

    def pending(self) -> tuple[tuple[str, MonkeyRunSnapshot], ...]:
        """返回尚未交付归档的固定快照，用于关闭补档及运行参数读取。"""
        return tuple(
            (device, state.snapshot) for device, state in self._targets.items()
            if state.snapshot is not None
        )

    def request_stop(self, device: str, batch_id: str = "") -> str | None:
        """登记一次停止请求；拒绝旧批次与重复请求，空批次沿用兼容停止入口。"""
        state = self._targets.get(device)
        current_batch = state.batch_id if state is not None else ""
        requested_batch = batch_id or current_batch
        if batch_id and batch_id != current_batch:
            return None
        if state is None:
            state = _MonkeyTargetState(requested_batch)
            self._targets[device] = state
        if state.stop_requested:
            return None
        state.stop_requested = True
        state.stop_acknowledged = False
        return requested_batch

    def stop_submission_failed(self, device: str, batch_id: str) -> bool:
        """提交失败时撤回请求以允许重试，不能修改另一批次的停止状态。"""
        state = self._matching(device, batch_id)
        if state is None or not state.stop_requested:
            return False
        state.stop_requested = False
        state.stop_acknowledged = False
        if state.snapshot is None:
            self._targets.pop(device)
        return True

    def record_stop_result(self, device: str, batch_id: str, *, success: bool) -> bool:
        """接受当前请求的停止结果；成功确认屏障，失败撤除屏障以等待运行终态。"""
        state = self._matching(device, batch_id)
        if state is None or not state.stop_requested or state.stop_acknowledged:
            return False
        state.stop_acknowledged = success
        if not success:
            state.stop_requested = False
        # 独立停止成功后仍保留幂等标记；新运行登记会替换它，重复点击不再派发。
        if state.snapshot is None and not success:
            self._targets.pop(device)
        return True

    def record_terminal(self, device: str, batch_id: str, result: dict) -> bool:
        """只接收当前运行的首次终态，等待停止确认期间也不覆盖已接收结果。"""
        state = self._matching(device, batch_id)
        if state is None or state.snapshot is None or state.result is not None:
            return False
        state.result = dict(result)
        return True

    def take_finished(self, device: str, batch_id: str) -> MonkeyTargetCompletion | None:
        """仅在运行终态和所需停止确认均具备时释放目标，重复调用返回空。"""
        state = self._matching(device, batch_id)
        if state is None or state.result is None:
            return None
        if state.stop_requested and not state.stop_acknowledged:
            return None
        return self._take(device, state)

    def fail_start(
        self, device: str, batch_id: str, error: str, *, finished_at: float,
    ) -> MonkeyTargetCompletion | None:
        """启动未提交时立即回滚该设备占位并交付失败，不影响其他目标。"""
        state = self._matching(device, batch_id)
        if state is None or state.snapshot is None:
            return None
        state.result = {"success": False, "error": error, "finished_at": finished_at}
        return self._take(device, state)

    def finish_for_shutdown(
        self, device: str, batch_id: str, cached_result: dict | None, *,
        resources_stopped: bool, finished_at: float,
    ) -> MonkeyTargetCompletion | None:
        """关闭等待后补交一次归档；实际资源停止证据决定取消或不完整状态。"""
        state = self._matching(device, batch_id)
        if state is None or state.snapshot is None:
            return None
        result = dict(cached_result if cached_result is not None else state.result or {})
        if not result.get("terminal"):
            result.update(
                success=False, cancelled=resources_stopped,
                archive_incomplete=not resources_stopped,
                error=("Application closed before the test completed" if resources_stopped
                       else "Application closed without confirming all test resources stopped"),
                finished_at=finished_at,
            )
        state.result = result
        return self._take(device, state)

    def _matching(self, device: str, batch_id: str) -> _MonkeyTargetState | None:
        state = self._targets.get(device)
        return state if state is not None and state.batch_id == batch_id else None

    def _take(self, device: str, state: _MonkeyTargetState) -> MonkeyTargetCompletion | None:
        if state.snapshot is None or state.result is None:
            return None
        self._targets.pop(device)
        return MonkeyTargetCompletion(device, state.snapshot, dict(state.result))
