from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from statistics import median
from typing import Protocol

from models.base.command_runner import CommandRunner
from models.base.process_runner import ProcessRunner

from .parsers import (
    build_cpu_sample,
    parse_proc_stat_total,
    parse_process_start_time_ticks,
    parse_process_stat_cpu_ticks,
    parse_process_thread_count,
)
from .types import CpuSample, FrameMetrics, MemorySample, PerformanceSnapshot


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
                rss_kb=round(memory_info.rss / 1024),
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
        sample_interval_seconds: float = 1.0,
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
        self._frame_sampler = AndroidFrameSampler(device_id)
        self._leak_detector = MemoryLeakDetector()

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
        self._frame_sampler.reset()
        self._frame_sampler.prime(target)
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
        frames = self._frame_sampler.sample(self._target)
        warnings = []
        leak_warning = self._leak_detector.observe(memory)
        if leak_warning:
            warnings.append(leak_warning)
        return PerformanceSnapshot(
            device_id=self.device_id,
            online=True,
            current_package=self._target,
            target_package=self._target,
            memory=memory,
            cpu=cpu,
            frames=frames,
            status="Collecting",
            warnings=warnings,
        )

    def stop(self) -> None:
        self.process_runner.stop(self.process_key, timeout=2.0)
        self._proc = None
        self._cpu_baselines.clear()
        self._cpu_total_baseline = None
        self._frame_sampler.reset()
        self._leak_detector.reset()

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
    memory: MemorySample | None = None

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
        "stat=$(cat \"$d/stat\" 2>/dev/null); "
        "printf 'ADBLAB_PROC\\t%s\\t%s\\t%s\\t%s\\t%s\\n' \"$pid\" \"$cmd\" \"$threads\" \"$rss\" \"$stat\"; "
        "[ -r \"$d/smaps\" ] && awk '"
        "BEGIN {name=\"\"; pss=0; swap=0} "
        "/^[0-9a-fA-F]+-[0-9a-fA-F]+/ {"
        "if (name != \"\" || pss || swap) printf \"ADBLAB_SMAP\\t%s\\t%s\\t%s\\t%s\\n\", pid, name, pss, swap; "
        "name=$0; sub(/^[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]*/, \"\", name); "
        "pss=0; swap=0; next"
        "} "
        "/^Pss:/ {pss += $2; next} "
        "/^SwapPss:/ {swap += $2; next} "
        "END {if (name != \"\" || pss || swap) printf \"ADBLAB_SMAP\\t%s\\t%s\\t%s\\t%s\\n\", pid, name, pss, swap}"
        "' pid=\"$pid\" \"$d/smaps\" 2>/dev/null; "
        "done; "
        "echo ADBLAB_END; "
        f"sleep {sleep_text}; "
        "done"
    )


def _parse_android_agent_batch(lines: list[str]) -> tuple[int | None, int, list[_AndroidAgentProcess]]:
    proc_stat_lines: list[str] = []
    processes_by_pid: dict[int, _AndroidAgentProcess] = {}
    smaps_by_pid: dict[int, list[str]] = {}
    for line in lines:
        if line.startswith("ADBLAB_STAT\t"):
            proc_stat_lines.append(line.partition("\t")[2])
        elif line.startswith("ADBLAB_PROC\t"):
            process = _parse_android_agent_process_line(line)
            if process is not None:
                processes_by_pid[process.pid] = process
        elif line.startswith("ADBLAB_SMAP\t"):
            parts = line.split("\t", 4)
            if len(parts) == 5:
                pid = _int_or_none(parts[1])
                if pid is not None:
                    smaps_by_pid.setdefault(pid, []).append(line)
    processes = []
    for pid, process in processes_by_pid.items():
        memory = parse_smaps_memory(smaps_by_pid.get(pid, []), timestamp_ms=0, rss_kb=process.rss_kb)
        processes.append(_copy_process_with_memory(process, memory))
    total_ticks = parse_proc_stat_total("\n".join(proc_stat_lines))
    cpu_count = sum(1 for line in proc_stat_lines if line.startswith("cpu") and len(line) > 3 and line[3].isdigit())
    return total_ticks, cpu_count, sorted(processes, key=lambda item: item.pid)


