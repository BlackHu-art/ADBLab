"""提供 Monkey 压测的启动、停止与批次状态协调能力。"""

from __future__ import annotations

import os
import random
import re
import time
import uuid

from adblab.application.cancellation import CancellationToken
from adblab.application.monkey_batch import MonkeyRunSnapshot, MonkeyTargetCompletion
from controllers._base import _ADBControllerBase
from controllers.signals import ADBControllerSignals
from core.log_service import LogLevel, LogService
from models.adb_app import ADBApp
from models.adb_testing import ADBTesting
from utils.adb_values import normalize_android_package


def _archive_monkey_target(controller, completed: MonkeyTargetCompletion) -> None:
    """仅在批次释放时发布一次终态；归档持久化由组合根订阅者负责。"""
    device, snapshot, result = completed.device, completed.snapshot, completed.result
    batch_id = snapshot.batch_id
    controller.testing_model.monkey_run_archive_snapshot(device, batch_id, consume=True)
    signal_ = getattr(getattr(controller, "signals", None), "run_record_ready", None)
    if signal_ is None:
        return
    from services.run_library import RunArtifact, RunRecord

    parameters = dict(snapshot.parameters)
    parameters["seed"] = result.get("seed", parameters["seed"])
    # 历史载入使用本次真实 seed；原方案仍保留随机模式，重复使用方案会重新抽样。
    parameters["seed_source"] = parameters.get("seed_mode", "random")
    parameters["seed_mode"] = "fixed"
    artifacts = tuple(
        RunArtifact(label=label, path=path)
        for key, label in (("monkey_log", "Monkey"), ("logcat_log", "Logcat"))
        if isinstance(path := result.get(key), str) and os.path.isfile(path)
    )
    state = "partial" if result.get("archive_incomplete") else (
        "cancelled" if result.get("cancelled") else
        "succeeded" if result.get("success") else "failed"
    )
    message = str(result.get("error") or "").replace(device, "<device>")[:1000]
    signal_.emit(RunRecord(
        run_id=f"{batch_id}-{snapshot.index}", kind="monkey",
        package_name=str(parameters.get("package_name", "")),
        started_at=float(result.get("started_at", snapshot.started_at)),
        finished_at=float(result.get("finished_at", time.time())), state=state,
        parameters=parameters, artifacts=artifacts,
        device_label=snapshot.device_label, app_version=snapshot.app_version,
        message=message,
    ))


def _emit_monkey_target_finished(controller, batch_id: str, device: str) -> None:
    """在信号存在时发布带批次标识的 Monkey 设备终态。"""

    signal_ = getattr(getattr(controller, "signals", None), "monkey_target_finished", None)
    if signal_ is not None and batch_id:
        signal_.emit(batch_id, device)


def _publish_monkey_completion(controller, completed: MonkeyTargetCompletion | None) -> None:
    """发布已经被业务用例消费的结果，重复回调不会获得第二份可发布终态。"""
    if completed is not None:
        _archive_monkey_target(controller, completed)
        _emit_monkey_target_finished(controller, completed.snapshot.batch_id, completed.device)


def _finalize_monkey_target(controller, batch_id: str, device: str) -> None:
    """在组合锁内消费已满足屏障的目标，并沿用归档和设备完成信号。"""
    with controller._monkey_lock:
        _publish_monkey_completion(
            controller, controller.monkey_batches.take_finished(device, batch_id),
        )


