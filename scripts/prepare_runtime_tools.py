"""准备固定版本的平台工具；应用运行时不下载，支持离线归档与只读校验。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

if TYPE_CHECKING:
    from utils.tool_manifest import ToolBundle

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

_RECEIPT = ".bundle.json"


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _check_files(bundle: ToolBundle, target: Path) -> None:
    for name in bundle.required_files:
        path = target / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"工具文件缺失或不是常规文件：{name}")
    if os.name != "nt" and not bundle.adb.endswith(".exe"):
        for name in (bundle.adb, bundle.scrcpy):
            if not os.access(target / name, os.X_OK):
                raise ValueError(f"工具没有执行权限：{name}")


def _check_prepared(bundle: ToolBundle, target: Path) -> None:
    _check_files(bundle, target)
    if not bundle.url:
        return
    receipt = json.loads((target / _RECEIPT).read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or not isinstance(receipt.get("files"), dict):
        raise ValueError("工具清单格式错误")
    files = receipt.get("files", {})
    if receipt.get("sha256") != bundle.sha256 or not set(bundle.required_files) <= files.keys():
        raise ValueError("工具包版本校验不一致")
    for name, digest in files.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ValueError("工具清单格式错误")
        path = target / name
        if not path.resolve().is_relative_to(target.resolve()) or path.is_symlink():
            raise ValueError("工具清单包含非法路径")
        if not path.is_file() or _digest(path) != digest:
            raise ValueError(f"工具文件校验失败：{name}")


def _extract_bundle(bundle: ToolBundle, archive: Path, destination: Path) -> None:
    """按已校验清单指定的格式安全解压，不依赖离线归档的文件扩展名。"""
    from utils.archive import safe_extract_zip

    if bundle.archive_format == "zip":
        with ZipFile(archive) as package:
            safe_extract_zip(package, destination)
        return
    if bundle.archive_format != "tar.gz":
        raise ValueError("不支持的工具归档格式")
    with tarfile.open(archive, "r:gz") as package:
        members = package.getmembers()
        for member in members:
            output = destination / member.name
            if (not output.resolve().is_relative_to(destination.resolve())
                    or not (member.isfile() or member.isdir())):
                raise ValueError("工具归档包含不安全成员 (archive)")
        package.extractall(destination, members=members, filter="data")


def prepare_bundle(
    bundle: ToolBundle, *, root: Path, archive: Path | None = None, check_only: bool = False,
) -> Path:
    """校验后才更新工具目录；准备失败不发布新清单，离线校验绝不联网或修复文件。"""
    target = root / bundle.directory
    try:
        _check_prepared(bundle, target)
        return target
    except (OSError, ValueError) as error:
        if check_only or not bundle.url:
            raise ValueError("内置工具未准备或已损坏，请运行工具准备脚本。") from error

    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".tools-prepare-", dir=root) as temporary:
        staging = Path(temporary)
        package_archive = archive
        if package_archive is None:
            package_archive = staging / "download.archive"
            with urllib.request.urlopen(bundle.url, timeout=60) as response:
                with package_archive.open("wb") as output:
                    shutil.copyfileobj(response, output)
        if _digest(package_archive) != bundle.sha256:
            raise ValueError("工具归档 SHA256 校验失败")
        unpacked = staging / "unpacked"
        _extract_bundle(bundle, package_archive, unpacked)
        prepared = unpacked / bundle.archive_root
        _check_files(bundle, prepared)
        files = {
            path.relative_to(prepared).as_posix(): _digest(path)
            for path in prepared.rglob("*") if path.is_file()
        }
        for name in files:
            destination = target / name
            if destination.is_symlink() or not destination.resolve().is_relative_to(root.resolve()):
                raise ValueError("工具目录包含不安全的链接")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(prepared, target, dirs_exist_ok=True)
        receipt = staging / _RECEIPT
        receipt.write_text(json.dumps({"sha256": bundle.sha256, "files": files}), encoding="utf-8")
        os.replace(receipt, target / _RECEIPT)
    return target


def main(argv: list[str] | None = None) -> int:
    """准备当前主机对应工具；未提供内置包的平台明确提示使用系统工具。"""
    from utils.tool_manifest import get_tool_bundle

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="仅校验现有工具，不下载")
    parser.add_argument("--archive", type=Path, help="使用已下载的官方归档")
    args = parser.parse_args(argv)
    bundle = get_tool_bundle()
    if bundle is None:
        print("当前平台/架构使用系统 ADB 和 scrcpy。")
        return 0
    try:
        prepare_bundle(bundle, root=ROOT, archive=args.archive, check_only=args.check)
    except OSError as error:
        print(
            f"工具准备失败：{error}。请检查网络或目录访问权限；如工具被占用，关闭后重试。",
            file=sys.stderr,
        )
        return 1
    except (ValueError, tarfile.TarError, BadZipFile) as error:
        print(f"工具准备失败：{error}", file=sys.stderr)
        return 1
    print(f"平台工具已就绪：{bundle.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
