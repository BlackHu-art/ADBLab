"""提供应用运行时可写的用户数据目录。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from utils.app_metadata import APP_NAME


def user_data_root() -> Path:
    """返回当前用户可写的 ADBLab 运行时数据根目录。"""
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
    """返回用户配置目录下指定文件的路径。"""
    return str(user_data_root() / "config" / filename)
