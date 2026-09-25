"""命令结果的程序状态独立于诊断文本，并兼容现有构造入口。"""

import subprocess
from types import SimpleNamespace

import pytest

from core import exec as execution
from core.adb_transport import ExecutionResult


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (ExecutionResult(stdout=b"ok"), "succeeded"),
        (ExecutionResult(stderr=b"rejected", returncode=1), "failed"),
        (ExecutionResult(kind="timeout"), "timed_out"),
        (ExecutionResult(kind="cancelled"), "cancelled"),
        (ExecutionResult(kind="stale"), "stale"),
        (ExecutionResult(kind="unavailable"), "failed"),
    ],
)
def test_backend_outcome_survives_diagnostic_text_change(monkeypatch, raw, expected):
    monkeypatch.setattr(execution, "resolve_command", lambda command: command)
    monkeypatch.setattr(
        execution, "_adb_runtime", SimpleNamespace(try_run=lambda *_args: raw),
    )
    result = execution.CommandRunner.run(["test-command"])
    result.error = "本地化或追加后的诊断说明"
    assert result.outcome == expected
    assert result.cancelled is (expected == "cancelled")
    assert result.timed_out is (expected == "timed_out")
    assert result.success is (expected == "succeeded")
    assert result.stale is (expected == "stale")


@pytest.mark.parametrize("to_file", [False, True])
def test_native_timeout_has_explicit_outcome(monkeypatch, tmp_path, to_file):
    monkeypatch.setattr(execution, "resolve_command", lambda command: command)
    monkeypatch.setattr(execution, "_adb_runtime", None)

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("test-command", 1)

    monkeypatch.setattr(execution, "run_native", timeout)
    result = (
        execution.CommandRunner.run_to_file(["test-command"], str(tmp_path / "output"))
        if to_file else execution.CommandRunner.run(["test-command"])
    )
    result.error = "执行超过预算"
    assert result.outcome == "timed_out"
    assert result.timed_out
    assert not result.cancelled


def test_cancelled_file_command_never_creates_output(monkeypatch, tmp_path):
    monkeypatch.setattr(execution, "resolve_command", lambda command: command)
    target = tmp_path / "output"
    result = execution.CommandRunner.run_to_file(
        ["test-command"], str(target), cancelled=lambda: True,
    )
    assert result.outcome == "cancelled"
    assert result.cancelled
    assert not target.exists()


def test_explicit_failure_text_does_not_change_outcome():
    result = execution.CommandResult(
        success=False, error="remote operation timed out", outcome="failed",
    )
    assert not result.timed_out
    assert not result.cancelled


def test_legacy_result_construction_keeps_cancellation_compatibility():
    result = execution.CommandResult(False, "", "Cancelled")
    assert result.outcome == "cancelled"
    result.error = "已取消"
    assert result.cancelled


def test_successful_command_text_is_never_classified_as_a_timeout():
    result = execution.CommandResult(True, "ok", "timed out in previous run")
    assert result.outcome == "succeeded"
    assert not result.timed_out


@pytest.mark.parametrize("option", ["input_bytes", "env", "command_scope"])
def test_native_options_cannot_be_consumed_by_fast_backend(monkeypatch, option):
    from core import native_process

    value = {
        "input_bytes": b"", "env": {},
        "command_scope": getattr(native_process, "NativeCommandScope", lambda: object())(),
    }[option]
    monkeypatch.setattr(execution, "resolve_command", lambda command: command)

    def forbidden(*_args, **_kwargs):
        pytest.fail("显式原生命令选项不能走快速通道或同步 run")

    monkeypatch.setattr(execution, "_adb_runtime", SimpleNamespace(try_run=forbidden))
    monkeypatch.setattr(execution, "run_native", forbidden)
    observed = []

    def capture(command, timeout, cancelled, **kwargs):
        observed.append((command, timeout, cancelled(), kwargs))
        return ExecutionResult(stdout=b"native result")

    monkeypatch.setattr(execution, "native_capture", capture)
    result = execution.CommandRunner.run(["test-command"], **{option: value})

    assert result.success and result.output == "native result"
    assert observed[0][0] == ["test-command"]
    assert 0 < observed[0][1] <= 30
    assert observed[0][2] is False
    assert observed[0][3][option] == value


@pytest.mark.parametrize(
    "options", [{"input_bytes": b""}, {"env": {}}, {"command_scope": object()}],
)
def test_native_options_reject_shell_before_spawning(monkeypatch, options):
    def forbidden(*_args, **_kwargs):
        pytest.fail("shell 与原生选项冲突时不能启动进程")

    monkeypatch.setattr(execution, "resolve_command", forbidden)
    result = execution.CommandRunner.run(["test-command"], shell=True, **options)
    assert result.outcome == "failed"
    assert "shell" in result.error
