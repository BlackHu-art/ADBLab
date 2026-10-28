"""无显式 owner 的短命令失败后仍保留资源，关闭检查不得提前报告空闲。"""

import subprocess
import threading

import pytest

from core import adb_runtime, native_process
from core import exec as execution
from core.native_process import NativeCommandScope
from tests.test_native_command_scope import ControlledProcess


@pytest.fixture
def default_stuck_client(monkeypatch):
    process = ControlledProcess()
    process.exit_on_kill = False
    starts = []

    def communicate(input=None, timeout=None):
        raise subprocess.TimeoutExpired("synthetic", timeout, output=b"partial")

    def spawn(*_args, **_kwargs):
        starts.append(process)
        return process

    process.communicate = communicate
    monkeypatch.setattr(native_process, "popen_native", spawn)
    monkeypatch.setattr(execution, "resolve_command", lambda command: command)
    monkeypatch.setattr(execution, "_adb_runtime", None)
    yield process, starts
    process.returncode = -9
    assert execution.CommandRunner.wait_for_idle(0)


@pytest.mark.parametrize("exit_late", [False, True])
def test_default_failure_retains_client_until_retry_or_natural_exit(
    default_stuck_client, exit_late,
):
    process, starts = default_stuck_client
    result = execution.CommandRunner.run(["synthetic-install"], timeout=0.01)
    assert result.outcome == "failed"
    assert process.returncode is None
    assert execution.CommandRunner.active_count() == 1
    assert not execution.CommandRunner.wait_for_idle(0.01)
    kills = process.kill_count
    if exit_late:
        process.returncode = 0
    else:
        process.exit_on_kill = True
    assert execution.CommandRunner.wait_for_idle(0.1)
    assert execution.CommandRunner.wait_for_idle(0)
    assert execution.CommandRunner.active_count() == 0
    assert process.kill_count == kills + int(not exit_late)
    assert starts == [process]


def test_direct_run_native_failure_keeps_exception_and_cleanup_owner(default_stuck_client):
    process, starts = default_stuck_client
    with pytest.raises(TimeoutError, match="尚未确认客户端退出"):
        native_process.run_native(["synthetic-install"], timeout=0.01)
    assert native_process.native_cleanup_count() == 1
    assert not native_process.wait_for_native_cleanup(0)
    process.returncode = -9
    assert adb_runtime.wait_for_native_cleanup(0)
    assert starts == [process]


def test_default_residual_cleanup_shares_total_budget(default_stuck_client, monkeypatch):
    first, _starts = default_stuck_client
    assert execution.CommandRunner.run(["first"], timeout=0.01).outcome == "failed"
    second = ControlledProcess()
    second.exit_on_kill = False
    second.communicate = first.communicate
    monkeypatch.setattr(native_process, "popen_native", lambda *_a, **_kw: second)
    try:
        assert execution.CommandRunner.run(["second"], timeout=0.01).outcome == "failed"
        assert execution.CommandRunner.active_count() == 2
        now = [0.0]
        budgets = []

        def cleanup(self, process, *, completed, timeout):
            budgets.append(timeout)
            now[0] += timeout
            raise TimeoutError("synthetic cleanup timeout")

        monkeypatch.setattr(native_process.time, "monotonic", lambda: now[0])
        monkeypatch.setattr(NativeCommandScope, "_cleanup_process", cleanup)
        assert not native_process.wait_for_native_cleanup(0.25)
        assert budgets == [0.25]
        assert execution.CommandRunner.active_count() == 2
    finally:
        first.returncode = second.returncode = -9
        assert execution.CommandRunner.wait_for_idle(0)


