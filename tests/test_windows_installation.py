"""安装准入状态与 Windows 跨进程文件共享协议。"""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import windows_installation as installation

ROOT = Path(__file__).parents[1]


def _write_identity(root, **overrides):
    digest = hashlib.sha256((root / installation.INSTALL_MANIFEST).read_bytes()).hexdigest()
    values = dict(
        FormatVersion="1", AppId=installation.APP_ID,
        MainExecutable=installation.MAIN_EXECUTABLE, State="ready",
        CompletedVersion="1.2.3", PendingVersion="", ManifestSha256=digest,
        PendingManifestSha256="",
    )
    values.update(overrides)
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser[installation.INSTALL_SECTION] = values
    with (root / installation.INSTALL_MARKER).open("w", encoding="utf-8-sig") as target:
        parser.write(target)


@pytest.fixture
def installed(tmp_path):
    if sys.platform != "win32":
        pytest.skip("安装运行准入仅用于 Windows")
    executable = tmp_path / installation.MAIN_EXECUTABLE
    executable.write_bytes(b"fixture")
    digest = hashlib.sha256(b"fixture").hexdigest()
    (tmp_path / installation.INSTALL_MANIFEST).write_text(
        f"{digest}\t{installation.MAIN_EXECUTABLE}\n", encoding="utf-8-sig",
    )
    (tmp_path / installation.INSTALL_LOCK).touch()
    _write_identity(tmp_path)
    return executable


def test_protocol_constants_are_stable():
    assert installation.APP_ID == "{1C0CD5FE-33F4-4BB0-964D-F2EC6A79F062}"
    assert installation.MAIN_EXECUTABLE == "ADBLab.exe"
    assert installation.INSTALL_SECTION == "Installation"
    assert installation.INSTALL_MARKER == ".adblab-install.ini"
    assert installation.INSTALL_MANIFEST == ".adblab-files.txt"
    assert installation.INSTALL_PENDING_MANIFEST == ".adblab-pending-files.txt"
    assert installation.INSTALL_LOCK == ".adblab-maintenance.lock"
    assert installation.INSTALL_PREVIOUS_MANIFEST == ".adblab-files.txt.previous"


@pytest.mark.parametrize("platform,frozen", [("linux", True), ("darwin", True), ("win32", False)])
def test_source_and_other_platforms_do_not_inspect_installation(
    monkeypatch, tmp_path, platform, frozen,
):
    monkeypatch.setattr(installation, "sys", SimpleNamespace(
        platform=platform, frozen=frozen, executable=str(tmp_path / "ADBLab.exe"),
    ))
    monkeypatch.setattr(
        installation, "_open_running_lock", lambda _path: pytest.fail("opened lock"),
    )
    assert installation.acquire_installation_guard() is None


def test_portable_has_no_control_files_and_creates_nothing(tmp_path):
    assert installation.acquire_installation_guard(tmp_path / "portable.exe") is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", [
    ".adblab-install.ini", ".adblab-files.txt",
    ".adblab-pending-files.txt", ".adblab-maintenance.lock",
    ".adblab-files.txt.previous",
])
def test_any_control_file_prevents_portable_fallback(tmp_path, name):
    if sys.platform != "win32":
        pytest.skip("安装运行准入仅用于 Windows")
    (tmp_path / name).touch()
    with pytest.raises(installation.InstallationUnavailable) as error:
        installation.acquire_installation_guard(tmp_path / "ADBLab.exe")
    assert error.value.reason == "damaged"
    assert str(tmp_path) not in str(error.value)


@pytest.mark.parametrize("overrides", [
    {"AppId": "other"}, {"FormatVersion": "2"}, {"MainExecutable": "other.exe"},
    {"State": "unknown"}, {"CompletedVersion": "1.2"}, {"ManifestSha256": "x"},
])
def test_invalid_identity_fails_closed(installed, overrides):
    _write_identity(installed.parent, **overrides)
    with pytest.raises(installation.InstallationUnavailable, match="安装信息损坏") as error:
        installation.acquire_installation_guard(installed)
    assert error.value.reason == "damaged"


@pytest.mark.parametrize("state", ["installing", "removing"])
def test_incomplete_installation_never_enters_business(installed, state):
    _write_identity(
        installed.parent, State=state, PendingVersion="1.2.4", PendingManifestSha256="a" * 64,
    )
    with pytest.raises(installation.InstallationUnavailable) as error:
        installation.acquire_installation_guard(installed)
    assert error.value.reason == "incomplete"


def test_missing_lock_is_not_recreated(installed):
    lock = installed.parent / installation.INSTALL_LOCK
    lock.unlink()
    with pytest.raises(installation.InstallationUnavailable) as error:
        installation.acquire_installation_guard(installed)
    assert error.value.reason == "damaged"
    assert not lock.exists()


