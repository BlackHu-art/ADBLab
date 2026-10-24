"""只在一次性 Windows 托管 runner 执行安装验收，保留日志且不清理既有目录。"""

from __future__ import annotations

import argparse
import configparser
import ctypes
import hashlib
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))


def validate_environment(workspace: Path, disposable: bool) -> Path:
    """拒绝桌面、共享 runner、复用目录和重解析路径，不能通过覆盖用户数据开始验收。"""
    if not disposable or not (
        sys.platform == "win32" and os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and os.environ.get("RUNNER_OS") == "Windows" and os.environ.get("RUNNER_TEMP")
    ):
        raise ValueError("真实安装验收仅允许显式指定的一次性 Windows 托管 runner")
    candidate = workspace.absolute()
    for part in (candidate, *candidate.parents):
        if part.is_symlink() or (part.exists() and (
            getattr(part.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )):
            raise ValueError("验收目录不能经过重解析点")
    base = Path(os.environ["RUNNER_TEMP"]).resolve()
    if candidate.exists() or candidate == base or not candidate.resolve().is_relative_to(base):
        raise ValueError("验收目录必须是 RUNNER_TEMP 内尚不存在的子目录")
    return candidate


def registered_installations() -> list[dict[str, str]]:
    """读取两种注册表视图；权限错误必须暴露，不能误判为尚未安装。"""
    import winreg

    from core.windows_installation import APP_ID

    entries = []
    key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                handle = winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view)
            except FileNotFoundError:
                continue
            with handle:
                entries.append({
                    "path": str(winreg.QueryValueEx(handle, "InstallLocation")[0]),
                    "version": str(winreg.QueryValueEx(handle, "DisplayVersion")[0]),
                })
    return entries


def run_checked(
    command: list[str], log: Path, *, env: dict[str, str],
    timeout: int = 180, reject: bool = False,
) -> None:
    """等待有界且保留输出；拒绝场景也须正常结束，超时不能当作成功拒绝。"""
    with log.open("wb") as stream:
        result = subprocess.run(
            command, env=env, stdin=subprocess.DEVNULL, stdout=stream,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if (reject and result.returncode == 0) or (not reject and result.returncode != 0):
        raise RuntimeError(f"验收进程返回非预期退出码 {result.returncode}，见 {log.name}")


def _known_folder(folder: int) -> Path:
    # 使用 Shell 的实际用户目录，不能假定用户文件夹没有重定向。
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p,
    ]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    output = ctypes.create_unicode_buffer(32768)
    if shell.SHGetFolderPathW(None, folder, None, 0, output) != 0:
        raise OSError("无法定位 Windows 用户目录")
    return Path(output.value)


def _shortcuts() -> list[Path]:
    return [_known_folder(2) / "ADBLab/ADBLab.lnk", _known_folder(16) / "ADBLab.lnk"]


