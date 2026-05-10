"""Lightweight ADB shell wrapper — adapted from guiscrcpy extracted_core.

Path resolution: delegates to utils.adb_resolver (bundled scrcpy ADB > system PATH).
"""

import logging
import subprocess
import sys

from utils.adb_resolver import adb_path

logger = logging.getLogger("adb_bridge")

_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class ADBBridge:
    """Thin wrapper around ADB shell/input/dimensions commands."""

    def __init__(self, path: str | None = None):
        self.path = path or adb_path()
        if not self.path:
            raise FileNotFoundError("ADB not found — install Android SDK Platform Tools")

    # -- core helpers ----------------------------------------------------

    def _open(self, cmd: list[str], **kw):
        kw.setdefault("creationflags", _CREATION_FLAGS)
        return subprocess.Popen(cmd, **kw)

    def _decode(self, proc: subprocess.Popen) -> str:
        out, _ = proc.communicate(timeout=15)
        return out.decode(errors="ignore") if out else ""

    # -- public API ------------------------------------------------------

    def shell(self, command: str, device_id: str | None = None):
        """Run an ADB shell command, return Popen with stdout=PIPE."""
        cmd = [self.path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", command])
        return self._open(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def shell_input(self, command: str, device_id: str | None = None):
        """Send an 'input' command to the device shell (keyevent, swipe, etc.)."""
        return self.shell(f"input {command}", device_id=device_id)

    def get_dimensions(self, device_id: str | None = None):
        """Get device screen [width, height] via 'wm size'. Returns list or None."""
        try:
            proc = self.shell("wm size", device_id=device_id)
            raw = self._decode(proc)
            for prefix in ("Physical size:", "Override size:"):
                if prefix in raw:
                    return raw[raw.find(prefix):].split(":")[1].strip().split("x")
            return None
        except Exception:
            return None

    def devices(self) -> list[list[str]]:
        """List connected devices as [[serial, status], ...]."""
        proc = self._open([self.path, "devices"], stdout=subprocess.PIPE)
        out = self._decode(proc)
        return [line.split("\t") for line in out.strip().splitlines()[1:] if line.strip()]