def test_concurrent_default_calls_keep_distinct_residual_owners(monkeypatch):
    entered = threading.Barrier(3)
    release = threading.Event()
    processes, results = [], []

    def spawn(*_args, **_kwargs):
        process = ControlledProcess()
        process.exit_on_kill = False

        def communicate(input=None, timeout=None):
            entered.wait(timeout=2)
            assert release.wait(2)
            raise subprocess.TimeoutExpired("synthetic", timeout)

        process.communicate = communicate
        processes.append(process)
        return process

    monkeypatch.setattr(native_process, "popen_native", spawn)
    monkeypatch.setattr(execution, "resolve_command", lambda command: command)
    monkeypatch.setattr(execution, "_adb_runtime", None)
    workers = [threading.Thread(target=lambda: results.append(
        execution.CommandRunner.run(["synthetic"], timeout=1),
    )) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        entered.wait(timeout=2)
        assert execution.CommandRunner.active_count() == 2
        assert not execution.CommandRunner.wait_for_idle(0)
        assert all(process.kill_count == 0 for process in processes)
        release.set()
        for worker in workers:
            worker.join(2)
            assert not worker.is_alive()
        assert len(results) == 2 and all(result.outcome == "failed" for result in results)
        assert execution.CommandRunner.active_count() == 2
        processes[0].returncode = -9
        assert execution.CommandRunner.active_count() == 1
        assert not execution.CommandRunner.wait_for_idle(0)
        processes[1].returncode = -9
        assert execution.CommandRunner.wait_for_idle(0)
    finally:
        release.set()
        for worker in workers:
            worker.join(2)
        for process in processes:
            process.returncode = -9
        assert execution.CommandRunner.wait_for_idle(0)


@pytest.fixture
def stuck_client(monkeypatch):
    process = ControlledProcess()
    process.exit_on_kill = False
    cancelled = threading.Event()
    spawned = []

    def spawn(*_args, **_kwargs):
        spawned.append(process)
        cancelled.set()
        return process

    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    monkeypatch.setattr(execution, "_adb_runtime", None)
    yield process, cancelled, spawned
    process.poll_error = False
    process.returncode = -9
    execution.CommandRunner.wait_for_idle(0.1)


@pytest.mark.parametrize("entry", ["command", "binary", "capture"])
def test_unscoped_cleanup_failure_remains_owned_until_retry_confirms_exit(
    stuck_client, tmp_path, entry,
):
    process, cancelled, spawned = stuck_client
    if entry == "command":
        result = execution.CommandRunner.run(["synthetic"], cancelled=cancelled.is_set)
        assert not result.success
    elif entry == "binary":
        result = execution.CommandRunner.run_to_file(
            ["synthetic"], str(tmp_path / "output.bin"), cancelled=cancelled.is_set,
        )
        assert not result.success
    else:
        result = adb_runtime.native_capture(["synthetic"], 1, cancelled.is_set)
        assert result.kind == "transport"
    assert process.poll() is None
    assert execution.CommandRunner.active_count() == 1
    assert not execution.CommandRunner.wait_for_idle(0.01)
    assert execution.CommandRunner.active_count() == 1

    process.exit_on_kill = True
    assert execution.CommandRunner.wait_for_idle(0.5)
    assert execution.CommandRunner.active_count() == 0
    assert process.poll() is not None
    assert len(spawned) == 1


def test_global_cleanup_does_not_take_resources_from_an_explicit_owner(stuck_client):
    process, cancelled, spawned = stuck_client
    scope = NativeCommandScope()
    result = execution.CommandRunner.run(
        ["synthetic"], cancelled=cancelled.is_set, command_scope=scope,
    )
    assert not result.success and scope.is_running()
    kills = process.kill_count
    assert execution.CommandRunner.wait_for_idle(0.01)
    assert process.kill_count == kills
    assert execution.CommandRunner.active_count() == 0
    assert len(spawned) == 1
    process.exit_on_kill = True
    scope.request_stop()
    assert scope.wait(0.5)


def test_timeout_cleanup_failure_stays_owned_without_replaying_business(monkeypatch):
    process = ControlledProcess()
    process.exit_on_kill = False
    starts = []

    def communicate(**kwargs):
        raise subprocess.TimeoutExpired("synthetic", kwargs.get("timeout", 0))

    def spawn(*_args, **_kwargs):
        starts.append(process)
        return process

    process.communicate = communicate
    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    monkeypatch.setattr(execution, "_adb_runtime", None)
    try:
        result = execution.CommandRunner.run(["synthetic"], timeout=0.002, cancelled=lambda: False)
        assert not result.success
        assert execution.CommandRunner.active_count() == 1
        assert not execution.CommandRunner.wait_for_idle(0.01)
        process.exit_on_kill = True
        assert execution.CommandRunner.wait_for_idle(0.1)
        assert len(starts) == 1
    finally:
        process.returncode = -9
        execution.CommandRunner.wait_for_idle(0.1)


def test_poll_failure_does_not_erase_retained_client(stuck_client):
    process, cancelled, _spawned = stuck_client
    process.poll_error = True
    result = execution.CommandRunner.run(["synthetic"], cancelled=cancelled.is_set)
    assert not result.success
    assert execution.CommandRunner.active_count() == 1
    assert not execution.CommandRunner.wait_for_idle(0.01)
    process.poll_error = False
    process.returncode = -9
    assert execution.CommandRunner.wait_for_idle(0)
    assert execution.CommandRunner.active_count() == 0


def test_retained_client_does_not_block_an_unrelated_new_command(stuck_client, monkeypatch):
    process, cancelled, _spawned = stuck_client
    result = execution.CommandRunner.run(["synthetic"], cancelled=cancelled.is_set)
    assert not result.success and execution.CommandRunner.active_count() == 1
    other = ControlledProcess()
    monkeypatch.setattr(adb_runtime, "popen_native", lambda *_a, **_kw: other)
    result = execution.CommandRunner.run(["other-client"], cancelled=lambda: False)
    assert result.success and other.returncode == 0
    assert execution.CommandRunner.active_count() == 1
    assert process.returncode is None


def test_runtime_retains_only_its_own_returned_native_client(stuck_client):
    process, cancelled, spawned = stuck_client
    owner = adb_runtime.AdbRuntime(lambda: None)
    other = adb_runtime.AdbRuntime(lambda: None)
    try:
        result = owner.run_native(["synthetic"], 1, cancelled.is_set)
        assert result.kind == "transport"
        assert owner.is_running()
        assert not owner.wait(0.01)
        kills = process.kill_count
        assert not other.is_running() and other.wait(0)
        assert execution.CommandRunner.wait_for_idle(0)
        assert process.kill_count == kills
        owner.close()
        assert not owner.wait(0.01)
        process.exit_on_kill = True
        assert owner.wait(0.5)
        assert not owner.is_running() and len(spawned) == 1
        assert owner.run_native(["synthetic"], 1).kind == "cancelled"
        assert len(spawned) == 1
    finally:
        process.returncode = -9
        owner.close()
        owner.wait(0.1)
        other.close()


def test_runtime_close_during_native_spawn_retains_starting_obligation(monkeypatch):
    owner = adb_runtime.AdbRuntime(lambda: None)
    entered, release = threading.Event(), threading.Event()
    process = ControlledProcess()
    results = []

    def spawn(*_args, **_kwargs):
        entered.set()
        assert release.wait(2)
        return process

    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    worker = threading.Thread(target=lambda: results.append(
        owner.run_native(["synthetic"], 1),
    ))
    try:
        worker.start()
        assert entered.wait(1)
        owner.close()
        assert owner.is_running() and not owner.wait(0.01)
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert results[0].kind == "cancelled"
        assert process.returncode is not None and owner.wait(0.1)
    finally:
        release.set()
        worker.join(2)
        owner.close()
        owner.wait(0.1)


def test_parallel_unscoped_commands_keep_distinct_owners_and_counts(monkeypatch):
    entered = threading.Barrier(3)
    release = threading.Event()
    processes = []
    results = []

    def spawn(*_args, **_kwargs):
        process = ControlledProcess()
        original = process.communicate

        def communicate(**kwargs):
            entered.wait(timeout=2)
            assert release.wait(2)
            return original(**kwargs)

        process.communicate = communicate
        processes.append(process)
        return process

    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    monkeypatch.setattr(execution, "_adb_runtime", None)
    workers = [threading.Thread(target=lambda: results.append(execution.CommandRunner.run(
        ["synthetic"], cancelled=lambda: False,
    ))) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        entered.wait(timeout=2)
        assert execution.CommandRunner.active_count() == 2
        assert not execution.CommandRunner.wait_for_idle(0.01)
        assert all(process.kill_count == 0 for process in processes)
        release.set()
        for worker in workers:
            worker.join(2)
        assert all(not worker.is_alive() for worker in workers)
        assert len(results) == 2 and all(result.success for result in results)
        assert execution.CommandRunner.wait_for_idle(0)
        assert execution.CommandRunner.active_count() == 0
    finally:
        release.set()
        for worker in workers:
            worker.join(2)


@pytest.mark.parametrize("shutdown", ["prepare_shutdown", "close"])
def test_runtime_status_keeps_admitted_scope_before_native_capture_starts(monkeypatch, shutdown):
    owner = adb_runtime.AdbRuntime(lambda: None)
    entered, release = threading.Event(), threading.Event()
    original = adb_runtime.native_capture
    results, spawned = [], []

    def delayed_capture(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    def spawn(*_args, **_kwargs):
        process = ControlledProcess()
        spawned.append(process)
        return process

    monkeypatch.setattr(adb_runtime, "native_capture", delayed_capture)
    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    worker = threading.Thread(target=lambda: results.append(owner.run_native(["synthetic"], 1)))
    try:
        worker.start()
        assert entered.wait(1)
        assert owner.is_running()
        getattr(owner, shutdown)()
        assert owner.is_running() and not owner.wait(0)
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert spawned == []
        assert len(results) == 1 and results[0].kind == "cancelled"
        assert owner.wait(0) and not owner.is_running()
    finally:
        release.set()
        worker.join(2)
        owner.close()
        owner.wait(0.1)