def test_manifest_digest_mismatch_fails_closed(installed):
    (installed.parent / installation.INSTALL_MANIFEST).write_bytes(b"changed")
    with pytest.raises(installation.InstallationUnavailable) as error:
        installation.acquire_installation_guard(installed)
    assert error.value.reason == "damaged"


@pytest.mark.parametrize("field", ["PendingVersion", "PendingManifestSha256"])
def test_ready_with_pending_identity_fields_is_damaged(installed, field):
    _write_identity(installed.parent, **{field: "1.2.4" if field == "PendingVersion" else "a" * 64})
    with pytest.raises(installation.InstallationUnavailable) as error:
        installation.acquire_installation_guard(installed)
    assert error.value.reason == "damaged"


@pytest.mark.parametrize("same", [False, True])
def test_ready_pending_cleanup_residue_requires_identical_digest(installed, same):
    manifest = installed.parent / installation.INSTALL_MANIFEST
    (installed.parent / installation.INSTALL_PENDING_MANIFEST).write_bytes(
        manifest.read_bytes() if same else b"conflicting pending",
    )
    if same:
        guard = installation.acquire_installation_guard(installed)
        assert guard is not None
        guard.close()
        guard.close()
    else:
        with pytest.raises(installation.InstallationUnavailable) as error:
            installation.acquire_installation_guard(installed)
        assert error.value.reason == "damaged"


def test_permission_failure_is_actionable_and_has_no_path(monkeypatch, installed):
    def denied(_path):
        raise PermissionError(13, "denied", str(installed))

    monkeypatch.setattr(installation, "_open_running_lock", denied)
    with pytest.raises(installation.InstallationUnavailable) as error:
        installation.acquire_installation_guard(installed)
    assert error.value.reason == "permission"
    assert "权限" in str(error.value)
    assert str(installed) not in str(error.value)


def test_identity_is_rechecked_after_lock_and_failed_acquire_releases_handle(
    monkeypatch, installed,
):
    original = installation._open_running_lock

    def race(path):
        handle = original(path)
        _write_identity(installed.parent, State="installing", PendingVersion="1.2.4",
                        PendingManifestSha256="a" * 64)
        return handle

    monkeypatch.setattr(installation, "_open_running_lock", race)
    with pytest.raises(installation.InstallationUnavailable) as error:
        installation.acquire_installation_guard(installed)
    assert error.value.reason == "incomplete"
    _write_identity(installed.parent)
    with _holder(installed, "exclusive"):
        pass


_HOLDER_CODE = r'''
import ctypes, json, pathlib, sys
from ctypes import wintypes
from core.windows_installation import (
    acquire_installation_guard, InstallationUnavailable, INSTALL_LOCK,
)
executable, mode, signal = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
if mode == "reader":
    try:
        guard = acquire_installation_guard(executable)
    except InstallationUnavailable as error:
        signal.write_text(json.dumps({"reason": error.reason}))
        sys.exit(73)
    signal.write_text(json.dumps({"ready": True}))
    sys.stdin.readline()
    guard.close()
else:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(
        str(executable.parent / INSTALL_LOCK), 0xC0000000, 0, None, 3, 0x80, None,
    )
    if handle == ctypes.c_void_p(-1).value:
        signal.write_text(json.dumps({"winerror": ctypes.get_last_error()}))
        sys.exit(1)
    signal.write_text(json.dumps({"ready": True}))
    sys.stdin.readline()
    kernel.CloseHandle(handle)
'''