def _data_sentinels() -> dict[Path, bytes]:
    """一次性 runner 的真实默认目录也必须验证，不能仅检查环境变量重定向目录。"""
    roots = [_known_folder(28) / "ADBLab", Path.home() / "ADBLab"]
    name = "installer-validation-sentinel.txt"
    for directory in roots:
        for part in (directory, *directory.parents):
            if part.is_symlink() or (part.exists() and (
                not part.is_dir()
                or (getattr(part.lstat(), "st_file_attributes", 0)
                    & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            )):
                raise ValueError("哨兵目录不能是文件或经过重解析点")
        if (directory / name).exists() or (directory / name).is_symlink():
            raise ValueError("验收哨兵已存在，拒绝覆盖")
    sentinels = {}
    for index, directory in enumerate(roots):
        # 前置源码或 frozen 自检可能已经创建目录；保留所有旧内容，仅排他创建本次哨兵。
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        sentinels[path] = f"preserve original directory {index}\n".encode()
        with path.open("xb") as stream:
            stream.write(sentinels[path])
    return sentinels


def assert_uninstalled(app: Path, managed: set[str]) -> None:
    """卸载器第一阶段退出 0 不代表完成，必须独立检查文件和注册状态。"""
    from core.windows_installation import (
        INSTALL_LOCK,
        INSTALL_MANIFEST,
        INSTALL_MARKER,
        INSTALL_PENDING_MANIFEST,
        INSTALL_PREVIOUS_MANIFEST,
    )

    controls = {
        INSTALL_LOCK, INSTALL_MANIFEST, INSTALL_MARKER,
        INSTALL_PENDING_MANIFEST, INSTALL_PREVIOUS_MANIFEST,
    }
    remaining = [name for name in managed | controls if (app / name).exists()]
    if remaining or registered_installations():
        raise RuntimeError("卸载未完成：仍有受管理文件或安装登记")


def _assert_ready(app: Path, version: str) -> set[str]:
    from core.windows_installation import (
        APP_ID,
        INSTALL_MANIFEST,
        INSTALL_MARKER,
        INSTALL_SECTION,
        MAIN_EXECUTABLE,
        acquire_installation_guard,
    )
    from scripts.windows_installer.manifest import validate_manifest

    raw = (app / INSTALL_MARKER).read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(raw.decode(encoding))
    identity = parser[INSTALL_SECTION]
    expected = {"AppId": APP_ID, "MainExecutable": MAIN_EXECUTABLE, "State": "ready",
                "CompletedVersion": version, "PendingVersion": "", "PendingManifestSha256": ""}
    if any(identity[key] != value for key, value in expected.items()):
        raise RuntimeError("安装身份与目标版本不一致")
    digest = hashlib.sha256((app / INSTALL_MANIFEST).read_bytes()).hexdigest()
    if digest != identity["ManifestSha256"]:
        raise RuntimeError("安装清单摘要不一致")
    managed = validate_manifest(app / INSTALL_MANIFEST, app)
    guard = acquire_installation_guard(app / MAIN_EXECUTABLE)
    if guard is None:
        raise RuntimeError("安装版没有取得运行准入锁")
    guard.close()
    entries = registered_installations()
    if not entries or any(
        Path(entry["path"]).resolve() != app.resolve() or entry["version"] != version
        for entry in entries
    ):
        raise RuntimeError("卸载登记与实际安装位置或版本不一致")
    if not _shortcuts()[0].is_file():
        raise RuntimeError("开始菜单快捷方式缺失")
    return set(managed)


def _uninstall(
    app: Path, workspace: Path, name: str, env: dict[str, str], managed: set[str],
) -> None:
    uninstaller = app / "unins000.exe"
    run_checked(
        [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
         f"/LOG={workspace / (name + '-inno.log')}"], workspace / (name + ".log"), env=env,
    )
    # Inno 的外层卸载器可能先退出；给其第二阶段清理有限的完成窗口，再检查实际后置状态。
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if not uninstaller.exists() and not (app / ".adblab-install.ini").exists():
            break
        time.sleep(0.2)
    assert_uninstalled(app, managed)
    if list(app.glob("unins*")) or any(path.exists() for path in _shortcuts()):
        raise RuntimeError("卸载仍有卸载器文件或快捷方式残留")


def smoke(installer: Path, version: str, workspace: Path) -> None:
    """安装、占用拒绝、覆盖修复及卸载保留数据；只由完成隔离检查的入口调用。"""
    from core.windows_installation import (
        MAIN_EXECUTABLE,
        InstallationGuard,
        _open_running_lock,
        acquire_installation_guard,
    )
    from scripts.check_build_artifacts import CheckError, check_installer_file

    try:
        check_installer_file(installer)
    except CheckError as error:
        raise ValueError(str(error)) from error
    if registered_installations() or any(path.exists() for path in _shortcuts()):
        raise ValueError("一次性 runner 已有产品登记或快捷方式，拒绝覆盖")
    sentinels = _data_sentinels()
    workspace.mkdir(parents=True, exist_ok=False)
    app = workspace / "安装 app space"
    user_data = workspace / "userdata" / "ADBLab"
    user_data.mkdir(parents=True)
    sentinel = user_data / "existing-settings-sentinel.txt"
    sentinel.write_bytes(b"preserve existing user data\n")
    env = dict(os.environ, LOCALAPPDATA=str(user_data.parent),
               MOBILEPERF_LOG_DIR=str(workspace / "logs"))
    base_command = [str(installer.resolve()), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/SP-",
                    "/NORESTART", "/RESTARTEXITCODE=3010", "/NOCLOSEAPPLICATIONS",
                    "/NORESTARTAPPLICATIONS", f"/DIR={app}"]

    def install(name: str, *, reject: bool = False) -> None:
        run_checked(base_command + [f"/LOG={workspace / (name + '-inno.log')}"],
                    workspace / (name + ".log"), env=env, reject=reject)

    install("first-install")
    managed = _assert_ready(app, version)
    unknown = app / "user-kept.txt"
    unknown.write_bytes(b"not owned by installer\n")
    guard = acquire_installation_guard(app / MAIN_EXECUTABLE)
    if guard is None:
        raise RuntimeError("维护互斥验收未取得共享锁")
    try:
        install("busy-install", reject=True)
        run_checked([str(app / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                     "/NORESTART", f"/LOG={workspace / 'busy-uninstall-inno.log'}"],
                    workspace / "busy-uninstall.log", env=env, reject=True)
        _assert_ready(app, version)
    finally:
        guard.close()
    adb_paths = sorted(name for name in managed if name.casefold().endswith("/adblab-adb.exe"))
    if not adb_paths:
        raise RuntimeError("安装载荷缺少预置 ADB 工具副本")
    # 只持有真实文件句柄模拟独立工具占用，不启动 ADB 服务或连接设备。
    tool_lock = InstallationGuard(_open_running_lock(app / adb_paths[0]))
    try:
        install("busy-tool", reject=True)
        _assert_ready(app, version)
    finally:
        tool_lock.close()
    install("same-version-repair")
    _assert_ready(app, version)
    run_checked([sys.executable, str(ROOT / "scripts/check_build_artifacts.py"), "frozen",
                 "--executable", str(app / MAIN_EXECUTABLE), "--timeout", "60"],
                workspace / "installed-frozen.log", env=env, timeout=210)
    _uninstall(app, workspace, "uninstall", env, managed)
    if unknown.read_bytes() != b"not owned by installer\n" or (
        sentinel.read_bytes() != b"preserve existing user data\n"
    ):
        raise RuntimeError("卸载未保留用户文件")
    # 未归属文件保留的旧目录不能被直接接管；重新安装使用一个新的空位置。
    app = workspace / "重装 app space"
    base_command[-1] = f"/DIR={app}"
    install("reinstall")
    managed = _assert_ready(app, version)
    _uninstall(app, workspace, "reuninstall", env, managed)
    if sentinel.read_bytes() != b"preserve existing user data\n":
        raise RuntimeError("重新安装后用户数据改变")
    if any(path.read_bytes() != value for path, value in sentinels.items()):
        raise RuntimeError("真实默认数据目录或导出目录未保留")
    print("PASS installed manifest, frozen commands, maintenance exclusion, "
          "repair, uninstall and data retention")


def main(argv: list[str] | None = None) -> int:
    """默认拒绝当前桌面；显式隔离开关也不能跳过托管 runner 和空目录校验。"""
    from scripts.check_build_artifacts import CheckError, check_installer_file
    from scripts.prepare_inno_setup import INNO_VERSION

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument(
        "--iscc", type=Path, default=ROOT / f"build/tools/inno-{INNO_VERSION}/ISCC.exe",
    )
    parser.add_argument("--disposable", action="store_true")
    args = parser.parse_args(argv)
    try:
        workspace = validate_environment(args.workspace, args.disposable)
        check_installer_file(args.installer)
        from tests.fixtures.windows_installer.upgrade_smoke import run_upgrade_fixture

        run_upgrade_fixture(args.iscc, workspace / "upgrade-fixture", disposable=True)
        smoke(args.installer, args.version.removeprefix("v"), workspace / "product-smoke")
        return 0
    except (CheckError, OSError, ValueError, RuntimeError, KeyError, configparser.Error,
            subprocess.SubprocessError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
