"""提供 Monkey 压测的启动、停止与批次状态协调能力。"""

from __future__ import annotations

import os
import random
import re
import time
import uuid
from dataclasses import dataclass

from adblab.application.cancellation import CancellationToken
from controllers._base import _ADBControllerBase
from controllers.signals import ADBControllerSignals
from core.log_service import LogLevel, LogService
from models.adb_app import ADBApp
from models.adb_testing import ADBTesting
from utils.adb_values import normalize_android_package


@dataclass(frozen=True)
class _MonkeyRunSnapshot:
    """在排队前固定归档身份与参数；页面后续修改不能改变这次运行。"""

    batch_id: str
    index: int
    parameters: dict
    started_at: float
    device_label: str
    app_version: str


def _archive_monkey_target(controller, batch_id: str, device: str) -> None:
    """仅在批次释放时发布一次终态；归档持久化由组合根订阅者负责。"""
    snapshots = _monkey_state_map(controller, "_monkey_run_snapshots")
    snapshot = snapshots.get(device)
    if not isinstance(snapshot, _MonkeyRunSnapshot) or snapshot.batch_id != batch_id:
        return
    snapshots.pop(device, None)
    result = _monkey_state_map(controller, "_monkey_run_results").pop(device, {})
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

def _monkey_state_map(controller, name: str) -> dict:
    """返回 Controller 上指定的 Monkey 批次映射。"""

    value = getattr(controller, name, None)
    if not isinstance(value, dict):
        value = {}
        setattr(controller, name, value)
    return value

def _finalize_monkey_target(controller, batch_id: str, device: str) -> bool:
    """在运行终态和停止确认均满足后，原子释放设备批次。"""

    lock = getattr(controller, "_monkey_lock", None)
    if lock is not None:
        lock.acquire()
    try:
        batch_map = _monkey_state_map(controller, "_monkey_batch_by_device")
        current_batch = str(batch_map.get(device, ""))
        if current_batch and current_batch != batch_id:
            return False
        if batch_id and not current_batch:
            return False
        batch_map.pop(device, None)
        controller._monkey_running.discard(device)
        for name in (
            "_monkey_stop_requests",
            "_monkey_stop_acks",
            "_monkey_run_terminals",
        ):
            state_map = _monkey_state_map(controller, name)
            if state_map.get(device) == batch_id:
                state_map.pop(device, None)
        _archive_monkey_target(controller, batch_id, device)
        _emit_monkey_target_finished(controller, batch_id, device)
        return True
    finally:
        if lock is not None:
            lock.release()


