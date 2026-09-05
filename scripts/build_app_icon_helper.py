"""用本机 JDK 与 Android SDK 构建可复现的图标 helper，不下载工具或修改环境。"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import subprocess
import tempfile
import zipfile
import zlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = _ROOT / "tools" / "app_icons" / "Main.java"
_SOURCE_ENTRY = "META-INF/adblab-source.sha256"
_STAMP = (1980, 1, 1, 0, 0, 0)


def _source_digest() -> str:
    """以 UTF-8/LF 源码计算摘要，避免 Git 的 Windows 换行转换误判旧产物。"""
    return hashlib.sha256(_SOURCE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify_helper(output: Path) -> None:
    """核对内嵌源码摘要与 DEX，避免修改 Java 后继续分发旧 helper。"""
    expected = _source_digest()
    with zipfile.ZipFile(output) as archive:
        if set(archive.namelist()) != {
            "META-INF/MANIFEST.MF", _SOURCE_ENTRY, "classes.dex"
        }:
            raise ValueError("图标 helper 归档条目不匹配")
        recorded = archive.read(_SOURCE_ENTRY).decode("ascii").strip()
        dex = archive.read("classes.dex")
        if (
            recorded != expected
            or len(dex) < 112
            or not dex.startswith(b"dex\n")
            or b"Lcom/adblab/icons/Main;" not in dex
            or struct.unpack_from("<I", dex, 32)[0] != len(dex)
            or dex[12:32] != hashlib.sha1(dex[32:]).digest()
            or struct.unpack_from("<I", dex, 8)[0] != zlib.adler32(dex[12:]) & 0xFFFFFFFF
        ):
            raise ValueError("图标 helper 与当前源码不匹配")


def build_helper(sdk: Path, java_home: Path, output: Path) -> None:
    """在临时目录编译，固定归档元数据后原子替换指定产物。"""
    suffix = ".exe" if os.name == "nt" else ""
    javac = java_home / "bin" / f"javac{suffix}"
    java = java_home / "bin" / f"java{suffix}"
    android = sdk / "platforms" / "android-33" / "android.jar"
    d8 = sdk / "build-tools" / "33.0.2" / "lib" / "d8.jar"
    for tool in (javac, java, android, d8):
        if not tool.is_file():
            raise ValueError("需要完整 JDK 与 Android SDK android-33/build-tools 33.0.2")
    with tempfile.TemporaryDirectory(prefix="adblab-icon-build-") as temporary:
        work = Path(temporary)
        classes = work / "classes"
        classes.mkdir()
        commands = [
            [
                str(javac), "--release", "8", "-encoding", "UTF-8", "-g:none",
                "-classpath", str(android), "-d", str(classes), str(_SOURCE),
            ],
            [
                str(java), "-cp", str(d8), "com.android.tools.r8.D8", "--release",
                "--min-api", "23", "--lib", str(android), "--output", str(work),
            ],
        ]
        subprocess.run(commands[0], check=True, timeout=60)
        commands[1].extend(str(path) for path in sorted(classes.rglob("*.class")))
        subprocess.run(commands[1], check=True, timeout=60)
        entries = {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\r\n\r\n",
            _SOURCE_ENTRY: (_source_digest() + "\n").encode(),
            "classes.dex": (work / "classes.dex").read_bytes(),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        # 同目录 staging 保证替换原子；只有完成全部检查的归档才覆盖目标产物。
        with tempfile.NamedTemporaryFile(
            prefix=".adblab-icons-", suffix=".jar", dir=output.parent, delete=False
        ) as handle:
            staged = Path(handle.name)
        try:
            with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, content in entries.items():
                    info = zipfile.ZipInfo(name, date_time=_STAMP)
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, content)
            verify_helper(staged)
            staged.replace(output)
        finally:
            staged.unlink(missing_ok=True)


def main() -> int:
    """支持显式工具路径或既有环境变量；校验模式不需要构建工具。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path)
    parser.add_argument("--java-home", type=Path)
    parser.add_argument("--output", type=Path, default=_ROOT / "resources/app-icon-helper.jar")
    parser.add_argument("--check", action="store_true", help="只核对归档与源码摘要")
    args = parser.parse_args()
    if args.check:
        verify_helper(args.output)
    else:
        sdk = args.sdk or os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        java_home = args.java_home or os.environ.get("JAVA_HOME")
        if not sdk or not java_home:
            parser.error("请指定 --sdk 与 --java-home，或设置对应已有环境变量")
        build_helper(Path(sdk), Path(java_home), args.output)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f"app-icon-helper.jar SHA256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
