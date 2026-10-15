"""真实探测和清理调用链的原生资源归属，不启动 ADB 或访问设备。"""

import subprocess
import threading

import pytest

from core import adb_runtime
from core.adb_transport import ExecutionResult
from tests.test_native_command_scope import ControlledProcess

LISTING = b"List of devices attached\nsession-device\tdevice transport_id:1\n"


@pytest.mark.parametrize("stage", ["bootstrap", "devices", "shell"])
def test_probe_native_residual_outlives_probe_thread_until_runtime_wait_confirms_exit(
    monkeypatch, tmp_path, stage,
):
    for key in (
        "ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT",
        "ANDROID_SERIAL",
    ):
        monkeypatch.delenv(key, raising=False)
    path = str(tmp_path / "synthetic-client")
    runtime = adb_runtime.AdbRuntime(lambda: path, probe_serial="session-device")
    residual = ControlledProcess()
    residual.exit_on_kill = False
    entered = threading.Event()
    commands = []
    expected = {
        "bootstrap": [path, "start-server"],
        "devices": [path, "devices", "-l"],
        "shell": [path, "-s", "session-device", "shell", runtime.PROBE_COMMAND],
    }[stage]

    def capture(command, _args, *, cancelled, **_kwargs):
        if cancelled():
            return ExecutionResult(kind="cancelled")
        if stage == "bootstrap":
            return ExecutionResult(kind="unavailable")
        if command == "devices":
            return ExecutionResult(LISTING)
        return ExecutionResult(b"ADBLAB_OUT", b"ADBLAB_ERR", 7)

    def spawn(command, **_kwargs):
        commands.append(command)
        if command == expected:
            runtime.prepare_shutdown()
            entered.set()
            return residual
        assert stage == "shell" and command == [path, "devices", "-l"]
        process = ControlledProcess()

        def complete(**_kwargs):
            process.returncode = 0
            return LISTING, b""

        process.communicate = complete
        return process

    monkeypatch.setattr(adb_runtime, "capture", capture)
    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    try:
        assert runtime.start()
        assert entered.wait(2)
        runtime._thread.join(2)
        assert not runtime._thread.is_alive()
        assert residual.poll() is None
        assert runtime.is_running()
        assert not runtime.wait(0.01)
        assert commands[-1] == expected
        assert len(commands) == (2 if stage == "shell" else 1)
        residual.exit_on_kill = True
        assert runtime.wait(0.5)
        assert residual.poll() is not None
        assert not runtime.is_running()
    finally:
        residual.returncode = -9
        runtime.close()
        assert runtime.wait(1)
        assert adb_runtime.wait_for_native_cleanup(0.1)


def test_native_cleanup_after_prepare_can_run_and_is_cancelled_by_final_close(monkeypatch):
    runtime = adb_runtime.AdbRuntime(lambda: None)
    completed = ControlledProcess()
    pending = ControlledProcess()
    entered = threading.Event()
    release = threading.Event()
    results = []
    commands = []

    def communicate(timeout=None):
        if pending.poll() is not None:
            return b"", b""
        entered.set()
        assert release.wait(2)
        raise subprocess.TimeoutExpired("synthetic-cleanup", timeout)

    pending.communicate = communicate

    def spawn(command, **_kwargs):
        commands.append(command)
        return completed if command == ["completed-cleanup"] else pending

    monkeypatch.setattr(adb_runtime, "popen_native", spawn)
    worker = threading.Thread(target=lambda: results.append(
        runtime.run_native(["pending-cleanup"], 5),
    ))
    try:
        runtime.prepare_shutdown()
        first = runtime.run_native(["completed-cleanup"], 1)
        assert first.kind == "completed" and first.stdout == b"done"
        worker.start()
        assert entered.wait(1)
        runtime.close()
        assert runtime.is_running()
        assert not runtime.wait(0)
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert len(results) == 1 and results[0].kind == "cancelled"
        assert pending.poll() is not None
        assert runtime.wait(0.1)
        assert runtime.run_native(["rejected-cleanup"], 1).kind == "cancelled"
        assert commands == [["completed-cleanup"], ["pending-cleanup"]]
    finally:
        runtime.close()
        release.set()
        if worker.ident is not None:
            worker.join(2)
        pending.returncode = -9
        assert runtime.wait(1)