class ADBAppMonkeyMixin(_ADBControllerBase):
    """协调 Monkey 压测的启动、停止与批次状态。"""

    # Monkey 状态（含 _monkey_stop_requests/_monkey_stop_acks/_monkey_run_terminals 与
    # _monkey_batch_by_device/_monkey_running）均为 GUI 线程读写：启动/停止入口来自 UI 信号，
    # 结果经 command_finished 的 AutoConnection 调度回 GUI 线程。_monkey_lock 仅覆盖启动占位
    # 与回滚的原子段，未覆盖其余字典是已知且无害的。

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
        snapshots = _monkey_state_map(self, "_monkey_run_snapshots")
        for device, snapshot in tuple(snapshots.items()):
            result = self.testing_model.monkey_run_archive_snapshot(device, snapshot.batch_id)
            if not isinstance(result, dict):
                result = dict(_monkey_state_map(self, "_monkey_run_results").get(device, {}))
            if not result.get("terminal"):
                result.update(
                    success=False, cancelled=resources_stopped,
                    archive_incomplete=not resources_stopped,
                    error=("Application closed before the test completed" if resources_stopped
                           else "Application closed without confirming all test resources stopped"),
                    finished_at=time.time(),
                )
            _monkey_state_map(self, "_monkey_run_results")[device] = result
            _finalize_monkey_target(self, snapshot.batch_id, device)

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
        batch_map = getattr(self, "_monkey_batch_by_device", {})
        if not isinstance(batch_map, dict):
            batch_map = {}
        stop_requests = getattr(self, "_monkey_stop_requests", None)
        if not isinstance(stop_requests, dict):
            stop_requests = {}
            self._monkey_stop_requests = stop_requests
        for idx, device_ip in enumerate(devices, 1):
            current_batch = str(batch_map.get(device_ip, ""))
            requested_batch = str(batch_id).strip() or current_batch
            if batch_id and requested_batch != current_batch:
                continue
            if stop_requests.get(device_ip) == requested_batch:
                continue
            stop_requests[device_ip] = requested_batch
            try:
                self.testing_model.kill_monkey_async(
                    device_ip,
                    idx,
                    batch_id=requested_batch,
                )
            except Exception as exc:
                stop_requests.pop(device_ip, None)
                self._emit_operation(
                    "kill_monkey",
                    False,
                    f"Failed to submit Monkey stop for {device_ip}: {exc}",
                )

    def _process_kill_monkey_result(self, result: dict):
        device_ip = result.get("device_ip")
        idx = result.get("index")
        result_batch = str(result.get("batch_id", ""))
        batch_map = getattr(self, "_monkey_batch_by_device", {})
        if not isinstance(batch_map, dict):
            batch_map = {}
        current_batch = str(batch_map.get(device_ip, ""))
        stop_requests = getattr(self, "_monkey_stop_requests", {})
        if current_batch and result_batch != current_batch:
            if isinstance(stop_requests, dict) and stop_requests.get(device_ip) == result_batch:
                stop_requests.pop(device_ip, None)
            return
        if result_batch and not current_batch:
            if isinstance(stop_requests, dict) and stop_requests.get(device_ip) == result_batch:
                stop_requests.pop(device_ip, None)
            return
        batch_id = current_batch or result_batch
        stop_acks = _monkey_state_map(self, "_monkey_stop_acks")
        run_terminals = _monkey_state_map(self, "_monkey_run_terminals")
        if result.get("already_stopped"):
            self._emit_operation(
                "kill_monkey", True, f"ℹ️ {idx}. Monkey was not running on {device_ip}"
            )
            stop_acks[device_ip] = batch_id
            if run_terminals.get(device_ip) == batch_id:
                _finalize_monkey_target(self, batch_id, str(device_ip))
            return
        if result.get("success"):
            self._emit_operation(
                "kill_monkey", True, f"✅ {idx}. Monkey process killed on {device_ip}"
            )
            stop_acks[device_ip] = batch_id
            if run_terminals.get(device_ip) == batch_id:
                _finalize_monkey_target(self, batch_id, str(device_ip))
        else:
            if isinstance(stop_requests, dict) and stop_requests.get(device_ip) == batch_id:
                stop_requests.pop(device_ip, None)
            if stop_acks.get(device_ip) == batch_id:
                stop_acks.pop(device_ip, None)
            self._emit_operation(
                "kill_monkey",
                False,
                f"❌ {idx}. Failed to kill monkey on {device_ip}:"
                f"\nError: {result.get('message', '')}",
            )
            if run_terminals.get(device_ip) == batch_id:
                _finalize_monkey_target(self, batch_id, str(device_ip))
            return

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
        # 同一设备只允许一个 Monkey 会话，避免重复启动后无法准确停止。
        # 占位与会话登记在同一锁内原子完成；save_dir 失败时回滚占位。
        if not hasattr(self, "_monkey_batch_by_device"):
            self._monkey_batch_by_device = {}
        with self._monkey_lock:
            dupes = [d for d in devices if d in self._monkey_running]
            if dupes:
                self._emit_operation(
                    "monkey", False, f"Monkey already running on: {', '.join(dupes)}"
                )
                for device in devices:
                    _emit_monkey_target_finished(self, batch_id, device)
                return
            for d in devices:
                self._monkey_running.add(d)
                self._monkey_batch_by_device[d] = batch_id
        for idx, device_ip in enumerate(devices, 1):
            target_params = dict(params)
            if target_params["seed_mode"] == "random":
                target_params["seed"] = random.randint(1, 99999)
            metadata = target_metadata.get(device_ip, {})
            if not isinstance(metadata, dict):
                metadata = {}
            _monkey_state_map(self, "_monkey_run_snapshots")[device_ip] = _MonkeyRunSnapshot(
                batch_id=batch_id, index=idx, parameters=dict(target_params),
                started_at=time.time(),
                device_label=str(metadata.get("device_label", f"Device {idx}")),
                app_version=str(metadata.get("app_version", "")),
            )
        try:
            save_dir = self._get_screenshot_dir()
        except (OSError, RuntimeError, ValueError) as exc:
            self._emit_operation(
                "monkey",
                False,
                f"Failed to prepare Monkey output directory: {exc}",
            )
            for device in devices:
                _monkey_state_map(self, "_monkey_run_results")[device] = {
                    "success": False, "error": str(exc), "finished_at": time.time(),
                }
                _finalize_monkey_target(self, batch_id, device)
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
            snapshot = _monkey_state_map(self, "_monkey_run_snapshots")[device_ip]
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
                _monkey_state_map(self, "_monkey_run_results")[device_ip] = {
                    "success": False, "error": str(exc), "finished_at": time.time(),
                }
                _finalize_monkey_target(self, batch_id, device_ip)

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
        batch_map = getattr(self, "_monkey_batch_by_device", {})
        if not isinstance(batch_map, dict):
            batch_map = {}
        current_batch = batch_map.get(device_ip, "")
        if current_batch and batch_id != current_batch:
            return
        if batch_id and not current_batch:
            return
        if current_batch:
            batch_id = current_batch
        if device_ip in _monkey_state_map(self, "_monkey_run_snapshots"):
            _monkey_state_map(self, "_monkey_run_results")[device_ip] = dict(result)
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
        stop_requests = _monkey_state_map(self, "_monkey_stop_requests")
        stop_acks = _monkey_state_map(self, "_monkey_stop_acks")
        if stop_requests.get(device_ip) == batch_id:
            run_terminals = _monkey_state_map(self, "_monkey_run_terminals")
            run_terminals[device_ip] = batch_id
            if stop_acks.get(device_ip) != batch_id:
                return emitted
        _finalize_monkey_target(self, batch_id, device_ip)
        return emitted
