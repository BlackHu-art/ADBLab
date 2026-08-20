"""提供 Monkey 压测的启动、停止与批次状态协调能力。"""

from __future__ import annotations

import re
import uuid

from controllers._base import _ADBControllerBase
from core.log_service import LogLevel, LogService
from gui.panels.adb_control_signals import ADBControllerSignals
from models.adb_testing import ADBTesting
from utils.adb_values import normalize_android_package


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
    _emit_monkey_target_finished(controller, batch_id, device)
    return True


class ADBAppMonkeyMixin(_ADBControllerBase):
    """协调 Monkey 压测的启动、停止与批次状态。"""

    # 以下属性由 _ADBControllerBase 提供。
    testing_model: ADBTesting
    signals: ADBControllerSignals
    log_service: LogService

    _handlers = {
        "run_monkey_test": "_process_run_monkey_test_result",
        "kill_monkey": "_process_kill_monkey_result",
    }

    # Monkey 测试

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
        if not package_name:
            return self._emit_operation("monkey", False, "No package name provided")
        # 同一设备只允许一个 Monkey 会话，避免重复启动后无法准确停止。
        dupes = [d for d in devices if d in self._monkey_running]
        if dupes:
            self._emit_operation("monkey", False, f"Monkey already running on: {', '.join(dupes)}")
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
                _emit_monkey_target_finished(self, batch_id, device)
            return
        if not hasattr(self, "_monkey_batch_by_device"):
            self._monkey_batch_by_device = {}
        for d in devices:
            self._monkey_running.add(d)
            self._monkey_batch_by_device[d] = batch_id
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
            try:
                self.testing_model.run_monkey_test_async(
                    device_ip,
                    package_name,
                    params,
                    sanitized_name,
                    save_dir,
                    idx,
                    callback=lambda msg: self.log_service.log(LogLevel.INFO, msg),
                    batch_id=batch_id,
                )
            except Exception as exc:
                self._monkey_running.discard(device_ip)
                self._monkey_batch_by_device.pop(device_ip, None)
                self._emit_operation(
                    "monkey",
                    False,
                    f"Failed to submit Monkey test for {device_ip}: {exc}",
                )
                _emit_monkey_target_finished(self, batch_id, device_ip)

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

        validated = dict(params)
        validated.update(
            package_name=package_name,
            events=events,
            throttle=throttle,
        )
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
        emitted = self._emit_operation("monkey", result.get("success"), message)
        stop_requests = _monkey_state_map(self, "_monkey_stop_requests")
        stop_acks = _monkey_state_map(self, "_monkey_stop_acks")
        if stop_requests.get(device_ip) == batch_id:
            run_terminals = _monkey_state_map(self, "_monkey_run_terminals")
            run_terminals[device_ip] = batch_id
            if stop_acks.get(device_ip) != batch_id:
                return emitted
        _finalize_monkey_target(self, batch_id, device_ip)
        return emitted
