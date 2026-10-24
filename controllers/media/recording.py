"""协调录屏批次提交、保存重试和终态通知。"""

from __future__ import annotations

import re
import time
import uuid

from controllers._base import _ADBControllerBase
from controllers.action_catalog import RECORDING_RESULT
from controllers.signals import ADBControllerSignals
from models.adb_advanced import ADBAdvanced


def _emit_record_target_finished(controller, batch_id: str, device: str) -> None:
    """发布带批次标识的录屏终态，并保留旧兼容通知。"""

    target_signal = getattr(getattr(controller, "signals", None), "record_target_finished", None)
    if target_signal is not None:
        target_signal.emit(batch_id, device)
    legacy_signal = getattr(getattr(controller, "signals", None), "record_finished", None)
    if legacy_signal is not None:
        legacy_signal.emit()


class ADBRecordingMixin(_ADBControllerBase):
    """协调录屏批次保存和失败重试，沿用原资源归属。"""

    # 以下属性由 _ADBControllerBase 提供。
    advanced_model: ADBAdvanced
    signals: ADBControllerSignals

    _handlers = {
        "start_screen_record": "_process_start_screen_record_result",
        "stop_screen_record": "_process_stop_screen_record_result",
        "pull_recorded_video": "_process_pull_recorded_video_result",
    }

    def start_screen_record(self, devices: list, duration: int = 30, batch_id: str = ""):
        """校验时长和批次标识后按设备提交录屏，逐台登记独立会话。

        提交成功只表示本机进程已登记，设备端完成和文件保存由后台拉取确认。重复目标、
        参数非法或提交异常必须为对应设备发布 record_target_finished，不能留下半批锁。
        """
        devices = list(dict.fromkeys(device for device in devices if device))
        if not self._require_devices(devices, "screen_record"):
            return
        requested_batch_id = str(batch_id).strip()
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            self._emit_operation("screen_record", False, "Invalid recording duration")
            for ip in devices:
                _emit_record_target_finished(self, requested_batch_id, ip)
            return
        if not 1 <= duration <= 3600:
            self._emit_operation(
                "screen_record", False, "Recording duration must be between 1 and 3600 seconds"
            )
            for ip in devices:
                _emit_record_target_finished(self, requested_batch_id, ip)
            return
        batch_id = requested_batch_id or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch_id):
            self._emit_operation("screen_record", False, "Invalid recording batch identifier")
            for ip in devices:
                _emit_record_target_finished(self, batch_id, ip)
            return
        try:
            save_dir = self._get_screenshot_dir()
        except (OSError, RuntimeError, ValueError) as exc:
            self._emit_operation(
                "screen_record",
                False,
                f"Failed to prepare recording directory: {exc}",
            )
            for ip in devices:
                _emit_record_target_finished(self, batch_id, ip)
            return
        now = time.time()
        for ip in devices:
            if not self.screen_records.start(ip, batch_id, save_dir, duration, start_time=now):
                self._emit_operation("screen_record", False, f"Recording is already active on {ip}")
                _emit_record_target_finished(self, batch_id, ip)
                continue
            try:
                self.advanced_model.start_screen_record_async(
                    ip,
                    save_dir,
                    duration,
                    batch_id=batch_id,
                )
            except Exception as exc:
                self.screen_records.finish(ip, batch_id)
                self._emit_operation(
                    "screen_record",
                    False,
                    f"Failed to submit recording for {ip}: {exc}",
                )
                _emit_record_target_finished(self, batch_id, ip)

    def _process_start_screen_record_result(self, result: dict):
        ip = result.get("device_ip", "")
        info = self.screen_records.active(ip)
        batch_id = result.get("batch_id") or (info or {}).get("batch_id", "")
        if info is None or batch_id != info.get("batch_id", ""):
            return
        if result.get("success"):
            dur = result.get("duration", 30)
            self.screen_records.mark_started(
                ip, batch_id, result["remote_path"], result["filename"]
            )
            self._emit_operation(
                "screen_record", True,
                f"Recording request submitted ({dur}s) on {ip} → {result['filename']}"
            )
            # 保存任务在后台等待所属进程自然结束，不用本机时长推断设备完成。
            self._auto_pull(ip, batch_id)
        else:
            self.screen_records.finish(ip, batch_id)
            self.screen_records.clear_stop_request(ip, batch_id)
            self._emit_operation(
                "screen_record", False, f"Failed to start recording on {ip}: {result.get('error')}"
            )
            _emit_record_target_finished(self, batch_id, ip)

    def _submit_recording_pull(self, device_ip: str, info: dict) -> bool:
        """同批次只允许一次在途拉取；失败后的显式重试沿用原目标及路径。"""

        if getattr(self, "_shutting_down", False):
            return False
        batch_id = str(info.get("batch_id", ""))
        # Stop 结果和启动回调都在 GUI 线程进入此入口；use case 内原子标记阻断重入。
        if not self.screen_records.mark_pull_submitted(device_ip, batch_id):
            return False
        try:
            def submit():
                self.advanced_model.pull_recorded_video_async(
                    device_ip, info["remote_path"], info["save_dir"], info["filename"],
                    batch_id=batch_id,
                )

            results = getattr(self, "action_results", None)
            if results is not None:
                from dataclasses import replace

                # 自动拉取没有按钮作用域；批次和设备共同标识一次独立保存。
                spec = replace(RECORDING_RESULT, key=f"save_recording:{batch_id}:{device_ip}")
                results.run(spec, (device_ip,), submit)
            else:
                submit()
            return True
        except Exception as exc:
            retryable = bool(info.get("retryable"))
            if retryable:
                expired = self.screen_records.mark_pull_failed(device_ip, batch_id)
                for old_device, old_batch in expired:
                    _emit_record_target_finished(self, old_batch, old_device)
            else:
                self.screen_records.finish(device_ip, batch_id)
            self.screen_records.clear_stop_request(device_ip, batch_id)
            self._emit_operation(
                "pull_recording",
                False,
                f"Failed to submit recording pull for {device_ip}: {exc}",
            )
            if retryable:
                self.signals.record_target_retryable.emit(batch_id, device_ip)
            else:
                _emit_record_target_finished(self, batch_id, device_ip)
            return False

    def _auto_pull(self, device_ip: str, batch_id: str = ""):
        if getattr(self, "_shutting_down", False):
            return
        info = self.screen_records.active(device_ip) or {}
        if batch_id and info.get("batch_id") != batch_id:
            return
        if info.get("remote_path") and not info.get("pull_submitted"):
            submitted = ADBRecordingMixin._submit_recording_pull(self, device_ip, info)
            if not submitted:
                return
            self._emit_operation(
                "screen_record", True, f"Waiting for recording completion on {device_ip}..."
            )

    def stop_screen_record(self, devices: list, batch_id: str = ""):
        """幂等登记停止请求并绑定原批次；已失败待重试的保存直接重试拉取。

        批次不匹配或没有活动会话的目标被跳过；停止提交失败会撤销屏障以允许重试。
        """
        if getattr(self, "_shutting_down", False):
            return
        devices = list(dict.fromkeys(device for device in devices if device))
        if not self._require_devices(devices, "stop_recording"):
            return
        for ip in devices:
            info = self.screen_records.active(ip) or {}
            if not info:
                continue
            current_batch = str(info.get("batch_id", ""))
            requested_batch = str(batch_id).strip() or current_batch
            if batch_id and requested_batch != current_batch:
                continue
            if info.get("retryable"):
                ADBRecordingMixin._submit_recording_pull(self, ip, info)
                continue
            if not self.screen_records.request_stop(ip, requested_batch):
                continue
            try:
                self.advanced_model.stop_screen_record_async(ip, batch_id=requested_batch)
            except Exception as exc:
                self.screen_records.clear_stop_request(ip, requested_batch)
                self._emit_operation(
                    "stop_recording",
                    False,
                    f"Failed to submit recording stop for {ip}: {exc}",
                )

    def _process_stop_screen_record_result(self, result: dict):
        ip = result.get("device_ip", "")
        result_batch = str(result.get("batch_id", ""))
        info = self.screen_records.active(ip) or {}
        current_batch = str(info.get("batch_id", ""))
        self.screen_records.clear_stop_request(ip, result_batch)
        if current_batch and result_batch != current_batch:
            return
        if result_batch and not current_batch:
            return
        self._emit_operation(
            "stop_recording",
            result.get("success", False),
            f"Recording on {ip}: {result.get('message', '')}",
        )
        if not result.get("success", False):
            return
        # 主动停止录制后也要拉取已经生成的文件。
        if info.get("remote_path"):
            ADBRecordingMixin._submit_recording_pull(self, ip, info)
        elif info:
            self.screen_records.mark_stop_succeeded(ip, current_batch)

    def _process_pull_recorded_video_result(self, result: dict):
        ip = result.get("device_ip", "")
        info = self.screen_records.active(ip)
        batch_id = result.get("batch_id") or (info or {}).get("batch_id", "")
        if info is None or batch_id != info.get("batch_id", ""):
            return
        retryable = (not result.get("success") and bool(result.get("retryable"))
                     and not getattr(self, "_shutting_down", False))
        if retryable:
            for old_device, old_batch in self.screen_records.mark_pull_failed(ip, batch_id):
                _emit_record_target_finished(self, old_batch, old_device)
        else:
            self.screen_records.finish(ip, batch_id)
        self.screen_records.clear_stop_request(ip, batch_id)
        if result.get("success"):
            self._emit_operation(
                "pull_recording", True, f"Recording saved: {result.get('local_path')}"
            )
        else:
            self._emit_operation(
                "pull_recording",
                False,
                f"Failed to pull recording from {ip}: {result.get('error')}",
            )
        if retryable:
            self.signals.record_target_retryable.emit(batch_id, ip)
        else:
            _emit_record_target_finished(self, batch_id, ip)
