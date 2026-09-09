"""使用现有 PyInstaller 构建独立 CLI，产物保持 onedir 以减少重复解压开销。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

def main() -> int:
    """只写项目 build 目录；标准输入输出由独立控制台入口保留。"""
    from utils.scrcpy_bridge import BRIDGE_NAME, bridge_source_digest

    output = ROOT / "build" / "runtime-helpers" / BRIDGE_NAME
    executable = output / (BRIDGE_NAME + (".exe" if sys.platform == "win32" else ""))
    stamp = output / "source.sha256"
    expected = bridge_source_digest(ROOT)
    if (
        executable.is_file() and stamp.is_file()
        and stamp.read_text(encoding="ascii").strip() == expected
    ):
        return subprocess.run([str(executable), "--self-check"], check=False).returncode
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
        "--noupx", "--name", BRIDGE_NAME, "--paths", str(ROOT),
        "--distpath", str(ROOT / "build" / "runtime-helpers"),
        "--workpath", str(ROOT / "build" / "adb-bridge-work"),
        "--specpath", str(ROOT / "build"),
        str(ROOT / "scripts" / "scrcpy_adb_bridge.py"),
    ], cwd=ROOT, check=True)
    subprocess.run([str(executable), "--self-check"], check=True)
    stamp.write_text(expected + "\n", encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
