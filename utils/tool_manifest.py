"""共享源码、打包和自检使用的平台工具清单；导入时不执行 I/O。"""

from __future__ import annotations

import platform as host_platform
import sys
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolBundle:
    """记录一套配套工具，目录相对应用资源根；下载仅由准备脚本执行。"""

    directory: str
    adb: str
    scrcpy: str
    required_files: tuple[str, ...]
    url: str = ""
    sha256: str = ""
    archive_root: str = ""
    server: str = "scrcpy-server"
    scrcpy_version: str = "4.1"
    server_sha256: str = "deacb991ed2509715160ffdc7907e47b4160eb30d1566217e9047fd5b8850cae"
    archive_format: Literal["tar.gz", "zip"] = "tar.gz"


WINDOWS_BUNDLE = ToolBundle(
    directory="runtime-tools/windows-x86_64",
    adb="adb.exe",
    scrcpy="scrcpy.exe",
    required_files=(
        "adb.exe", "scrcpy.exe", "scrcpy-server", "AdbWinApi.dll", "AdbWinUsbApi.dll",
        "SDL3.dll", "avcodec-62.dll", "avformat-62.dll", "avutil-60.dll", "swresample-6.dll",
        "libusb-1.0.dll", "LICENSE.txt",
    ),
    url="https://github.com/Genymobile/scrcpy/releases/download/v4.1/scrcpy-win64-v4.1.zip",
    sha256="5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db",
    archive_root="scrcpy-win64-v4.1",
    archive_format="zip",
)
LINUX_BUNDLE = ToolBundle(
    "runtime-tools/linux-x86_64", "adb", "scrcpy",
    ("adb", "scrcpy", "scrcpy-server", "LICENSE"),
    "https://github.com/Genymobile/scrcpy/releases/download/v4.1/scrcpy-linux-x86_64-v4.1.tar.gz",
    "ad56ae8bfeedf41e824945c11dbf55fcb092b3e615b9b486f48a50e30d389635",
    "scrcpy-linux-x86_64-v4.1",
)


def get_tool_bundle(platform: str | None = None, machine: str | None = None) -> ToolBundle | None:
    """仅返回已交付架构的工具；其他环境沿用系统工具，绝不跨架构猜测。"""
    platform = sys.platform if platform is None else platform
    machine = (host_platform.machine() if machine is None else machine).lower()
    if machine not in {"x86_64", "amd64"}:
        return None
    if platform == "win32":
        return WINDOWS_BUNDLE
    if platform == "linux":
        return LINUX_BUNDLE
    return None
