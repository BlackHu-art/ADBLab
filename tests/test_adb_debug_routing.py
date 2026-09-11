"""核对调试日志记录真实的客户端解析与执行路径，不启动 ADB 或访问设备。"""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from core import adb_runtime
from core import exec as execution
from core.adb_transport import ExecutionResult
from core.log_service import LogService
from utils import adb_debug, adb_resolver


@pytest.fixture
def debug_log(monkeypatch, capsys):
    monkeypatch.delattr(sys, "frozen", raising=False)
    for name in (
        "ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT",
    ):
        monkeypatch.delenv(name, raising=False)
    rows = []

    def records():
        rows.extend(
            json.loads(line.split("[ADB] ", 1)[1])
            for line in capsys.readouterr().out.splitlines() if "[ADB] {" in line
        )
        return rows

    return records


@pytest.mark.parametrize("bundled_exists", [True, False])
def test_frozen_resolver_logs_internal_candidate_and_actual_source(
    debug_log, tmp_path, monkeypatch, bundled_exists,
):
    package = tmp_path / "package"
    candidate = package / "_internal" / "scrcpy-win64" / "adb.exe"
    candidate.parent.mkdir(parents=True)
    if bundled_exists:
        candidate.write_bytes(b"synthetic")
    fallback = str(tmp_path / "system" / "adb.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(package / "_internal"), raising=False)
    monkeypatch.setattr(sys, "executable", str(package / "ADBLab.exe"))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(adb_resolver, "_resolved", False)
    monkeypatch.setattr(adb_resolver, "_adb_path", None)
    monkeypatch.setattr(adb_resolver.shutil, "which", lambda _name: fallback)
    # 此处只验证打包路径解析的诊断字段，冻结模式的控制台策略由独立测试覆盖。
    monkeypatch.setattr(adb_debug, "enabled", lambda: True)
    console = sys.stdout
    monkeypatch.setattr(
        LogService, "write_developer_console",
        lambda _level, message: console.write(message + "\n"),
    )

    actual = adb_resolver.resolve_adb_path()

    assert actual == (str(candidate) if bundled_exists else fallback)
    records = debug_log()
    probe = next(row for row in records if row["event"] == "resolve_candidate")
    assert probe["candidate"] == str(candidate)
    assert probe["exists"] is bundled_exists
    selected = next(row for row in records if row["event"] == "resolve_result")
    assert selected["selected_adb"] == actual
    assert selected["source"] == ("bundled" if bundled_exists else "PATH")


@pytest.mark.parametrize("entry", ["short", "cancellable", "process", "file"])
def test_native_entries_log_resolved_client_without_command_values(
    debug_log, monkeypatch, tmp_path, entry,
):
    executable = str(tmp_path / "_internal" / "scrcpy-win64" / "adb.exe")
    monkeypatch.setattr(execution, "_adb_path", executable)
    monkeypatch.setattr(execution, "_adb_runtime", None)
    monkeypatch.setattr(execution, "_log_if_slow", lambda *_: None)
    calls = []

    class Process:
        returncode = 0

        def __init__(self, cmd, **_kwargs):
            calls.append(cmd)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def communicate(self, **_kwargs):
            return b"", b""

        def poll(self):
            return 0

    def run(cmd, **_kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", Process)
    monkeypatch.setattr(subprocess, "run", run)
    cmd = ["adb", "-s", "synthetic-private-device", "shell", "echo secret=hidden-value"]
    if entry == "short":
        assert execution.CommandRunner.run(cmd).success
    elif entry == "cancellable":
        assert execution.CommandRunner.run(cmd, cancelled=lambda: False).success
    elif entry == "file":
        assert execution.CommandRunner.run_to_file(cmd, str(tmp_path / "output")).success
    else:
        execution.ProcessRunner().spawn(cmd)

    assert calls[0][0] == executable
    rows = [row for row in debug_log() if row["event"] == "execute"]
    assert rows and rows[0]["backend"] == "native_client"
    assert rows[0]["executable"] == executable
    assert rows[0]["command"] == "shell"
    assert "synthetic-private-device" not in str(rows)
    assert "hidden-value" not in str(rows)


def test_fast_entry_logs_direct_backend_and_does_not_launch_client(debug_log, monkeypatch):
    runtime = adb_runtime.AdbRuntime(lambda: "C:/bundle/adb.exe")
    runtime._path = "C:/bundle/adb.exe"
    runtime._host.available = True
    monkeypatch.setattr(runtime, "request_device_check", lambda: None)
    monkeypatch.setattr(
        adb_runtime, "capture",
        lambda *_args, **_kwargs: ExecutionResult(b"List of devices attached\n"),
    )
    try:
        result = runtime.try_run(["C:/bundle/adb.exe", "devices"], 1)
        assert result is not None and result.kind == "completed"
        rows = [row for row in debug_log() if row["event"] == "execute"]
        assert rows and all(row["backend"] == "server_direct" for row in rows)
        assert rows[0]["client_spawned"] is False
        assert rows[0]["endpoint"] == "127.0.0.1:5037"
    finally:
        runtime.close()


def test_probe_logs_selected_client_endpoint_and_timeout(debug_log, monkeypatch):
    runtime = adb_runtime.AdbRuntime(lambda: "C:/bundle/adb.exe")
    monkeypatch.setattr(
        adb_runtime, "capture", lambda *_args, **_kwargs: ExecutionResult(kind="timeout"),
    )
    runtime._probe_once()
    rows = debug_log()
    start = next(row for row in rows if row["event"] == "probe_start")
    assert start["selected_adb"] == "C:/bundle/adb.exe"
    assert start["endpoint"] == "127.0.0.1:5037"
    results = [row for row in rows if row["event"] == "probe_result"]
    assert results and results[-1]["status"] == "timeout"
    assert runtime.snapshot().status == "host_timeout"


def test_switch_logs_policy_without_claiming_capability_success(debug_log):
    runtime = adb_runtime.AdbRuntime(lambda: None)
    runtime.set_native_only(True)
    rows = [row for row in debug_log() if row["event"] == "mode"]
    assert rows[-1]["selection_mode"] == "native"
    assert rows[-1]["host_available"] is False
    runtime.close()
