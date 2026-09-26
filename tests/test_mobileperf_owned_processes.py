"""仅创建本用例 Python 进程，验证 worker 退出后的客户端和独立服务归属。"""

import gc
import json
import os
import subprocess
import sys
import threading
import time
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from core.exec import ProcessRunner


def _wait(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


@pytest.mark.parametrize("natural_exit", [False, True])
def test_worker_exit_reaps_owned_client_and_preserves_independent_service(tmp_path, natural_exit):
    scope = tmp_path / "clients"
    scope.mkdir()
    ready = tmp_path / "ready.json"
    release = tmp_path / "release"
    child_code = (
        "import subprocess,sys,time,json,os; from pathlib import Path; "
        "server=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"ready=Path({str(ready)!r}); temporary=ready.with_suffix('.tmp'); "
        "temporary.write_text(json.dumps([os.getpid(),server.pid])); temporary.replace(ready); "
        "time.sleep(60)"
    )
    worker_code = (
        "import sys,time; from pathlib import Path; "
        "from core.native_process import popen_native; "
        f"p=popen_native([sys.executable,'-c',{child_code!r}], owned_client=True); "
        f"release=Path({str(release)!r}); "
        "exec('while not release.exists(): time.sleep(0.02)')"
    )
    runner = ProcessRunner()
    process = None
    identities = []
    try:
        process = runner.start(
            "worker", [sys.executable, "-c", worker_code],
            owned_clients_dir=str(scope), env=dict(os.environ), stderr=subprocess.PIPE,
        )
        _wait(ready.exists)
        client_pid, server_pid = json.loads(ready.read_text())
        identities = [psutil.Process(pid) for pid in (client_pid, server_pid)]
        if natural_exit:
            release.touch()
            _wait(lambda: process.poll() is not None)
        assert runner.stop("worker", timeout=5) is not None
        assert not identities[0].is_running()
        assert identities[1].is_running()
        assert "worker" not in runner.active_keys
    finally:
        release.touch()
        runner.stop_all()
        if process is not None and process.stderr is not None:
            process.stderr.close()
        for identity in identities:
            if identity.is_running():
                identity.kill()
                identity.wait(timeout=5)


def test_corrupt_or_unfinished_client_registration_retains_tracking(tmp_path, monkeypatch):
    from core import owned_process
    from core.owned_process import OwnedWorkerProcess
    monkeypatch.setattr(owned_process, "_alive", lambda _identity: False)
    slot = tmp_path / "client"
    slot.mkdir()
    record = slot / "record.json"
    underlying = SimpleNamespace(poll=lambda: 0, returncode=0, args=["worker"])
    wrapper = OwnedWorkerProcess(underlying, str(tmp_path))
    runner = ProcessRunner()
    runner._procs["worker"] = wrapper
    try:
        for text in ("invalid JSON", '{"phase":"starting"}', '{"phase":"running"}'):
            record.write_text(text)
            assert runner.stop("worker", timeout=0) is None
            assert runner.active_keys == ["worker"]
        record.write_text('{"phase":"done","helper":[123,100.0]}')
        assert runner.stop("worker", timeout=0) == 0
        assert not runner.active_keys
    finally:
        record.write_text('{"phase":"done","helper":[123,100.0]}')
        runner.stop_all()


def test_reused_pid_is_not_treated_as_owned_client(monkeypatch):
    from core import owned_process
    process = Mock()
    process.create_time.return_value = 200.0
    monkeypatch.setattr(owned_process.psutil, "Process", Mock(return_value=process))
    assert not owned_process._alive([123, 100.0])
    process.kill.assert_not_called()


def test_helper_cancelled_before_creation_never_spawns_client(tmp_path, monkeypatch):
    from core import owned_process
    monkeypatch.setattr(owned_process, "_identity", lambda pid: [pid, 100.0])
    monkeypatch.setattr(owned_process, "_alive", lambda _identity: False)
    spawn = Mock()
    monkeypatch.setattr(owned_process.subprocess, "Popen", spawn)
    code = owned_process.launch_owned_client([
        "--owned-client", str(tmp_path), "123", "100.0", "--", "fake-client",
    ])
    assert code == 130
    spawn.assert_not_called()
    assert json.loads((tmp_path / "record.json").read_text())["phase"] == "done"


def test_portable_helper_reaps_only_direct_client_when_owner_exits(tmp_path, monkeypatch):
    from core import owned_process
    child = Mock(pid=999)
    child.returncode = None
    child.poll.side_effect = lambda: child.returncode
    child.kill.side_effect = lambda: setattr(child, "returncode", -9)
    monkeypatch.setattr(owned_process, "_identity", lambda pid: [pid, 100.0])
    monkeypatch.setattr(owned_process, "_alive", Mock(side_effect=[True, False]))
    monkeypatch.setattr(owned_process.sys, "platform", "linux")
    spawn = Mock(return_value=child)
    monkeypatch.setattr(owned_process.subprocess, "Popen", spawn)
    code = owned_process.launch_owned_client([
        "--owned-client", str(tmp_path), "123", "100.0", "--", "fake-client",
    ])
    assert code == -9
    spawn.assert_called_once_with(["fake-client"])
    child.kill.assert_called_once()
    assert json.loads((tmp_path / "record.json").read_text())["phase"] == "done"


def test_helper_cleanup_denied_keeps_unfinished_registration(tmp_path, monkeypatch):
    from core import owned_process
    child = Mock(pid=999)
    child.poll.return_value = None
    child.kill.side_effect = PermissionError("test denied")
    monkeypatch.setattr(owned_process, "_identity", lambda pid: [pid, 100.0])
    monkeypatch.setattr(owned_process, "_alive", Mock(side_effect=[True, False]))
    monkeypatch.setattr(owned_process.sys, "platform", "linux")
    monkeypatch.setattr(owned_process.subprocess, "Popen", Mock(return_value=child))
    with pytest.raises(PermissionError):
        owned_process.launch_owned_client([
            "--owned-client", str(tmp_path), "123", "100.0", "--", "fake-client",
        ])
    assert json.loads((tmp_path / "record.json").read_text())["phase"] == "running"


@pytest.mark.parametrize("interrupt_at", ["record.json", "record.tmp", "cancel", "rmdir"])
def test_finished_registration_is_retired_before_interruptible_cleanup(
    tmp_path, monkeypatch, interrupt_at,
):
    from core import owned_process
    slot = tmp_path / "slot"
    slot.mkdir()
    (slot / "record.json").write_text('{"phase":"done","helper":[123,100.0]}')
    client = owned_process.OwnedClientProcess.__new__(owned_process.OwnedClientProcess)
    client._directory = slot
    client._confirmed_exit = False
    client._child_created = False
    monkeypatch.setattr(subprocess.Popen, "poll", lambda _self: 0)
    original_unlink, original_rmdir = Path.unlink, Path.rmdir

    class WorkerInterrupted(BaseException):
        pass

    def unlink(path, **kwargs):
        original_unlink(path, **kwargs)
        if path.name == interrupt_at:
            raise WorkerInterrupted()

    def rmdir(path):
        if interrupt_at == "rmdir":
            raise WorkerInterrupted()
        original_rmdir(path)

    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(Path, "rmdir", rmdir)
    with pytest.raises(WorkerInterrupted):
        client.poll()
    worker = owned_process.OwnedWorkerProcess(SimpleNamespace(poll=lambda: 0), str(tmp_path))
    assert worker.poll() == 0
    assert not slot.exists()


@pytest.mark.parametrize("owned_client", [False, True])
def test_worker_scope_does_not_wrap_ordinary_synchronous_native_queries(
    tmp_path, monkeypatch, owned_client,
):
    from core import native_process
    from core.owned_process import SCOPE_ENV
    monkeypatch.setenv(SCOPE_ENV, str(tmp_path))
    monkeypatch.setattr(native_process, "_should_isolate", lambda *_args: False)
    ordinary = Mock(return_value=object())
    owned = Mock(return_value=object())
    monkeypatch.setattr(native_process.subprocess, "Popen", ordinary)
    monkeypatch.setattr(native_process, "OwnedClientProcess", owned)
    result = native_process.popen_native(["fake-adb", "shell"], isolate=True,
                                         owned_client=owned_client)
    if owned_client:
        assert result is owned.return_value
        ordinary.assert_not_called()
    else:
        assert result is ordinary.return_value
        owned.assert_not_called()


def test_remote_lease_failure_is_business_terminal_but_retains_resource_obligation(
    tmp_path, monkeypatch,
):
    from core.monkey_process import MonkeyProcessLease
    from core.owned_process import SCOPE_ENV, OwnedWorkerProcess
    monkeypatch.setenv(SCOPE_ENV, str(tmp_path))
    lease = MonkeyProcessLease()
    lease.command(["monkey", "1"])
    worker = OwnedWorkerProcess(SimpleNamespace(poll=lambda: 0), str(tmp_path))
    runner = ProcessRunner()
    runner._procs["worker"] = worker
    runner._register_global("worker", worker)
    try:
        assert worker.poll() == 1
        assert not worker.resources_released()
        assert runner.stop("worker", timeout=0) is None
        assert runner.active_keys == ["worker"]
        assert not runner.release_finished("worker", worker)
        assert ProcessRunner.tracked_active_count() >= 1
        assert lease.stop(lambda _command: f"ADBLAB_MONKEY_STOPPED_{lease.token}")
        assert worker.resources_released()
        assert runner.stop("worker", timeout=0) == 1
    finally:
        lease.discard_unsubmitted()
        runner.stop_all()


@pytest.mark.parametrize("spawn_failed", [False, True])
def test_remote_lease_released_before_worker_exit_does_not_delay_cleanup(
    tmp_path, monkeypatch, spawn_failed,
):
    from core.monkey_process import MonkeyProcessLease
    from core.owned_process import SCOPE_ENV, OwnedWorkerProcess
    monkeypatch.setenv(SCOPE_ENV, str(tmp_path))
    lease = MonkeyProcessLease()
    lease.command(["monkey", "1"])
    if spawn_failed:
        lease.discard_unsubmitted()
    else:
        assert lease.stop(lambda _command: f"ADBLAB_MONKEY_STOPPED_{lease.token}")
    worker = OwnedWorkerProcess(SimpleNamespace(poll=lambda: 0), str(tmp_path))
    assert worker.poll() == 0
    assert worker.resources_released()
    tmp_path.rmdir()
    assert worker.poll() == 0
    assert worker.resources_released()


def test_owned_worker_force_stop_escalates_only_parent_when_terminate_is_ignored(tmp_path):
    from core.owned_process import OwnedWorkerProcess
    parent = Mock()
    parent.returncode = None
    parent.poll.side_effect = lambda: parent.returncode
    parent.wait.side_effect = subprocess.TimeoutExpired("worker", 0)
    parent.kill.side_effect = lambda: setattr(parent, "returncode", -9)
    runner = ProcessRunner()
    worker = OwnedWorkerProcess(parent, str(tmp_path))
    runner._procs["worker"] = worker
    try:
        assert runner.force_stop("worker", timeout=1)
        parent.kill.assert_called_once()
        assert not runner.active_keys
    finally:
        parent.returncode = -9
        runner.stop_all()


def test_forced_worker_with_remote_residual_reports_failure_and_keeps_temporary_owner(
    tmp_path, monkeypatch,
):
    from services import mobileperf_runner as runner_module
    from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner
    monkeypatch.setattr(runner_module, "user_data_root", lambda: tmp_path)
    monkeypatch.setattr(MobilePerfRunner, "_resolve_adb_path", staticmethod(lambda: "adb-unused"))
    ready = tmp_path / "ready"
    script = (
        "import os,time; from pathlib import Path; "
        "(Path(os.environ['ADBLAB_OWNED_CLIENT_DIR'])/'remote-test').mkdir(); "
        f"Path({str(ready)!r}).touch(); time.sleep(60)"
    )
    processes = ProcessRunner()
    runner = MobilePerfRunner(process_runner=processes, project_root=tmp_path)
    runner._build_command = lambda: [sys.executable, "-u", "-c", script]
    finished = threading.Event()
    runner.start(MobilePerfRunConfig(), on_finished=finished.set)
    key = runner._process_key
    process = runner._proc
    config_path = Path(runner.config_path)
    scope = config_path.parent / "clients"
    owner = weakref.ref(runner._config_dir)
    try:
        _wait(ready.exists)
        assert not runner.force_stop(timeout=2)
        assert finished.wait(3)
        _wait(lambda current=runner: not current.is_running())
        assert runner.last_exit_code != 0
        assert key in processes.active_keys
        assert config_path.exists()
        with pytest.raises(RuntimeError, match="cleanup"):
            runner.start(MobilePerfRunConfig())
        del runner
        gc.collect()
        assert owner() is not None
        assert config_path.exists()
    finally:
        marker = scope / "remote-test"
        if marker.exists():
            marker.rename(scope / ".done-remote-test")
        processes.stop(key, timeout=2)
        if owner() is not None:
            owner().cleanup()
        assert process.poll() is not None or not scope.exists()


@pytest.mark.parametrize("stop_cleared_proc", [False, True])
def test_start_rejects_remote_residual_before_finish_callback_collects_context(
    tmp_path, stop_cleared_proc,
):
    from core.owned_process import OwnedWorkerProcess
    from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner
    scope = tmp_path / "clients"
    scope.mkdir()
    (scope / "remote-test").mkdir()
    runner = MobilePerfRunner(project_root=tmp_path)
    runner._proc = OwnedWorkerProcess(SimpleNamespace(poll=lambda: 0), str(scope))
    if stop_cleared_proc:
        runner._active_context = SimpleNamespace(proc=runner._proc)
        runner._proc = None
    runner._capture_result_baseline = Mock(side_effect=AssertionError("new start was admitted"))
    with pytest.raises(RuntimeError, match="cleanup"):
        runner.start(MobilePerfRunConfig())
    runner._capture_result_baseline.assert_not_called()


@pytest.mark.parametrize("exit_code", [0, 7])
def test_fast_client_exit_preserves_real_code_when_pid_identity_is_already_gone(
    tmp_path, monkeypatch, exit_code,
):
    from core import owned_process
    child = Mock(pid=999, returncode=exit_code)
    child.poll.return_value = exit_code
    monkeypatch.setattr(owned_process, "_identity", Mock(side_effect=[
        [123, 100.0], psutil.NoSuchProcess(999),
    ]))
    monkeypatch.setattr(owned_process, "_alive", lambda _identity: True)
    monkeypatch.setattr(owned_process.sys, "platform", "linux")
    monkeypatch.setattr(owned_process.subprocess, "Popen", Mock(return_value=child))
    assert owned_process.launch_owned_client([
        "--owned-client", str(tmp_path), "1", "100.0", "--", "fake-client",
    ]) == exit_code
    child.kill.assert_not_called()
    assert json.loads((tmp_path / "record.json").read_text())["phase"] == "done"


@pytest.mark.skipif(sys.platform != "win32", reason="验证 Windows 读句柄拒绝替换的实际语义")
def test_record_publication_recovers_after_parent_reader_releases_windows_handle(
    tmp_path, monkeypatch,
):
    from core.owned_process import _write_record
    _write_record(tmp_path, {"phase": "running"})
    blocked = threading.Event()
    failures = []
    original_replace = Path.replace

    def replace(path, target):
        try:
            return original_replace(path, target)
        except PermissionError:
            blocked.set()
            raise

    monkeypatch.setattr(Path, "replace", replace)

    def publish():
        try:
            _write_record(tmp_path, {"phase": "done"})
        except OSError as error:
            failures.append(error)

    writer = threading.Thread(target=publish)
    try:
        with (tmp_path / "record.json").open(encoding="utf-8"):
            writer.start()
            assert blocked.wait(1), "Windows 共享冲突未复现"
        writer.join(1)
        assert not writer.is_alive()
        assert not failures
        assert json.loads((tmp_path / "record.json").read_text()) == {"phase": "done"}
    finally:
        writer.join(1)


def test_record_publication_keeps_failure_when_permission_denial_persists(tmp_path, monkeypatch):
    from core import owned_process
    owned_process._write_record(tmp_path, {"phase": "running"})
    error = PermissionError("test denied")
    error.winerror = 5
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr(owned_process.sys, "platform", "win32")
    monkeypatch.setattr(owned_process.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(Path, "replace", Mock(side_effect=error))
    with pytest.raises(PermissionError):
        owned_process._write_record(tmp_path, {"phase": "done"})
    assert json.loads((tmp_path / "record.json").read_text()) == {"phase": "running"}
