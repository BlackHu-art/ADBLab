"""ADB path resolver — bundled > system PATH > None, with startup validation."""

import os
import shutil

from utils.resource_path import resource_path

_adb_path: str | None = None
_resolved: bool = False


def resolve_adb_path() -> str | None:
    """Find the best available ADB binary. Cached after first call.

    Priority:
      1. Bundled: scrcpy-win64-v3.3.1/adb.exe
      2. System: shutil.which("adb")
      3. None
    """
    global _adb_path, _resolved
    if _resolved:
        return _adb_path

    from utils.log_utils import get_logger
    log = get_logger("adb")

    bundled = resource_path(os.path.join("scrcpy-win64-v3.3.1", "adb.exe"))
    if os.path.isfile(bundled):
        _adb_path = bundled
        log.info(f"using bundled ADB: {_adb_path}")
    else:
        system_adb = shutil.which("adb")
        if system_adb:
            _adb_path = system_adb
            log.info(f"using system ADB: {_adb_path}")
        else:
            log.warning("ADB not found — install Android SDK Platform Tools")
            _adb_path = None

    _resolved = True
    return _adb_path


def adb_path() -> str:
    """Return ADB path or 'adb' as fallback."""
    path = resolve_adb_path()
    return path if path else "adb"


def is_adb_available() -> bool:
    """Check if a usable ADB binary exists."""
    return resolve_adb_path() is not None

