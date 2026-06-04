from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol

from .types import CpuSample, MemorySample, PerformanceSnapshot


class PerformanceSampleProvider(Protocol):
    """Common interface for realtime performance sample backends."""

    name: str

    def start(self, target: str = "") -> None:
        """Prepare the provider for sampling a target."""

    def sample(self, target: str = "") -> PerformanceSnapshot:
        """Return one normalized sample for the current target."""

    def stop(self) -> None:
        """Release provider resources."""


@dataclass(frozen=True)
class ProviderCapability:
    name: str
    realtime: bool
    android: bool
    host: bool
    description: str


def provider_capabilities() -> list[ProviderCapability]:
    return [
        ProviderCapability(
            name="psutil-host",
            realtime=True,
            android=False,
            host=True,
            description="Host process CPU, RSS memory, and thread sampling via psutil.",
        ),
        ProviderCapability(
            name="perfetto-android",
            realtime=False,
            android=True,
            host=False,
            description="Android scenario trace capture and offline analysis via Perfetto.",
        ),
        ProviderCapability(
            name="android-agent",
            realtime=True,
            android=True,
            host=False,
            description="Long-lived device-side sampler streaming normalized counters.",
        ),
        ProviderCapability(
            name="adb-compat",
            realtime=False,
            android=True,
            host=False,
            description="Compatibility-only one-shot adb metrics for quick checks and reports.",
        ),
    ]


class PsutilHostProvider:
    """Sample a local host process with psutil.

    This provider is intentionally scoped to host processes. It cannot observe
    performance counters inside a connected Android device.
    """

    name = "psutil-host"

    def __init__(self, pid: int | None = None):
        self.pid = pid or os.getpid()
        self._process = None

    @property
    def available(self) -> bool:
        try:
            import psutil  # noqa: F401
        except ImportError:
            return False
        return True

    def start(self, target: str = "") -> None:
        pid = _target_pid(target) if target else self.pid
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("psutil is not installed; install psutil to use host sampling") from exc
        self.pid = pid
        self._process = psutil.Process(pid)
        # Prime psutil's CPU delta baseline; the first real sample arrives on the next call.
        self._process.cpu_percent(interval=None)

    def sample(self, target: str = "") -> PerformanceSnapshot:
        if self._process is None:
            self.start(target)
        process = self._process
        timestamp_ms = _now_ms()
        try:
            cpu_percent = process.cpu_percent(interval=None)
            memory_info = process.memory_info()
            thread_count = process.num_threads()
            process_name = process.name()
            pid = process.pid
        except Exception as exc:
            return PerformanceSnapshot(
                device_id="host",
                online=False,
                current_package=str(target or self.pid),
                target_package=str(target or self.pid),
                status=f"Host sample failed: {exc}",
            )
        return PerformanceSnapshot(
            device_id="host",
            online=True,
            current_package=process_name,
            target_package=f"{process_name}:{pid}",
            memory=MemorySample(
                timestamp_ms=timestamp_ms,
                total_pss_kb=round(memory_info.rss / 1024),
            ),
            cpu=CpuSample(
                timestamp_ms=timestamp_ms,
                process_percent=round(cpu_percent, 2),
                is_foreground=True,
                pid=pid,
                thread_count=thread_count,
                process_count=1,
            ),
            status="Online",
        )

    def stop(self) -> None:
        self._process = None


class PerfettoAndroidProvider:
    """Placeholder for Android Perfetto trace-backed sampling."""

    name = "perfetto-android"

    def start(self, target: str = "") -> None:
        raise NotImplementedError("Perfetto Android provider is planned for scenario trace capture.")

    def sample(self, target: str = "") -> PerformanceSnapshot:
        raise NotImplementedError("Perfetto Android provider does not expose polling samples yet.")

    def stop(self) -> None:
        return None


class AndroidAgentProvider:
    """Placeholder for a long-lived Android device-side sampler."""

    name = "android-agent"

    def start(self, target: str = "") -> None:
        raise NotImplementedError("Android agent provider is planned for realtime device sampling.")

    def sample(self, target: str = "") -> PerformanceSnapshot:
        raise NotImplementedError("Android agent provider is not implemented yet.")

    def stop(self) -> None:
        return None


def _target_pid(target: str) -> int:
    text = str(target).strip()
    if not text:
        return os.getpid()
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError("psutil-host target must be a local process id") from exc


def _now_ms() -> int:
    return int(time.time() * 1000)
