from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

from models.base.process_runner import ProcessRunner

from .parsers import (
    build_cpu_sample,
    parse_proc_stat_total,
    parse_process_start_time_ticks,
    parse_process_stat_cpu_ticks,
    parse_process_thread_count,
)
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
    """Stream normalized Android process counters from one long-lived adb shell."""

    name = "android-agent"
    paced = True

    def __init__(
        self,
        device_id: str,
        *,
        process_runner: ProcessRunner | None = None,
        process_key_prefix: str = "performance_agent",
        sample_interval_seconds: float = 0.5,
    ):
        self.device_id = device_id
        self.process_runner = process_runner or ProcessRunner()
        self.process_key = f"{process_key_prefix}_{device_id}_{id(self)}"
        self.sample_interval_seconds = max(0.2, float(sample_interval_seconds))
        self._proc: subprocess.Popen | None = None
        self._target = ""
        self._cpu_baselines: dict[str, tuple[int, int, int, int]] = {}
        self._cpu_total_baseline: int | None = None
        self._cpu_count = 1

    def start(self, target: str = "") -> None:
        target = str(target or "").strip()
        if not self.device_id:
            raise RuntimeError("Android agent provider requires a device id")
        if not target:
            raise RuntimeError("Android agent provider requires a target package")
        if self._proc is not None and self._proc.poll() is None and target == self._target:
            return
        self.stop()
        self._target = target
        self._cpu_baselines.clear()
        self._cpu_total_baseline = None
        command = _android_agent_command(target, interval_seconds=self.sample_interval_seconds)
        self._proc = self.process_runner.start(
            self.process_key,
            ["adb", "-s", self.device_id, "shell", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    def sample(self, target: str = "") -> PerformanceSnapshot:
        target = str(target or self._target or "").strip()
        if self._proc is None or self._proc.poll() is not None or (target and target != self._target):
            self.start(target)
        timestamp_ms = _now_ms()
        batch = self._read_batch()
        if batch is None:
            return PerformanceSnapshot(
                device_id=self.device_id,
                online=False,
                current_package=self._target,
                target_package=self._target,
                status=self._process_error() or "Android agent stream stopped",
            )
        total_ticks, cpu_count, processes = batch
        self._cpu_count = cpu_count or self._cpu_count or 1
        if total_ticks is None:
            return PerformanceSnapshot(
                device_id=self.device_id,
                online=False,
                current_package=self._target,
                target_package=self._target,
                status="Android agent did not return /proc/stat",
            )
        if not processes:
            self._cpu_baselines.clear()
            self._cpu_total_baseline = total_ticks
            return PerformanceSnapshot(
                device_id=self.device_id,
                online=True,
                current_package=self._target,
                target_package=self._target,
                cpu=CpuSample(timestamp_ms=timestamp_ms, process_count=0, thread_count=0),
                status="No target process",
                warnings=[f"No process matched {self._target}"],
            )
        memory = _memory_from_agent_processes(processes, timestamp_ms)
        cpu = self._cpu_from_agent_processes(processes, total_ticks, timestamp_ms)
        return PerformanceSnapshot(
            device_id=self.device_id,
            online=True,
            current_package=self._target,
            target_package=self._target,
            memory=memory,
            cpu=cpu,
            status="Collecting",
        )

    def stop(self) -> None:
        self.process_runner.stop(self.process_key, timeout=2.0)
        self._proc = None
        self._cpu_baselines.clear()
        self._cpu_total_baseline = None

    def _read_batch(self) -> tuple[int | None, int, list["_AndroidAgentProcess"]] | None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return None
        lines: list[str] = []
        while True:
            line = proc.stdout.readline()
            if line == "":
                return None
            text = line.rstrip("\r\n")
            if text == "ADBLAB_END":
                break
            lines.append(text)
        return _parse_android_agent_batch(lines)

    def _process_error(self) -> str:
        proc = self._proc
        if proc is None or proc.stderr is None or proc.poll() is None:
            return ""
        try:
            return proc.stderr.read().strip()
        except Exception:
            return ""

    def _cpu_from_agent_processes(
        self,
        processes: list["_AndroidAgentProcess"],
        total_ticks: int,
        timestamp_ms: int,
    ) -> CpuSample:
        previous_processes = self._cpu_baselines
        previous_total = self._cpu_total_baseline
        process_delta = 0
        user_delta = 0
        system_delta = 0
        has_delta = False
        current_baselines: dict[str, tuple[int, int, int, int]] = {}
        thread_count = 0
        primary_pid = processes[0].pid
        for process in processes:
            if process.process_name == self._target:
                primary_pid = process.pid
            thread_count += process.thread_count
            current_baselines[process.identity] = (
                process.process_ticks,
                total_ticks,
                process.user_ticks,
                process.system_ticks,
            )
            previous = previous_processes.get(process.identity)
            if previous is None:
                continue
            delta = process.process_ticks - previous[0]
            delta_user = process.user_ticks - previous[2]
            delta_system = process.system_ticks - previous[3]
            if delta >= 0 and delta_user >= 0 and delta_system >= 0:
                process_delta += delta
                user_delta += delta_user
                system_delta += delta_system
                has_delta = True
        self._cpu_baselines = current_baselines
        self._cpu_total_baseline = total_ticks
        return build_cpu_sample(
            timestamp_ms=timestamp_ms,
            pid=primary_pid,
            process_ticks=process_delta if has_delta else None,
            total_ticks=total_ticks,
            previous_process_ticks=0 if has_delta else None,
            previous_total_ticks=previous_total,
            is_foreground=True,
            user_ticks=user_delta if has_delta else None,
            system_ticks=system_delta if has_delta else None,
            previous_user_ticks=0 if has_delta else None,
            previous_system_ticks=0 if has_delta else None,
            thread_count=thread_count,
            cpu_count=self._cpu_count or 1,
            process_count=len(processes),
        )


@dataclass(frozen=True)
class _AndroidAgentProcess:
    pid: int
    process_name: str
    start_time_ticks: int
    user_ticks: int
    system_ticks: int
    thread_count: int
    rss_kb: int | None = None
    pss_kb: int | None = None

    @property
    def identity(self) -> str:
        return f"{self.pid}:{self.start_time_ticks}"

    @property
    def process_ticks(self) -> int:
        return self.user_ticks + self.system_ticks


def _android_agent_command(target: str, *, interval_seconds: float) -> str:
    escaped_target = _shell_single_quote(target)
    sleep_text = f"{interval_seconds:.3f}".rstrip("0").rstrip(".")
    return (
        "while true; do "
        "while IFS= read -r line; do case \"$line\" in cpu*) printf 'ADBLAB_STAT\\t%s\\n' \"$line\";; esac; done < /proc/stat; "
        "for d in /proc/[0-9]*; do "
        "pid=${d##*/}; "
        "[ -r \"$d/cmdline\" ] || continue; "
        "cmd=$(tr '\\0' ' ' < \"$d/cmdline\" | sed 's/[[:space:]]*$//'); "
        f"[ \"$cmd\" = {escaped_target} ] || case \"$cmd\" in {escaped_target}:*) ;; *) continue ;; esac; "
        "[ -r \"$d/stat\" ] || continue; "
        "threads=$(awk '/^Threads:/ {print $2; exit}' \"$d/status\" 2>/dev/null); "
        "rss=$(awk '/^VmRSS:/ {print $2; exit}' \"$d/status\" 2>/dev/null); "
        "pss=''; "
        "[ -r \"$d/smaps_rollup\" ] && pss=$(awk '/^Pss:/ {print $2; exit}' \"$d/smaps_rollup\" 2>/dev/null); "
        "stat=$(cat \"$d/stat\" 2>/dev/null); "
        "printf 'ADBLAB_PROC\\t%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n' \"$pid\" \"$cmd\" \"$threads\" \"$rss\" \"$pss\" \"$stat\"; "
        "done; "
        "echo ADBLAB_END; "
        f"sleep {sleep_text}; "
        "done"
    )


def _parse_android_agent_batch(lines: list[str]) -> tuple[int | None, int, list[_AndroidAgentProcess]]:
    proc_stat_lines: list[str] = []
    processes: list[_AndroidAgentProcess] = []
    for line in lines:
        if line.startswith("ADBLAB_STAT\t"):
            proc_stat_lines.append(line.partition("\t")[2])
        elif line.startswith("ADBLAB_PROC\t"):
            process = _parse_android_agent_process_line(line)
            if process is not None:
                processes.append(process)
    total_ticks = parse_proc_stat_total("\n".join(proc_stat_lines))
    cpu_count = sum(1 for line in proc_stat_lines if line.startswith("cpu") and len(line) > 3 and line[3].isdigit())
    return total_ticks, cpu_count, processes


def _parse_android_agent_process_line(line: str) -> _AndroidAgentProcess | None:
    parts = line.split("\t", 6)
    if len(parts) != 7 or parts[0] != "ADBLAB_PROC":
        return None
    _, pid_text, process_name, thread_text, rss_text, pss_text, stat_text = parts
    try:
        pid = int(pid_text)
    except ValueError:
        return None
    cpu_ticks = parse_process_stat_cpu_ticks(stat_text)
    start_time = parse_process_start_time_ticks(stat_text)
    if cpu_ticks is None or start_time is None:
        return None
    thread_count = _int_or_none(thread_text)
    return _AndroidAgentProcess(
        pid=pid,
        process_name=process_name,
        start_time_ticks=start_time,
        user_ticks=cpu_ticks[0],
        system_ticks=cpu_ticks[1],
        thread_count=thread_count if thread_count is not None else (parse_process_thread_count(stat_text) or 0),
        rss_kb=_int_or_none(rss_text),
        pss_kb=_int_or_none(pss_text),
    )


def _memory_from_agent_processes(processes: list[_AndroidAgentProcess], timestamp_ms: int) -> MemorySample:
    pss_values = [process.pss_kb for process in processes if process.pss_kb is not None]
    rss_values = [process.rss_kb for process in processes if process.rss_kb is not None]
    total_pss = sum(pss_values) if pss_values else (sum(rss_values) if rss_values else None)
    return MemorySample(timestamp_ms=timestamp_ms, total_pss_kb=total_pss)


def _int_or_none(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
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


def _shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
