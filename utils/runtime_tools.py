"""解析内置外部工具，并避免从 PyInstaller 临时目录运行长进程。"""

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
    """返回内置外部程序或数据文件的可用路径。

    PyInstaller onefile 会将二进制文件解压到 ``sys._MEIPASS``。ADB 等长进程可能在
    Qt 应用退出后继续锁定该目录，导致引导程序无法删除临时目录。因此打包运行时先把
    整个工具目录复制到稳定的用户缓存，再从缓存位置启动。
    """
    source_dir = Path(resource_path(bundle_dir))
    source_path = source_dir.joinpath(*relative_parts)
    if not getattr(sys, "frozen", False) or not source_dir.is_dir():
        return str(source_path)
    if not _is_onefile_extraction():
        return str(source_path)

    target_dir = _runtime_root() / bundle_dir
    target_path = target_dir.joinpath(*relative_parts)
    try:
        _ensure_runtime_copy(source_dir, target_dir)
    except OSError:
        return str(source_path)
    return str(target_path)


def _ensure_runtime_copy(source_dir: Path, target_dir: Path) -> None:
    """在进程内串行补齐用户缓存中的工具目录。"""
    with _copy_lock:
        if target_dir.exists():
            required_files = list(source_dir.iterdir())
            if required_files and all(
                _cache_entry_ok(source_dir / item.name, target_dir / item.name)
                for item in required_files
            ):
                return
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)


def _cache_entry_ok(source: Path, target: Path) -> bool:
    """目录存在即视为有效；文件额外校验大小，识别截断/损坏的残留副本。"""
    try:
        if source.is_dir():
            return target.is_dir()
        return target.is_file() and target.stat().st_size == source.stat().st_size
    except OSError:
        return False


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


def _is_onefile_extraction() -> bool:
    """判断 PyInstaller 当前是否从 onefile 临时解压目录运行。"""
    meipass = getattr(sys, "_MEIPASS", "")
    if not meipass:
        return False
    try:
        Path(meipass).resolve().relative_to(Path(sys.executable).resolve().parent)
        return False
    except ValueError:
        return True
    except OSError:
        return True