def _parse_android_agent_process_line(line: str) -> _AndroidAgentProcess | None:
    parts = line.split("\t", 5)
    if len(parts) != 6 or parts[0] != "ADBLAB_PROC":
        return None
    _, pid_text, process_name, thread_text, rss_text, stat_text = parts
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
    )


def _memory_from_agent_processes(processes: list[_AndroidAgentProcess], timestamp_ms: int) -> MemorySample:
    memories = [process.memory for process in processes if process.memory is not None]
    if not memories:
        rss_values = [process.rss_kb for process in processes if process.rss_kb is not None]
        return MemorySample(
            timestamp_ms=timestamp_ms,
            total_pss_kb=sum(rss_values) if rss_values else None,
            rss_kb=sum(rss_values) if rss_values else None,
        )

    def total(field: str) -> int | None:
        values = [getattr(memory, field) for memory in memories if getattr(memory, field) is not None]
        return sum(values) if values else None

    return MemorySample(
        timestamp_ms=timestamp_ms,
        total_pss_kb=total("total_pss_kb"),
        rss_kb=total("rss_kb"),
        java_heap_kb=total("java_heap_kb"),
        native_heap_kb=total("native_heap_kb"),
        graphics_kb=total("graphics_kb"),
        gpu_kb=total("gpu_kb"),
        stack_kb=total("stack_kb"),
        code_kb=total("code_kb"),
        private_other_kb=total("private_other_kb"),
        system_kb=total("system_kb"),
        total_swap_pss_kb=total("total_swap_pss_kb"),
    )


def _copy_process_with_memory(process: _AndroidAgentProcess, memory: MemorySample) -> _AndroidAgentProcess:
    return _AndroidAgentProcess(
        pid=process.pid,
        process_name=process.process_name,
        start_time_ticks=process.start_time_ticks,
        user_ticks=process.user_ticks,
        system_ticks=process.system_ticks,
        thread_count=process.thread_count,
        rss_kb=process.rss_kb,
        memory=memory,
    )


def parse_smaps_memory(lines: list[str] | str, *, timestamp_ms: int = 0, rss_kb: int | None = None) -> MemorySample:
    """Parse compact ADBLAB_SMAP rows or raw /proc/<pid>/smaps text into PSS buckets."""

    rows = _smaps_rows(lines)
    buckets = {
        "java_heap_kb": 0,
        "native_heap_kb": 0,
        "graphics_kb": 0,
        "gpu_kb": 0,
        "stack_kb": 0,
        "code_kb": 0,
        "private_other_kb": 0,
        "system_kb": 0,
    }
    total_pss = 0
    total_swap = 0
    for name, pss_kb, swap_kb in rows:
        if pss_kb is None:
            continue
        total_pss += pss_kb
        total_swap += swap_kb or 0
        bucket = _smaps_bucket(name)
        buckets[bucket] += pss_kb
    if total_pss == 0 and rss_kb is not None:
        total_pss = rss_kb
    return MemorySample(
        timestamp_ms=timestamp_ms,
        total_pss_kb=total_pss or None,
        rss_kb=rss_kb,
        java_heap_kb=buckets["java_heap_kb"] or None,
        native_heap_kb=buckets["native_heap_kb"] or None,
        graphics_kb=buckets["graphics_kb"] or None,
        gpu_kb=buckets["gpu_kb"] or None,
        stack_kb=buckets["stack_kb"] or None,
        code_kb=buckets["code_kb"] or None,
        private_other_kb=buckets["private_other_kb"] or None,
        system_kb=buckets["system_kb"] or None,
        total_swap_pss_kb=total_swap or None,
    )


def _smaps_rows(lines: list[str] | str) -> list[tuple[str, int | None, int | None]]:
    if isinstance(lines, str):
        return _raw_smaps_rows(lines)
    rows = []
    for line in lines:
        if not line.startswith("ADBLAB_SMAP\t"):
            continue
        parts = line.split("\t", 4)
        if len(parts) != 5:
            continue
        rows.append((parts[2], _int_or_none(parts[3]), _int_or_none(parts[4])))
    return rows