class ADBAppMonkeyMixin(_ADBControllerBase):
    """协调 Monkey 压测的启动、停止与批次状态。"""

    # 业务状态由 monkey_batches 独占；入口和 command_finished 回调均在 GUI 线程。
    # Controller 组合锁仍保护批次登记及归档交付，模型资源锁不跨层迁移。

    # 以下属性由 _ADBControllerBase 提供。
    testing_model: ADBTesting
    app_model: ADBApp
    signals: ADBControllerSignals
    log_service: LogService

    _handlers = {
        "prepare_monkey_targets": "_process_monkey_preparation_result",
        "run_monkey_test": "_process_run_monkey_test_result",
        "kill_monkey": "_process_kill_monkey_result",
    }

    # Monkey 测试

    def archive_finished_monkey_runs(self, *, resources_stopped: bool) -> None:
        """主窗口完成停止阶段后在 GUI 线程补记被关闭栅栏拦截的运行结果。

        resources_stopped 必须来自关闭阶段的实际等待结果；仍有残留时只记录不完整，
        不将未收到结果的工作误报为成功或已取消。调用本方法不启动或等待任何进程。
        """
        for device, snapshot in self.monkey_batches.pending():
            result = self.testing_model.monkey_run_archive_snapshot(device, snapshot.batch_id)
            with self._monkey_lock:
                completed = self.monkey_batches.finish_for_shutdown(
                    device, snapshot.batch_id, result if isinstance(result, dict) else None,
                    resources_stopped=resources_stopped, finished_at=time.time(),
                )
                _publish_monkey_completion(self, completed)

    def prepare_monkey_targets(
        self, devices: list[str], package_name: str, request_id: str,
        cancellation: CancellationToken,
    ) -> None:
        """提交只读准备任务，沿用 model 线程池与关闭栅栏，不在回调中自动启动测试。"""
        if getattr(self, "_shutting_down", False) or cancellation.is_cancelled:
            return
        try:
            self.app_model.prepare_monkey_targets_async(
                list(devices), package_name, request_id, cancellation
            )
        except Exception as exc:
            self._process_monkey_preparation_result({
                "request_id": request_id, "success": False,
                "error": "无法提交测试包查询，请重试", "error_detail": str(exc),
            })

    def _process_monkey_preparation_result(self, result: dict) -> None:
        """保留请求标识转发结果，由拥有目标快照的面板决定是否接受。"""
        if getattr(self, "_shutting_down", False):
            return
        if result.get("error_detail"):
            self.log_service.log("ERROR", f"Monkey preparation failed: {result['error_detail']}")
        self.signals.monkey_preparation_finished.emit(str(result.get("request_id", "")), result)

    def kill_monkey(self, devices: list, batch_id: str = ""):
        devices = list(dict.fromkeys(device for device in devices if device))
        if not self._require_devices(devices, "kill_monkey"):
            return
        for idx, device_ip in enumerate(devices, 1):
            requested_batch = self.monkey_batches.request_stop(device_ip, str(batch_id).strip())
            if requested_batch is None:
                continue
            try:
                self.testing_model.kill_monkey_async(
                    device_ip,
                    idx,
                    batch_id=requested_batch,
                )
            except Exception as exc:
                self.monkey_batches.stop_submission_failed(device_ip, requested_batch)
                self._emit_operation(
                    "kill_monkey",
                    False,
                    f"Failed to submit Monkey stop for {device_ip}: {exc}",
                )

    def _process_kill_monkey_result(self, result: dict):
        device_ip = str(result.get("device_ip", ""))
        idx = result.get("index")
        result_batch = str(result.get("batch_id", ""))
        if not self.monkey_batches.record_stop_result(
            device_ip, result_batch,
            success=bool(result.get("already_stopped") or result.get("success")),
        ):
            return
        if result.get("already_stopped"):
            self._emit_operation(
                "kill_monkey", True, f"ℹ️ {idx}. Monkey was not running on {device_ip}"
            )
        elif result.get("success"):
            self._emit_operation(
                "kill_monkey", True, f"✅ {idx}. Monkey process killed on {device_ip}"
            )
        else:
            self._emit_operation(
                "kill_monkey",
                False,
                f"❌ {idx}. Failed to kill monkey on {device_ip}:"
                f"\nError: {result.get('message', '')}",
            )
        _finalize_monkey_target(self, result_batch, str(device_ip))

    def run_monkey_test(self, devices: list, params: dict, batch_id: str = ""):
        devices = list(dict.fromkeys(device for device in devices if device))
        if not devices:
            return self._emit_operation("monkey", False, "No devices selected")
        batch_id = str(batch_id).strip() or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch_id):
            self._emit_operation("monkey", False, "Invalid Monkey batch identifier")
            for device in devices:
                _emit_monkey_target_finished(self, batch_id, device)
            return
        try:
            params = ADBAppMonkeyMixin._validated_monkey_params(params)
        except (TypeError, ValueError) as exc:
            self._emit_operation("monkey", False, f"Invalid Monkey parameters: {exc}")
            for device in devices:
                _emit_monkey_target_finished(self, batch_id, device)
            return
        package_name = params["package_name"]
        target_metadata = params.pop("_target_metadata", {})
        if not isinstance(target_metadata, dict):
            target_metadata = {}
        if not package_name:
            return self._emit_operation("monkey", False, "No package name provided")
        snapshots = {}
        for idx, device_ip in enumerate(devices, 1):
            target_params = dict(params)
            if target_params["seed_mode"] == "random":
                target_params["seed"] = random.randint(1, 99999)
            metadata = target_metadata.get(device_ip, {})
            if not isinstance(metadata, dict):
                metadata = {}
            snapshots[device_ip] = MonkeyRunSnapshot(
                batch_id=batch_id, index=idx, parameters=dict(target_params),
                started_at=time.time(),
                device_label=str(metadata.get("device_label", f"Device {idx}")),
                app_version=str(metadata.get("app_version", "")),
            )
        # 所有目标一次登记，任何设备冲突都不留下半批占位。
        with self._monkey_lock:
            dupes = self.monkey_batches.reserve(snapshots)
            if dupes:
                self._emit_operation(
                    "monkey", False, f"Monkey already running on: {', '.join(dupes)}"
                )
                for device in devices:
                    _emit_monkey_target_finished(self, batch_id, device)
                return
        try:
            save_dir = self._get_screenshot_dir()
        except (OSError, RuntimeError, ValueError) as exc:
            self._emit_operation(
                "monkey",
                False,
                f"Failed to prepare Monkey output directory: {exc}",
            )
            for device in devices:
                with self._monkey_lock:
                    _publish_monkey_completion(self, self.monkey_batches.fail_start(
                        device, batch_id, str(exc), finished_at=time.time(),
                    ))
            return
        log = self.log_service.log
        pct_keys = [
            "touch",
            "motion",
            "trackball",
            "nav",
            "majornav",
            "syskeys",
            "appswitch",
            "anyevent",
            "pinch",
        ]
        pct_str = " ".join(f"{k}={params.get(k, '?')}%" for k in pct_keys)
        log(
            LogLevel.INFO,
            f"Monkey start: {len(devices)} device(s) → {package_name} | "
            f"events={params.get('events')} throttle={params.get('throttle')}ms | "
            f"{pct_str} | "
            f"crash_ignore={params.get('ignore_crashes')} "
            f"timeout_ignore={params.get('ignore_timeouts')} "
            f"security_ignore={params.get('ignore_security')} | "
            f"save_dir={save_dir}",
        )
        for idx, device_ip in enumerate(devices, 1):
            sanitized_name = re.sub(r"\W+", "_", device_ip)
            snapshot = snapshots[device_ip]
            target_params = dict(snapshot.parameters)
            prepared = False
            try:
                prepared = self.testing_model.prepare_monkey_batch(device_ip, batch_id)
                if not prepared:
                    raise RuntimeError("Monkey batch could not be registered")
                self.testing_model.run_monkey_test_async(
                    device_ip,
                    package_name,
                    target_params,
                    sanitized_name,
                    save_dir,
                    idx,
                    callback=lambda msg: self.log_service.log(LogLevel.INFO, msg),
                    batch_id=batch_id,
                )
            except Exception as exc:
                if prepared:
                    self.testing_model.discard_prepared_monkey_batch(device_ip, batch_id)
                self._emit_operation(
                    "monkey",
                    False,
                    f"Failed to submit Monkey test for {device_ip}: {exc}",
                )
                with self._monkey_lock:
                    _publish_monkey_completion(self, self.monkey_batches.fail_start(
                        device_ip, batch_id, str(exc), finished_at=time.time(),
                    ))

    @staticmethod
    def _validated_monkey_params(params: dict) -> dict:
        """在 Controller 边界规范化 Monkey 数值，避免绕过 UI 后异常或失控。"""

        if not isinstance(params, dict):
            raise TypeError("parameter payload must be a mapping")
        package_name = normalize_android_package(params.get("package_name", ""))
        events = int(params.get("events", ""))
        throttle = int(params.get("throttle", ""))
        if not 1 <= events <= 1_000_000:
            raise ValueError("events must be between 1 and 1000000")
        if not 0 <= throttle <= 60_000:
            raise ValueError("throttle must be between 0 and 60000")

        validated = {
            key: params.get(key, True)
            for key in ("ignore_crashes", "ignore_timeouts", "ignore_security")
        }
        if "_target_metadata" in params:
            validated["_target_metadata"] = params["_target_metadata"]
        validated.update(
            package_name=package_name,
            events=events,
            throttle=throttle,
        )
        seed_mode = params.get("seed_mode", "fixed" if params.get("seed") is not None else "random")
        if seed_mode not in ("random", "fixed"):
            raise ValueError("seed mode must be random or fixed")
        seed = params.get("seed")
        if seed_mode == "fixed":
            if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2147483647:
                raise ValueError("seed must be an integer between 0 and 2147483647")
        validated.update(seed_mode=seed_mode, seed=seed if seed_mode == "fixed" else None)
        for key in (
            "touch",
            "motion",
            "trackball",
            "nav",
            "majornav",
            "syskeys",
            "appswitch",
            "anyevent",
            "pinch",
        ):
            value = int(params.get(key, 0))
            if not 0 <= value <= 100:
                raise ValueError(f"{key} percentage must be between 0 and 100")
            validated[key] = value
        return validated

    def _process_run_monkey_test_result(self, result: dict):
        device_ip = result.get("device_ip", "unknown")
        batch_id = str(result.get("batch_id", ""))
        if not self.monkey_batches.record_terminal(device_ip, batch_id, result):
            return
        duration = result.get("duration", "N/A")
        monkey_log = result.get("monkey_log", "")
        logcat_log = result.get("logcat_log", "")
        error = str(result.get("error", "None"))
        if result.get("success"):
            message = (
                "\n╔════════════════════════════════════════════════════════════════╗\n"
                f"║ ✅ Monkey Test Report - Device: {device_ip}\n"
                "╠════════════════════════════════════════════════════════════════╣\n"
                f"║ ⏱️ Duration: {duration}\n"
                f"║ 📄 Monkey Log: {monkey_log}\n"
                f"║ 📄 Logcat Log: {logcat_log}\n"
                "╚════════════════════════════════════════════════════════════════╝"
            )
        else:
            message = (
                "\n╔════════════════════════════════════════════════════════════════╗\n"
                f"║ ❌ Monkey Test Failed - Device: {device_ip}\n"
                "╠════════════════════════════════════════════════════════════════╣\n"
                f"║ ⏱️ Duration: {duration}\n"
                f"║ 💥 Error: {error[:200]}{'...' if len(error) > 200 else ''}\n"
                f"║ 🔍 Detailed Log: {monkey_log}\n"
                "╚════════════════════════════════════════════════════════════════╝"
            )
        emitted = self._emit_operation("monkey", bool(result.get("success")), message)
        _finalize_monkey_target(self, batch_id, device_ip)
        return emitted
