from __future__ import annotations

import os
import re
import time

from models.base.command_runner import CommandRunner
from models.base.focus_detector import detect_current_package
from models.base.process_runner import ProcessRunner

from .parsers import (
    build_cpu_sample,
    enrich_startup_from_logcat,
    parse_am_start_output,
    parse_gfxinfo_output,
    parse_meminfo_output,
    parse_proc_stat_total,
    parse_process_stat_ticks,
)
from .report_service import PerformanceReportService
from .types import CpuSample, DeviceInfo, FrameMetrics, MemorySample, PerformanceSnapshot, StartupMetrics


class PerformanceService:
    """ADB-backed performance collection for one device."""

    def __init__(self, device_id: str, process_key_prefix: str | None = None):
        self.device_id = device_id
        self.process_key_prefix = process_key_prefix or f"performance_{device_id}_{id(self)}"
        self.process_runner = ProcessRunner()
        self.report_service = PerformanceReportService()
        self._cpu_baselines: dict[str, tuple[int, int]] = {}
        self._device_info_cache: DeviceInfo | None = None

    def stop(self) -> None:
        self.process_runner.stop_all()

    def device_online(self) -> bool:
        result = CommandRunner.run(["adb", "-s", self.device_id, "get-state"], timeout=5)
        return result.success and result.output.strip() == "device"

    def current_package(self) -> str:
        result = detect_current_package(self.device_id)
        return result.get("package_name", "") if result.get("success") else ""

    def device_info(self, refresh: bool = False) -> DeviceInfo:
        if self._device_info_cache is not None and not refresh:
            return self._device_info_cache
        props = self._shell("getprop", timeout=8)
        cpuinfo = self._shell("cat /proc/cpuinfo", timeout=8)
        meminfo = self._shell("cat /proc/meminfo", timeout=8)
        serial = self._adb(["get-serialno"], timeout=5)
        gl = self._shell("dumpsys SurfaceFlinger | grep -iE 'GLES|OpenGL|GPU'", timeout=8)
        if not gl.strip():
            gl = self._shell("dumpsys SurfaceFlinger", timeout=8)
        info = DeviceInfo(
            device_name=_first_available(
                _prop(props, "ro.product.marketname"),
                _prop(props, "ro.product.name"),
                _prop(props, "ro.product.device"),
            ),
            device_type=_first_available(
                _prop(props, "ro.product.model"),
                _prop(props, "ro.product.vendor.model"),
                _prop(props, "ro.product.board"),
            ),
            os=_first_available(_prop(props, "ro.build.version.release"), _prop(props, "ro.system.build.version.release")),
            cpu_type=_cpu_type(cpuinfo, props),
            cpu_info=_cpu_info(cpuinfo, props),
            cpu_arch=_first_available(_prop(props, "ro.product.cpu.abi"), _prop(props, "ro.product.cpu.abilist")),
            cpu_core_num=str(self._cpu_core_count()),
            cpu_freq=self._cpu_freq(),
            gpu_type=_gpu_type(gl),
            opengl=_opengl_info(gl),
            gpu_freq=self._gpu_freq(),
            ram_size=_ram_size(meminfo),
            swap=_swap_size(meminfo),
            root="Yes" if self._is_rooted() else "No",
            serial_num=serial.strip() or "unavailable",
        )
        self._device_info_cache = info
        return info

    def _adb(self, args: list[str], timeout: int = 10) -> str:
        result = CommandRunner.run(["adb", "-s", self.device_id, *args], timeout=timeout)
        return result.output if result.success else ""

    def _shell(self, command: str, timeout: int = 10) -> str:
        result = CommandRunner.run(["adb", "-s", self.device_id, "shell", command], timeout=timeout)
        return result.output if result.success else ""

    def _cpu_core_count(self) -> int:
        output = self._shell("ls /sys/devices/system/cpu | grep -E '^cpu[0-9]+$'", timeout=5)
        return len([line for line in output.splitlines() if re.match(r"cpu\d+$", line.strip())])

    def _cpu_freq(self) -> str:
        output = self._shell(
            "for d in /sys/devices/system/cpu/cpu[0-9]*; do "
            "c=${d##*/}; "
            "min=$d/cpufreq/cpuinfo_min_freq; max=$d/cpufreq/cpuinfo_max_freq; "
            "[ -f $min ] && [ -f $max ] && echo $c=$(cat $min)-$(cat $max); "
            "done",
            timeout=8,
        )
        ranges: dict[str, list[str]] = {}
        for line in output.splitlines():
            name, sep, raw_range = line.partition("=")
            if not sep or "-" not in raw_range:
                continue
            min_text, max_text = raw_range.split("-", 1)
            try:
                formatted = f"{_format_khz(int(min_text))}-{_format_khz(int(max_text))}"
            except ValueError:
                continue
            ranges.setdefault(formatted, []).append(name.strip())
        if not ranges:
            return "unavailable"
        return "\n".join(f"{','.join(cpus)}: {freq}" for freq, cpus in ranges.items())

    def _gpu_freq(self) -> str:
        output = self._shell(
            "for f in "
            "/sys/class/kgsl/kgsl-3d0/devfreq/min_freq "
            "/sys/class/kgsl/kgsl-3d0/devfreq/max_freq "
            "/sys/class/devfreq/*gpu*/min_freq "
            "/sys/class/devfreq/*gpu*/max_freq; do "
            "[ -f $f ] && echo ${f##*/}=$(cat $f); "
            "done",
            timeout=8,
        )
        values = {}
        for line in output.splitlines():
            key, sep, value = line.partition("=")
            if sep and value.strip().isdigit():
                values[key.strip()] = int(value.strip())
        if "min_freq" in values and "max_freq" in values:
            return f"{_format_hz(values['min_freq'])}-{_format_hz(values['max_freq'])}"
        return "unavailable"

    def _is_rooted(self) -> bool:
        output = self._shell("su -c id", timeout=3)
        return "uid=0" in output

    def memory_sample(self, package_name: str = "", timestamp_ms: int | None = None) -> MemorySample | None:
        package_name = package_name or self.current_package()
        if not package_name:
            return None
        result = CommandRunner.run(
            ["adb", "-s", self.device_id, "shell", "dumpsys", "meminfo", package_name],
            timeout=10,
        )
        if not result.success:
            return None
        return parse_meminfo_output(result.output, timestamp_ms=timestamp_ms or _now_ms())

    def frame_metrics(self, package_name: str) -> FrameMetrics | None:
        if not package_name:
            return None
        result = CommandRunner.run(
            ["adb", "-s", self.device_id, "shell", "dumpsys", "gfxinfo", package_name, "framestats"],
            timeout=15,
        )
        if not result.success:
            return None
        return parse_gfxinfo_output(result.output)

    def cpu_sample(
        self,
        package_name: str,
        *,
        current_package: str = "",
        timestamp_ms: int | None = None,
    ) -> CpuSample | None:
        if not package_name:
            return None
        pid = self._package_pid(package_name)
        if pid is None:
            self._cpu_baselines.pop(package_name, None)
            return None
        process_result = CommandRunner.run(
            ["adb", "-s", self.device_id, "shell", "cat", f"/proc/{pid}/stat"],
            timeout=5,
        )
        total_result = CommandRunner.run(
            ["adb", "-s", self.device_id, "shell", "cat", "/proc/stat"],
            timeout=5,
        )
        if not process_result.success or not total_result.success:
            return None
        process_ticks = parse_process_stat_ticks(process_result.output)
        total_ticks = parse_proc_stat_total(total_result.output)
        previous = self._cpu_baselines.get(package_name)
        if process_ticks is not None and total_ticks is not None:
            self._cpu_baselines[package_name] = (process_ticks, total_ticks)
        previous_process = previous[0] if previous else None
        previous_total = previous[1] if previous else None
        return build_cpu_sample(
            timestamp_ms=timestamp_ms or _now_ms(),
            pid=pid,
            process_ticks=process_ticks,
            total_ticks=total_ticks,
            previous_process_ticks=previous_process,
            previous_total_ticks=previous_total,
            is_foreground=bool(current_package and current_package == package_name),
        )

    def _package_pid(self, package_name: str) -> int | None:
        result = CommandRunner.run(
            ["adb", "-s", self.device_id, "shell", "pidof", package_name],
            timeout=5,
        )
        if not result.success or not result.output.strip():
            return None
        first = result.output.strip().split()[0]
        try:
            return int(first)
        except ValueError:
            return None

    def reset_frame_stats(self, package_name: str) -> None:
        if package_name:
            CommandRunner.run(
                ["adb", "-s", self.device_id, "shell", "dumpsys", "gfxinfo", package_name, "reset"],
                timeout=8,
            )

    def startup_metrics(self, package_name: str, activity: str = "") -> StartupMetrics:
        if not package_name:
            return StartupMetrics(
                device_id=self.device_id,
                package_name="",
                success=False,
                message="No package name provided",
            )
        CommandRunner.run(["adb", "-s", self.device_id, "logcat", "-c"], timeout=5)
        if activity:
            target = activity if "/" in activity else f"{package_name}/{activity}"
            command = ["adb", "-s", self.device_id, "shell", "am", "start", "-S", "-W", "-n", target]
        else:
            command = [
                "adb", "-s", self.device_id, "shell", "monkey",
                "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1",
            ]
            CommandRunner.run(["adb", "-s", self.device_id, "shell", "am", "force-stop", package_name], timeout=8)
            start = time.monotonic()
            result = CommandRunner.run(command, timeout=20)
            elapsed = int((time.monotonic() - start) * 1000)
            metrics = StartupMetrics(
                device_id=self.device_id,
                package_name=package_name,
                activity=activity,
                success=result.success,
                total_time_ms=elapsed if result.success else None,
                message="Launcher monkey start measured" if result.success else result.error,
            )
            logcat = CommandRunner.run(["adb", "-s", self.device_id, "logcat", "-d", "-v", "time"], timeout=10)
            if logcat.success:
                enrich_startup_from_logcat(metrics, logcat.output)
            return metrics

        result = CommandRunner.run(command, timeout=25)
        metrics = parse_am_start_output(
            result.output if result.success else result.error,
            device_id=self.device_id,
            package_name=package_name,
            activity=activity,
        )
        metrics.success = result.success and metrics.success
        if not result.success:
            metrics.message = result.error
        logcat = CommandRunner.run(["adb", "-s", self.device_id, "logcat", "-d", "-v", "time"], timeout=10)
        if logcat.success:
            enrich_startup_from_logcat(metrics, logcat.output)
        return metrics

    def snapshot(self, package_name: str = "") -> PerformanceSnapshot:
        online = self.device_online()
        current = self.current_package() if online else ""
        target = package_name or current
        memory = self.memory_sample(target) if online and target else None
        cpu = self.cpu_sample(target, current_package=current) if online and target else None
        return PerformanceSnapshot(
            device_id=self.device_id,
            online=online,
            current_package=current,
            target_package=target,
            memory=memory,
            cpu=cpu,
            status="Online" if online else "Offline",
        )

    def quick_check(self, package_name: str, activity: str = "") -> dict:
        package_name = package_name or self.current_package()
        report_dir = self.report_service.create_report_dir(self.device_id, package_name or "unknown")
        raw_files: dict[str, str] = {}
        samples: list[MemorySample] = []
        findings: list[str] = []

        startup = self.startup_metrics(package_name, activity) if package_name else None
        if startup:
            raw_files["startup"] = self.report_service.write_raw(
                report_dir,
                "startup.json",
                _json_text(startup.to_dict()),
            )

        self.reset_frame_stats(package_name)
        time.sleep(1)
        gfx = CommandRunner.run(
            ["adb", "-s", self.device_id, "shell", "dumpsys", "gfxinfo", package_name, "framestats"],
            timeout=15,
        ) if package_name else None
        frames = parse_gfxinfo_output(gfx.output) if gfx and gfx.success else None
        if gfx:
            raw_files["gfxinfo"] = self.report_service.write_raw(
                report_dir,
                "gfxinfo_framestats.txt",
                gfx.output if gfx.success else gfx.error,
            )

        mem = CommandRunner.run(
            ["adb", "-s", self.device_id, "shell", "dumpsys", "meminfo", package_name],
            timeout=10,
        ) if package_name else None
        if mem:
            raw_files["meminfo"] = self.report_service.write_raw(
                report_dir,
                "meminfo.txt",
                mem.output if mem.success else mem.error,
            )
            if mem.success:
                samples.append(parse_meminfo_output(mem.output, timestamp_ms=_now_ms()))

        status = _status_for(startup, frames, samples, findings)
        artifacts = self.report_service.write_report(
            report_dir,
            device_id=self.device_id,
            package_name=package_name,
            startup=startup,
            frames=frames,
            samples=samples,
            raw_files=raw_files,
            status=status,
            findings=findings,
        )
        return {
            "success": True,
            "report_dir": report_dir,
            "artifacts": artifacts,
            "startup": startup,
            "frames": frames,
            "samples": samples,
            "findings": findings,
            "status": status,
        }


