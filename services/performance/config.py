"""承载性能采集配置及兼容的配置序列化边界。"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field


def _split_semicolon(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if item.strip()]
    return [item.strip() for item in value.split(";") if item.strip()]


def _normalize_package(value: str) -> str:
    """规范化分号分隔的包名，并保留原有顺序、大小写和重复项。"""
    return ";".join(_split_semicolon(value))


def _primary_package(value: str) -> str:
    parts = _split_semicolon(value)
    return parts[0] if parts else value.strip()


def normalize_local_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    return os.path.normpath(value)


@dataclass(slots=True)
class MobilePerfMonkeyConfig:
    """写入 MobilePerf 临时配置的结构化 Monkey 命令选项。"""

    throttle_ms: int = 500
    seed: int = 1000000
    ignore_crashes: bool = True
    ignore_timeouts: bool = True
    ignore_security: bool = True
    kill_after_error: bool = True
    pct_touch: int = 15
    pct_motion: int = 5
    pct_trackball: int = 0
    pct_nav: int = 40
    pct_majornav: int = 30
    pct_syskeys: int = 5
    pct_appswitch: int = 0
    pct_anyevent: int = 5
    pct_flip: int = 0
    pct_pinchzoom: int = 0

    @property
    def total_percentage(self) -> int:
        return sum(
            self._clamped_percent(value)
            for value in (
                self.pct_touch,
                self.pct_motion,
                self.pct_trackball,
                self.pct_nav,
                self.pct_majornav,
                self.pct_syskeys,
                self.pct_appswitch,
                self.pct_anyevent,
                self.pct_flip,
                self.pct_pinchzoom,
            )
        )

    def to_config_values(self) -> dict[str, str]:
        return {
            "monkey_throttle": str(max(1, int(self.throttle_ms))),
            "monkey_seed": str(max(0, int(self.seed))),
            "monkey_ignore_crashes": self._bool_text(self.ignore_crashes),
            "monkey_ignore_timeouts": self._bool_text(self.ignore_timeouts),
            "monkey_ignore_security": self._bool_text(self.ignore_security),
            "monkey_kill_after_error": self._bool_text(self.kill_after_error),
            "monkey_pct_touch": str(self._clamped_percent(self.pct_touch)),
            "monkey_pct_motion": str(self._clamped_percent(self.pct_motion)),
            "monkey_pct_trackball": str(self._clamped_percent(self.pct_trackball)),
            "monkey_pct_nav": str(self._clamped_percent(self.pct_nav)),
            "monkey_pct_majornav": str(self._clamped_percent(self.pct_majornav)),
            "monkey_pct_syskeys": str(self._clamped_percent(self.pct_syskeys)),
            "monkey_pct_appswitch": str(self._clamped_percent(self.pct_appswitch)),
            "monkey_pct_anyevent": str(self._clamped_percent(self.pct_anyevent)),
            "monkey_pct_flip": str(self._clamped_percent(self.pct_flip)),
            "monkey_pct_pinchzoom": str(self._clamped_percent(self.pct_pinchzoom)),
        }

    @staticmethod
    def _bool_text(value: bool) -> str:
        return "true" if bool(value) else "false"

    @staticmethod
    def _clamped_percent(value: int) -> int:
        return max(0, min(100, int(value)))


@dataclass(slots=True)
class MobilePerfRunConfig:
    """承载界面提交的 MobilePerf 单次运行配置。"""

    device_id: str = ""
    package: str = ""
    frequency_seconds: int = 5
    timeout_minutes: int = 10
    dumpheap_minutes: int = 60
    monkey_enabled: bool = False
    exception_keywords: list[str] = field(default_factory=lambda: ["fatal exception", "has died"])
    phone_log_paths: list[str] = field(default_factory=lambda: ["/data/anr"])
    save_path: str = ""
    mailbox: str = ""
    monkey_config: MobilePerfMonkeyConfig = field(default_factory=MobilePerfMonkeyConfig)

    def __post_init__(self) -> None:
        """在模型边界固化分号字段，避免后续序列化产生空项和多余空白。"""
        self.package = _normalize_package(self.package)
        self.exception_keywords = _split_semicolon(self.exception_keywords)
        self.phone_log_paths = _split_semicolon(self.phone_log_paths)

    @property
    def result_root(self) -> str:
        return normalize_local_path(self.save_path)

    def to_config_parser(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        common = {
            "package": self.package,
            "frequency": str(max(1, int(self.frequency_seconds))),
            "timeout": str(max(1, int(self.timeout_minutes))),
            "dumpheap_freq": str(max(1, int(self.dumpheap_minutes))),
            "serialnum": self.device_id.strip(),
            "exceptionlog": ";".join(self.exception_keywords),
            "monkey": "true" if self.monkey_enabled else "false",
            "save_path": self.result_root,
            "phone_log_path": ";".join(self.phone_log_paths),
            "mailbox": self.mailbox.strip(),
            "pid_change_focus_package": "",
            "main_activity": "",
            "activity_list": "",
        }
        common.update(self.monkey_config.to_config_values())
        parser["Common"] = common
        return parser

    def write_config(self, directory: str | os.PathLike[str]) -> str:
        """把本次运行配置写入调用方给定的目录并返回路径。

        文件含设备、包名和本机保存路径，只属于单次运行；目录的创建与清理由调用方负责。
        """
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "mobileperf_run.conf")
        parser = self.to_config_parser()
        with open(path, "w", encoding="utf-8") as fh:
            parser.write(fh)
        return path
