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

    @property
    def executable_files(self) -> tuple[str, ...]:
        """列出准备后需要执行权限的主机程序。"""
        return (self.adb, self.scrcpy)


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


@dataclass(frozen=True)
class Aapt2Bundle:
    """独立 APK 分析工具归档，不混入 scrcpy 的上游文件清单。"""

    directory: str
    executable: str
    required_files: tuple[str, ...]
    url: str
    sha256: str
    version: str = "9.4.1-15978811"
    runtime_version: str = "2.20-15978811"
    archive_root: str = ""
    archive_format: Literal["zip"] = "zip"

    @property
    def executable_files(self) -> tuple[str, ...]:
        """列出需要执行权限的 AAPT2 程序。"""
        return (self.executable,)


_AAPT2_URL = "https://dl.google.com/dl/android/maven2/com/android/tools/build/aapt2/9.4.1-15978811"
AAPT2_WINDOWS_BUNDLE = Aapt2Bundle(
    "runtime-tools/aapt2/windows-x86_64", "aapt2.exe", ("aapt2.exe", "NOTICE"),
    f"{_AAPT2_URL}/aapt2-9.4.1-15978811-windows.jar",
    "5fe3c8ee5c6b3f47efd1fced1d6418084037f54f13290816c5db717e6b5c92aa",
)
AAPT2_LINUX_BUNDLE = Aapt2Bundle(
    "runtime-tools/aapt2/linux-x86_64", "aapt2", ("aapt2", "NOTICE"),
    f"{_AAPT2_URL}/aapt2-9.4.1-15978811-linux.jar",
    "f5bebd466ecf14d341fd465f2756a16d86052f29eb4532003d5ff7bcffd08de5",
)


def get_aapt2_bundle(platform: str | None = None, machine: str | None = None) -> Aapt2Bundle | None:
    """仅在已交付平台选用内置 APK 工具，其他平台保留环境工具兼容。"""
    platform = sys.platform if platform is None else platform
    machine = (host_platform.machine() if machine is None else machine).lower()
    if machine not in {"x86_64", "amd64"}:
        return None
    if platform == "win32":
        return AAPT2_WINDOWS_BUNDLE
    if platform == "linux":
        return AAPT2_LINUX_BUNDLE
    return None


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


def macos_tool_candidates(tool: str, machine: str | None = None) -> list[tuple[str, str]]:
    """仅生成 Homebrew 标准位置；当前架构前缀优先，存在性与能力由调用方检查。"""
    machine = (host_platform.machine() if machine is None else machine).lower()
    arm = ("homebrew_arm64", f"/opt/homebrew/bin/{tool}")
    intel = ("homebrew_x64", f"/usr/local/bin/{tool}")
    return [arm, intel] if machine in {"arm64", "aarch64"} else [intel, arm]
