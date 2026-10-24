"""独立身份的跨版本 Inno 完整事件验收，仅允许一次性 Windows 托管 runner 执行。"""

from __future__ import annotations

import configparser
import hashlib
import os
import stat
import subprocess
import time
from pathlib import Path

from core import windows_installation as protocol
from scripts.prepare_inno_setup import verify_compiler
from scripts.windows_installer.manifest import stage_payload, validate_manifest

FIXTURE_APP_ID = "{73BE31ED-B8CB-4DD7-BF77-B4E9AC4DB55B}"
VERSIONS = ("1.0.0", "1.1.0", "1.2.0")
CONTROLS = {
    protocol.INSTALL_MARKER,
    protocol.INSTALL_MANIFEST,
    protocol.INSTALL_PENDING_MANIFEST,
    protocol.INSTALL_PREVIOUS_MANIFEST,
    protocol.INSTALL_LOCK,
}
_FIELDS = (
    "FormatVersion",
    "AppId",
    "MainExecutable",
    "State",
    "CompletedVersion",
    "PendingVersion",
    "ManifestSha256",
    "PendingManifestSha256",
)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _run(command: list[str], log: Path, *, reject: bool = False, timeout: int = 180) -> None:
    """进程必须在限时内返回预期成功/失败；超时不视为有效拒绝。"""
    with log.open("wb") as stream:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if (reject and result.returncode == 0) or (not reject and result.returncode != 0):
        raise RuntimeError(f"fixture 非预期退出码 {result.returncode}，见 {log.name}")


def compile_versions(iscc: Path, workspace: Path) -> dict[str, tuple[Path, Path]]:
    """只编译独立版本，无安装副作用；本机可以调用该步骤核实 Inno 语法。"""
    verify_compiler(iscc)
    include = workspace / "fixture-protocol.iss"
    constants = {
        "InstallAppId": FIXTURE_APP_ID,
        "MainExecutable": protocol.MAIN_EXECUTABLE,
        "InstallMarker": protocol.INSTALL_MARKER,
        "InstallManifest": protocol.INSTALL_MANIFEST,
        "InstallPendingManifest": protocol.INSTALL_PENDING_MANIFEST,
        "InstallPreviousManifest": protocol.INSTALL_PREVIOUS_MANIFEST,
        "InstallLock": protocol.INSTALL_LOCK,
        "InstallSection": protocol.INSTALL_SECTION,
    }
    include.write_text(
        "".join(f'#define {key} "{value}"\n' for key, value in constants.items()),
        encoding="utf-8",
    )
    compiled = {}
    for version in VERSIONS:
        source = workspace / f"source-{version}"
        (source / "_internal").mkdir(parents=True)
        # 这些字节只供复制/摘要验证；fixture 没有 Run，不把它们作为可执行程序启动。
        (source / "versioned.exe").write_bytes(f"fixture main {version}".encode())
        (source / "_internal/adb.exe").write_bytes(f"fixture tool {version}".encode())
        if version == VERSIONS[0]:
            (source / "retired.dat").write_bytes(b"owned only by A\n")
        else:
            (source / "_internal/introduced-b.dat").write_bytes(f"new payload {version}".encode())
        payload = workspace / f"payload-{version}"
        stage_payload(source, "versioned.exe", payload)
        executable = workspace / f"upgrade-fixture-{version}.exe"
        _run(
            [
                str(iscc.resolve()),
                "/Q",
                f"/DProtocolInclude={include.resolve()}",
                f"/DAppVersion={version}",
                f"/DAppSourceDir={payload.resolve()}",
                f"/O{workspace.resolve()}",
                str(Path(__file__).with_name("upgrade_fixture.iss")),
            ],
            workspace / f"compile-{version}.log",
            timeout=120,
        )
        if not executable.is_file() or executable.stat().st_size == 0:
            raise RuntimeError("fixture 编译产物缺失或为空")
        compiled[version] = executable, payload
    return compiled


def _registrations(app_id: str) -> list[tuple[str, str]]:
    """两个视图和两个权限域都检查；权限错误不得误报为不存在。"""
    import winreg

    result = []
    key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{app_id}_is1"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                handle = winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view)
            except FileNotFoundError:
                continue
            with handle:
                result.append(
                    (
                        str(winreg.QueryValueEx(handle, "InstallLocation")[0]),
                        str(winreg.QueryValueEx(handle, "DisplayVersion")[0]),
                    )
                )
    return sorted(result)


