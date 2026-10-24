"""用官方旧 ZIP 的真实字节验证升级；测试封装不是历史发布过的安装器。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

from core import windows_installation as protocol
from scripts import check_windows_installer as product
from scripts.build_windows_installer import protocol_include
from scripts.check_build_artifacts import check_installer_file
from scripts.prepare_inno_setup import verify_compiler
from scripts.windows_installer.manifest import (
    _check_no_reparse,
    stage_payload,
    validate_manifest,
    validate_payload,
    validate_relative_path,
)
from utils.archive import safe_extract_zip

LEGACY_VERSION = "3.3.2"
LEGACY_TAG_SHA = "e0c0d0487ee350c2ba8e3389a84ec998b616de33"
LEGACY_ASSET_ID = 653828320
LEGACY_SIZE = 157937553
LEGACY_SHA256 = "10f7322a6d9189b36dba50097d9d9f4e6c51fbbc7426af989d7c55a56765e8bc"
LEGACY_ARCHIVE = "ADBLab-win-x64-v3.3.2.zip"
LEGACY_ENTRY = "ADBLab-win-x64-v3.3.2.exe"
LEGACY_URL = (
    "https://github.com/BlackHu-art/ADBLab/releases/download/v3.3.2/" + LEGACY_ARCHIVE
)
LEGACY_INSTALLER = "legacy-zip-v3.3.2-test-setup.exe"


def _download_archive(destination: Path) -> None:
    """只接受固定发布资产的完整字节；失败保留诊断文件，不解压或执行。"""
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(LEGACY_URL, timeout=60) as response, destination.open("xb") as out:
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > LEGACY_SIZE:
                raise ValueError("官方旧 ZIP 下载大小超出固定值")
            digest.update(block)
            out.write(block)
    if size != LEGACY_SIZE or digest.hexdigest() != LEGACY_SHA256:
        raise ValueError("官方旧 ZIP 大小或 SHA-256 摘要不符")


def _extract_archive(archive: Path, destination: Path) -> None:
    """解压前拒绝 Windows 别名、碰撞及链接元数据，再由共享边界检查规模与路径。"""
    _check_no_reparse(destination)
    if destination.exists():
        raise ValueError("旧 ZIP 解压目录必须全新")
    with zipfile.ZipFile(archive) as zipped:
        explicit: set[str] = set()
        nodes: dict[str, tuple[str, bool]] = {}
        for member in zipped.infolist():
            is_directory = member.is_dir()
            raw_name = member.orig_filename
            name = raw_name[:-1] if is_directory else raw_name
            validate_relative_path(name)
            mode = stat.S_IFMT(member.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or member.external_attr & 0x400:
                raise ValueError("旧 ZIP 不能包含链接或重解析点")
            if (mode == stat.S_IFDIR and not is_directory) or member.flag_bits & 1:
                raise ValueError("旧 ZIP 文件类型或加密标记无效")
            folded = name.casefold()
            if folded in explicit:
                raise ValueError("旧 ZIP 存在重复或大小写碰撞")
            explicit.add(folded)
            parts = name.split("/")
            for index in range(1, len(parts) + 1):
                path = "/".join(parts[:index])
                directory = index < len(parts) or is_directory
                previous = nodes.get(path.casefold())
                if previous is not None and previous != (path, directory):
                    raise ValueError("旧 ZIP 存在文件目录或大小写碰撞")
                nodes[path.casefold()] = (path, directory)
        safe_extract_zip(zipped, destination)
    validate_payload(destination, LEGACY_ENTRY)


def prepare_legacy_installer(iscc: Path, workspace: Path) -> Path:
    """在全新目录下载、校验和编译旧载荷；允许本地调用，但绝不执行安装器。"""
    workspace = workspace.absolute()
    _check_no_reparse(workspace)
    if workspace.exists():
        raise ValueError("旧载荷编译 workspace 必须全新")
    verify_compiler(iscc)
    workspace.mkdir(parents=True, exist_ok=False)
    archive = workspace / LEGACY_ARCHIVE
    _download_archive(archive)
    source, payload = workspace / "source", workspace / "payload"
    _extract_archive(archive, source)
    stage_payload(source, LEGACY_ENTRY, payload)
    include = workspace / "protocol.iss"
    protocol_include(include)
    executable = workspace / LEGACY_INSTALLER
    product.run_checked(
        [str(iscc.resolve()), "/Qp", f"/DProtocolInclude={include}",
         f"/DAppSourceDir={payload}", f"/O{workspace}",
         str(Path(__file__).with_name("legacy_fixture.iss"))],
        workspace / "legacy-compile.log", env=dict(os.environ), timeout=900,
    )
    check_installer_file(executable)
    receipt = {
        "kind": "official ZIP payload in current test-only installer",
        "historical_installer": False,
        "version": LEGACY_VERSION,
        "tag_sha": LEGACY_TAG_SHA,
        "asset_id": LEGACY_ASSET_ID,
        "url": LEGACY_URL,
        "archive_size": LEGACY_SIZE,
        "archive_sha256": LEGACY_SHA256,
        "payload_manifest_sha256": hashlib.sha256(
            (payload / protocol.INSTALL_MANIFEST).read_bytes()
        ).hexdigest(),
    }
    (workspace / "legacy-origin.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8",
    )
    print("Prepared official v3.3.2 ZIP payload with current test-only wrapper; "
          "not a historical installer", flush=True)
    return executable


def _create_sentinels() -> dict[Path, bytes]:
    """仅排他创建 CI 合成配置和历史；任何目标已存在时拒绝，不读取或覆盖其字节。"""
    config = product._known_folder(28) / "ADBLab/config"
    exports = Path.home() / "ADBLab/installer-legacy-validation"
    sentinels = {
        config / "app_settings.json": b'{"schema_version":3,"language":"zh_CN"}\n',
        config / "test_runs.json": (
            b'{"version":1,"runs":[{"run_id":"installer-legacy-ci-run","kind":"monkey",'
            b'"package_name":"com.example.installer.fixture","started_at":1792800000,'
            b'"finished_at":1792800001,"state":"succeeded","parameters":{},'
            b'"artifacts":[],"device_label":"CI synthetic data","app_version":"3.3.2",'
            b'"message":"No device command executed"}],"presets":['
            b'{"preset_id":"installer-legacy-ci","name":"CI synthetic history",'
            b'"kind":"monkey","parameters":{},"updated_at":1792800000}]}\n'
        ),
        config / "connected_devices.yaml": b"{}\n",
        exports / "synthetic-export.txt": b"synthetic legacy export; no real device data\n",
    }
    for path in sentinels:
        _check_no_reparse(path)
        if path.exists():
            raise ValueError("CI 合成数据目标已存在，拒绝读取或覆盖")
        if any(parent.exists() and not parent.is_dir() for parent in path.parents):
            raise ValueError("CI 合成数据目录无效")
    for path, content in sentinels.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    return sentinels


def _assert_preserved(sentinels: dict[Path, bytes]) -> None:
    """只读本次排他创建的文件；路径替换、丢失和字节变化均是验收失败。"""
    for path, expected in sentinels.items():
        _check_no_reparse(path)
        if not path.is_file() or path.read_bytes() != expected:
            raise RuntimeError("升级或卸载改变了 CI 合成数据")


def run_legacy_upgrade(
    iscc: Path, installer: Path, version: str, workspace: Path, *, disposable: bool = False,
) -> None:
    """真实旧载荷安装、正式包升级及卸载均限一次性 runner，失败留存现场和日志。"""
    workspace = product.validate_environment(workspace, disposable)
    version = version.removeprefix("v")
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None or (
        tuple(map(int, version.split("."))) <= tuple(map(int, LEGACY_VERSION.split(".")))
    ):
        raise ValueError("旧载荷验收要求正式目标版本高于 3.3.2")
    check_installer_file(installer)
    if product.registered_installations() or any(path.exists() for path in product._shortcuts()):
        raise ValueError("一次性 runner 已有产品登记或快捷方式，拒绝接管")
    workspace.mkdir(parents=True, exist_ok=False)
    old_installer = prepare_legacy_installer(iscc, workspace / "legacy-build")
    sentinels = _create_sentinels()
    app = workspace / "真实旧载荷 中文 space"
    env = dict(os.environ, MOBILEPERF_LOG_DIR=str(workspace / "logs"))

    def install(setup: Path, label: str) -> None:
        product.run_checked(
            [str(setup.resolve()), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/SP-",
             "/NORESTART", "/RESTARTEXITCODE=3010", "/NOCLOSEAPPLICATIONS",
             "/NORESTARTAPPLICATIONS", f"/DIR={app}",
             f"/LOG={workspace / (label + '-inno.log')}"],
            workspace / (label + ".log"), env=env,
        )
        _assert_preserved(sentinels)

    def frozen(label: str) -> None:
        product.run_checked(
            [sys.executable, str(product.ROOT / "scripts/check_build_artifacts.py"), "frozen",
             "--executable", str(app / protocol.MAIN_EXECUTABLE), "--timeout", "60"],
            workspace / (label + "-frozen.log"), env=env, timeout=210,
        )
        _assert_preserved(sentinels)

    install(old_installer, "legacy-install")
    product._assert_ready(app, LEGACY_VERSION)
    old_files = validate_manifest(app / protocol.INSTALL_MANIFEST, app)
    expected_old = validate_manifest(
        workspace / "legacy-build/payload" / protocol.INSTALL_MANIFEST,
        workspace / "legacy-build/payload",
    )
    if old_files != expected_old:
        raise RuntimeError("实际安装的旧载荷与固定官方 ZIP staging 不一致")
    old_manifest_sha = hashlib.sha256((app / protocol.INSTALL_MANIFEST).read_bytes()).hexdigest()
    frozen("legacy")
    if validate_manifest(app / protocol.INSTALL_MANIFEST, app) != old_files:
        raise RuntimeError("旧版本冻结探针改变了安装清单")
    unknown = app / "legacy-user-kept.txt"
    with unknown.open("xb") as stream:
        stream.write(b"unknown user data in legacy install\n")
    sentinels[unknown] = b"unknown user data in legacy install\n"
    install(installer, "legacy-to-current")
    managed = product._assert_ready(app, version)
    current_files = validate_manifest(app / protocol.INSTALL_MANIFEST, app)
    if current_files[protocol.MAIN_EXECUTABLE] == old_files[protocol.MAIN_EXECUTABLE]:
        raise RuntimeError("升级后主入口仍是旧载荷字节")
    retired = sorted(old_files.keys() - current_files.keys())
    if any((app / name).exists() for name in retired):
        raise RuntimeError("正式升级未清理真实旧载荷的退役文件")
    current_manifest_sha = hashlib.sha256(
        (app / protocol.INSTALL_MANIFEST).read_bytes()
    ).hexdigest()
    frozen("current")
    if validate_manifest(app / protocol.INSTALL_MANIFEST, app) != current_files:
        raise RuntimeError("新版本冻结探针改变了安装清单")
    if retired:
        replacement = app / retired[0]
        replacement.parent.mkdir(parents=True, exist_ok=True)
        with replacement.open("xb") as stream:
            stream.write(b"new user data at retired legacy path\n")
        sentinels[replacement] = b"new user data at retired legacy path\n"
    product._uninstall(app, workspace, "legacy-current-uninstall", env, managed)
    _assert_preserved(sentinels)
    evidence = {
        "historical_installer": False, "old_version": LEGACY_VERSION, "new_version": version,
        "legacy_asset_sha256": LEGACY_SHA256, "legacy_tag_sha": LEGACY_TAG_SHA,
        "old_managed_count": len(old_files), "new_managed_count": len(current_files),
        "retired_paths": retired, "retired_replacement_verified": bool(retired),
        "old_main_sha256": old_files[protocol.MAIN_EXECUTABLE],
        "new_main_sha256": current_files[protocol.MAIN_EXECUTABLE],
        "old_manifest_sha256": old_manifest_sha, "new_manifest_sha256": current_manifest_sha,
    }
    (workspace / "legacy-upgrade-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2) + "\n", encoding="utf-8",
    )
    print("PASS official legacy ZIP payload upgrade (not a historical installer): "
          "old/new frozen commands, manifests, unknown files and synthetic data retention; "
          f"retired files={len(retired)}", flush=True)
