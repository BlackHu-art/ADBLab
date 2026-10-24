"""真实 Inno 事件故障验收；仅一次性托管 runner 可安装，编译与屏障探针可单独验证。"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from core import windows_installation as protocol
from scripts.prepare_inno_setup import verify_compiler
from scripts.windows_installer.manifest import _check_no_reparse, stage_payload, validate_manifest
from tests.fixtures.windows_installer import upgrade_smoke as common

REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURE_APP_ID = "{61FBA494-1705-46E6-B2DC-7F19EE7805A4}"
INSTALL_STAGES = (
    "preflight",
    "pending",
    "installing",
    "payload",
    "retired",
    "previous",
    "manifest",
    "ready",
    "pending-cleaned",
)
UNINSTALL_STAGES = ("removing", "uninstall-file", "uninstall-payload", "uninstall-post")


def _wait_stage(report: Path, token: str, stage: str, *, timeout: float = 95) -> tuple[int, str]:
    """必须收到本轮完整原子发布的到达证据；超时和陈旧记录均为失败。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if report.is_file():
            fields = report.read_text(encoding="utf-8-sig").splitlines()
            if (
                len(fields) != 4
                or fields[:2] != [token, stage]
                or not fields[2].isdigit()
                or int(fields[2]) <= 0
            ):
                raise RuntimeError("故障屏障证据的 nonce、阶段或 PID 不匹配")
            return int(fields[2]), fields[3]
        time.sleep(0.05)
    raise TimeoutError(f"未到达故障阶段 {stage}")


class Channel:
    """每次测试使用新目录与编译时固定 nonce；不借用环境变量启用故障。"""

    def __init__(self, root: Path, stage: str):
        if stage not in INSTALL_STAGES + UNINSTALL_STAGES + ("probe",):
            raise ValueError("未知故障阶段")
        root.mkdir(parents=True, exist_ok=False)
        self.root, self.stage, self.token = root.resolve(), stage, uuid.uuid4().hex

    def action(self, command: str) -> None:
        if command not in {"continue", "crash"}:
            raise ValueError("未知屏障动作")
        temporary = self.root / "action.tmp"
        temporary.write_bytes(f"{self.token}\n{command}".encode("ascii"))
        os.replace(temporary, self.root / "action")


class Engine:
    """等待到达屏障的实际 Inno 引擎；外层卸载启动器的退出码不能代表完成。"""

    def __init__(self, pid: int):
        from ctypes import wintypes

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetExitCodeProcess.restype = wintypes.BOOL
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.TerminateProcess.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000 | 0x1, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "无法打开故障屏障的实际 Inno 引擎")

    def wait(self, timeout: int = 180) -> int:
        outcome = self.kernel.WaitForSingleObject(self.handle, timeout * 1000)
        if outcome == 258:
            raise TimeoutError("实际 Inno 引擎未在限时内退出")
        if outcome != 0:
            raise OSError(ctypes.get_last_error(), "等待 Inno 引擎失败")
        code = ctypes.c_ulong()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise OSError(ctypes.get_last_error(), "读取 Inno 引擎退出码失败")
        return int(code.value)

    def close(self) -> None:
        self.kernel.CloseHandle(self.handle)

    def stop(self) -> None:
        """清理只针对屏障证明属于本轮的精确进程句柄，退出后才释放占用句柄。"""
        outcome = self.kernel.WaitForSingleObject(self.handle, 0)
        if outcome == 0:
            return
        if outcome != 258:
            raise OSError(ctypes.get_last_error(), "无法核实本轮 Inno 引擎的退出状态")
        if not self.kernel.TerminateProcess(self.handle, 93):
            # 已进入终止但尚未 signal 时 Windows 也可能返回 ACCESS_DENIED；必须等真实退出。
            error = ctypes.get_last_error()
            if self.kernel.WaitForSingleObject(self.handle, 10000) != 0:
                raise OSError(error, "终止本轮 Inno 引擎失败")
        self.wait(timeout=10)


class _JobBasicLimits(ctypes.Structure):
    _fields_ = [
        ("user_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", ctypes.c_ulong),
        ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t),
        ("active_limit", ctypes.c_ulong),
        ("affinity", ctypes.c_size_t),
        ("priority", ctypes.c_ulong),
        ("scheduling", ctypes.c_ulong),
    ]


