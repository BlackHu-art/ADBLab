"""Lightweight ADB shell wrapper for ADBLab.

Path resolution: delegates to utils.adb_resolver (bundled scrcpy ADB > system PATH).
"""

import logging

from models.base.command_runner import CommandResult, CommandRunner
from models.base.process_runner import ProcessRunner
from utils.adb_resolver import adb_path

logger = logging.getLogger("adb_bridge")


class ADBBridge:
    """Thin wrapper around ADB shell/input/dimensions commands."""

    def __init__(self, path: str | None = None):
        self.path = path or adb_path()
        self._process_runner = ProcessRunner()
        if not self.path:
            raise FileNotFoundError("ADB not found — install Android SDK Platform Tools")

    # -- public API ------------------------------------------------------

    def shell(self, command: str, device_id: str | None = None) -> CommandResult:
        """Run an ADB shell command and return a standardized result."""
        cmd = [self.path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", command])
        return CommandRunner.run(cmd, timeout=15)

    def shell_input(self, command: str, device_id: str | None = None):
        """Send an 'input' command to the device shell (keyevent, swipe, etc.)."""
        cmd = [self.path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", f"input {command}"])
        return self._process_runner.spawn(cmd)

    def get_dimensions(self, device_id: str | None = None):
        """Get device screen [width, height] via 'wm size'. Returns list or None."""
        try:
            result = self.shell("wm size", device_id=device_id)
            raw = result.output if result.success else result.error
            for prefix in ("Physical size:", "Override size:"):
                if prefix in raw:
                    return raw[raw.find(prefix):].split(":")[1].strip().split("x")
            return None
        except Exception:
            return None

    def devices(self) -> list[list[str]]:
        """List connected devices as [[serial, status], ...]."""
        result = CommandRunner.run([self.path, "devices"], timeout=15)
        out = result.output if result.success else result.error
        return [line.split("\t") for line in out.strip().splitlines()[1:] if line.strip()]