class _holder:
    def __init__(self, executable, mode):
        self.signal = executable.parent / f"signal-{mode}-{time.time_ns()}.json"
        self.process = subprocess.Popen(
            [sys.executable, "-c", _HOLDER_CODE, str(executable), mode, str(self.signal)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env=os.environ.copy(),
        )
        try:
            deadline = time.monotonic() + 15
            while not self.signal.exists():
                if self.process.poll() is not None:
                    raise AssertionError(self.process.communicate(timeout=3))
                assert time.monotonic() < deadline, "child lock handshake timed out"
                time.sleep(0.02)
            self.result = json.loads(self.signal.read_text())
        except BaseException:
            self.process.kill()
            self.process.communicate(timeout=3)
            raise

    def __enter__(self):
        assert self.result == {"ready": True}
        return self

    def __exit__(self, *_args):
        self.process.communicate("exit\n", timeout=5)
        assert self.process.returncode == 0


@pytest.mark.skipif(sys.platform != "win32", reason="真实 Windows 文件共享协议")
def test_two_reader_processes_block_maintenance_until_last_exit(installed):
    with _holder(installed, "reader"):
        with _holder(installed, "reader"):
            blocked = _holder(installed, "exclusive")
            blocked.process.communicate(timeout=5)
            assert blocked.result == {"winerror": 32}
            assert blocked.process.returncode == 1
        blocked = _holder(installed, "exclusive")
        blocked.process.communicate(timeout=5)
        assert blocked.result == {"winerror": 32}
    with _holder(installed, "exclusive"):
        pass


@pytest.mark.skipif(sys.platform != "win32", reason="真实 Windows 文件共享协议")
def test_maintenance_process_blocks_application_and_crash_releases_lock(installed):
    maintenance = _holder(installed, "exclusive")
    assert maintenance.result == {"ready": True}
    try:
        reader = _holder(installed, "reader")
        reader.process.communicate(timeout=5)
        assert reader.result == {"reason": "maintenance"}
        assert reader.process.returncode == 73
    finally:
        maintenance.process.kill()
        maintenance.process.communicate(timeout=5)
    guard = installation.acquire_installation_guard(installed)
    assert guard is not None
    guard.close()


@pytest.mark.skipif(sys.platform != "win32", reason="真实 Windows 文件共享协议")
def test_reader_crash_releases_lock(installed):
    reader = _holder(installed, "reader")
    assert reader.result == {"ready": True}
    reader.process.kill()
    reader.process.communicate(timeout=5)
    with _holder(installed, "exclusive"):
        pass


@pytest.mark.parametrize("argv", [
    [], ["--self-check", "packaging"], ["--self-check", "gui"],
    ["--mobileperf-worker"], ["--startup-splash", "server"],
    ["--adblab-native-launch", "--", "fixture.exe"],
])
def test_entry_acquires_before_dispatch_and_closes_after_mode(monkeypatch, argv):
    import main

    events = []

    def acquire():
        events.append("acquire")
        return SimpleNamespace(close=lambda: events.append("close"))

    def dispatch(actual):
        assert actual == argv
        assert events == ["acquire"]
        events.append("dispatch")
        return 9 if argv else None

    def gui():
        events.append("gui")
        return 8

    monkeypatch.setattr(installation, "acquire_installation_guard", acquire)
    monkeypatch.setattr(main, "_dispatch_cli", dispatch)
    monkeypatch.setattr(main, "_run_gui", gui)
    assert main._run_entry(argv) == (9 if argv else 8)
    assert events == ["acquire", "dispatch", *([] if argv else ["gui"]), "close"]


@pytest.mark.parametrize("failure", [
    RuntimeError("fixture failure"), SystemExit(2), KeyboardInterrupt(),
])
def test_entry_closes_guard_on_exception_and_preserves_original(monkeypatch, failure):
    import main

    closed = []

    def dispatch(_argv):
        raise failure

    monkeypatch.setattr(installation, "acquire_installation_guard", lambda: SimpleNamespace(
        close=lambda: closed.append(True),
    ))
    monkeypatch.setattr(main, "_dispatch_cli", dispatch)
    with pytest.raises(type(failure)) as raised:
        main._run_entry(["--self-check", "invalid"])
    assert raised.value is failure
    assert closed == [True]


@pytest.mark.parametrize("argv,cli", [
    ([], False), (["--self-check", "packaging"], True), (["--mobileperf-worker"], True),
    (["--startup-splash", "server"], True), (["--adblab-native-launch"], True),
])
def test_entry_failure_blocks_business_and_returns_73(monkeypatch, argv, cli):
    import main

    error = installation.InstallationUnavailable("maintenance")

    def unavailable():
        raise error

    reported = []
    monkeypatch.setattr(installation, "acquire_installation_guard", unavailable)
    monkeypatch.setattr(main, "_dispatch_cli", lambda _argv: pytest.fail("business initialized"))
    monkeypatch.setattr(main, "_run_gui", lambda: pytest.fail("GUI initialized"))
    monkeypatch.setattr(
        main, "_report_installation_unavailable",
        lambda failure, *, cli: reported.append((failure, cli)),
    )
    assert main._run_entry(argv) == 73
    assert reported == [(error, cli)]


def test_cli_installation_failure_recovers_only_stderr(monkeypatch):
    import io

    import main
    from core import worker_stdio

    prepared = []
    output = io.StringIO()

    def prepare(name):
        prepared.append(name)
        return output

    monkeypatch.setattr(main.sys, "stderr", None)
    monkeypatch.setattr(worker_stdio, "_open_windows_output", prepare)
    main._report_installation_unavailable(
        installation.InstallationUnavailable("maintenance"), cli=True,
    )
    assert prepared == ["stderr"]
    assert main.sys.stderr is output
    assert "正在维护" in output.getvalue()


def test_gui_installation_failure_uses_native_prompt_without_qt(monkeypatch):
    import main

    messages = []
    monkeypatch.setattr(main.ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(
        MessageBoxW=lambda *args: messages.append(args),
    )), raising=False)
    error = installation.InstallationUnavailable("damaged")
    main._report_installation_unavailable(error, cli=False)
    assert messages == [(None, str(error), "ADBLab", 0x10)]


