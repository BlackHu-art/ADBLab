"""通过共享资源清单构建应用；dry-run 只输出命令，不执行工具或写入产物。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))


def build_command(
    *, name: str, platform: str | None = None, onefile: bool = False,
    windowed: bool = False, icon: str = "",
) -> list[str]:
    """生成当前解释器的构建参数，平台差异仅影响工具资源及参数分隔符。"""
    from scripts.packaging_manifest import collection_options

    command = [
        sys.executable, "-m", "PyInstaller", "--name", name,
        "--specpath", str(ROOT / "build/app-spec"),
        "--onefile" if onefile else "--onedir",
    ]
    if windowed:
        command.append("--windowed")
    if icon:
        command.extend(("--icon", icon if icon == "NONE" else str(ROOT / icon)))
    # 生成的 spec 位于子目录，源文件必须相对仓库解析，避免改变资源根目录。
    command.extend(collection_options(platform, root=ROOT))
    command.append(str(ROOT / "main.py"))
    return command


def main(argv: list[str] | None = None) -> int:
    """先准备平台工具并构建桥接工具；任一子进程失败均保留其退出码。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="ADBLab")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--onefile", action="store_true")
    modes.add_argument("--onedir", action="store_true")
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--icon", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    commands = [
        [sys.executable, str(ROOT / "scripts/prepare_runtime_tools.py")],
        [sys.executable, str(ROOT / "scripts/build_scrcpy_adb_bridge.py")],
        build_command(
            name=args.name, onefile=args.onefile, windowed=args.windowed, icon=args.icon,
        ),
    ]
    if args.dry_run:
        print(json.dumps(commands, ensure_ascii=True))
        return 0
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
