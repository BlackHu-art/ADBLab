"""校验固定来源后便携准备 Inno 编译器；仅写入本次构建目录，不修改系统安装。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INNO_VERSION = "6.7.3"
INNO_URL = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"
INNO_SHA256 = "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732"
RECEIPT = ".adblab-compiler.json"


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _reject_links(path: Path) -> None:
    for part in (path, *path.parents):
        if part.exists() and (
            part.is_symlink()
            or getattr(part.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("编译器目录不能经过重解析点或符号链接")


def validate_destination(destination: Path) -> Path:
    """限定固定版本工具只能部署在仓库构建区或显式 runner 临时区。"""
    target = destination.absolute()
    _reject_links(target)
    target = target.resolve()
    roots = [ROOT / "build", ROOT / ".tmp"]
    if os.environ.get("RUNNER_TEMP"):
        roots.append(Path(os.environ["RUNNER_TEMP"]))
    if target.name != f"inno-{INNO_VERSION}" or not any(
        target != root.resolve() and target.is_relative_to(root.resolve()) for root in roots
    ):
        raise ValueError("编译器目标必须位于构建临时目录且使用固定版本目录名")
    return target


def portable_command(archive: Path, destination: Path, log: Path) -> list[str]:
    """使用官方便携开关，不创建卸载项、快捷方式或文件关联。"""
    return [
        str(archive), "/PORTABLE=1", "/CURRENTUSER", "/VERYSILENT", "/SUPPRESSMSGBOXES",
        "/SP-", "/NORESTART", "/NOICONS", "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS",
        f"/DIR={destination}", f"/LOG={log}",
    ]


def _powershell(script: str, path: Path) -> str:
    # PowerShell 7 的模块路径不能传给 Windows PowerShell 5.1，否则内置信任校验模块无法加载。
    env = {key: value for key, value in os.environ.items() if key.casefold() != "psmodulepath"}
    env["ADBLAB_VERIFY_FILE"] = str(path)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise ValueError("编译器签名或版本校验失败")
    return result.stdout.strip()


def verify_signature(path: Path) -> None:
    """执行之前验证 Windows 信任链和官方发布者，路径通过环境变量传递。"""
    _powershell(
        "$ErrorActionPreference='Stop'; "
        "$s=Get-AuthenticodeSignature -LiteralPath $env:ADBLAB_VERIFY_FILE; "
        "if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch "
        "'(^|, )CN=Pyrsys B\\.V\\.(,|$)') { exit 1 }", path,
    )


def verify_compiler(path: Path) -> None:
    """验签后在临时目录编译无输出探针，核对真实引擎而非全零的 PE 版本资源。"""
    if not path.is_file() or path.is_symlink():
        raise ValueError("未找到已核验的 ISCC.exe")
    verify_signature(path)
    with tempfile.TemporaryDirectory(prefix="adblab-inno-probe-") as temporary:
        result = subprocess.run(
            [str(path.resolve()), "/O-", "-"], cwd=temporary,
            input="[Setup]\nAppName=ADBLab Compiler Probe\nAppVersion=1.0.0\n"
            "DefaultDirName={tmp}\\ADBLab-Compiler-Probe\nUninstallable=no\n",
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    version = re.search(r"Compiler engine version: Inno Setup ([0-9.]+)\b", result.stdout)
    if result.returncode or not version or version.group(1) != INNO_VERSION:
        raise ValueError(f"必须使用 Inno Setup {INNO_VERSION}")


def _inventory(directory: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        _reject_links(path)
        if path.is_file() and path.name != RECEIPT:
            files[path.relative_to(directory).as_posix()] = _digest(path)
    return files


def verify_receipt(directory: Path) -> None:
    """拒绝编译器文件被修改或额外注入，复用目录不靠可执行文件名字判断。"""
    receipt = json.loads((directory / RECEIPT).read_text(encoding="utf-8"))
    if (
        not isinstance(receipt, dict)
        or receipt.get("version") != INNO_VERSION
        or receipt.get("archive_sha256") != INNO_SHA256
        or receipt.get("files") != _inventory(directory)
        or not (directory / "ISCC.exe").is_file()
    ):
        raise ValueError("已有编译器目录的来源或文件校验不匹配")


def prepare(destination: Path, *, archive: Path | None = None) -> Path:
    """拒绝覆盖不明目录；部署失败保留诊断，不发布成功凭据，也不自动删除文件。"""
    target = validate_destination(destination)
    if target.exists() and any(target.iterdir()):
        try:
            verify_receipt(target)
        except (OSError, ValueError) as error:
            raise ValueError("目标目录非空且未通过验证，请保留该目录并使用干净构建目录") from error
        verify_compiler(target / "ISCC.exe")
        return target / "ISCC.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="inno-download-", dir=target.parent) as temporary:
        package = archive
        if package is None:
            package = Path(temporary) / "innosetup.exe"
            with (
                urllib.request.urlopen(INNO_URL, timeout=60) as response,
                package.open("wb") as output,
            ):
                size = 0
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > 64 * 1024 * 1024:
                        raise ValueError("编译器下载超出允许大小")
                    output.write(block)
        if not package.is_file() or package.is_symlink() or _digest(package) != INNO_SHA256:
            raise ValueError("Inno Setup SHA256 校验失败")
        verify_signature(package)
        result = subprocess.run(
            portable_command(package.resolve(), target, target.parent / "inno-prepare.log"),
            timeout=180, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise ValueError(f"Inno 便携准备失败，退出码 {result.returncode}")
    verify_compiler(target / "ISCC.exe")
    receipt = {"version": INNO_VERSION, "archive_sha256": INNO_SHA256, "files": _inventory(target)}
    (target / RECEIPT).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return target / "ISCC.exe"


def main(argv: list[str] | None = None) -> int:
    """准备仅供构建使用的固定编译器；dry-run 不联网、执行或写入。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        target = validate_destination(args.destination)
        if args.dry_run:
            print(json.dumps({
                "version": INNO_VERSION, "url": INNO_URL, "destination": str(target),
            }))
            return 0
        if sys.platform != "win32":
            raise ValueError("Inno 编译器准备仅支持 Windows")
        print(prepare(target, archive=args.archive))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
