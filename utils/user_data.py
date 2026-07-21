"""User-writable application data paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from utils.app_metadata import APP_NAME


def user_data_root() -> Path:
    """Return the per-user writable root for ADBLab runtime data."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return Path(base) / APP_NAME

    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def user_config_path(filename: str) -> str:
    """Return a path under the writable config directory."""
    return str(user_data_root() / "config" / filename)
