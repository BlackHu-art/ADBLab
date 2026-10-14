"""Bugreport 的长任务预算、产物和关闭语义，不连接真实设备。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.exec import CommandResult
from models.adb_testing import ADBTesting


@pytest.fixture
def report_boundary(monkeypatch):
    model = ADBTesting()
    monkeypatch.setattr("core.exec.resolve_command", lambda command: list(command))
    clock = [100.0]
    monkeypatch.setattr("models.adb_testing.time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []
    streams = []

    def run(command, **kwargs):
        calls.append(command)
        if "getprop" in command:
            return {"success": True, "output": "13"}
        return {"success": False, "error": "Timeout(180s)"}

    monkeypatch.setattr(model, "_run", run)
    convert = Mock()
    monkeypatch.setattr(model, "_convert_bugreport_to_html", convert)

    def spawn(mode="success", elapsed=241, partial=False, error_stream="stderr"):
        class Process:
            returncode = None
            terminated = False

            def poll(self):
                if self.returncode is not None:
                    return self.returncode
                clock[0] = 100.0 + elapsed
                if mode == "cancel":
                    model.begin_shutdown()
                if mode in {"timeout", "cancel"}:
                    return None
                if mode == "success":
                    (self.target / "bugreport-current.txt").write_text("fixture report")
                self.returncode = 1 if mode == "error" else 0
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def wait(self, timeout=None):
                return self.returncode

        process = Process()

        def start(command, **kwargs):
            assert command[:4] == ["adb", "-s", "demo-device", "bugreport"]
            process.target = Path(command[-1])
            streams.extend([kwargs["stdout"], kwargs["stderr"]])
            if partial:
                (process.target / "partial.zip").write_bytes(b"partial")
            if mode == "error":
                kwargs[error_stream].write(b"dumpstate failed")
            return process

        monkeypatch.setattr(model._procs, "spawn", start)
        return process

    yield SimpleNamespace(model=model, spawn=spawn, calls=calls, streams=streams, convert=convert)
    model.shutdown()


def capture(model, root):
    return model.capture_bugreport_async.__wrapped__(model, "demo-device", str(root), 1)


def test_report_taking_four_minutes_completes_in_owned_long_process(report_boundary, tmp_path):
    boundary = report_boundary
    process = boundary.spawn()
    result = capture(boundary.model, tmp_path)
    assert result["success"], result
    directory = Path(result["bugreport_path"])
    assert (directory / "bugreport-current.txt").read_text() == "fixture report"
    assert len(directory.name) <= 64 and "demo-device" not in directory.name
    assert not process.terminated
    assert boundary.model._procs.active_keys == []
    assert all(stream.closed for stream in boundary.streams)


@pytest.mark.parametrize("mode", ["error", "timeout", "cancel", "empty"])
@pytest.mark.parametrize("partial", [False, True])
def test_failed_report_cleans_only_its_empty_directory(report_boundary, tmp_path, mode, partial):
    boundary = report_boundary
    process = boundary.spawn(mode, elapsed=601 if mode == "timeout" else 1, partial=partial)
    historical = tmp_path / "historical"
    historical.mkdir()
    (historical / "saved.txt").write_text("keep")
    result = capture(boundary.model, tmp_path)
    assert not result["success"]
    if mode == "error":
        assert "dumpstate failed" in result["message"]
    elif mode == "timeout":
        assert "Timeout(600s)" in result["message"]
    elif mode == "cancel":
        assert result["cancelled"]
    else:
        assert "No bugreport" in result["message"]
    assert (historical / "saved.txt").read_text() == "keep"
    current = [item for item in tmp_path.iterdir() if item != historical]
    if partial:
        assert len(current) == 1
        assert (current[0] / "partial.zip").read_bytes() == b"partial"
    else:
        assert current == []
    if mode in {"cancel", "timeout"}:
        assert process.terminated
    assert boundary.convert.call_count == 0
    assert boundary.model._procs.active_keys == []
    assert all(stream.closed for stream in boundary.streams)


def test_failed_preflight_does_not_start_report_or_leave_directory(report_boundary, tmp_path):
    boundary = report_boundary
    boundary.spawn()
    boundary.model._run = Mock(return_value={"success": False, "error": "device offline"})
    result = capture(boundary.model, tmp_path)
    assert not result["success"] and "device offline" in result["message"]
    assert len(boundary.model._run.call_args_list) == 1
    assert boundary.streams == []
    assert list(tmp_path.iterdir()) == []


def test_report_preserves_failure_written_to_stdout(report_boundary, tmp_path):
    report_boundary.spawn("error", error_stream="stdout")
    result = capture(report_boundary.model, tmp_path)
    assert not result["success"] and "dumpstate failed" in result["message"]


def test_unconfirmed_client_exit_keeps_tracking_and_its_directory(
    report_boundary, monkeypatch, tmp_path,
):
    boundary = report_boundary
    process = boundary.spawn("timeout", elapsed=601)
    real_stop = boundary.model._procs.stop
    monkeypatch.setattr(boundary.model._procs, "stop", lambda *_args, **_kwargs: None)
    try:
        result = capture(boundary.model, tmp_path)
        assert not result["success"] and "exit was not confirmed" in result["message"]
        assert boundary.model._procs.active_keys
        assert process.target.is_dir(), "未退出的采集客户端仍拥有输出目录"
    finally:
        process.returncode = -15
        for key in tuple(boundary.model._procs._procs):
            real_stop(key, timeout=0)


def test_client_start_failure_closes_streams_and_removes_empty_directory(
    report_boundary, monkeypatch, tmp_path,
):
    boundary = report_boundary
    streams = []

    def fail_start(_command, **kwargs):
        streams.extend([kwargs["stdout"], kwargs["stderr"]])
        raise OSError("cannot start client")

    monkeypatch.setattr(boundary.model._procs, "spawn", fail_start)
    result = capture(boundary.model, tmp_path)
    assert not result["success"] and "cannot start client" in result["message"]
    assert len(streams) == 2 and all(stream.closed for stream in streams)
    assert list(tmp_path.iterdir()) == []


def test_shutdown_during_html_conversion_keeps_raw_report(report_boundary, monkeypatch, tmp_path):
    boundary = report_boundary
    boundary.spawn()
    monkeypatch.setattr(
        boundary.model, "_convert_bugreport_to_html",
        ADBTesting._convert_bugreport_to_html.__get__(boundary.model),
    )
    monkeypatch.setattr("models.adb_testing.shutil.which", lambda _program: "/fixture/java")
    callbacks = []

    def convert(command, **kwargs):
        assert command[0] == "java"
        stop = kwargs.get("cancelled")
        callbacks.append(stop)
        assert callable(stop) and not stop()
        boundary.model.begin_shutdown()
        assert stop()
        return CommandResult(False, error="Cancelled", outcome="cancelled")

    monkeypatch.setattr("models.adb_testing.CommandRunner.run", convert)
    result = capture(boundary.model, tmp_path)
    assert not result["success"] and result["cancelled"]
    assert len(callbacks) == 1
    assert next(tmp_path.glob("*/bugreport-current.txt")).read_text() == "fixture report"
