"""安装版身份与维护准入协议；不依赖 Qt 或构建脚本。"""

from __future__ import annotations

import configparser
import ctypes
import hashlib
import re
import stat
import sys
from ctypes import wintypes
from pathlib import Path

APP_ID = "{1C0CD5FE-33F4-4BB0-964D-F2EC6A79F062}"
MAIN_EXECUTABLE = "ADBLab.exe"
INSTALL_MARKER = ".adblab-install.ini"
INSTALL_MANIFEST = ".adblab-files.txt"
INSTALL_PENDING_MANIFEST = ".adblab-pending-files.txt"
INSTALL_PREVIOUS_MANIFEST = ".adblab-files.txt.previous"
INSTALL_LOCK = ".adblab-maintenance.lock"
INSTALL_SECTION = "Installation"

_MESSAGES = {
    "maintenance": "ADBLab 正在维护，请稍后重试。",
    "incomplete": "ADBLab 安装尚未完成，请重新运行原安装程序修复或继续卸载。",
    "damaged": "ADBLab 安装信息损坏，请保留原目录后重新安装。",
    "permission": "ADBLab 无法读取安装信息，请检查目录读取权限后重试。",
}
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class InstallationUnavailable(RuntimeError):
    """安装准入失败；公开原因和提示仅包含分类，不携带磁盘路径。"""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(_MESSAGES[reason])


def _windows_api():
    """延迟加载指针宽度正确的 Win32 接口，其他平台不触及动态链接库。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _open_running_lock(path: Path) -> int:
    """只打开既有稳定锁；读者共享读、拒绝写和删除，句柄不可继承。"""
    handle = _windows_api().CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


class InstallationGuard:
    """入口拥有的共享运行句柄，必须保持至业务与其清理全部结束。"""

    def __init__(self, handle: int):
        self._handle: int | None = handle

    def close(self) -> None:
        """幂等释放当前进程的句柄，不修改或删除锁文件。"""
        if self._handle is not None:
            handle, self._handle = self._handle, None
            if not _windows_api().CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())


def _control_exists(path: Path) -> bool:
    """不能把无权限或重解析控制文件误判为免安装目录。"""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
        raise InstallationUnavailable("damaged")
    return True


def _read_identity(root: Path, executable: Path) -> configparser.SectionProxy:
    """同时兼容 UTF-8 与 Windows INI 的 UTF-16 BOM，拒绝残缺或未知身份。"""
    raw = (root / INSTALL_MARKER).read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(raw.decode(encoding))
    section = parser[INSTALL_SECTION]
    required = (
        "FormatVersion", "AppId", "MainExecutable", "State", "CompletedVersion",
        "PendingVersion", "ManifestSha256", "PendingManifestSha256",
    )
    if any(key not in section for key in required):
        raise InstallationUnavailable("damaged")
    if (
        section["FormatVersion"] != "1" or section["AppId"] != APP_ID
        or section["MainExecutable"] != MAIN_EXECUTABLE
        or executable.name.casefold() != MAIN_EXECUTABLE.casefold()
        or section["State"] not in {"installing", "ready", "removing"}
    ):
        raise InstallationUnavailable("damaged")
    for key, pattern in (
        ("CompletedVersion", _VERSION), ("PendingVersion", _VERSION),
        ("ManifestSha256", _SHA256), ("PendingManifestSha256", _SHA256),
    ):
        if section[key] and pattern.fullmatch(section[key]) is None:
            raise InstallationUnavailable("damaged")
    return section


def _verify_ready(root: Path, executable: Path) -> None:
    """取锁后再读身份和清单；仅接受完整提交或相同清单的清理残留。"""
    for name in (
        INSTALL_MARKER, INSTALL_MANIFEST, INSTALL_PENDING_MANIFEST,
        INSTALL_PREVIOUS_MANIFEST, INSTALL_LOCK,
    ):
        _control_exists(root / name)
    section = _read_identity(root, executable)
    if section["State"] != "ready":
        raise InstallationUnavailable("incomplete")
    if (
        not section["CompletedVersion"] or not section["ManifestSha256"]
        or section["PendingVersion"] or section["PendingManifestSha256"]
    ):
        raise InstallationUnavailable("damaged")
    manifest_digest = hashlib.sha256((root / INSTALL_MANIFEST).read_bytes()).hexdigest()
    if section["ManifestSha256"] != manifest_digest:
        raise InstallationUnavailable("damaged")
    pending = root / INSTALL_PENDING_MANIFEST
    if (
        _control_exists(pending)
        and hashlib.sha256(pending.read_bytes()).hexdigest() != manifest_digest
    ):
        raise InstallationUnavailable("damaged")


def acquire_installation_guard(executable: Path | None = None) -> InstallationGuard | None:
    """冻结 Windows 入口在分派前准入；显式路径仅绕过冻结限制供隔离测试。

    无控制文件的便携目录不创建任何文件；任一控制文件存在即失败关闭。
    取得共享锁后重新读取 ready 身份和摘要，任何失败都先释放已取得的句柄。
    """
    if sys.platform != "win32" or (executable is None and not getattr(sys, "frozen", False)):
        return None
    executable = Path(sys.executable) if executable is None else Path(executable)
    root = executable.absolute().parent
    guard = None
    try:
        managed = [_control_exists(root / name) for name in (
            INSTALL_MARKER, INSTALL_MANIFEST, INSTALL_PENDING_MANIFEST,
            INSTALL_PREVIOUS_MANIFEST, INSTALL_LOCK,
        )]
        if not any(managed):
            return None
        _read_identity(root, executable)
        guard = InstallationGuard(_open_running_lock(root / INSTALL_LOCK))
        _verify_ready(root, executable)
        return guard
    except BaseException as error:
        if guard is not None:
            guard.close()
        if isinstance(error, InstallationUnavailable):
            raise
        if isinstance(error, OSError):
            if getattr(error, "winerror", None) in {32, 33}:
                raise InstallationUnavailable("maintenance") from error
            reason = "permission" if isinstance(error, PermissionError) else "damaged"
            raise InstallationUnavailable(reason) from error
        if isinstance(error, (configparser.Error, UnicodeError, KeyError)):
            raise InstallationUnavailable("damaged") from error
        raise
