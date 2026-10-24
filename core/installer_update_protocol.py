"""独立安装交接协议；仅私有管道 COMMIT 与成功退出共同授予执行权。"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from core.installer_update_process import ParentProcess, check_plain_path, locked_file
from services.app_update import InstallerAsset, validate_installer_asset
from utils.user_data import user_data_root

HELPER_NAME = "adblab-update-handoff"
COMMIT_TIMEOUT = 120.0
EXIT_TIMEOUT = 45.0


def validate_request(request: object) -> tuple[Path, InstallerAsset]:
    """请求只能指向用户升级缓存中的规范安装资产；持久化 JSON 不授予执行权。"""
    if not isinstance(request, dict) or set(request) != {
        "protocol", "pid", "created", "nonce", "path", "asset",
    }:
        raise ValueError("invalid handoff descriptor")
    if type(request["protocol"]) is not int or request["protocol"] != 1:
        raise ValueError("invalid protocol")
    if any(type(request[key]) is not int or request[key] <= 0 for key in ("pid", "created")):
        raise ValueError("invalid parent identity")
    if not isinstance(request["nonce"], str) or not re.fullmatch("[0-9a-f]{32}", request["nonce"]):
        raise ValueError("invalid request identity")
    try:
        asset = InstallerAsset(**request["asset"])
        validate_installer_asset(asset)
        path = Path(request["path"])
        root = (user_data_root() / "updates").absolute()
        if path.name != asset.name or path.parent.parent != root:
            raise ValueError("installer is outside update cache")
        check_plain_path(path)
    except (KeyError, TypeError, OSError) as error:
        raise ValueError("invalid installer descriptor") from error
    return path, asset


def child_environment() -> dict[str, str]:
    """独立 helper 使用自己的解包环境，外部 setup 不继承冻结依赖搜索目录。"""
    environment = dict(os.environ)
    for name in tuple(environment):
        if name.startswith("_PYI_") or name in {"PYTHONHOME", "PYTHONPATH"}:
            environment.pop(name)
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    roots = [Path(sys.executable).parent]
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(getattr(sys, "_MEIPASS")))
    entries = []
    for entry in environment.get("PATH", "").split(os.pathsep):
        if entry and not any(Path(entry).is_relative_to(root) for root in roots):
            entries.append(entry)
    environment["PATH"] = os.pathsep.join(entries)
    return environment


def _launch_installer(path: Path) -> None:
    """只启动交互向导，不拼接 shell 参数、不等待或宣称安装完成。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    kernel.SetDllDirectoryW.restype = ctypes.c_int
    if not kernel.SetDllDirectoryW(None):
        raise ctypes.WinError(ctypes.get_last_error())
    # 仅当前用户安装器不要求 UAC；CreateProcess 失败保留可重试缓存。
    subprocess.Popen([str(path)], cwd=path.parent, env=child_environment(),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True)


def _record(path: Path, nonce: str, status: str) -> None:
    """仅写本请求独占的脱敏结果；该记录不能用于恢复执行授权。"""
    try:
        check_plain_path(path)
        with (path.parent / f"handoff-{nonce}.json").open("x", encoding="utf-8") as stream:
            json.dump({"status": status}, stream)
    except (OSError, ValueError):
        # 结果记录失败不能改变执行判定，交接进程退出码仍保留失败。
        return


def execute_handoff(request: dict, *, receive, send) -> int:
    """先绑定父对象再 READY；授权、真实退出和锁内复核缺一不可。"""
    path, asset = validate_request(request)
    nonce = request["nonce"]
    status = "cancelled"
    try:
        with ParentProcess(request["pid"], request["created"]) as parent:
            send(f"READY {nonce}".encode("ascii"))
            if receive() != f"COMMIT {nonce}".encode("ascii"):
                return 2
            if not parent.wait(EXIT_TIMEOUT) or parent.exit_code != 0:
                status = "parent_exit_failed"
                return 3
            with locked_file(path) as stream:
                metadata = os.fstat(stream.fileno())
                if metadata.st_nlink != 1 or metadata.st_size != asset.size:
                    raise ValueError("installer size or link identity changed")
                if hashlib.file_digest(stream, "sha256").hexdigest() != asset.sha256:
                    raise ValueError("installer digest changed")
                check_plain_path(path)
                _launch_installer(path)
            status = "handed_off"
            return 0
    except (OSError, ValueError, EOFError, TimeoutError):
        status = "handoff_failed"
        return 4
    finally:
        _record(path, nonce, status)
