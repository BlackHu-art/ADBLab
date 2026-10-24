"""在一次性标准账户中串联真实旧载荷、故障事件和默认位置安装验收。"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import check_windows_installer as basic
from scripts.windows_installer.standard_user import (
    assert_current_user_installation as check_user_installation,
)
from scripts.windows_installer.standard_user import assert_standard_user as standard_identity
from tests.fixtures.windows_installer.fault_smoke import run_fault_fixture
from tests.fixtures.windows_installer.fault_smoke import run_product_install_race as product_race
from tests.fixtures.windows_installer.legacy_upgrade import run_legacy_upgrade


def run_default_installation(
    installer: Path, version: str, iscc: Path, workspace: Path, identity: dict[str, object],
) -> None:
    """仅由通过标准身份准入的入口调用；失败保留证据，成功时用正式安装器恢复后卸载。"""
    app = Path(str(identity["local_appdata"])) / "Programs/ADBLab"
    if app.exists() or app.is_symlink():
        raise ValueError("标准账户默认安装目录已存在，拒绝接管")
    workspace.mkdir(parents=True, exist_ok=False)
    sentinels = {}
    for directory in (Path(str(identity["local_appdata"])) / "ADBLab",
                      Path(str(identity["profile"])) / "ADBLab"):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "installer-race-sentinel.txt"
        with path.open("xb") as stream:
            stream.write(b"preserve default user data\n")
        sentinels[path] = b"preserve default user data\n"
    command = [str(installer.resolve()), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/SP-",
               "/NORESTART", "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS",
               "/TASKS=desktopicon"]
    env = dict(os.environ)

    def install(label: str) -> set[str]:
        basic.run_checked(command + [f"/LOG={workspace / (label + '-inno.log')}"],
                          workspace / f"{label}.log", env=env, timeout=300)
        managed = basic._assert_ready(app, version)
        check_user_installation(app, version, identity)
        return managed

    install("default-install")
    unknown = app / "unmanaged-user-file.txt"
    with unknown.open("xb") as stream:
        stream.write(b"preserve unknown file\n")
    product_race(iscc, app, version, workspace / "race", disposable=True)
    # 测试安装器会写入测试卸载器；成功路径必须以正式 setup 修复，再验系统集成并卸载。
    managed = install("formal-repair-after-race")
    basic._uninstall(app, workspace, "default-uninstall", env, managed)
    if unknown.read_bytes() != b"preserve unknown file\n" or any(
        path.read_bytes() != value for path, value in sentinels.items()
    ):
        raise RuntimeError("默认安装/竞争/卸载未保留用户文件")
    print("PASS standard user default location, HKCU identity, desktop/menu targets, "
          "real application maintenance exclusion and data retention", flush=True)


def run_extended(
    installer: Path, version: str, iscc: Path, workspace: Path, identity: dict[str, object],
) -> None:
    """所有阶段顺序执行，任何异常阻断后续安装；独立子目录保留失败日志。"""
    workspace.mkdir(parents=True, exist_ok=False)
    (workspace / "standard-identity.json").write_text(
        json.dumps(identity, ensure_ascii=True, indent=2), encoding="utf-8",
    )
    print("START standard user base lifecycle", flush=True)
    result = basic.main([
        "--installer", str(installer), "--version", version, "--iscc", str(iscc),
        "--workspace", str(workspace / "basic"), "--disposable",
    ])
    if result:
        raise RuntimeError("标准用户基础安装验收失败")
    print("START standard user fault injection", flush=True)
    run_fault_fixture(iscc, workspace / "faults", disposable=True)
    print("START official legacy payload upgrade", flush=True)
    run_legacy_upgrade(iscc, installer, version, workspace / "legacy", disposable=True)
    print("START default location and application startup race", flush=True)
    run_default_installation(installer, version, iscc, workspace / "default", identity)
    print("PASS extended standard-user installation, legacy-payload upgrade and fault matrix",
          flush=True)


def main(argv: list[str] | None = None) -> int:
    """显式隔离与真实标准身份缺一不可，不为本机或管理员提供绕过开关。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--iscc", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--disposable", action="store_true")
    parser.add_argument("--require-standard-user", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        workspace = basic.validate_environment(args.workspace, args.disposable)
        identity = standard_identity()
        run_extended(args.installer, args.version.removeprefix("v"), args.iscc, workspace, identity)
    except (OSError, ValueError, RuntimeError, KeyError, configparser.Error,
            subprocess.SubprocessError) as error:
        print(f"FAIL extended installer acceptance: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