def _raw_smaps_rows(text: str) -> list[tuple[str, int | None, int | None]]:
    rows = []
    name = ""
    pss = 0
    swap = 0
    for line in text.splitlines():
        if _is_smaps_header(line):
            if name or pss or swap:
                rows.append((name, pss, swap))
            name = _smaps_mapping_name(line)
            pss = 0
            swap = 0
            continue
        stripped = line.strip()
        if stripped.startswith("Pss:"):
            pss += _first_int(stripped) or 0
        elif stripped.startswith("SwapPss:"):
            swap += _first_int(stripped) or 0
    if name or pss or swap:
        rows.append((name, pss, swap))
    return rows


def _is_smaps_header(line: str) -> bool:
    text = line.strip()
    if "-" not in text:
        return False
    first = text.split(maxsplit=1)[0]
    left, _, right = first.partition("-")
    return bool(left and right and all(ch in "0123456789abcdefABCDEF" for ch in left + right))


def _smaps_mapping_name(line: str) -> str:
    parts = line.split(maxsplit=5)
    return parts[5] if len(parts) >= 6 else ""


def _smaps_bucket(name: str) -> str:
    text = (name or "").lower()
    if any(token in text for token in ("dalvik", "zygote", "art", "jit-cache", "linearalloc")):
        return "java_heap_kb"
    if "[heap]" in text or "libc_malloc" in text or "scudo" in text or "malloc" in text:
        return "native_heap_kb"
    if any(token in text for token in ("graphic", "gralloc", "egl", "gl mtrack", "gfx", "ashmem")):
        return "graphics_kb"
    if any(token in text for token in ("kgsl", "gpu", "mali", "adreno", "vulkan")):
        return "gpu_kb"
    if "[stack" in text:
        return "stack_kb"
    if any(token in text for token in (".so", ".jar", ".apk", ".vdex", ".odex", ".oat", ".dex")):
        return "code_kb"
    if text.startswith("/") or "[anon:" in text or "[anon]" in text:
        return "private_other_kb"
    return "system_kb"


class AndroidFrameSampler:
    """Provider-owned one-second frame sampler.

    SurfaceFlinger layer latency is preferred when a target layer can be found.
    The runtime fallback uses gfxinfo framestats but stays inside the provider.
    """

    def __init__(self, device_id: str):
        self.device_id = device_id
        self._surface_layer_by_package: dict[str, str] = {}
        self._last_surface_present_ns_by_package: dict[str, int] = {}
        self._last_gfx_completed_ns_by_package: dict[str, int] = {}

    def reset(self) -> None:
        self._surface_layer_by_package.clear()
        self._last_surface_present_ns_by_package.clear()
        self._last_gfx_completed_ns_by_package.clear()

    def prime(self, package_name: str) -> None:
        if not package_name:
            return
        surface_output = self._surface_latency_output(package_name)
        latest_surface = _last_surface_present_ns(surface_output)
        if latest_surface is not None:
            self._last_surface_present_ns_by_package[package_name] = latest_surface
        gfx_output = self._framestats_output(package_name)
        latest_gfx = _last_completed_ns(gfx_output)
        if latest_gfx is not None:
            self._last_gfx_completed_ns_by_package[package_name] = latest_gfx

    def sample(self, package_name: str) -> FrameMetrics | None:
        if not package_name:
            return None
        surface_frames = self._sample_surfaceflinger(package_name)
        if surface_frames is not None:
            return surface_frames
        return self._sample_gfxinfo(package_name)

    def _sample_surfaceflinger(self, package_name: str) -> FrameMetrics | None:
        previous = self._last_surface_present_ns_by_package.get(package_name)
        output = self._surface_latency_output(package_name)
        if not output:
            return None
        frames = parse_surfaceflinger_latency(output, min_present_ns=previous)
        latest = _last_surface_present_ns(output)
        if latest is not None:
            self._last_surface_present_ns_by_package[package_name] = latest
        return frames if frames and frames.total_frames > 0 else None

    def _sample_gfxinfo(self, package_name: str) -> FrameMetrics | None:
        previous = self._last_gfx_completed_ns_by_package.get(package_name)
        output = self._framestats_output(package_name)
        if not output:
            return None
        frames = parse_frame_latency(output, min_completed_ns=previous)
        latest = _last_completed_ns(output)
        if latest is not None:
            self._last_gfx_completed_ns_by_package[package_name] = latest
        return frames if frames and frames.total_frames > 0 else None

    def _surface_latency_output(self, package_name: str) -> str:
        layer = self._surface_layer(package_name)
        if not layer:
            return ""
        result = CommandRunner.run(
            ["adb", "-s", self.device_id, "shell", f"dumpsys SurfaceFlinger --latency {_shell_single_quote(layer)}"],
            timeout=4,
        )
        return result.output if result.success else ""

    def _surface_layer(self, package_name: str) -> str:
        cached = self._surface_layer_by_package.get(package_name)
        if cached is not None:
            return cached
        result = CommandRunner.run(
            ["adb", "-s", self.device_id, "shell", "dumpsys", "SurfaceFlinger", "--list"],
            timeout=4,
        )
        if not result.success:
            self._surface_layer_by_package[package_name] = ""
            return ""
        candidates = [line.strip() for line in result.output.splitlines() if package_name in line]
        layer = _best_surface_layer(candidates, package_name)
        self._surface_layer_by_package[package_name] = layer
        return layer

    def _framestats_output(self, package_name: str) -> str:
        result = CommandRunner.run(
            ["adb", "-s", self.device_id, "shell", "dumpsys", "gfxinfo", package_name, "framestats"],
            timeout=6,
        )
        return result.output if result.success else ""