@pytest.mark.parametrize("argv,code", [
    (["--self-check", "invalid"], 2), (["--self-check", "--help"], 0),
    (["--mobileperf-worker", "--help"], 0), (["--startup-splash"], 2),
])
def test_entry_preserves_original_cli_argument_exit_codes(argv, code):
    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), *argv], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == code, result.stderr


def test_cli_rejection_still_returns_73_when_no_standard_handles_exist(monkeypatch):
    import main
    from core import worker_stdio

    messages = []

    def denied():
        raise installation.InstallationUnavailable("maintenance")

    def missing_stdio(name):
        assert name == "stderr"
        raise OSError("standard pipe unavailable")

    monkeypatch.setattr(installation, "acquire_installation_guard", denied)
    monkeypatch.setattr(worker_stdio, "_open_windows_output", missing_stdio)
    monkeypatch.setattr(main.sys, "stderr", None)
    monkeypatch.setattr(main.ctypes, "windll", SimpleNamespace(kernel32=SimpleNamespace(
        OutputDebugStringW=lambda message: messages.append(message),
    )), raising=False)
    assert main._run_entry(["--mobileperf-worker"]) == 73
    assert messages == [str(installation.InstallationUnavailable("maintenance"))]


def test_cli_rejection_uses_stderr_even_if_stdout_pipe_is_missing(monkeypatch, capsys):
    import main
    from core import worker_stdio

    def missing_stdout():
        pytest.fail("错误报告不能要求恢复 stdout")

    monkeypatch.setattr(worker_stdio, "prepare_worker_stdio", missing_stdout)
    main._report_installation_unavailable(
        installation.InstallationUnavailable("incomplete"), cli=True,
    )
    assert "安装尚未完成" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform != "win32", reason="真实 Windows 维护期间入口")
def test_real_maintenance_blocks_entry_before_any_gui_or_cli_initialization(installed):
    child_code = r'''
import sys
import main
sys.frozen = True
sys.executable = sys.argv[1]
main._dispatch_cli = lambda _args: (_ for _ in ()).throw(AssertionError("initialized"))
raise SystemExit(main._run_entry(["--self-check", "packaging"]))
'''
    with _holder(installed, "exclusive"):
        result = subprocess.run(
            [sys.executable, "-c", child_code, str(installed)], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
    assert result.returncode == 73, result.stderr
    assert "正在维护" in result.stderr
    assert str(installed.parent) not in result.stderr


def test_manifest_is_rechecked_after_acquiring_lock(monkeypatch, installed):
    original = installation._open_running_lock

    def changed(path):
        handle = original(path)
        (installed.parent / installation.INSTALL_MANIFEST).write_bytes(b"concurrent change")
        return handle

    monkeypatch.setattr(installation, "_open_running_lock", changed)
    with pytest.raises(installation.InstallationUnavailable) as error:
        installation.acquire_installation_guard(installed)
    assert error.value.reason == "damaged"
    with _holder(installed, "exclusive"):
        pass


def test_ready_previous_manifest_cleanup_residue_does_not_block_current_version(installed):
    previous = installed.parent / ".adblab-files.txt.previous"
    previous.write_bytes(b"previous version journal")
    guard = installation.acquire_installation_guard(installed)
    assert guard is not None
    guard.close()
    assert previous.read_bytes() == b"previous version journal"


@pytest.mark.skipif(sys.platform != "win32", reason="真实 Windows stderr-only 标准句柄")
@pytest.mark.parametrize("interpreter", ["python.exe", "pythonw.exe"])
def test_entry_reports_rejection_when_only_stderr_native_pipe_exists(interpreter):
    executable = Path(sys.executable).with_name(interpreter)
    if not executable.is_file():
        pytest.skip(f"活动解释器没有 {interpreter}")
    child_code = r'''
import ctypes, sys
from ctypes import wintypes
import main
from core import windows_installation
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
kernel.SetStdHandle.restype = wintypes.BOOL
assert kernel.SetStdHandle(-11, None)
sys.stdout = sys.stderr = None
def reject():
    raise windows_installation.InstallationUnavailable("maintenance")
windows_installation.acquire_installation_guard = reject
raise SystemExit(main._run_entry(["--self-check", "packaging"]))
'''
    result = subprocess.run(
        [str(executable), "-c", child_code], cwd=ROOT,
        capture_output=True, timeout=15, check=False,
    )
    assert result.returncode == 73, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == b""
    assert result.stderr.decode("utf-8").strip() == str(
        installation.InstallationUnavailable("maintenance"),
    )
