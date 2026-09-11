"""ADB 诊断复用现有开发控制台，不增加启动参数、文件或日志服务实例。"""

import io
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from core.log_service import LogService
from utils import adb_debug


@pytest.fixture
def console(monkeypatch, capsys):
    monkeypatch.delattr(sys, "frozen", raising=False)

    class Console:
        output = ""

        def getvalue(self):
            self.output += capsys.readouterr().out
            return self.output

    return Console()


def records(console):
    return [
        json.loads(line.split("[ADB] ", 1)[1])
        for line in console.getvalue().splitlines() if "[ADB] {" in line
    ]


def test_source_outputs_without_configuration_through_existing_console(console):
    executable = r"D:\Downloads\_internal\scrcpy-win64\adb.exe"
    with patch.object(
        LogService, "write_developer_console", wraps=LogService.write_developer_console,
    ) as writer, patch.object(LogService, "__new__", side_effect=AssertionError("new service")):
        adb_debug.event("resolve_result", selected_adb=executable)
    writer.assert_called_once()
    assert writer.call_args.args[0] == "DEBUG"
    assert "[DEBUG] [MainThread] [ADB] " in console.getvalue()
    assert records(console) == [{"event": "resolve_result", "selected_adb": executable}]


@pytest.mark.parametrize("frozen,has_stdout", [(False, True), (True, True), (False, False)])
def test_console_policy_never_creates_diagnostic_files(
    console, monkeypatch, tmp_path, frozen, has_stdout,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user-data"))
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    if not has_stdout:
        monkeypatch.setattr(sys, "stdout", None)
    adb_debug.event("probe", status="ready")
    assert bool(records(console)) is (not frozen and has_stdout)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("arguments, category", [
    (["-s", "SERIAL_SECRET", "shell", "echo TOKEN_SECRET"], "shell"),
    (["-s", "SERIAL_SECRET", "exec-out", "cat /private/secret"], "exec-out"),
    (["-H", "HOST_SECRET", "-P", "PORT_SECRET", "devices", "-l"], "devices"),
    (["connect", "HOST_SECRET"], "connect"),
    (["TOKEN_SECRET"], "other"),
    (["--TOKEN_SECRET", "devices"], "other"),
    (["-s", "SERIAL_SECRET"], "other"),
])
def test_command_preserves_executable_but_never_raw_arguments(console, arguments, category):
    executable = r"D:\Downloads\中文目录\_internal\scrcpy-win64\adb.exe"
    adb_debug.command([executable, *arguments], backend="native_client")
    record = records(console)[-1]
    assert record["event"] == "execute"
    assert record["executable"] == executable
    assert record["command"] == category
    for sensitive in (
        "SERIAL_SECRET", "TOKEN_SECRET", "HOST_SECRET", "PORT_SECRET", "/private/secret",
    ):
        assert sensitive not in console.getvalue()


def test_non_adb_command_is_not_recorded(console):
    adb_debug.command(["scrcpy.exe", "--serial", "SECRET"], backend="native_client")
    assert console.getvalue() == ""


def test_source_diagnostic_uses_stdout_when_stderr_is_missing(console, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    adb_debug.event("probe", status="ready")
    assert records(console) == [{"event": "probe", "status": "ready"}]


def test_concurrent_events_remain_complete_json_lines(console):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: adb_debug.event("probe", sequence=index), range(80)))
    assert sorted(record["sequence"] for record in records(console)) == list(range(80))


def test_closed_stdout_does_not_break_diagnostics(monkeypatch):
    stream = io.StringIO()
    stream.close()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.delattr(sys, "frozen", raising=False)
    adb_debug.event("probe", status="ready")


def test_source_cli_diagnostic_does_not_import_qt():
    script = """
import sys
from utils import adb_debug
adb_debug.event('probe', status='ready')
adb_debug.command(['adb.exe', 'devices'], backend='native_client')
assert 'core.log_service' not in sys.modules
assert not any(name.startswith('PySide6') for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("source,label", [
    ("bundled", "应用自带"), ("runtime_cache", "应用工具缓存"), ("PATH", "系统 PATH"),
])
def test_selected_client_is_announced_at_info_with_readable_path(source, label):
    executable = r"D:\Downloads\中文目录\_internal\scrcpy-win64\adb.exe"
    with patch.object(LogService, "write_developer_console") as writer:
        adb_debug.event("resolve_result", selected_adb=executable, source=source, cached=False)
        adb_debug.event("resolve_result", selected_adb=executable, cached=True)
    summaries = [call for call in writer.call_args_list if call.args[0] == "INFO"]
    assert len(summaries) == 1
    assert writer.call_args_list[0] == summaries[0]
    message = summaries[0].args[1]
    assert "已选择 ADB 客户端" in message
    assert executable in message
    assert label in message
    assert source in message


def test_missing_client_is_warning_without_claiming_selection():
    with patch.object(LogService, "write_developer_console") as writer:
        adb_debug.event("resolve_result", selected_adb=None, source="missing", cached=False)
    assert writer.call_args_list[0].args[0] == "WARNING"
    assert "未找到可用的 ADB" in writer.call_args_list[0].args[1]
    assert all(call.args[0] != "INFO" for call in writer.call_args_list)
