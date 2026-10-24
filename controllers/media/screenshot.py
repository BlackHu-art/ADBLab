"""协调截图的操作身份、产物交付和终态通知。"""

from __future__ import annotations

import os
import re
from collections import Counter
from datetime import datetime
from typing import Any, cast

from PySide6.QtCore import QTimer

from adblab.application.envelope import OperationMetadata
from adblab.application.operations import (
    OperationArtifact,
    OperationSnapshot,
    OperationState,
    OperationUnitResult,
)
from controllers._base import _ADBControllerBase
from controllers.signals import ADBControllerSignals
from core.log_service import LogService
from models.adb_testing import ADBTesting


class ADBScreenshotMixin(_ADBControllerBase):
    """协调截图身份校验、产物交付与取消终态。"""

    # 以下属性由 _ADBControllerBase 提供。
    testing_model: ADBTesting
    signals: ADBControllerSignals
    log_service: LogService

    _operation_handlers = {
        "take_screenshot": "_process_screenshot_operation_result",
    }

    def take_screenshot(self, devices: list) -> str | None:
        """为每台去重目标分配单元身份和唯一本地路径，并启动截图批次。

        成功产物先登记 artifact 再记录单元终态；取消或晚到结果不得发布截图，只有同一
        generation 的结果能完成该批次。返回 operation_id，目录准备失败时返回 None。
        """
        valid = tuple(dict.fromkeys(device for device in devices if device))
        if not valid:
            self._emit_operation("screenshot", False, "⚠️ No devices selected")
            return None
        try:
            screenshot_dir = self._get_screenshot_dir()
        except Exception:
            self._emit_operation(
                "screenshot",
                False,
                "Unable to prepare screenshot directory",
            )
            return None

        operation_id = self._generate_operation_id()
        tasks = [
            (
                self._generate_operation_id(),
                device,
                self._screenshot_path(screenshot_dir, device),
            )
            for device in valid
        ]
        operation = self.operation_manager.begin(
            "screenshot",
            operation_id=operation_id,
            unit_ids=(task_id for task_id, _device, _path in tasks),
        )
        running = self.operation_manager.mark_running(
            operation.operation_id,
            expected_kind=operation.kind,
            expected_generation=operation.generation_token,
        )
        if running is None:
            return operation.operation_id
        self.log_service.log(
            "DEBUG",
            f"[screenshot] operation started: target_count={len(tasks)}",
        )
        self.log_service.log(
            "INFO",
            f"Capturing screenshots for {len(tasks)} selected target(s)",
            flush_immediately=True,
        )
        for task_id, device, save_path in tasks:
            try:
                self._start_screenshot_process(
                    device,
                    save_path,
                    operation.operation_id,
                    task_id,
                    operation.generation_token,
                )
            except Exception:
                self.log_service.log(
                    "ERROR",
                    "[screenshot] Failed to queue one capture task",
                )
                self.operation_manager.record_unit_result(
                    operation.operation_id,
                    OperationUnitResult(
                        task_id,
                        OperationState.FAILED,
                        "Screenshot task submission failed",
                    ),
                    expected_kind=operation.kind,
                    expected_generation=operation.generation_token,
                )
        self._finish_screenshot_if_complete(
            operation.operation_id,
            operation.generation_token,
        )
        return operation.operation_id

    def _screenshot_path(self, save_dir: str, device_ip: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        device_name = re.sub(r"\W+", "_", device_ip).strip("_") or "device"
        filename_stem = f"{device_name}_{timestamp}"

        # 同一秒内连续截图时追加简短序号，避免覆盖已有或尚未落盘的截图。
        if getattr(self, "_screenshot_name_timestamp", None) != timestamp:
            self._screenshot_name_timestamp = timestamp
            self._allocated_screenshot_paths = set()
        allocated_paths = self._allocated_screenshot_paths

        sequence = 1
        while True:
            suffix = "" if sequence == 1 else f"_{sequence}"
            path = os.path.normpath(os.path.join(save_dir, f"{filename_stem}{suffix}.png"))
            path_key = os.path.normcase(os.path.abspath(path))
            if path_key not in allocated_paths and not os.path.exists(path):
                allocated_paths.add(path_key)
                return path
            sequence += 1

    def _start_screenshot_process(
        self,
        device_ip: str,
        save_path: str,
        operation_id: str,
        task_id: str,
        generation_token: object,
    ):
        manager = self.operation_manager

        def cancelled() -> bool:
            # OperationManager 的锁保护跨线程快照；旧批次终态不能影响新截图。
            snapshot = manager.get(
                operation_id, expected_kind="screenshot", expected_generation=generation_token,
            )
            return snapshot is None or snapshot.is_terminal or snapshot.cancel_requested

        cast(Any, self.testing_model).take_screenshot_async(
            device_ip,
            save_path,
            cancelled=cancelled,
            _operation_id=operation_id,
            _operation_kind="screenshot",
            _operation_task_id=task_id,
            _operation_unit_id=task_id,
            _operation_target_id=device_ip,
            _operation_expected_artifact_path=save_path,
            _operation_generation_token=generation_token,
        )

    def _process_screenshot_operation_result(
        self,
        result,
        metadata: OperationMetadata,
    ) -> OperationSnapshot | None:
        operation_id = metadata.operation_id
        snapshot = self.operation_manager.get(
            operation_id,
            expected_kind="screenshot",
            expected_generation=metadata.generation_token,
        )
        if snapshot is None:
            return None
        task_id = metadata.unit_id
        if not task_id or task_id != metadata.task_id:
            return self._fail_screenshot_operation(
                operation_id,
                "Screenshot task identity mismatch",
                expected_generation=metadata.generation_token,
            )
        if any(item.unit_id == task_id for item in snapshot.unit_results):
            self.log_service.log("DEBUG", "[screenshot] Duplicate result ignored")
            return None

        valid, message, path = self._classify_screenshot_result(result, metadata)
        unit_state = OperationState.SUCCEEDED if valid else OperationState.FAILED
        if valid and path:
            if any(artifact.path == path for artifact in snapshot.artifacts):
                return self._fail_screenshot_operation(
                    operation_id,
                    "Screenshot artifact identity conflict",
                    expected_generation=metadata.generation_token,
                )
            artifact_snapshot = self.operation_manager.add_artifact(
                operation_id,
                OperationArtifact(path, "screenshot", task_id),
                expected_kind="screenshot",
                expected_generation=metadata.generation_token,
            )
            if artifact_snapshot is None:
                return None
        result_snapshot = self.operation_manager.record_unit_result(
            operation_id,
            OperationUnitResult(task_id, unit_state, message),
            expected_kind="screenshot",
            expected_generation=metadata.generation_token,
        )
        if result_snapshot is None:
            return None
        if valid and path:
            self.signals.screenshot_captured.emit(metadata.target_id, path)
        return self._finish_screenshot_if_complete(
            operation_id,
            metadata.generation_token,
        )

    def _operation_metadata_matches(
        self,
        op_type: str,
        metadata: OperationMetadata,
        snapshot,
        response_claim: object | None,
    ) -> bool:
        if snapshot.kind == "screenshot" and metadata.generation_token is None:
            return False
        return super()._operation_metadata_matches(
            op_type,
            metadata,
            snapshot,
            response_claim,
        )

    @staticmethod
    def _classify_screenshot_result(
        result,
        metadata: OperationMetadata,
    ) -> tuple[bool, str, str]:
        if not isinstance(result, dict):
            return False, "Screenshot returned an invalid result", ""
        if not metadata.target_id or result.get("device_ip") != metadata.target_id:
            return False, "Screenshot target identity mismatch", ""
        if not result.get("success"):
            return False, "Screenshot command failed", ""
        path = result.get("screenshot_path")
        expected = metadata.expected_artifact_path
        if not isinstance(path, str) or not path or not expected:
            return False, "Screenshot artifact path missing", ""
        actual_path = os.path.normcase(os.path.abspath(path))
        expected_path = os.path.normcase(os.path.abspath(expected))
        if actual_path != expected_path:
            return False, "Screenshot artifact path mismatch", ""
        if not ADBTesting._is_valid_png(path):
            return False, "Screenshot artifact missing or invalid", ""
        return True, "Screenshot captured", path

    def _finish_screenshot_if_complete(
        self,
        operation_id: str,
        generation_token: object,
    ) -> OperationSnapshot | None:
        snapshot = self.operation_manager.get(
            operation_id,
            expected_kind="screenshot",
            expected_generation=generation_token,
        )
        if snapshot is None or len(snapshot.unit_results) != len(snapshot.unit_ids):
            return None
        terminal = self.operation_manager.finish_from_unit_results(
            operation_id,
            expected_kind="screenshot",
            expected_generation=generation_token,
        )
        if terminal is not None:
            self._emit_screenshot_terminal(terminal)
        return terminal

    def _fail_screenshot_operation(
        self,
        operation_id: str,
        message: str,
        *,
        expected_generation: object,
    ) -> OperationSnapshot | None:
        terminal = self.operation_manager.finish(
            operation_id,
            OperationState.FAILED,
            message=message,
            expected_kind="screenshot",
            expected_generation=expected_generation,
        )
        if terminal is not None:
            self._emit_screenshot_terminal(terminal)
        return terminal

    def _fail_operation_protocol(self, snapshot, message: str):
        if snapshot.kind == "screenshot":
            return self._fail_screenshot_operation(
                snapshot.operation_id,
                message,
                expected_generation=snapshot.generation_token,
            )
        return super()._fail_operation_protocol(snapshot, message)

    def cancel_screenshot(self, operation_id: str) -> bool:
        """取消仍在途的截图单元并发布终态；操作已结束或身份不符时返回 False。"""
        snapshot = self.operation_manager.get(
            operation_id,
            expected_kind="screenshot",
        )
        if snapshot is None:
            return False
        generation_token = snapshot.generation_token
        terminal = self.operation_manager.cancel_pending_units(
            operation_id,
            unit_message="Screenshot cancelled",
            expected_kind="screenshot",
            expected_generation=generation_token,
        )
        if terminal is None:
            return False
        self._emit_screenshot_terminal(terminal)
        return True

    def _emit_screenshot_terminal(self, terminal: OperationSnapshot):
        counts = Counter(result.state for result in terminal.unit_results)
        total = len(terminal.unit_ids)
        succeeded = counts[OperationState.SUCCEEDED]
        failed = max(
            counts[OperationState.FAILED],
            total - succeeded - counts[OperationState.CANCELLED],
        )
        cancelled = counts[OperationState.CANCELLED]
        self.log_service.log(
            "DEBUG",
            (
                "[screenshot] operation finished: "
                f"state={terminal.state.value} total={total} "
                f"succeeded={succeeded} failed={failed} cancelled={cancelled}"
            ),
        )
        message = (
            f"Screenshot completed: {succeeded}/{total} succeeded, "
            f"{failed} failed, {cancelled} cancelled"
        )
        self._emit_operation(
            "screenshot",
            terminal.state is OperationState.SUCCEEDED,
            message,
        )
        succeeded_units = {
            result.unit_id
            for result in terminal.unit_results
            if result.state is OperationState.SUCCEEDED
        }
        paths_by_unit = {
            artifact.unit_id: artifact.path
            for artifact in terminal.artifacts
            if artifact.kind == "screenshot" and artifact.unit_id in succeeded_units
        }
        paths = [
            paths_by_unit[unit_id] for unit_id in terminal.unit_ids if unit_id in paths_by_unit
        ]
        if paths:
            QTimer.singleShot(
                0,
                self.signals,
                lambda captured=tuple(paths): self._emit_screenshot_batch(list(captured)),
            )

    def _emit_screenshot_batch(self, image_paths: list[str]) -> None:
        """在 GUI 线程发布完整截图批次，不创建或持有具体页面。"""

        if getattr(self, "_shutting_down", False):
            return
        paths = [str(path) for path in image_paths if path]
        if paths:
            self.signals.screenshot_batch_ready.emit(paths)
