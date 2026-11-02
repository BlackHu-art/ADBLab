"""离线检查 macOS app 的架构、嵌套签名和内置工具动态依赖，不连接设备。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


class PackageError(Exception):
    """表示制品检查失败；失败的制品不得继续压缩或分发。"""


def _inspect(command: list[str]) -> str:
    """有界执行系统检查工具；错误输出只归构建诊断，不进入产品界面。"""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PackageError(f"{Path(command[0]).name} 检查无法完成") from error
    if result.returncode:
        raise PackageError(f"{Path(command[0]).name} 检查失败：{result.stderr.strip()}")
    return result.stdout


def check_package(app: Path, machine: str) -> Path:
    """验证当前架构的完整 app；允许 ADB 保留含目标架构的 universal2 载荷。

    检查只读取既有制品，不签名或修复；返回主程序供后续冻结探针使用。
    """
    if machine not in {"arm64", "x86_64"}:
        raise PackageError("不支持的 macOS 目标架构")
    if app.suffix != ".app" or not app.is_dir():
        raise PackageError("macOS app 缺失或不是目录")
    executable = app / "Contents/MacOS" / app.stem
    resources = app / "Contents/Frameworks"
    tool_root = resources / "runtime-tools" / f"macos-{machine}"
    binaries = (
        (executable, True),
        (resources / "runtime-helpers/adblab-adb-bridge/adblab-adb-bridge", True),
        (tool_root / "adb", False),
        (tool_root / "scrcpy", False),
    )
    for binary, thin in binaries:
        if not binary.is_file():
            raise PackageError(f"制品入口缺失：{binary.name}")
        architectures = set(_inspect(["/usr/bin/lipo", "-archs", str(binary)]).split())
        if machine not in architectures or (thin and architectures != {machine}):
            raise PackageError(f"制品架构不匹配：{binary.name}")
        _inspect([
            "/usr/bin/codesign", "--verify", "--all-architectures", "--strict", str(binary),
        ])
    for name in ("adb", "scrcpy"):
        output = _inspect(["/usr/bin/otool", "-L", str(tool_root / name)])
        libraries = [line.strip().split(" (", 1)[0] for line in output.splitlines()
                     if line.startswith("\t")]
        if not libraries or any(not library.startswith(("/System/Library/", "/usr/lib/"))
                                for library in libraries):
            raise PackageError(f"内置工具依赖非系统库：{name}")
    _inspect([
        "/usr/bin/codesign", "--verify", "--all-architectures", "--deep", "--strict", str(app),
    ])
    return executable


def main(argv: list[str] | None = None) -> int:
    """检查显式指定的已构建 app；失败保留非零退出码，绝不申请发布身份。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--machine", choices=("arm64", "x86_64"), required=True)
    args = parser.parse_args(argv)
    try:
        check_package(args.app, args.machine)
    except PackageError as error:
        print(f"macOS 制品检查失败：{error}", file=sys.stderr)
        return 1
    print("PASS macOS 架构、内置工具依赖与 codesign")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
