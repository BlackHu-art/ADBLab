"""Resolve bundled external tools without running them from PyInstaller temp dirs."""

from __future__ import annotations

import os
import shutil
import sys
import threading
from pathlib import Path

from utils.app_metadata import APP_NAME, APP_VERSION
from utils.resource_path import resource_path

_copy_lock = threading.Lock()


def bundled_tool_path(bundle_dir: str, *relative_parts: str) -> str:
    """Return a usable path for a bundled external executable or data file.

    PyInstaller onefile extracts bundled binaries under ``sys._MEIPASS``. Long-lived
    tools such as adb can keep that directory locked after the Qt app exits, which
    makes the bootloader show "Failed to remove temporary directory". In frozen
    builds, copy the whole tool bundle to a stable per-user cache first and launch
    from there.
    """
    source_dir = Path(resource_path(bundle_dir))
    source_path = source_dir.joinpath(*relative_parts)
    if not getattr(sys, "frozen", False) or not source_dir.is_dir():
        return str(source_path)

    target_dir = _runtime_root() / bundle_dir
    target_path = target_dir.joinpath(*relative_parts)
    try:
        _ensure_runtime_copy(source_dir, target_dir)
    except OSError:
        return str(source_path)
    return str(target_path)


def _ensure_runtime_copy(source_dir: Path, target_dir: Path) -> None:
    with _copy_lock:
        if target_dir.exists():
            required_files = list(source_dir.iterdir())
            if required_files and all((target_dir / item.name).exists() for item in required_files):
                return
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)


def _runtime_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return Path(base) / APP_NAME / "runtime" / APP_VERSION

    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / APP_NAME / "runtime" / APP_VERSION
    return Path.home() / ".cache" / APP_NAME / "runtime" / APP_VERSION
