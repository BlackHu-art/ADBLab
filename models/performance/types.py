from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StartupMetrics:
    device_id: str
    package_name: str
    activity: str = ""
    success: bool = False
    this_time_ms: int | None = None
    total_time_ms: int | None = None
    wait_time_ms: int | None = None
    displayed_ms: int | None = None
    fully_drawn_ms: int | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FrameMetrics:
    total_frames: int = 0
    janky_frames: int = 0
    jank_rate: float = 0.0
    slow_frame_rate: float = 0.0
    frozen_frame_rate: float = 0.0
    p50_ms: float | None = None
    p90_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    avg_frame_time_ms: float | None = None
    max_frame_time_ms: float | None = None
    slow_frames: int = 0
    frozen_frames: int = 0
    estimated_fps: float | None = None
    missed_vsync: int = 0
    high_input_latency: int = 0
    slow_ui_thread: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemorySample:
    timestamp_ms: int
    total_pss_kb: int | None = None
    java_heap_kb: int | None = None
    native_heap_kb: int | None = None
    graphics_kb: int | None = None
    stack_kb: int | None = None
    code_kb: int | None = None
    private_other_kb: int | None = None
    system_kb: int | None = None
    total_swap_pss_kb: int | None = None
    activities: int | None = None
    views: int | None = None
    view_roots: int | None = None
    app_contexts: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CpuSample:
    timestamp_ms: int
    process_percent: float | None = None
    process_user_percent: float | None = None
    process_system_percent: float | None = None
    is_foreground: bool = False
    pid: int | None = None
    thread_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceSnapshot:
    device_id: str
    online: bool
    current_package: str = ""
    target_package: str = ""
    uptime_seconds: int = 0
    memory: MemorySample | None = None
    cpu: CpuSample | None = None
    frames: FrameMetrics | None = None
    status: str = "Idle"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


@dataclass
class DeviceInfo:
    device_name: str = "unavailable"
    device_type: str = "unavailable"
    os: str = "unavailable"
    cpu_type: str = "unavailable"
    cpu_info: str = "unavailable"
    cpu_arch: str = "unavailable"
    cpu_core_num: str = "unavailable"
    cpu_freq: str = "unavailable"
    gpu_type: str = "unavailable"
    opengl: str = "unavailable"
    gpu_freq: str = "unavailable"
    ram_size: str = "unavailable"
    swap: str = "unavailable"
    root: str = "No"
    serial_num: str = "unavailable"

    def rows(self) -> list[dict[str, str]]:
        return [
            {"info": "Device Name", "value": self.device_name},
            {"info": "Device Type", "value": self.device_type},
            {"info": "OS", "value": self.os},
            {"info": "CPU Type", "value": self.cpu_type},
            {"info": "CPU Info", "value": self.cpu_info},
            {"info": "CPU Arch", "value": self.cpu_arch},
            {"info": "CPU CoreNum", "value": self.cpu_core_num},
            {"info": "CPU Freq", "value": self.cpu_freq},
            {"info": "GPU Type", "value": self.gpu_type},
            {"info": "OpenGL", "value": self.opengl},
            {"info": "GPU Freq", "value": self.gpu_freq},
            {"info": "Ram Size", "value": self.ram_size},
            {"info": "Swap", "value": self.swap},
            {"info": "Root", "value": self.root},
            {"info": "SerialNum", "value": self.serial_num},
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