def _status_for(
    startup: StartupMetrics | None,
    frames: FrameMetrics | None,
    samples: list[MemorySample],
    findings: list[str],
) -> str:
    status = "pass"
    if startup and startup.total_time_ms and startup.total_time_ms > 5000:
        findings.append(f"Startup TotalTime exceeded 5000ms: {startup.total_time_ms}ms")
        status = "fail"
    if frames and frames.jank_rate > 0.10:
        findings.append(f"Jank rate exceeded 10%: {frames.jank_rate:.2%}")
        status = "fail"
    elif frames and frames.jank_rate > 0.05 and status != "fail":
        findings.append(f"Jank rate exceeded 5%: {frames.jank_rate:.2%}")
        status = "warn"
    if samples and samples[-1].activities and samples[-1].activities > 1:
        findings.append(f"Activity count is high: {samples[-1].activities}")
        if status != "fail":
            status = "warn"
    return status


def _now_ms() -> int:
    return int(time.time() * 1000)


def _json_text(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


def _first_available(*values: str) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return "unavailable"


def _prop(getprop_output: str, key: str) -> str:
    match = re.search(rf"^\[{re.escape(key)}\]: \[(.*?)\]$", getprop_output, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _cpu_info(cpuinfo: str, props: str = "") -> str:
    values = []
    for line in cpuinfo.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() in {"hardware", "model name"}:
            text = value.strip()
            if text and text not in values:
                values.append(text)
    return "\n".join(values[:4]) or _first_available(_prop(props, "ro.hardware"), _prop(props, "ro.board.platform"))


def _cpu_type(cpuinfo: str, props: str = "") -> str:
    text = _cpu_info(cpuinfo, props)
    if text == "unavailable":
        return text
    return text.splitlines()[0].split()[0]


def _format_khz(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} GHz"
    return f"{value / 1000:.0f} MHz"


def _format_hz(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} GHz"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.0f} MHz"
    if value >= 1000:
        return f"{value / 1000:.0f} kHz"
    return f"{value} Hz"


def _ram_size(meminfo: str) -> str:
    match = re.search(r"^MemTotal:\s+(\d+)\s+kB", meminfo, re.MULTILINE)
    if not match:
        return "unavailable"
    gb = int(match.group(1)) / 1024 / 1024
    return f"{gb:.1f} GB"


def _swap_size(meminfo: str) -> str:
    total = 0
    for key in ("SwapTotal", "Zram"):
        match = re.search(rf"^{key}:\s+(\d+)\s+kB", meminfo, re.MULTILINE)
        if match:
            total += int(match.group(1))
    return f"{round(total / 1024)} MB" if total else "0 MB"


def _gpu_type(surfaceflinger: str) -> str:
    lines = [
        line.strip()
        for line in surfaceflinger.splitlines()
        if re.search(r"\b(GPU|GLES|renderer|vendor)\b", line, re.IGNORECASE)
    ]
    return "\n".join(lines[:4]) if lines else "unavailable"


def _opengl_info(surfaceflinger: str) -> str:
    lines = [
        line.strip()
        for line in surfaceflinger.splitlines()
        if re.search(r"\b(OpenGL|GLES|EGL)\b", line, re.IGNORECASE)
    ]
    return "\n".join(lines[:4]) if lines else "unavailable"
