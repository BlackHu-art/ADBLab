"""定义 Remote 服务层使用的配置、预检结果和启动计划。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScrcpyConfig:
    """描述一次 scrcpy 启动所需的可执行文件、设备和视频选项。"""

    exe: str
    adb: str
    device: str
    maxsize: str
    fps: str
    bitrate: str
    codec: str
    buffer: str
    orientation: str
    prefer_text: bool = True
    window_title: str = ""
    hw_encoder: bool = False
    fullscreen: bool = False
    always_on_top: bool = False
    no_audio: bool = True
    show_touches: bool = False
    stay_awake: bool = False
    turn_screen_off: bool = False
    record_path: str = ""
    no_window: bool = False
    extra_args: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, values: dict) -> "ScrcpyConfig":
        return cls(
            exe=values["exe"],
            adb=values.get("adb", "adb"),
            device=values["device"],
            maxsize=values["maxsize"],
            fps=values["fps"],
            bitrate=values["bitrate"],
            codec=values["codec"],
            buffer=values["buffer"],
            orientation=values["orientation"],
            prefer_text=bool(values.get("prefer_text", True)),
            window_title=values.get("window_title", ""),
            hw_encoder=bool(values.get("hw_encoder", False)),
            fullscreen=bool(values.get("fullscreen", False)),
            always_on_top=bool(values.get("always_on_top", False)),
            no_audio=bool(values.get("no_audio", True)),
            show_touches=bool(values.get("show_touches", False)),
            stay_awake=bool(values.get("stay_awake", False)),
            turn_screen_off=bool(values.get("turn_screen_off", False)),
            record_path=values.get("record_path", ""),
            no_window=bool(values.get("no_window", False)),
            extra_args=list(values.get("extra_args", [])),
        )


@dataclass(frozen=True)
class PreflightResult:
    """记录 Remote 启动预检是否通过及其用户提示。"""

    success: bool
    messages: list[tuple[str, str]]


@dataclass(frozen=True)
class ScrcpyLaunchPlan:
    """保存预检后可直接交给进程层的 scrcpy 启动计划。"""

    args: list[str]
    device_info: str
    version: str
    encoder: str | None = None
    messages: list[tuple[str, str]] = field(default_factory=list)
