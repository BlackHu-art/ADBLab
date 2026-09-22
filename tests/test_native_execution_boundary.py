"""应用各执行入口必须共用原生工具隔离边界。"""

from __future__ import annotations

import io
import subprocess
from types import SimpleNamespace

import pytest

import core.adb_runtime as runtime_module
import core.exec as execution
import main
from core.adb_transport import ExecutionResult
from services.remote import ScrcpyService
from services.remote.types import ScrcpyLaunchPlan


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


class _FinishedNativeChild:
    """提供已退出进程和可关闭管道，避免边界测试创建真实工具或遗留跟踪。"""

    returncode = 0

    def __init__(self, output=b""):
        self.stdin = None
        self.stdout = io.BytesIO(output)
        self.stderr = io.BytesIO()
        self.output = output

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def communicate(self, **_kwargs):
        return self.output, b""


@pytest.mark.parametrize("entry", ["version", "encoder"])
@pytest.mark.parametrize("cancellable", [False, True])
def test_custom_scrcpy_commands_request_native_isolation(
    monkeypatch, tmp_path, entry, cancellable,
):
    tool = str(tmp_path / "custom mirror tool")
    monkeypatch.setenv("SCRCPY_PATH", tool)
    monkeypatch.setattr(execution, "_adb_runtime", None)
    monkeypatch.setattr(execution, "_adb_path", None)
    observed = []
    output = "scrcpy 4.1" if entry == "version" else "OMX.test.encoder h264 encoder"

    def run(command, **kwargs):
        observed.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, output, "")

    def popen(command, **kwargs):
        observed.append((command, kwargs))
        return _FinishedNativeChild(output.encode())

    monkeypatch.setattr(execution, "run_native", run)
    monkeypatch.setattr(runtime_module, "popen_native", popen)
    service = ScrcpyService()
    cancelled = (lambda: False) if cancellable else None
    if entry == "version":
        assert service.version(service.resolve_executable(), cancelled=cancelled) == "4.1"
        expected = [tool, "--version"]
    else:
        assert service.detect_encoder(tool, "fixture", cancelled=cancelled) == "OMX.test.encoder"
        expected = [tool, "-s", "fixture", "shell", "dumpsys media.codec"]
    assert len(observed) == 1
    assert observed[0][0] == expected
    assert observed[0][1]["isolate"] is True


@pytest.mark.parametrize("entry", ["legacy", "plan"])
def test_custom_scrcpy_processes_request_native_isolation(monkeypatch, tmp_path, entry):
    tool = str(tmp_path / "custom mirror tool")
    monkeypatch.setenv("SCRCPY_PATH", tool)
    monkeypatch.setattr(execution, "_adb_path", None)
    observed = []
    child = _FinishedNativeChild()

    def popen(command, **kwargs):
        observed.append((command, kwargs))
        return child

    monkeypatch.setattr(execution, "popen_native", popen)
    service = ScrcpyService()
    command = [service.resolve_executable(), "--port=27183"]
    try:
        if entry == "plan":
            process = service.start_plan("fixture", ScrcpyLaunchPlan(
                args=command, device_info="", version="4.1", env={"ADB": "chosen-adb"},
            ))
        else:
            process = service.start("fixture", command)
        assert process is child
        assert len(observed) == 1
        assert observed[0][0] == command
        assert observed[0][1]["isolate"] is True
    finally:
        service.stop("fixture")
        child.stdout.close()
        child.stderr.close()


def test_scrcpy_preflight_keeps_fast_adb_route_with_native_tool_marker(monkeypatch, tmp_path):
    command = [str(tmp_path / "chosen-adb"), "-s", "fixture", "shell", "echo ok"]
    calls = []

    def try_run(resolved, _timeout, _cancelled):
        calls.append(resolved)
        return ExecutionResult(stdout=b"ok", returncode=0)

    runtime = SimpleNamespace(try_run=try_run, can_shell_fast=lambda *_args: True)
    monkeypatch.setattr(execution, "_adb_runtime", runtime)
    monkeypatch.setattr(execution, "run_native", _reject_direct_spawn)
    assert ScrcpyService().preflight_check(command[0], "fixture").success
    assert calls == [command]


@pytest.mark.parametrize("entry", ["run", "spawn", "start"])
def test_application_worker_retains_default_nonisolated_execution(monkeypatch, tmp_path, entry):
    command = [str(tmp_path / "ADBLab"), "--mobileperf-worker", "--config", "fixture.json"]
    monkeypatch.setattr(execution, "_adb_path", None)
    monkeypatch.setattr(execution, "_adb_runtime", None)
    observed = []
    child = _FinishedNativeChild()

    def run(cmd, **kwargs):
        observed.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "ready", "")

    def popen(cmd, **kwargs):
        observed.append((cmd, kwargs))
        return child

    monkeypatch.setattr(execution, "run_native", run)
    monkeypatch.setattr(execution, "popen_native", popen)
    runner = execution.ProcessRunner()
    try:
        if entry == "run":
            assert execution.CommandRunner.run(command).success
        elif entry == "spawn":
            assert runner.spawn(command) is child
        else:
            assert runner.start("fixture", command) is child
        assert len(observed) == 1
        assert observed[0][0] == command
        assert observed[0][1]["isolate"] is False
    finally:
        runner.stop("fixture")
        child.stdout.close()
        child.stderr.close()


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
