"""屏幕录制批次状态用例：按设备登记运行中的录屏并协调停止与拉取。

纯 Python、线程安全、无 Qt（ADR-0003 Phase 3）。Controller 的录屏路径把原来散落在
``_record_info``/``_record_stop_requests`` 字典上的共享状态收敛到本用例，保持原有
信号与文案语义不变。
"""

from __future__ import annotations

import threading
import time


class ScreenRecordUseCase:
    """管理每设备录屏记录与停止请求的登记、幂等标记和终态移除。"""

    def __init__(self) -> None:
        self._records: dict[str, dict] = {}
        self._stop_requests: dict[str, str] = {}
        self._lock = threading.RLock()

    def start(
        self,
        device_ip: str,
        batch_id: str,
        save_dir: str,
        duration: int,
        *,
        start_time: float | None = None,
    ) -> bool:
        """登记新录屏；仅允许替换该设备已失败且未重试中的保存，不影响在途任务。"""
        with self._lock:
            previous = self._records.get(device_ip)
            if previous is not None and (
                not previous.get("retryable") or previous.get("pull_submitted")
            ):
                return False
            self._stop_requests.pop(device_ip, None)
            self._records[device_ip] = {
                "start_time": start_time if start_time is not None else time.time(),
                "duration": duration,
                "save_dir": save_dir,
                "batch_id": batch_id,
            }
            return True

    def active(self, device_ip: str) -> dict | None:
        """返回设备的活动录屏记录；无则 None。"""
        with self._lock:
            return self._records.get(device_ip)

    def mark_started(
        self,
        device_ip: str,
        batch_id: str,
        remote_path: str,
        filename: str,
    ) -> bool:
        """补记录制远端路径与文件名；批次不匹配或记录已移除返回 False。"""
        with self._lock:
            info = self._records.get(device_ip)
            if info is None or info.get("batch_id") != batch_id:
                return False
            info["remote_path"] = remote_path
            info["filename"] = filename
            return True

    def mark_pull_submitted(self, device_ip: str, batch_id: str) -> bool:
        """幂等标记拉取已提交；仅首次提交返回 True（替代旧的防重入标记）。"""
        with self._lock:
            info = self._records.get(device_ip)
            if info is None or info.get("batch_id") != batch_id:
                return False
            if info.get("pull_submitted"):
                return False
            info["pull_submitted"] = True
            return True

    def mark_stop_succeeded(self, device_ip: str, batch_id: str) -> bool:
        """标记"停止成功、等待启动结果后立即拉取"。"""
        with self._lock:
            info = self._records.get(device_ip)
            if info is None or info.get("batch_id") != batch_id:
                return False
            info["stop_succeeded"] = True
            return True

    def mark_pull_failed(self, device_ip: str, batch_id: str) -> tuple[tuple[str, str], ...]:
        """保留最多 64 份最近失败的原目标；返回淘汰项，供控制器释放其界面状态。

        正在录制或下载的任务不参与淘汰；晚到旧批次不能重置新任务。
        """
        with self._lock:
            info = self._records.get(device_ip)
            if info is None or info.get("batch_id") != batch_id or not info.get("remote_path"):
                return ()
            info["retryable"] = True
            info["pull_submitted"] = False
            self.clear_stop_request(device_ip, batch_id)
            self._records.pop(device_ip)
            self._records[device_ip] = info
            failed_devices = [
                device for device, saved in self._records.items()
                if saved.get("retryable") and not saved.get("pull_submitted")
            ]
            expired = []
            for device in failed_devices[:-64]:
                old = self._records.pop(device)
                self.clear_stop_request(device, old["batch_id"])
                expired.append((device, old["batch_id"]))
            return tuple(expired)

    def is_stop_succeeded(self, device_ip: str, batch_id: str) -> bool:
        with self._lock:
            info = self._records.get(device_ip)
            return bool(
                info
                and info.get("batch_id") == batch_id
                and info.get("stop_succeeded")
            )

    def finish(self, device_ip: str, batch_id: str) -> dict | None:
        """终态移除设备记录；批次不匹配或不存在返回 None。"""
        with self._lock:
            info = self._records.get(device_ip)
            if info is None or info.get("batch_id") != batch_id:
                return None
            self._records.pop(device_ip, None)
            return info

    def request_stop(self, device_ip: str, batch_id: str) -> bool:
        """幂等登记停止请求；该批次首次请求返回 True。"""
        with self._lock:
            if self._stop_requests.get(device_ip) == batch_id:
                return False
            self._stop_requests[device_ip] = batch_id
            return True

    def stop_requested(self, device_ip: str, batch_id: str) -> bool:
        with self._lock:
            return self._stop_requests.get(device_ip) == batch_id

    def clear_stop_request(self, device_ip: str, batch_id: str) -> None:
        """停止请求已处理或已失效时清理登记。"""
        with self._lock:
            if self._stop_requests.get(device_ip) == batch_id:
                self._stop_requests.pop(device_ip, None)

    def active_devices(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._records)