def parse_surfaceflinger_latency(output: str, *, min_present_ns: int | None = None) -> FrameMetrics | None:
    rows = _surface_latency_rows(output, min_present_ns=min_present_ns)
    if not rows:
        return None
    durations = [duration_ms for _desired, _present, duration_ms in rows]
    total = len(rows)
    slow = sum(1 for value in durations if value > 16.67)
    frozen = sum(1 for value in durations if value > 700)
    return FrameMetrics(
        total_frames=total,
        janky_frames=slow,
        jank_rate=slow / total if total else 0,
        slow_frames=slow,
        frozen_frames=frozen,
        slow_frame_rate=slow / total if total else 0,
        frozen_frame_rate=frozen / total if total else 0,
        estimated_fps=_fps_from_rows(rows),
        p50_ms=round(_percentile(durations, 50), 2),
        p90_ms=round(_percentile(durations, 90), 2),
        p95_ms=round(_percentile(durations, 95), 2),
        p99_ms=round(_percentile(durations, 99), 2),
        avg_frame_time_ms=round(sum(durations) / total, 2),
        max_frame_time_ms=round(max(durations), 2),
    )


def parse_frame_latency(output: str, *, min_completed_ns: int | None = None) -> FrameMetrics | None:
    rows = _frame_rows(output, min_completed_ns=min_completed_ns)
    if not rows:
        return None
    durations = [duration_ms for _intended, _completed, duration_ms in rows]
    total = len(durations)
    slow = sum(1 for value in durations if value > 16.67)
    frozen = sum(1 for value in durations if value > 700)
    metrics = FrameMetrics(
        total_frames=total,
        janky_frames=slow,
        jank_rate=slow / total if total else 0,
        slow_frames=slow,
        frozen_frames=frozen,
        slow_frame_rate=slow / total if total else 0,
        frozen_frame_rate=frozen / total if total else 0,
        estimated_fps=_fps_from_rows(rows),
        p50_ms=round(_percentile(durations, 50), 2),
        p90_ms=round(_percentile(durations, 90), 2),
        p95_ms=round(_percentile(durations, 95), 2),
        p99_ms=round(_percentile(durations, 99), 2),
        avg_frame_time_ms=round(sum(durations) / total, 2),
        max_frame_time_ms=round(max(durations), 2),
    )
    return metrics


def _frame_rows(output: str, *, min_completed_ns: int | None = None) -> list[tuple[int, int, float]]:
    rows = []
    header = []
    for line in output.splitlines():
        if line.startswith("Flags,"):
            header = line.split(",")
            continue
        if not header or not line or line.startswith("---PROFILEDATA---"):
            continue
        values = line.split(",")
        try:
            intended = int(values[header.index("IntendedVsync")] or "0")
            completed = int(values[header.index("FrameCompleted")] or "0")
        except (ValueError, IndexError):
            continue
        if intended <= 0 or completed <= intended:
            continue
        if min_completed_ns is not None and completed <= min_completed_ns:
            continue
        rows.append((intended, completed, (completed - intended) / 1_000_000))
    return rows


