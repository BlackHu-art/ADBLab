"""在单次采集内合并同设备、同包、同周期的 PID 与进程状态查询。"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessStatusSample:
    """保存一次真实读取的时间、PID 和原始状态；不同指标独立校验其字段。"""

    collected_at: float
    pid: int
    status: str


class ProcessStatusSampler:
    """只属于一个设备和目标包；周期结束必重新查 PID，不跨运行共享快照。"""

    def __init__(self, adb, package: str, interval: float):
        self._adb = adb
        self._package = package
        self._interval = max(0.001, float(interval))
        self._origin = time.monotonic()
        self._lock = threading.Lock()
        self._cycle = -1
        self._sample: ProcessStatusSample | None = None

    def read(
        self, *, timeout: float = 10, cancelled: Callable[[], bool] | None = None,
    ) -> ProcessStatusSample | None:
        """共享同周期在途结果；等待、PID 和状态读取共用预算，取消只影响本次调用。"""
        started = time.monotonic()
        deadline = started + max(0.0, timeout)
        cycle = int((started - self._origin) // self._interval)

        def stopped() -> bool:
            return time.monotonic() >= deadline or bool(cancelled and cancelled())

        while not stopped():
            if self._lock.acquire(timeout=min(0.1, max(0, deadline - time.monotonic()))):
                break
        else:
            return None
        try:
            if stopped():
                return None
            if self._cycle >= cycle:
                return self._sample
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            pid = self._adb.get_pid_from_pck(
                self._package, timeout=remaining, cancelled=stopped,
            )
            if stopped():
                return None
            sample = None
            # PID 是设备输出，只有正十进制整数才能进入 /proc 路径。
            if re.fullmatch(r"[1-9][0-9]*", str(pid or "")):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                status = self._adb.run_shell_cmd(
                    f"cat /proc/{int(pid)}/status",
                    timeout=remaining, cancelled=stopped,
                )
                if stopped():
                    return None
                if status:
                    sample = ProcessStatusSample(time.time(), int(pid), status)
            # 无进程或读取失败也只在本周期复用，避免两个指标在失败时反复请求。
            self._cycle, self._sample = cycle, sample
            return sample
        finally:
            self._lock.release()
