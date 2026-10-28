"""升级交接的原生句柄、私有管道和入口授权回归。"""

import hashlib
import io
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 原生交接")
def test_parent_handle_is_bound_to_creation_time_and_timeout():
    from core.installer_update_process import ParentProcess

    with ParentProcess(os.getpid()) as parent:
        assert not parent.wait(0.01)
        with pytest.raises(ValueError, match="identity"):
            ParentProcess(os.getpid(), parent.created + 1)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 原生交接")
def test_parent_handle_observes_real_exit_and_exit_code():
    from core.installer_update_process import ParentProcess

    child = subprocess.Popen([sys.executable, "-c", "input();raise SystemExit(7)"],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
    try:
        with ParentProcess(child.pid) as parent:
            assert not parent.wait(0.01)
            child.communicate(b"exit\n", timeout=5)
            assert parent.wait(2)
            assert parent.exit_code == 7
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 原生交接")
def test_locked_installer_denies_write_delete_and_replacement(tmp_path):
    from core.installer_update_process import locked_file

    target = tmp_path / "setup.exe"
    target.write_bytes(b"verified fixture")
    with locked_file(target) as stream:
        assert stream.read() == b"verified fixture"
        with pytest.raises(PermissionError):
            target.write_bytes(b"changed")
        with pytest.raises(PermissionError):
            target.unlink()
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"changed")
        with pytest.raises(PermissionError):
            replacement.replace(target)
        with pytest.raises(PermissionError):
            tmp_path.rename(tmp_path.with_name(tmp_path.name + "-moved"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 原生交接")
def test_pipe_read_has_size_deadline_and_eof_boundaries():
    from core.installer_update_process import read_pipe_line

    child = subprocess.Popen([sys.executable, "-c", "import sys;print('READY',flush=True);input()"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        assert read_pipe_line(child.stdout, timeout=5) == b"READY"
        with pytest.raises(TimeoutError):
            read_pipe_line(child.stdout, timeout=0.03)
        child.communicate(b"exit\n", timeout=5)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.parametrize("failure", [None, "gui", "lock", "exit_code"])
def test_entry_commits_only_after_successful_gui_cleanup_and_lock_release(monkeypatch, failure):
    import main
    from core import windows_installation

    events = []

    def close():
        events.append("lock-close")
        if failure == "lock":
            raise RuntimeError("lock failed")

    handoff = SimpleNamespace(commit=lambda: events.append("commit"),
                              abort=lambda: events.append("abort"))
    monkeypatch.setattr(windows_installation, "acquire_installation_guard",
                        lambda: SimpleNamespace(close=close))
    monkeypatch.setattr(main, "_create_installer_handoff", lambda guard: handoff)
    monkeypatch.setattr(main, "_dispatch_cli", lambda argv: None)

    def gui(*, handoff):
        events.append("gui-cleanup")
        if failure == "gui":
            raise RuntimeError("GUI failed")
        return 1 if failure == "exit_code" else 0

    monkeypatch.setattr(main, "_run_gui", gui)
    if failure in {"gui", "lock"}:
        with pytest.raises(RuntimeError):
            main._run_entry([])
    else:
        assert main._run_entry([]) == (1 if failure else 0)
    assert events == ["gui-cleanup", "lock-close", "commit" if failure is None else "abort"]


def test_portable_and_source_do_not_get_handoff(monkeypatch):
    import main

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert main._create_installer_handoff(SimpleNamespace()) is None
    assert main._create_installer_handoff(None) is None


def _request(tmp_path, monkeypatch):
    from core import installer_update_protocol as protocol
    from services.app_update import InstallerAsset

    root = tmp_path / "updates"
    job = root / "fixture"
    job.mkdir(parents=True)
    asset = InstallerAsset(
        1, 2, "v99.0.0", "99.0.0", "ADBLab-win-x64-v99.0.0-setup.exe",
        "https://github.com/BlackHu-art/ADBLab/releases/download/v99.0.0/"
        "ADBLab-win-x64-v99.0.0-setup.exe", 3, hashlib.sha256(b"abc").hexdigest(),
    )
    path = job / asset.name
    path.write_bytes(b"abc")
    monkeypatch.setattr(protocol, "user_data_root", lambda: tmp_path)
    return {"protocol": 1, "pid": os.getpid(), "created": 1, "nonce": "a" * 32,
            "path": str(path), "asset": asdict(asset)}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 原生文件锁")
@pytest.mark.parametrize("condition", ["success", "no_commit", "timeout", "abnormal", "corrupt"])
def test_helper_requires_commit_real_parent_exit_and_matching_payload(
    tmp_path, monkeypatch, condition,
):
    from core import installer_update_protocol as protocol

    request = _request(tmp_path, monkeypatch)
    class Parent:
        def __init__(self, pid, created):
            assert pid == request["pid"] and created == 1
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def wait(self, timeout):
            return condition != "timeout"
        exit_code = 1 if condition == "abnormal" else 0
    monkeypatch.setattr(protocol, "ParentProcess", Parent)
    output = []
    launched = []
    def receive():
        if condition == "corrupt":
            Path(request["path"]).write_bytes(b"xyz")
        return b"COMMIT " + b"a" * 32 if condition != "no_commit" else b"ABORT"
    monkeypatch.setattr(protocol, "_launch_installer", lambda path: launched.append(path))
    result = protocol.execute_handoff(request, receive=receive, send=output.append)
    assert output == [b"READY " + b"a" * 32]
    assert (result == 0) is (condition == "success")
    assert bool(launched) is (condition == "success")


@pytest.mark.parametrize("field,value", [("pid", True), ("created", 0), ("nonce", "../bad"),
                                         ("protocol", 2), ("path", "C:/untrusted.exe")])
def test_helper_rejects_invalid_descriptor_before_ready(tmp_path, monkeypatch, field, value):
    from core import installer_update_protocol as protocol

    request = _request(tmp_path, monkeypatch)
    request[field] = value
    with pytest.raises(ValueError):
        protocol.validate_request(request)


def test_handoff_requires_success_report_and_is_idempotent():
    from core.installer_handoff import InstallerHandoff

    for approved in (False, True):
        owner = InstallerHandoff()
        pipe = io.BytesIO()
        owner._process = SimpleNamespace(stdin=pipe, stdout=io.BytesIO(), poll=lambda: None)
        owner._nonce = "a" * 32
        owner._prepared = True
        owner.mark_shutdown_success(approved)
        written = []
        class Pipe(io.BytesIO):
            def close(self):
                written.append(self.getvalue())
                super().close()
        owner._process.stdin = Pipe()
        owner.commit()
        owner.commit()
        assert written == ([b"COMMIT " + b"a" * 32 + b"\n"] if approved else [b""])


def test_rearm_never_revives_an_active_or_unfinished_attempt():
    from core.installer_handoff import InstallerHandoff

    owner = InstallerHandoff()
    owner.abort()
    owner._preparing = True
    with pytest.raises(RuntimeError):
        owner.reset_attempt()
    owner._preparing = False
    owner._process = SimpleNamespace(poll=lambda: None)
    with pytest.raises(RuntimeError):
        owner.reset_attempt()
    owner._process = SimpleNamespace(poll=lambda: 4, stdout=io.BytesIO())
    owner.reset_attempt()
    assert not owner._cancel.is_set()
    assert not owner.prepared


def fake_handoff_attempt(tmp_path, monkeypatch, *, answer=b"INVALID"):
    """仅替换原生进程边界，执行真实复制、握手及异常清理路径。"""
    from core import installer_handoff as module
    from services.app_update import InstallerAsset
    from services.installer_update import VerifiedInstaller

    request = _request(tmp_path, monkeypatch)
    verified = VerifiedInstaller(Path(request["path"]), InstallerAsset(**request["asset"]))
    source = tmp_path / "helper.exe"
    source.write_bytes(b"helper fixture")
    owner = module.InstallerHandoff()
    monkeypatch.setattr(owner, "_helper_source", lambda: (
        source, hashlib.sha256(b"helper fixture").hexdigest(),
    ))

    class Parent:
        created = 1
        def __init__(self, _pid):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    class Process:
        def __init__(self):
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO()
            self.returncode = None
            self.wait_calls = []
        def poll(self):
            return self.returncode
        def wait(self, timeout):
            self.wait_calls.append(timeout)
            if self.returncode is None:
                raise subprocess.TimeoutExpired("fake helper", timeout)
            return self.returncode

    process = Process()
    monkeypatch.setattr(module, "ParentProcess", Parent)
    monkeypatch.setattr(module, "locked_file", lambda path: path.open("rb"))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(module, "read_pipe_line", lambda *args, **kwargs: (
        f"READY {owner._nonce}".encode("ascii") if answer == b"READY" else answer
    ))
    return owner, verified, process


def test_failed_handshake_retains_live_helper_until_late_exit(tmp_path, monkeypatch):
    owner, verified, process = fake_handoff_attempt(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="handshake"):
        owner.prepare(verified)
    assert process.wait_calls == [5]
    assert owner._process is process
    assert not process.stdout.closed
    assert not owner.prepared
    for _ in range(2):
        owner.abort()
        with pytest.raises(RuntimeError, match="still active"):
            owner.reset_attempt()
        with pytest.raises(RuntimeError):
            owner.prepare(verified)
    process.returncode = 1
    owner.reset_attempt()
    assert process.stdout.closed
    assert owner._process is None
    assert not owner._cancel.is_set()
    retry_process = type(process)()
    from core import installer_handoff as module
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: retry_process)
    monkeypatch.setattr(module, "read_pipe_line", lambda *args, **kwargs: (
        f"READY {owner._nonce}".encode("ascii")
    ))
    owner.prepare(verified)
    assert owner.prepared
    owner.abort()
    retry_process.returncode = 0
    assert owner.wait_pending_helper(0)


def test_committed_helper_remains_live_without_becoming_a_failed_resource(tmp_path, monkeypatch):
    owner, verified, process = fake_handoff_attempt(tmp_path, monkeypatch, answer=b"READY")
    owner.prepare(verified)
    written = []

    class Pipe(io.BytesIO):
        def close(self):
            written.append(self.getvalue())
            super().close()

    process.stdin = Pipe()
    owner.mark_shutdown_success(True)
    owner.commit()
    assert written == [f"COMMIT {owner._nonce}\n".encode("ascii")]
    assert not owner.has_pending_helper()
    assert owner.wait_pending_helper(0.01)
    assert process.wait_calls == []
    assert process.poll() is None
    assert owner._process is process
