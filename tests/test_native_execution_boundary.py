"""应用各执行入口必须共用原生工具隔离边界。"""

from __future__ import annotations

import io
import subprocess
from types import SimpleNamespace

import pytest

import core.adb_runtime as runtime_module
import core.exec as execution
import main


def _reject_direct_spawn(*_args, **_kwargs):
    pytest.fail("原生执行绕过隔离入口")


@pytest.mark.parametrize("entry", ["run", "file", "spawn", "capture"])
def test_native_entry_routes_through_isolated_boundary(monkeypatch, tmp_path, entry):
    tool = str(tmp_path / "adb.exe")
    command = [tool, "version"]
    monkeypatch.setattr(execution, "resolve_command", lambda _cmd: command)
    monkeypatch.setattr(execution, "_adb_runtime", None)
    monkeypatch.setattr(subprocess, "run", _reject_direct_spawn)
    monkeypatch.setattr(subprocess, "Popen", _reject_direct_spawn)
    observed = []

    class Child:
        returncode = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def poll(self):
            return 0

        def communicate(self, **_kwargs):
            return b"ready", b""

    def run(cmd, **kwargs):
        observed.append((cmd, kwargs))
        if "stdout" in kwargs:
            kwargs["stdout"].write(b"ready")
        return subprocess.CompletedProcess(cmd, 0, "ready", "")

    def popen(cmd, **kwargs):
        observed.append((cmd, kwargs))
        return Child()

    monkeypatch.setattr(execution, "run_native", run, raising=False)
    monkeypatch.setattr(execution, "popen_native", popen, raising=False)
    monkeypatch.setattr(runtime_module, "popen_native", popen, raising=False)
    if entry == "run":
        assert execution.CommandRunner.run(command).success
    elif entry == "file":
        assert execution.CommandRunner.run_to_file(command, tmp_path / "output.bin").success
    elif entry == "spawn":
        assert execution.ProcessRunner().spawn(command).poll() == 0
    else:
        result = runtime_module.native_capture(command, 2, lambda: False, stdout_sink=io.BytesIO())
        assert result.returncode == 0
    assert len(observed) == 1
    assert observed[0][0] == command
    assert observed[0][1]["isolate"] is True


def test_main_dispatches_native_launcher_without_gui(monkeypatch):
    from core import native_launcher

    received = []
    monkeypatch.setattr(native_launcher, "launch", lambda args: received.append(args) or 7)
    assert main._dispatch_cli(["--adblab-native-launch", "--", "tool.exe"]) == 7
    assert received == [["--", "tool.exe"]]


def test_force_stop_uses_launcher_control_instead_of_killing_server_tree(monkeypatch):
    import time

    process = object()
    observed = []
    monkeypatch.setattr(
        execution, "stop_native_process", lambda proc, **kw: observed.append(proc) or True,
        raising=False,
    )
    monkeypatch.setattr(execution, "kill_process_tree", _reject_direct_spawn)
    assert execution.ProcessRunner._kill_process_tree_bounded(process, time.monotonic() + 1)
    assert observed == [process]


@pytest.mark.parametrize("entry", ["single", "all"])
@pytest.mark.parametrize("confirmed", [False, True])
def test_native_force_stop_keeps_shared_budget_and_unconfirmed_tracking(
    monkeypatch, entry, confirmed,
):
    """隔离入口耗尽预算后不能另开 kill 预算；只有确认退出才解除全局跟踪。"""
    clock = [0.0]
    monkeypatch.setattr(execution, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(execution.ProcessRunner, "_global_procs", {})

    class NativeChild:
        returncode = None

        def poll(self):
            return self.returncode

        def kill(self):
            clock[0] += 2.0
            self.returncode = 1

        def wait(self, timeout=None):
            if self.returncode is None:
                clock[0] += timeout
                raise subprocess.TimeoutExpired("native-helper", timeout)
            return self.returncode

    def stop_native(process, *, timeout):
        clock[0] += timeout
        if confirmed:
            process.returncode = 0
        return confirmed

    monkeypatch.setattr(execution, "stop_native_process", stop_native)
    monkeypatch.setattr(execution, "kill_process_tree", _reject_direct_spawn)
    runner = execution.ProcessRunner()
    children = [NativeChild() for _ in range(2 if entry == "all" else 1)]
    for index, child in enumerate(children):
        key = f"native-{index}"
        runner._procs[key] = child
        runner._register_global(key, child)

    if entry == "single":
        assert runner.force_stop("native-0", timeout=0.2) is confirmed
    else:
        assert runner.force_all_tracked(timeout=0.2) is True

    assert clock[0] == pytest.approx(0.2)
    assert execution.ProcessRunner.tracked_active_count() == (0 if confirmed else len(children))
    if not confirmed:
        assert runner.active_keys == [f"native-{index}" for index in range(len(children))]
