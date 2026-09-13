"""Selected missing clients must fail before process or output side effects."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import exec as execution
from utils import adb_resolver


@pytest.fixture
def missing_client(monkeypatch):
    execution.reset_adb_program_cache()
    monkeypatch.setattr(adb_resolver, "resolve_adb_path", lambda: None)
    monkeypatch.setattr(adb_resolver, "adb_path", lambda: "adb")
    yield
    execution.reset_adb_program_cache()


def test_missing_client_short_command_cannot_fall_back_to_path(missing_client, monkeypatch):
    spawn = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(execution.subprocess, "run", spawn)
    result = execution.CommandRunner.run(["adb", "devices"])
    assert not result.success
    assert "ADB" in result.error
    spawn.assert_not_called()
    assert execution.CommandRunner.active_count() == 0


def test_missing_client_does_not_truncate_existing_output(missing_client, monkeypatch, tmp_path):
    target = tmp_path / "existing.png"
    target.write_bytes(b"previous image")
    spawn = Mock(return_value=SimpleNamespace(returncode=0, stderr=b""))
    monkeypatch.setattr(execution.subprocess, "run", spawn)
    result = execution.CommandRunner.run_to_file(
        ["adb", "exec-out", "screencap", "-p"], str(target),
    )
    assert not result.success
    assert target.read_bytes() == b"previous image"
    spawn.assert_not_called()
    assert execution.CommandRunner.active_count() == 0


def test_invalid_replacement_keeps_old_key_process(missing_client, monkeypatch):
    runner = execution.ProcessRunner()
    previous = object()
    runner._procs["mirror"] = previous
    stop = Mock(side_effect=lambda key: runner._procs.pop(key, None))
    monkeypatch.setattr(runner, "stop", stop)
    spawn = Mock()
    monkeypatch.setattr(runner, "spawn", spawn)
    with pytest.raises(FileNotFoundError, match="ADB"):
        runner.start("mirror", ["adb", "shell"])
    assert runner._procs["mirror"] is previous
    stop.assert_not_called()
    spawn.assert_not_called()


def test_missing_resolution_is_cached_until_explicit_reset(monkeypatch):
    execution.reset_adb_program_cache()
    resolver = Mock(return_value=None)
    monkeypatch.setattr(adb_resolver, "resolve_adb_path", resolver)
    assert execution.resolve_adb_program() is None
    assert execution.resolve_adb_program() is None
    assert resolver.call_count == 1
    execution.reset_adb_program_cache()

def test_bridge_missing_client_is_lazy_and_never_warms(missing_client, monkeypatch):
    from core.adb_bridge import ADBBridge
    bridge = ADBBridge()
    spawn = Mock()
    monkeypatch.setattr(bridge._process_runner, "start", spawn)
    assert bridge.warm_input_session("device") is False
    assert bridge.shell_input("keyevent 3", "device") is False
    assert not bridge.shell("echo ok", "device").success
    assert bridge._input_sessions == {}
    spawn.assert_not_called()


def test_bridge_replaces_input_session_when_selected_path_changes(monkeypatch):
    from core import adb_bridge
    selected = ["C:/first/adb.exe"]
    monkeypatch.setattr(adb_bridge, "adb_path", lambda: selected[0])
    bridge = adb_bridge.ADBBridge()
    first = bridge._input_session("device")
    closed = Mock()
    monkeypatch.setattr(first, "close", closed)
    selected[0] = "C:/second/adb.exe"
    second = bridge._input_session("device")
    assert second is not first
    assert second.adb == selected[0]
    closed.assert_called_once()

@pytest.mark.ui
def test_remote_client_invalidation_queues_cleanup_without_blocking_gui(monkeypatch):
    from core.adb_bridge import ADBBridge
    from gui.panels.remote_panel import RemotePanel
    bridge = ADBBridge("C:/test/adb.exe")
    previous = bridge._input_session("device")
    closed = Mock()
    monkeypatch.setattr(previous, "close", closed)
    queued = []
    future = object()
    executor = SimpleNamespace(submit=lambda action: queued.append(action) or future)
    tracked = []
    import threading
    frame = SimpleNamespace(
        _adb=bridge, _closing=False, _remote_input_closing=False,
        _remote_executor=executor, _shutdown_lifecycle_lock=lambda: threading.Lock(),
        _track_remote_future=tracked.append, _log=Mock(),
    )
    RemotePanel.invalidate_adb_input_sessions(frame)
    closed.assert_not_called()
    assert tracked == [future]
    replacement = bridge._input_session("device")
    assert replacement is not previous
    queued[0]()
    closed.assert_called_once()
    assert bridge._input_session("device") is replacement

def test_mobileperf_missing_selected_client_cleans_config_without_start(missing_client, tmp_path):
    from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner
    process_runner = Mock()
    runner = MobilePerfRunner(process_runner=process_runner, project_root=tmp_path)
    with pytest.raises(FileNotFoundError, match="ADB"):
        runner.start(MobilePerfRunConfig(package="com.example.app"))
    process_runner.start.assert_not_called()
    assert runner._config_dir is None
    assert runner._config_path == ""


def test_scrcpy_missing_adb_fails_before_preflight_or_session(tmp_path):
    from services.remote.scrcpy_service import ScrcpyService
    from services.remote.types import ScrcpyConfig
    command_runner = Mock()
    service = ScrcpyService(command_runner=command_runner)
    config = ScrcpyConfig(
        exe="scrcpy", adb=str(tmp_path / "missing-adb.exe"), device="device",
        maxsize="1080p", fps="60", bitrate="12", codec="h264", buffer="50", orientation="0",
    )
    with pytest.raises(FileNotFoundError, match="ADB"):
        service.build_launch_plan(config)
    command_runner.run.assert_not_called()
    assert not service._bridge_sessions


def test_mobileperf_report_reuses_result_directory_and_filters_empty_reports(tmp_path, monkeypatch):
    from services.mobileperf_runner import MobilePerfRunner
    runner = MobilePerfRunner(project_root=tmp_path)
    folder = tmp_path / "finished"
    folder.mkdir()
    report = folder / "summary_valid.xlsx"
    report.write_bytes(b"report")
    (folder / "summary_empty.xlsx").touch()
    scan = Mock(side_effect=AssertionError("directory must not be enumerated twice"))
    monkeypatch.setattr(runner, "latest_result_dir", scan)
    assert runner.latest_report_file(result_dir=str(folder)) == str(report)
    assert runner.latest_report_file(result_dir="") == ""
    scan.assert_not_called()

@pytest.mark.ui
@pytest.mark.parametrize("directory", ["result-dir", "", OSError("temporarily unavailable")])
def test_legacy_performance_finish_reuses_discovery_but_retries_after_oserror(
    directory, monkeypatch,
):
    from gui.features.performance import PerformancePage
    from tests.test_performance_library import _Runner

    page = PerformancePage(device_ip="device-1")
    # 注入旧同步契约仍受支持；真实 runner 的后台单次发现由结果任务回归覆盖。
    page._runner = _Runner()
    try:
        page._runner_finished_handled = False
        page._runner.latest_result_dir = Mock(
            side_effect=directory if isinstance(directory, OSError) else None,
            return_value=directory,
        )
        report = Mock(return_value="")
        page._runner.latest_report_file = report
        page._mark_runner_finished()
        if isinstance(directory, OSError):
            report.assert_called_once_with()
        elif directory:
            report.assert_called_once_with(result_dir=directory)
        else:
            report.assert_not_called()
    finally:
        page.close()


def test_cached_client_removed_after_resolution_cannot_use_fast_backend(tmp_path, monkeypatch):
    selected = tmp_path / "adb.exe"
    selected.touch()
    execution.reset_adb_program_cache()
    monkeypatch.setattr(adb_resolver, "resolve_adb_path", lambda: str(selected))
    assert execution.resolve_adb_program() == str(selected)
    selected.unlink()
    runtime = Mock()
    monkeypatch.setattr(execution, "_adb_runtime", runtime)
    result = execution.CommandRunner.run(["adb", "shell", "echo ok"])
    assert not result.success
    runtime.try_run.assert_not_called()
    execution.reset_adb_program_cache()

def test_scrcpy_config_rejects_missing_client_before_reading_launch_options():
    from gui.panels.remote_panel_scrcpy import RemotePanelScrcpy
    frame = SimpleNamespace(_adb=SimpleNamespace(path=None))
    with pytest.raises(FileNotFoundError, match="ADB"):
        RemotePanelScrcpy(frame)._scrcpy_config("scrcpy", "device")

def test_retired_input_session_cannot_restart_from_late_send(monkeypatch):
    from core.adb_bridge import ADBBridge
    bridge = ADBBridge("C:/old/adb.exe")
    session = bridge._input_session("device")
    process = SimpleNamespace(stdin=Mock(), poll=lambda: None)
    start = Mock(return_value=process)
    stop = Mock()
    monkeypatch.setattr(bridge._process_runner, "start", start)
    monkeypatch.setattr(bridge._process_runner, "stop", stop)
    assert session.warm()
    bridge.detach_input_sessions()
    bridge.close_retired_input_sessions()
    assert session.send("keyevent 3") is False
    assert session.warm() is False
    assert start.call_count == 1
    stop.assert_called_once()

@pytest.mark.parametrize("entry", ["file", "process"])
def test_explicit_missing_adb_has_no_output_or_replacement_side_effect(
    tmp_path, monkeypatch, entry,
):
    cmd = [str(tmp_path / "adb.exe"), "shell", "echo ok"]
    if entry == "file":
        target = tmp_path / "output"
        target.write_bytes(b"old output")
        monkeypatch.setattr(execution.subprocess, "run", Mock(side_effect=FileNotFoundError("ADB")))
        result = execution.CommandRunner.run_to_file(cmd, str(target))
        assert not result.success
        assert target.read_bytes() == b"old output"
    else:
        runner = execution.ProcessRunner()
        stop = Mock()
        monkeypatch.setattr(runner, "stop", stop)
        monkeypatch.setattr(runner, "spawn", Mock(side_effect=FileNotFoundError("ADB")))
        with pytest.raises(FileNotFoundError):
            runner.start("old-key", cmd)
        stop.assert_not_called()
