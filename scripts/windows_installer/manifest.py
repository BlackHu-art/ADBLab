"""把已构建 onedir 复制为安装专用载荷，严格限定清单的文件归属。"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import shutil
import stat
import sys
from pathlib import Path

from core.windows_installation import (
    INSTALL_LOCK,
    INSTALL_MANIFEST,
    INSTALL_MARKER,
    INSTALL_PENDING_MANIFEST,
    MAIN_EXECUTABLE,
)

_RESERVED = {
    name.casefold()
    for name in (
        INSTALL_LOCK,
        INSTALL_MANIFEST,
        INSTALL_MARKER,
        INSTALL_PENDING_MANIFEST,
    )
}
_DOS_DEVICE = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(?:\.|$)", re.I)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def validate_relative_path(value: str) -> str:
    """拒绝 Windows 别名、控制文件、ADS 和非规范相对路径。"""
    if not value or any(ord(char) < 32 or char in '\\:*?"<>|' for char in value):
        raise ValueError(f"非法清单路径: {value!r}")
    for part in value.split("/"):
        if (
            not part
            or part in {".", ".."}
            or part.endswith((" ", "."))
            or _DOS_DEVICE.match(part)
            or part.casefold() in _RESERVED
            or part.casefold().startswith((".adblab-", "unins"))
        ):
            raise ValueError(f"非法或保留的清单路径: {value!r}")
    return value


def _check_collisions(paths: list[str]) -> None:
    """大小写不敏感文件系统不得出现重名或文件与祖先目录冲突。"""
    names: set[str] = set()
    directories: set[str] = set()
    for path in paths:
        folded = path.casefold()
        if folded in names or folded in directories:
            raise ValueError(f"路径大小写或文件目录冲突: {path}")
        names.add(folded)
        parts = folded.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            if parent in names:
                raise ValueError(f"文件目录冲突: {path}")
            directories.add(parent)


def _check_no_reparse(path: Path) -> None:
    """逐级 lstat，避免 resolve 隐藏被拒绝的重解析点。"""
    for candidate in (path, *path.parents):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"不允许符号链接或重解析点: {candidate}")


def _check_streams(path: Path) -> None:
    """Windows 载荷不接受复制时会丢失或藏匿内容的备用数据流。"""
    if sys.platform != "win32":
        return
    from ctypes import wintypes

    class StreamData(ctypes.Structure):
        _fields_ = [("size", ctypes.c_longlong), ("name", wintypes.WCHAR * 296)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    first = kernel.FindFirstStreamW
    first.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(StreamData), wintypes.DWORD]
    first.restype = wintypes.HANDLE
    next_stream = kernel.FindNextStreamW
    next_stream.argtypes = [wintypes.HANDLE, ctypes.POINTER(StreamData)]
    next_stream.restype = wintypes.BOOL
    close = kernel.FindClose
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    data = StreamData()
    handle = first(str(path), 0, ctypes.byref(data), 0)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error == 38:
            return
        raise OSError(error, "无法验证文件备用数据流", str(path))
    try:
        while True:
            if data.name != "::$DATA":
                raise ValueError(f"不允许备用数据流: {path}")
            if not next_stream(handle, ctypes.byref(data)):
                error = ctypes.get_last_error()
                if error != 38:
                    raise OSError(error, "无法枚举文件备用数据流", str(path))
                break
    finally:
        close(handle)


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def parse_manifest(data: bytes) -> dict[str, str]:
    """解析有 BOM 的 UTF-8 清单；非法清单整体失败，不忽略错误行。"""
    if not data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("清单必须包含 UTF-8 BOM")
    try:
        text = data[3:].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("清单必须为 UTF-8") from exc
    result: dict[str, str] = {}
    paths: list[str] = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or not _DIGEST.fullmatch(fields[0]):
            raise ValueError("清单摘要或分隔符无效")
        path = validate_relative_path(fields[1])
        paths.append(path)
        result[path] = fields[0]
    if not result:
        raise ValueError("清单不能为空")
    _check_collisions(paths)
    return result


def validate_manifest(manifest_path: Path, root: Path | None = None) -> dict[str, str]:
    """验证清单；指定根目录时同时验证每个实际文件的路径与摘要。"""
    manifest_path = Path(manifest_path)
    _check_no_reparse(manifest_path)
    result = parse_manifest(manifest_path.read_bytes())
    if root is not None:
        root = Path(root).absolute()
        for relative, expected in result.items():
            path = root / relative
            _check_no_reparse(path)
            if not path.is_file() or _hash(path) != expected:
                raise ValueError(f"载荷摘要不符或文件缺失: {relative}")
            _check_streams(path)
    return result


def validate_payload(source_dir: Path, entry_name: str) -> dict[str, str]:
    """只读验证 onedir 输入，先检查完整树再允许创建 staging。"""
    source_dir = Path(source_dir).absolute()
    validate_relative_path(entry_name)
    if "/" in entry_name or not entry_name.lower().endswith(".exe"):
        raise ValueError("主入口必须为根目录 EXE 文件名")
    _check_no_reparse(source_dir)
    if not source_dir.is_dir():
        raise ValueError("载荷目录不存在")
    files: dict[str, str] = {}
    seen: dict[str, str] = {}
    for folder, dirs, filenames in os.walk(source_dir, followlinks=False):
        for name in sorted(dirs + filenames):
            path = Path(folder) / name
            relative = path.relative_to(source_dir).as_posix()
            validate_relative_path(relative)
            folded = relative.casefold()
            if folded in seen:
                raise ValueError(f"路径大小写冲突: {relative}")
            seen[folded] = relative
            _check_no_reparse(path)
            _check_streams(path)
            if name in filenames:
                if not path.is_file():
                    raise ValueError(f"不支持的载荷类型: {relative}")
                files[relative] = _hash(path)
    entry = source_dir / entry_name
    if entry_name not in files or entry.stat().st_size == 0:
        raise ValueError("主入口缺失或为空")
    if not (source_dir / "_internal").is_dir():
        raise ValueError("载荷缺少 _internal 目录")
    mapped = [MAIN_EXECUTABLE if path == entry_name else path for path in files]
    _check_collisions(mapped)
    for relative, digest in files.items():
        if Path(relative).name.lower() == "adb.exe":
            alias = str(Path(relative).with_name("adblab-adb.exe")).replace("\\", "/")
            existing = seen.get(alias.casefold())
            if existing is not None and (existing not in files or files[existing] != digest):
                raise ValueError("ADB 同名副本与原工具内容不一致")
    return dict(sorted(files.items()))


def stage_payload(source_dir: Path, entry_name: str, staging_dir: Path) -> Path:
    """建立全新隔离副本；不改输入，预置受清单管理的 ADB 同字节副本。"""
    source_dir, staging_dir = Path(source_dir).absolute(), Path(staging_dir).absolute()
    _check_no_reparse(staging_dir)
    if (
        staging_dir == source_dir
        or source_dir in staging_dir.parents
        or staging_dir in source_dir.parents
        or staging_dir.exists()
    ):
        raise ValueError("staging 必须是与输入不重叠的新目录")
    original = validate_payload(source_dir, entry_name)
    staging_dir.mkdir(parents=True)
    for relative in original:
        target_relative = MAIN_EXECUTABLE if relative == entry_name else relative
        target = staging_dir / target_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_dir / relative, target)
    for relative in original:
        if Path(relative).name.lower() == "adb.exe":
            source = staging_dir / relative
            alias = source.with_name("adblab-adb.exe")
            if not alias.exists():
                shutil.copyfile(source, alias)
    staged = validate_payload(staging_dir, MAIN_EXECUTABLE)
    if validate_payload(source_dir, entry_name) != original:
        raise ValueError("复制期间输入载荷发生变化")
    for relative, digest in original.items():
        mapped = MAIN_EXECUTABLE if relative == entry_name else relative
        if staged[mapped] != digest:
            raise ValueError("复制载荷摘要不一致")
    manifest = staging_dir / INSTALL_MANIFEST
    manifest.write_bytes(
        (
            "\ufeff" + "".join(f"{digest}\t{relative}\n" for relative, digest in staged.items())
        ).encode("utf-8")
    )
    validate_manifest(manifest, staging_dir)
    return manifest
