"""Headless scrcpy service for ADBLab's Remote tab."""

import os
import platform
import re
import shutil
import subprocess
import time

from models.base.command_runner import CommandRunner
from models.base.process_runner import ProcessRunner
from utils.resource_path import resource_path

from .scrcpy_args import build_scrcpy_args
from .types import PreflightResult, ScrcpyConfig, ScrcpyLaunchPlan


class ScrcpyService:
    """Prepare and manage scrcpy without coupling to Qt widgets."""

    FPS_PATTERN = re.compile(r"\[(\d+\.?\d*)\s*fps\]")

    def __init__(
        self,
        process_runner: ProcessRunner | None = None,
        command_runner: type[CommandRunner] = CommandRunner,
    ):
        self.process_runner = process_runner or ProcessRunner()
        self.command_runner = command_runner
        self._version_cache: dict[str, str] = {}

    def run_command(self, cmd: list[str], timeout: int = 5):
        return self.command_runner.run(cmd, timeout=timeout)

    def resolve_executable(self) -> str:
        """解析 scrcpy 可执行文件路径，UI 层不直接关心平台和打包目录。"""
        if platform.system() == "Windows":
            return resource_path(os.path.join("scrcpy-win64-v3.3.1", "scrcpy.exe"))
        return shutil.which("scrcpy") or "scrcpy"

    def version(self, exe: str) -> str:
        cached = self._version_cache.get(exe)
        if cached:
            return cached
        try:
            result = self.run_command([exe, "--version"], timeout=3)
            match = re.search(r"(\d+\.\d+(?:\.\d+)?)", result.output)
            version = match.group(1) if match else "unknown"
        except Exception:
            version = "unknown"
        self._version_cache[exe] = version
        return version

    def device_info(self, adb: str, device: str) -> str:
        try:
            result = self.run_command([adb, "-s", device, "shell", "wm size"], timeout=5)
            raw = result.output or ""
            for prefix in ("Physical size:", "Override size:"):
                if prefix in raw:
                    return raw[raw.find(prefix):].split(":")[1].strip()
        except Exception:
            pass
        return ""

    def preflight_check(self, adb: str, device: str) -> PreflightResult:
        messages: list[tuple[str, str]] = []
        try:
            result = self.run_command([adb, "-s", device, "shell", "echo ok"], timeout=5)
            if (result.output or "").strip() != "ok":
                messages.append(("WARNING", f"Device {device} not responding"))
                return PreflightResult(False, messages)

            started = time.monotonic()
            self.run_command(
                [adb, "-s", device, "shell", "dd if=/dev/zero bs=1024 count=1 2>/dev/null"],
                timeout=5,
            )
            elapsed = time.monotonic() - started
            if elapsed > 1.0:
                messages.append(
                    (
                        "WARNING",
                        f"USB speed: {elapsed:.1f}s (slow). Try a different cable or USB 3.0 port",
                    )
                )
            else:
                messages.append(("INFO", f"USB speed: {elapsed * 1000:.0f}ms (OK)"))
            return PreflightResult(True, messages)
        except Exception as exc:
            messages.append(("WARNING", f"Pre-flight failed: {exc}"))
            return PreflightResult(False, messages)

    def detect_encoder(self, adb: str, device: str) -> str | None:
        try:
            result = self.run_command([adb, "-s", device, "shell", "dumpsys media.codec"], timeout=8)
            for line in (result.output or "").splitlines():
                lowered = line.lower()
                if "h264" in lowered and "encoder" in lowered:
                    name = line.strip().split()[0]
                    if "OMX" in name or name.startswith("c2."):
                        return name
        except Exception:
            pass
        return None

    def build_launch_plan(self, config: ScrcpyConfig) -> ScrcpyLaunchPlan:
        messages: list[tuple[str, str]] = []
        version = self.version(config.exe)
        messages.append(("INFO", f"scrcpy v{version}"))

        # 先做轻量连通性/USB 预检，离线设备可少跑一次耗时的 wm size。
        preflight = self.preflight_check(config.adb, config.device)
        messages.extend(preflight.messages)
        if not preflight.success:
            messages.append(("WARNING", "Pre-flight check failed - launching anyway..."))
            device_info = ""
        else:
            device_info = self.device_info(config.adb, config.device)

        encoder = None
        if config.hw_encoder:
            encoder = self.detect_encoder(config.adb, config.device)
            if encoder:
                messages.append(("INFO", f"Using encoder: {encoder}"))
            else:
                messages.append(("WARNING", "No hardware encoder found, using default"))

        return ScrcpyLaunchPlan(
            args=build_scrcpy_args(config, encoder),
            device_info=device_info,
            version=version,
            encoder=encoder,
            messages=messages,
        )

    def start(self, key: str, args: list[str]):
        return self.process_runner.start(
            key,
            args,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
        )

    def stop(self, key: str, timeout: float = 2.0) -> int | None:
        return self.process_runner.stop(key, timeout=timeout)

    @classmethod
    def parse_fps(cls, line: str) -> str | None:
        match = cls.FPS_PATTERN.search(line)
        return f"{match.group(1)} fps" if match else None