class _JobExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _JobBasicLimits),
        ("io_counters", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class _JobAccounting(ctypes.Structure):
    _fields_ = [
        ("times", ctypes.c_int64 * 4),
        ("page_faults", ctypes.c_ulong),
        ("total_processes", ctypes.c_ulong),
        ("active_processes", ctypes.c_ulong),
        ("terminated_processes", ctypes.c_ulong),
    ]


class OwnedProcess:
    """先把等待 stdin 的启动器加入独立 Job，再启动命令，确保早期失败也拥有全部后代。"""

    def __init__(self, command: list[str], stream: BinaryIO):
        from ctypes import wintypes

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        self.kernel.QueryInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.TerminateJobObject.restype = wintypes.BOOL
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.IsProcessInJob.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.BOOL),
        ]
        self.kernel.IsProcessInJob.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.job = self.kernel.CreateJobObjectW(None, None)
        if not self.job:
            raise OSError(ctypes.get_last_error(), "无法建立本轮安装进程 Job")
        self.process = None
        try:
            limits = _JobExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(
                self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise OSError(ctypes.get_last_error(), "无法设置本轮 Job 关闭清理")
            gate = (
                "import sys,json; command=json.loads(sys.stdin.buffer.readline()); "
                "import subprocess; sys.exit(subprocess.call(command))"
            )
            self.process = subprocess.Popen(
                [sys.executable, "-I", "-S", "-c", gate],
                stdin=subprocess.PIPE,
                stdout=stream,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            handle = self.kernel.OpenProcess(0x100 | 0x1, False, self.process.pid)
            if not handle:
                raise OSError(ctypes.get_last_error(), "无法取得本轮等待启动器句柄")
            try:
                if not self.kernel.AssignProcessToJobObject(self.job, handle):
                    raise OSError(ctypes.get_last_error(), "无法将本轮启动器放入独立 Job")
            finally:
                self.kernel.CloseHandle(handle)
            if self.process.stdin is None:
                raise RuntimeError("本轮启动器没有受控输入")
            self.process.stdin.write(json.dumps(command).encode("ascii") + b"\n")
            self.process.stdin.close()
        except BaseException:
            try:
                # 尚未发出命令时只存在我们创建的等待启动器；不能留下它的 stdin 等待。
                if self.process is not None and self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=10)
            finally:
                self.close()
            raise

    def wait(self, *, timeout: int) -> int:
        if self.process is None:
            raise RuntimeError("本轮 Job 尚未创建启动器")
        return self.process.wait(timeout=timeout)

    def _active(self) -> int:
        info = _JobAccounting()
        if not self.kernel.QueryInformationJobObject(
            self.job, 1, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            raise OSError(ctypes.get_last_error(), "无法读取本轮 Job 的剩余进程数")
        return int(info.active_processes)

    def close(self) -> None:
        if not self.job:
            return
        handles = []
        try:
            # ActiveProcesses 可在进程对象最终 signal 前归零；保留成员句柄并逐一等待。
            class Members(ctypes.Structure):
                _fields_ = [
                    ("assigned", ctypes.c_ulong),
                    ("count", ctypes.c_ulong),
                    ("pids", ctypes.c_size_t * 256),
                ]

            members = Members()
            if not self.kernel.QueryInformationJobObject(
                self.job, 3, ctypes.byref(members), ctypes.sizeof(members), None
            ):
                raise OSError(ctypes.get_last_error(), "无法核实本轮 Job 的进程成员")
            for pid in members.pids[: members.count]:
                handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
                if not handle:
                    if ctypes.get_last_error() == 87:
                        continue  # 查询后已彻底退出，PID 不再存在。
                    raise OSError(ctypes.get_last_error(), "无法等待本轮 Job 成员")
                belongs = ctypes.c_int()
                if not self.kernel.IsProcessInJob(handle, self.job, ctypes.byref(belongs)):
                    self.kernel.CloseHandle(handle)
                    raise OSError(ctypes.get_last_error(), "无法确认本轮 Job 成员归属")
                if belongs.value:
                    handles.append(handle)
                else:
                    self.kernel.CloseHandle(handle)
            if self._active():
                if not self.kernel.TerminateJobObject(self.job, 93):
                    raise OSError(ctypes.get_last_error(), "终止本轮 Job 失败")
                deadline = time.monotonic() + 10
                while self._active():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("本轮 Job 仍有安装进程，不能进入下一场景")
                    time.sleep(0.05)
            for handle in handles:
                if self.kernel.WaitForSingleObject(handle, 10000) != 0:
                    raise TimeoutError("本轮 Job 成员尚未退出，不能进入下一场景")
            if self.process is not None:
                self.process.wait(timeout=10)
        finally:
            for handle in handles:
                self.kernel.CloseHandle(handle)
            self.kernel.CloseHandle(self.job)
            self.job = None


def _fault_run(
    command: list[str],
    channel: Channel,
    log: Path,
    *,
    action: str = "crash",
    at_stage: Callable[[str], protocol.InstallationGuard | None] | None = None,
) -> int:
    """动作只能在阶段证据验证之后发布；持有的测试共享句柄覆盖整个故障执行窗口。"""
    held = None
    engine = None
    with log.open("wb") as stream:
        process = OwnedProcess(command, stream)
        try:
            pid, detail = _wait_stage(channel.root / "reached", channel.token, channel.stage)
            engine = Engine(pid)
            if at_stage:
                held = at_stage(detail)
            channel.action(action)
            code = engine.wait()
            process.wait(timeout=30)
            (channel.root / "engine-exit.txt").write_text(str(code), encoding="ascii")
            if action == "crash" and code != 91:
                raise RuntimeError(f"故障阶段没有按要求退出实际引擎：{code}")
            return code
        finally:
            # 屏障放行后不会再读取动作，必须终止/等待精确引擎及本轮 Job 的所有后代。
            try:
                if engine is not None:
                    engine.stop()
            finally:
                try:
                    process.close()
                finally:
                    if engine is not None:
                        engine.close()
                    if held is not None:
                        held.close()


def _write_protocol(path: Path, app_id: str) -> None:
    constants = {
        "InstallAppId": app_id,
        "MainExecutable": protocol.MAIN_EXECUTABLE,
        "InstallMarker": protocol.INSTALL_MARKER,
        "InstallManifest": protocol.INSTALL_MANIFEST,
        "InstallPendingManifest": protocol.INSTALL_PENDING_MANIFEST,
        "InstallPreviousManifest": protocol.INSTALL_PREVIOUS_MANIFEST,
        "InstallLock": protocol.INSTALL_LOCK,
        "InstallSection": protocol.INSTALL_SECTION,
    }
    path.write_text(
        "".join(f'#define {key} "{value}"\n' for key, value in constants.items()), encoding="utf-8"
    )


def _payload(source: Path, target: Path, version: str, *, variant: bool = False) -> Path:
    (source / "_internal").mkdir(parents=True, exist_ok=False)
    (source / "main.exe").write_bytes(f"main {version} {variant}".encode())
    (source / "_internal/adb.exe").write_bytes(f"tool {version}".encode())
    (source / "_internal/stable.dat").write_bytes(b"stable managed bytes")
    if version == "1.0.0":
        (source / "retired.dat").write_bytes(b"retired owned bytes")
    else:
        (source / "introduced.dat").write_bytes(f"introduced {version}".encode())
    stage_payload(source, "main.exe", target)
    return target


def _compile(
    iscc: Path,
    payload: Path,
    version: str,
    output: Path,
    *,
    channel: Channel | None = None,
    app_id: str = FIXTURE_APP_ID,
) -> Path:
    """本函数只编译；生产入口不接受这里的测试宏。"""
    verify_compiler(iscc)
    validate_manifest(payload / protocol.INSTALL_MANIFEST, payload)
    output.mkdir(parents=True, exist_ok=False)
    include = output / "protocol.iss"
    _write_protocol(include, app_id)
    common._run(
        [
            str(iscc.resolve()),
            "/Q",
            f"/DProtocolInclude={include.resolve()}",
            f"/DAppVersion={version}",
            f"/DAppSourceDir={payload.resolve()}",
            f"/DFaultRoot={channel.root if channel else output.resolve()}",
            f"/DFaultStage={channel.stage if channel else ''}",
            f"/DFaultToken={channel.token if channel else 'disabled'}",
            f"/O{output.resolve()}",
            str(Path(__file__).with_name("fault_fixture.iss")),
        ],
        output / "compile.log",
        timeout=180,
    )
    executable = output / "fault-fixture.exe"
    if not executable.is_file() or executable.stat().st_size == 0:
        raise RuntimeError("故障 fixture 编译产物缺失或为空")
    return executable


def _command(executable: Path, log: Path, app: Path | None = None) -> list[str]:
    command = [
        str(executable),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/SP-",
        "/NORESTART",
        "/NOCLOSEAPPLICATIONS",
        "/NORESTARTAPPLICATIONS",
        f"/LOG={log}",
    ]
    if app is not None:
        command.append(f"/DIR={app}")
    return command


def _ready(app: Path, version: str, app_id: str = FIXTURE_APP_ID) -> set[str]:
    identity = common._identity(app)
    expected = {
        "AppId": app_id,
        "State": "ready",
        "CompletedVersion": version,
        "PendingVersion": "",
        "PendingManifestSha256": "",
    }
    if any(identity[key] != value for key, value in expected.items()):
        raise RuntimeError("故障 fixture 未恢复 ready 身份")
    manifest = app / protocol.INSTALL_MANIFEST
    if identity["ManifestSha256"] != common._digest(manifest):
        raise RuntimeError("故障 fixture 清单摘要不匹配")
    files = validate_manifest(manifest, app)
    if (
        any(
            (app / name).exists()
            for name in (
                protocol.INSTALL_PENDING_MANIFEST,
                protocol.INSTALL_PREVIOUS_MANIFEST,
            )
        )
        or not (app / protocol.INSTALL_LOCK).is_file()
    ):
        raise RuntimeError("故障 fixture 控制文件状态未完成")
    registered = common._registrations(app_id)
    if not registered or any(
        Path(path).resolve() != app.resolve() or registered_version != version
        for path, registered_version in registered
    ):
        raise RuntimeError("故障 fixture 登记未恢复")
    return set(files)


def _install(executable: Path, app: Path, version: str, log: Path) -> set[str]:
    common._run(_command(executable, log.with_suffix(".inno.log"), app), log)
    return _ready(app, version)


def _reject(executable: Path, app: Path, log: Path, *, uninstall: bool = False) -> None:
    before, registered = common._snapshot(app), common._registrations(FIXTURE_APP_ID)
    common._run(
        _command(executable, log.with_suffix(".inno.log"), None if uninstall else app),
        log,
        reject=True,
    )
    if common._snapshot(app) != before or common._registrations(FIXTURE_APP_ID) != registered:
        raise RuntimeError("故障 fixture 拒绝请求修改了文件或登记")


def _uninstall(app: Path, files: set[str], log: Path) -> None:
    common._run(_command(app / "unins000.exe", log.with_suffix(".inno.log")), log)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not (
            any((app / name).exists() for name in files | common.CONTROLS)
            or list(app.glob("unins*"))
            or common._registrations(FIXTURE_APP_ID)
        ):
            return
        time.sleep(0.1)
    raise RuntimeError("故障 fixture 卸载后置核验仍有载荷、控制文件或登记")


def _retain_and_reinstall(app: Path, executable: Path, version: str, workspace: Path) -> set[str]:
    preserved = app.with_name(app.name + "-preserved")
    common._preserve_installation(app, preserved, workspace)
    before = common._snapshot(preserved)
    files = _install(executable, app, version, app.parent / "empty-reinstall.log")
    if common._snapshot(preserved) != before:
        raise RuntimeError("空目录重装修改了保留的故障现场")
    return files


def _held_file(path: Path) -> protocol.InstallationGuard:
    return protocol.InstallationGuard(protocol._open_running_lock(path))


def _stage_state(app: Path, stage: str, payload_a: Path, payload_b: Path) -> None:
    identity = common._identity(app)
    expected_state = (
        "ready" if stage in {"preflight", "pending", "ready", "pending-cleaned"} else "installing"
    )
    if identity["State"] != expected_state:
        raise RuntimeError(f"阶段 {stage} 身份状态不符合提交顺序")
    pending = app / protocol.INSTALL_PENDING_MANIFEST
    if stage not in {"preflight", "pending-cleaned"}:
        if common._digest(pending) != common._digest(payload_b / protocol.INSTALL_MANIFEST):
            raise RuntimeError("待完成清单并非原 B 载荷")
    if stage == "payload":
        if common._digest(app / protocol.MAIN_EXECUTABLE) != common._digest(
            payload_b / protocol.MAIN_EXECUTABLE
        ) or common._digest(app / "_internal/adb.exe") != common._digest(
            payload_a / "_internal/adb.exe"
        ):
            raise RuntimeError("未得到主程序已更新、工具仍为旧版的真实部分复制状态")
    if (
        stage in {"retired", "previous", "manifest", "ready", "pending-cleaned"}
        and (app / "retired.dat").exists()
    ):
        raise RuntimeError("退役路径尚未在预期事件阶段删除")
    if stage in {"previous", "manifest", "ready", "pending-cleaned"}:
        if common._digest(app / protocol.INSTALL_PREVIOUS_MANIFEST) != common._digest(
            payload_a / protocol.INSTALL_MANIFEST
        ):
            raise RuntimeError("提交日志未保留旧 A 清单")
    if stage in {"manifest", "ready", "pending-cleaned"}:
        if common._digest(app / protocol.INSTALL_MANIFEST) != common._digest(
            payload_b / protocol.INSTALL_MANIFEST
        ):
            raise RuntimeError("当前清单尚未提交为 B")


def run_fault_fixture(iscc: Path, workspace: Path, *, disposable: bool = False) -> None:
    """阶段退出和真实文件共享失败均走完整安装/卸载事件；失败现场保留在 runner workspace。"""
    from scripts.check_windows_installer import _shortcuts, validate_environment

    workspace = validate_environment(workspace, disposable)
    if (
        common._registrations(FIXTURE_APP_ID)
        or common._registrations(protocol.APP_ID)
        or any(path.exists() for path in _shortcuts())
    ):
        raise ValueError("故障验收要求没有已有产品或 fixture 的一次性 runner")
    workspace.mkdir(parents=True, exist_ok=False)
    payloads, installers = {}, {}
    for key, version, variant in (
        ("a", "1.0.0", False),
        ("b", "1.1.0", False),
        ("different-b", "1.1.0", True),
        ("c", "1.2.0", False),
    ):
        payloads[key] = _payload(
            workspace / f"source-{key}", workspace / f"payload-{key}", version, variant=variant
        )
        installers[key] = _compile(iscc, payloads[key], version, workspace / f"build-{key}")

    # 首装尚无 completed 清单；过早中断不能伪装成可自动修复的已有安装。
    for stage in ("preflight", "pending", "installing"):
        case = workspace / ("first-" + stage)
        channel = Channel(case / "barrier", stage)
        executable = _compile(iscc, payloads["b"], "1.1.0", case / "build", channel=channel)
        app = case / "app"
        _fault_run(_command(executable, case / "fault.inno.log", app), channel, case / "fault.log")
        if common._registrations(FIXTURE_APP_ID) or (app / protocol.MAIN_EXECUTABLE).exists():
            raise RuntimeError("首装准备阶段意外写入载荷或登记")
        if stage == "installing":
            identity = common._identity(app)
            if identity["State"] != "installing" or identity["CompletedVersion"]:
                raise RuntimeError("首装 installing 身份错误")
            _reject(installers["different-b"], app, case / "reject-different-b.log")
            _reject(installers["c"], app, case / "reject-c.log")
            files = _install(installers["b"], app, "1.1.0", case / "repair.log")
        else:
            expected = {protocol.INSTALL_LOCK}
            if stage == "pending":
                expected.add(protocol.INSTALL_PENDING_MANIFEST)
            if set(common._snapshot(app)) != expected:
                raise RuntimeError("首装早期故障现场与预期控制文件不一致")
            _reject(installers["b"], app, case / "incomplete-identity-reject.log")
            files = _retain_and_reinstall(app, installers["b"], "1.1.0", workspace)
        _uninstall(app, files, case / "uninstall.log")
        print(f"PASS fault first-install stage={stage}", flush=True)

    for stage in INSTALL_STAGES:
        case = workspace / stage
        channel = Channel(case / "barrier", stage)
        executable = _compile(iscc, payloads["b"], "1.1.0", case / "build", channel=channel)
        app = case / "app"
        _install(installers["a"], app, "1.0.0", case / "baseline.log")
        unknown = app / "user-extra.dat"
        unknown.write_bytes(b"must survive every fault")
        before = common._snapshot(app)
        _fault_run(_command(executable, case / "fault.inno.log", app), channel, case / "fault.log")
        _stage_state(app, stage, payloads["a"], payloads["b"])
        if stage == "preflight" and common._snapshot(app) != before:
            raise RuntimeError("预检后退出改变了既有安装")
        if stage == "pending":
            _reject(installers["b"], app, case / "conflicting-pending.log")
            files = _retain_and_reinstall(app, installers["b"], "1.1.0", workspace)
            if (
                app.with_name("app-preserved") / unknown.name
            ).read_bytes() != b"must survive every fault":
                raise RuntimeError("损坏目录保留遗漏用户文件")
        else:
            if stage in {"installing", "payload", "retired", "previous", "manifest"}:
                _reject(installers["different-b"], app, case / "reject-different-b.log")
                _reject(installers["c"], app, case / "reject-c.log")
            files = _install(installers["b"], app, "1.1.0", case / "repair.log")
            if unknown.read_bytes() != b"must survive every fault":
                raise RuntimeError("故障恢复改变了未知用户文件")
        _uninstall(app, files, case / "uninstall.log")
        print(f"PASS fault upgrade stage={stage}", flush=True)

    # 真正的 Win32 共享冲突发生在预检之后，验证复制与原子清单替换失败路径。
    for stage, name in (
        ("installing", "_internal/adb.exe"),
        ("previous", protocol.INSTALL_MANIFEST),
    ):
        case = workspace / (stage + "-sharing")
        channel = Channel(case / "barrier", stage)
        executable = _compile(iscc, payloads["b"], "1.1.0", case / "build", channel=channel)
        app = case / "app"
        _install(installers["a"], app, "1.0.0", case / "baseline.log")
        code = _fault_run(
            _command(executable, case / "fault.inno.log", app),
            channel,
            case / "fault.log",
            action="continue",
            at_stage=lambda _, path=app / name: _held_file(path),
        )
        if code == 0 or common._identity(app)["State"] != "installing":
            raise RuntimeError("真实共享冲突未留下失败的 installing 状态")
        files = _install(installers["b"], app, "1.1.0", case / "repair.log")
        _uninstall(app, files, case / "uninstall.log")
        print(f"PASS fault sharing stage={stage}", flush=True)

    for stage in UNINSTALL_STAGES:
        case = workspace / stage
        channel = Channel(case / "barrier", stage)
        executable = _compile(iscc, payloads["b"], "1.1.0", case / "build", channel=channel)
        app = case / "app"
        files = _install(executable, app, "1.1.0", case / "baseline.log")
        unknown = app / "user-extra.dat"
        unknown.write_bytes(b"must survive uninstall failure")
        # 修改受管文件必须在任何删除/状态变更之前拒绝完整卸载事件。
        owned = app / protocol.MAIN_EXECUTABLE
        original = owned.read_bytes()
        owned.write_bytes(b"user modified managed file")
        _reject(app / "unins000.exe", app, case / "modified-reject.log", uninstall=True)
        owned.write_bytes(original)

        def share_failure(detail: str) -> protocol.InstallationGuard | None:
            if stage == "uninstall-post":
                return _held_file(app / protocol.INSTALL_MANIFEST)
            if stage == "uninstall-file":
                remaining = [name for name in sorted(files) if (app / name).is_file()]
                if not remaining or (app / detail).exists():
                    raise RuntimeError("未到达真实部分删除状态")
                return _held_file(app / remaining[0])
            return None

        sharing = stage in {"uninstall-file", "uninstall-post"}
        code = _fault_run(
            _command(app / "unins000.exe", case / "fault.inno.log"),
            channel,
            case / "fault.log",
            action="continue" if sharing else "crash",
            at_stage=share_failure,
        )
        if code == 0 or common._identity(app)["State"] != "removing":
            raise RuntimeError("卸载故障没有留下失败的 removing 身份")
        if unknown.read_bytes() != b"must survive uninstall failure":
            raise RuntimeError("卸载故障删除了用户文件")
        _reject(installers["b"], app, case / "removing-reject-install.log")
        if stage == "uninstall-post":
            if common._registrations(FIXTURE_APP_ID) or (app / "unins000.dat").exists():
                raise RuntimeError("未到达 Inno 系统集成清理后的后置失败边界")
            files = _retain_and_reinstall(app, installers["b"], "1.1.0", workspace)
        else:
            # 只有同一个测试屏障放行；重试使用原卸载器及其真实 removing 协议。
            channel.action("continue")
        _uninstall(app, files, case / "retry-uninstall.log")
        print(f"PASS fault uninstall stage={stage}", flush=True)
    if common._registrations(FIXTURE_APP_ID):
        raise RuntimeError("故障矩阵结束仍有 fixture 登记")
    print(
        "PASS full-event fault matrix: process exits, sharing failures, "
        "exact pending repair, uninstall recovery"
    )


def _race_location(installed_app: Path) -> Path:
    """仅放行 runner 临时子目录或经真实令牌核实的当前标准用户唯一默认位置。"""
    _check_no_reparse(installed_app.absolute())
    app = installed_app.resolve()
    base = Path(os.environ["RUNNER_TEMP"]).resolve()
    if app != base and app.is_relative_to(base):
        return app
    from scripts.windows_installer.standard_user import assert_standard_user

    identity = assert_standard_user()
    expected = Path(identity["local_appdata"]) / "Programs/ADBLab"
    _check_no_reparse(expected)
    if app != expected.resolve():
        raise ValueError("启动竞争只允许 runner 临时子目录或标准账户唯一默认位置")
    return app


def run_product_install_race(
    iscc: Path,
    installed_app: Path,
    version: str,
    workspace: Path,
    *,
    disposable: bool = False,
) -> None:
    """在实际 Inno 独占维护窗口启动真实冻结应用；调用者随后用正式安装器恢复卸载器。"""
    from scripts.check_windows_installer import _assert_ready, validate_environment

    workspace = validate_environment(workspace, disposable)
    app = _race_location(installed_app)
    files = _assert_ready(app, version)
    workspace.mkdir(parents=True, exist_ok=False)
    payload = workspace / "payload"
    payload.mkdir()
    # 仅复制验证过的当前载荷；不把用户文件、卸载器和维护状态重新打包。
    for name in files | {protocol.INSTALL_MANIFEST}:
        destination = payload / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(app / name, destination)
    channel = Channel(workspace / "barrier", "installing")
    executable = _compile(
        iscc, payload, version, workspace / "build", channel=channel, app_id=protocol.APP_ID
    )

    def launch_while_locked(_: str) -> protocol.InstallationGuard | None:
        before = common._identity(app)
        result = subprocess.run(
            [str(app / protocol.MAIN_EXECUTABLE), "--self-check", "packaging"],
            capture_output=True,
            timeout=60,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        (workspace / "blocked-launch.log").write_bytes(result.stdout + result.stderr)
        if (
            result.returncode != 73
            or before["State"] != "installing"
            or common._identity(app) != before
        ):
            raise RuntimeError("真实应用未在实际 Inno installing 屏障处拒绝启动或改写了身份")
        if (channel.root / "action").exists():
            raise RuntimeError("应用启动前屏障已提前放行")
        return None

    code = _fault_run(
        _command(executable, workspace / "race.inno.log", app),
        channel,
        workspace / "race.log",
        action="continue",
        at_stage=launch_while_locked,
    )
    if code != 0:
        raise RuntimeError(f"竞争验收中的实际安装未完成：{code}")
    _ready(app, version, protocol.APP_ID)
    common._run(
        [str(app / protocol.MAIN_EXECUTABLE), "--self-check", "packaging"],
        workspace / "ready-launch.log",
        timeout=60,
    )
    print(
        "PASS real frozen application rejected during actual Inno installing event "
        "and admitted after ready"
    )