def _identity(app: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    data = (app / protocol.INSTALL_MARKER).read_bytes()
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    parser.read_string(data.decode(encoding))
    section = parser[protocol.INSTALL_SECTION]
    return {name: section[name] for name in _FIELDS}


def _assert_ready(app: Path, version: str) -> set[str]:
    identity = _identity(app)
    expected = {
        "FormatVersion": "1",
        "AppId": FIXTURE_APP_ID,
        "MainExecutable": protocol.MAIN_EXECUTABLE,
        "State": "ready",
        "CompletedVersion": version,
        "PendingVersion": "",
        "PendingManifestSha256": "",
    }
    if any(identity[key] != value for key, value in expected.items()):
        raise RuntimeError("fixture 安装身份与目标版本不一致")
    manifest = app / protocol.INSTALL_MANIFEST
    if identity["ManifestSha256"] != _digest(manifest):
        raise RuntimeError("fixture 安装清单摘要不一致")
    files = validate_manifest(manifest, app)
    if not (app / protocol.INSTALL_LOCK).is_file():
        raise RuntimeError("fixture 缺少稳定维护锁")
    if any(
        (app / name).exists()
        for name in (
            protocol.INSTALL_PENDING_MANIFEST,
            protocol.INSTALL_PREVIOUS_MANIFEST,
        )
    ):
        raise RuntimeError("fixture 安装成功后仍有提交控制文件残留")
    registrations = _registrations(FIXTURE_APP_ID)
    if not registrations or any(
        Path(path).resolve() != app.resolve() or registered_version != version
        for path, registered_version in registrations
    ):
        raise RuntimeError("fixture 卸载登记不一致")
    return set(files)


def _snapshot(app: Path) -> dict[str, str]:
    return {
        path.relative_to(app).as_posix(): _digest(path)
        for path in sorted(app.rglob("*"))
        if path.is_file()
    }


def _expect_rejected(command: list[str], app: Path, log: Path) -> None:
    """失败不仅要返回非零，还必须保持全部已有文件与登记不变。"""
    before, registration = _snapshot(app), _registrations(FIXTURE_APP_ID)
    _run(command, log, reject=True)
    if _snapshot(app) != before or _registrations(FIXTURE_APP_ID) != registration:
        raise RuntimeError("fixture 拒绝操作修改了原安装目录或登记")


def _assert_absent(app: Path, managed: set[str]) -> None:
    if (
        any((app / name).exists() for name in managed | CONTROLS)
        or list(app.glob("unins*"))
        or _registrations(FIXTURE_APP_ID)
    ):
        raise RuntimeError("fixture 卸载仍有载荷、控制文件、卸载器或登记残留")


def _preserve_installation(app: Path, preserved: Path, workspace: Path) -> None:
    """仅保留改名本次 workspace 的两个严格子路径，拒绝重解析点和已有目的地。"""
    base = workspace.resolve()
    resolved = []
    for target in (app, preserved):
        candidate = target.absolute()
        for part in (candidate, *candidate.parents):
            if part.is_symlink() or (
                part.exists()
                and getattr(part.lstat(), "st_file_attributes", 0)
                & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ValueError("fixture workspace 路径不能经过重解析点")
        candidate = candidate.resolve()
        if candidate == base or not candidate.is_relative_to(base):
            raise ValueError("fixture 改名的源和目标必须严格位于本次 workspace 内")
        resolved.append(candidate)
    source, destination = resolved
    if destination.exists():
        raise ValueError("fixture 保留目录已存在，拒绝覆盖")
    if not source.is_dir() or source in destination.parents or destination in source.parents:
        raise ValueError("fixture workspace 改名路径无效或相互包含")
    source.rename(destination)


def _uninstall(app: Path, workspace: Path, label: str, managed: set[str]) -> None:
    _run(
        [
            str(app / "unins000.exe"),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            f"/LOG={workspace / (label + '-inno.log')}",
        ],
        workspace / f"{label}.log",
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if not (app / protocol.INSTALL_MARKER).exists() and not list(app.glob("unins*")):
            break
        time.sleep(0.2)
    _assert_absent(app, managed)


def _simulate_interrupted_b(app: Path, payload_b: Path) -> None:
    """在独占锁内构造正式协议允许的 A 完成/B 部分写入状态，不改变产品实现。"""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    lock = kernel.CreateFileW(str(app / protocol.INSTALL_LOCK), 0xC0000000, 0, None, 3, 0x80, None)
    if lock == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "fixture 无法取得维护独占锁")
    try:
        identity = _identity(app)
        if identity["State"] != "ready" or identity["CompletedVersion"] != VERSIONS[0]:
            raise RuntimeError("中断夹具要求先完成版本 A")
        pending = payload_b / protocol.INSTALL_MANIFEST
        (app / protocol.INSTALL_PENDING_MANIFEST).write_bytes(pending.read_bytes())
        identity.update(
            State="installing", PendingVersion=VERSIONS[1], PendingManifestSha256=_digest(pending)
        )
        temporary = app / (protocol.INSTALL_MARKER + ".tmp")
        temporary.write_text(
            "["
            + protocol.INSTALL_SECTION
            + "]\n"
            + "".join(f"{key}={identity[key]}\n" for key in _FIELDS),
            encoding="utf-8",
        )
        os.replace(temporary, app / protocol.INSTALL_MARKER)
        for name in (protocol.MAIN_EXECUTABLE, "_internal/introduced-b.dat"):
            (app / name).write_bytes((payload_b / name).read_bytes())
    finally:
        kernel.CloseHandle(lock)


def run_upgrade_fixture(iscc: Path, workspace: Path, *, disposable: bool = False) -> None:
    """显式一次性上下文与全新 runner 临时目录缺一不可；失败保留证据，不自动清理目录。"""
    from scripts.check_windows_installer import _shortcuts, validate_environment

    workspace = validate_environment(workspace, disposable)
    if (
        _registrations(protocol.APP_ID)
        or _registrations(FIXTURE_APP_ID)
        or any(path.exists() for path in _shortcuts())
    ):
        raise ValueError("一次性 runner 已有正式产品或 fixture，拒绝接管")
    workspace.mkdir(parents=True, exist_ok=False)
    compiled = compile_versions(iscc, workspace)

    def command(version: str, app: Path, label: str) -> list[str]:
        return [
            str(compiled[version][0]),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/SP-",
            "/NORESTART",
            "/RESTARTEXITCODE=3010",
            "/NOCLOSEAPPLICATIONS",
            "/NORESTARTAPPLICATIONS",
            f"/DIR={app}",
            f"/LOG={workspace / (label + '-inno.log')}",
        ]

    def install(version: str, app: Path, label: str) -> set[str]:
        _run(command(version, app, label), workspace / f"{label}.log")
        return _assert_ready(app, version)

    a, b, c = VERSIONS
    app = workspace / "升级 fixture 中文 space"
    install(a, app, "first-a")
    unknown = app / "user-extra.dat"
    unknown.write_bytes(b"user file must remain\n")

    # 先验证损坏清单失败关闭，再原样恢复夹具自己的字节供后续场景使用。
    manifest = app / protocol.INSTALL_MANIFEST
    original = manifest.read_bytes()
    manifest.write_bytes(original + b"corrupted\n")
    _expect_rejected(command(b, app, "bad-manifest"), app, workspace / "bad-manifest.log")
    manifest.write_bytes(original)

    # 独立工具不持有运行锁，必须由全文件占用预检阻断；不启动 ADB 服务。
    tool_handle = protocol.InstallationGuard(protocol._open_running_lock(app / "_internal/adb.exe"))
    try:
        _expect_rejected(command(b, app, "busy-tool"), app, workspace / "busy-tool.log")
    finally:
        tool_handle.close()
    managed = install(b, app, "a-to-b")
    if (app / "retired.dat").exists():
        raise RuntimeError("A 退役文件未由 B 精确清理")
    _expect_rejected(command(a, app, "reject-old-a"), app, workspace / "reject-old-a.log")
    (app / protocol.MAIN_EXECUTABLE).write_bytes(b"repair me")
    install(b, app, "repair-b")
    retired_replacement = app / "retired.dat"
    retired_replacement.write_bytes(b"new user file at retired path\n")
    managed = install(c, app, "b-to-c")
    if retired_replacement.read_bytes() != b"new user file at retired path\n":
        raise RuntimeError("升级覆盖了退役路径的新用户文件")
    _uninstall(app, workspace, "uninstall-c", managed)
    if (
        unknown.read_bytes() != b"user file must remain\n"
        or retired_replacement.read_bytes() != b"new user file at retired path\n"
    ):
        raise RuntimeError("历史卸载日志删除了未知文件或退役路径的新用户文件")

    # 第二个全新位置模拟中断，再通过真实安装事件验证严格修复顺序。
    recovery = workspace / "恢复 fixture 中文 space"
    install(a, recovery, "recovery-a")
    _simulate_interrupted_b(recovery, compiled[b][1])
    _expect_rejected(
        command(c, recovery, "pending-reject-c"), recovery, workspace / "pending-reject-c.log"
    )
    install(b, recovery, "pending-repair-b")
    managed = install(c, recovery, "recovered-to-c")
    # 保留旧目录后只在原登记位置重装；移动过的旧卸载器不能影响新安装或旧保留文件。
    preserved = workspace / "保留旧安装 fixture"
    _preserve_installation(recovery, preserved, workspace)
    old_snapshot = _snapshot(preserved)
    managed = install(c, recovery, "reinstall-at-registered-position")
    _expect_rejected(
        [
            str(preserved / "unins000.exe"),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            f"/LOG={workspace / 'moved-old-uninstaller-inno.log'}",
        ],
        recovery,
        workspace / "moved-old-uninstaller.log",
    )
    if _snapshot(preserved) != old_snapshot:
        raise RuntimeError("移动后的旧卸载器修改了保留目录")
    _assert_ready(recovery, c)
    _uninstall(recovery, workspace, "uninstall-reinstalled-c", managed)
    if _registrations(protocol.APP_ID) or any(path.exists() for path in _shortcuts()):
        raise RuntimeError("独立 fixture 意外产生了正式产品系统集成")
    print(
        "PASS fixture full events: A-B upgrade, downgrade rejection, repair, "
        "retired path and unknown retention, busy tool, corrupt manifest, pending B recovery, "
        "moved old uninstaller rejection"
    )