def _surface_latency_rows(output: str, *, min_present_ns: int | None = None) -> list[tuple[int, int, float]]:
    refresh_period_ns = _surface_refresh_period_ns(output)
    refresh_ms = (refresh_period_ns or 16_666_667) / 1_000_000
    rows = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            desired = int(parts[0])
            actual = int(parts[1])
            ready = int(parts[2])
        except ValueError:
            continue
        if desired <= 0 or actual <= 0 or ready < 0:
            continue
        if min_present_ns is not None and actual <= min_present_ns:
            continue
        lateness_ms = max(0.0, (actual - desired) / 1_000_000)
        rows.append((desired, actual, refresh_ms + lateness_ms))
    return rows


def _fps_from_rows(rows: list[tuple[int, int, float]]) -> float | None:
    if len(rows) < 2:
        return None
    elapsed = (rows[-1][0] - rows[0][0]) / 1_000_000_000
    if elapsed <= 0:
        return None
    return round((len(rows) - 1) / elapsed, 2)


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * percentile / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _last_completed_ns(output: str) -> int | None:
    completed_values = [completed for _intended, completed, _duration in _frame_rows(output)]
    return max(completed_values) if completed_values else None


def _last_surface_present_ns(output: str) -> int | None:
    present_values = [actual for _desired, actual, _duration in _surface_latency_rows(output)]
    return max(present_values) if present_values else None


def _surface_refresh_period_ns(output: str) -> int | None:
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 1:
            value = _int_or_none(parts[0])
            if value and 1_000_000 <= value <= 100_000_000:
                return value
        if len(parts) >= 3:
            break
    return None


def _best_surface_layer(candidates: list[str], package_name: str) -> str:
    if not candidates:
        return ""
    return max(candidates, key=lambda layer: _surface_layer_score(layer, package_name))


def _surface_layer_score(layer: str, package_name: str) -> int:
    text = layer.lower()
    package = package_name.lower()
    score = 0
    if text.startswith(package):
        score += 6
    if package in text:
        score += 3
    if "surfaceview" in text:
        score += 2
    if any(token in text for token in ("splash", "starting", "dim layer", "wallpaper", "statusbar", "navigationbar", "ime")):
        score -= 8
    return score


class MemoryLeakDetector:
    def __init__(
        self,
        *,
        warmup_seconds: int = 10,
        window_seconds: int = 60,
        min_growth_kb: int = 10 * 1024,
        min_growth_ratio: float = 0.15,
    ):
        self.warmup_seconds = warmup_seconds
        self.window_seconds = window_seconds
        self.min_growth_kb = min_growth_kb
        self.min_growth_ratio = min_growth_ratio
        self._samples: list[tuple[int, int]] = []
        self._last_warning_at = 0

    def reset(self) -> None:
        self._samples.clear()
        self._last_warning_at = 0

    def observe(self, memory: MemorySample) -> str | None:
        value = memory.total_pss_kb
        if value is None:
            return None
        timestamp = memory.timestamp_ms
        self._samples.append((timestamp, value))
        window_ms = self.window_seconds * 1000
        self._samples = [(ts, pss) for ts, pss in self._samples if timestamp - ts <= window_ms]
        if timestamp - self._samples[0][0] < self.warmup_seconds * 1000:
            return None
        baseline = median(pss for _ts, pss in self._samples[: max(1, len(self._samples) // 3)])
        growth = value - baseline
        ratio = growth / baseline if baseline else 0
        can_warn = self._last_warning_at == 0 or timestamp - self._last_warning_at >= 10_000
        if growth >= self.min_growth_kb and ratio >= self.min_growth_ratio and can_warn:
            self._last_warning_at = timestamp
            return f"Memory growth trend: PSS +{int(growth)} KB over rolling window"
        return None


def _int_or_none(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _first_int(text: str) -> int | None:
    for token in str(text).replace(":", " ").split():
        try:
            return int(token)
        except ValueError:
            continue
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
