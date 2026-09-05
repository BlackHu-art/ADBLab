# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import subprocess
import threading
import warnings
from unittest.mock import Mock, patch

import pytest

from core.exec import ProcessRunner
from gui.dialogs.lifecycle import safe_disconnect
from services.remote import ScrcpyConfig, build_scrcpy_args


def test_scrcpy_launch_args_include_selected_ui_options():
    cfg = {
        "exe": "scrcpy.exe",
        "device": "device-1",
        "maxsize": "1080p",
        "fps": "60",
        "bitrate": "12",
        "codec": "h265",
        "buffer": "50",
        "orientation": "90",
        "fullscreen": True,
        "always_on_top": True,
        "no_audio": True,
        "show_touches": True,
        "stay_awake": True,
        "turn_screen_off": True,
        "record_path": "C:/tmp/out.mp4",
        "no_window": True,
    }

    args = build_scrcpy_args(ScrcpyConfig.from_mapping(cfg), "OMX.test.encoder")

    assert args[:3] == ["scrcpy.exe", "-s", "device-1"]
    assert ["-m", "1080"] == args[3:5]
    assert "--video-codec" in args
    assert "h265" in args
    assert "--video-encoder" in args
    assert "OMX.test.encoder" in args
    assert "--record" in args
    assert "C:/tmp/out.mp4" in args
    assert "--no-playback" in args
    assert "--no-window" in args
    assert "--capture-orientation=@90" in args
    assert args[-1] == "--print-fps"


def test_scrcpy_launch_args_omit_defaults():
    cfg = {
        "exe": "scrcpy.exe",
        "device": "device-1",
        "maxsize": "Default",
        "fps": "30",
        "bitrate": "8",
        "codec": "h264",
        "buffer": "0",
        "orientation": "0",
        "fullscreen": False,
        "always_on_top": False,
        "no_audio": False,
        "show_touches": False,
        "stay_awake": False,
        "turn_screen_off": False,
        "record_path": "",
        "no_window": False,
    }

    args = build_scrcpy_args(ScrcpyConfig.from_mapping(cfg), None)

    assert "-m" not in args
    assert "--video-codec" not in args
    assert "--video-encoder" not in args
    assert "--video-buffer=0" not in args
    assert not any(arg.startswith("--capture-orientation") for arg in args)
    assert "--record" not in args
    assert "--no-window" not in args
    assert args[-1] == "--print-fps"


def test_safe_disconnect_ignores_already_disconnected_signals():
    class AlreadyDisconnectedSignal:
        def disconnect(self, _handler=None):
            raise RuntimeError("already disconnected")

    safe_disconnect(AlreadyDisconnectedSignal(), Mock())


def test_safe_disconnect_ignores_generic_signal_missing_handler():
    class AlreadyDisconnectedSignal:
        def disconnect(self, _handler=None):
            raise ValueError("handler is not connected")

    safe_disconnect(AlreadyDisconnectedSignal(), Mock())


def test_safe_disconnect_suppresses_pyside_disconnect_warnings():
    class WarningSignal:
        def disconnect(self, _handler=None):
            warnings.warn("Failed to disconnect from signal", RuntimeWarning)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        safe_disconnect(WarningSignal(), Mock())

    assert caught == []


def test_process_runner_start_replaces_existing_process_without_deadlock():
    ProcessRunner._global_procs.clear()
    runner = ProcessRunner()
    old_proc = Mock()
    old_proc.poll.return_value = None
    old_proc.wait.return_value = 0
    new_proc = Mock()

    runner._procs["device_logcat"] = old_proc

    started = []

    def start_process():
        with patch("core.exec.subprocess.Popen", return_value=new_proc):
            started.append(runner.start("device_logcat", ["adb", "logcat"]))

    thread = threading.Thread(target=start_process, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert started == [new_proc]
    old_proc.terminate.assert_called_once()
    assert runner._procs["device_logcat"] is new_proc


def test_process_runner_start_preserves_old_process_when_replacement_cannot_stop_it():
    """旧进程未能退出时拒绝替换，保留本地和全局跟踪以便再次清理。"""
    runner = ProcessRunner()
    old_proc = Mock()
    old_proc.poll.return_value = None
    old_proc.returncode = None
    old_proc.terminate.side_effect = PermissionError("test stop denied")
    runner._procs["capture"] = old_proc
    runner._register_global("capture", old_proc)

    try:
        with patch.object(runner, "spawn") as spawn:
            with pytest.raises(RuntimeError, match="previous process"):
                runner.start("capture", ["test-command"])
        spawn.assert_not_called()
        assert runner.active_keys == ["capture"]
        assert runner._procs["capture"] is old_proc
        assert ProcessRunner._global_procs[(runner._instance_id, "capture")] is old_proc
    finally:
        old_proc.poll.return_value = 0
        old_proc.returncode = 0
        runner.stop_all()
        runner._unregister_global("capture", old_proc)


def test_process_runner_late_global_registration_does_not_hide_replacement():
    """旧启动延迟登记全局表时，应用退出仍须能够停止新一代进程。"""
    runner = ProcessRunner()
    old_proc = Mock(returncode=None)
    new_proc = Mock(returncode=None)
    for proc in (old_proc, new_proc):
        proc.poll.side_effect = lambda proc=proc: proc.returncode
        proc.terminate.side_effect = lambda proc=proc: setattr(proc, "returncode", 0)
        proc.wait.return_value = 0
    old_register_entered = threading.Event()
    resume_old_register = threading.Event()
    register_global = runner._register_global
    errors = []

    def delayed_registration(key, proc):
        if proc is old_proc:
            old_register_entered.set()
            if not resume_old_register.wait(timeout=5):
                raise TimeoutError("test registration was not released")
        register_global(key, proc)

    def start_old():
        try:
            runner.start("capture", ["test-command"])
        except Exception as error:
            errors.append(error)

    starter = threading.Thread(target=start_old, daemon=True)
    with (
        patch.object(runner, "spawn", side_effect=[old_proc, new_proc]),
        patch.object(runner, "_register_global", side_effect=delayed_registration),
    ):
        try:
            starter.start()
            assert old_register_entered.wait(timeout=5)
            assert runner.start("capture", ["test-command"]) is new_proc
            resume_old_register.set()
            starter.join(timeout=5)
            assert not starter.is_alive()
            assert errors == []

            ProcessRunner.stop_all_tracked()
            new_proc.terminate.assert_called_once_with()
            assert runner.active_keys == []
        finally:
            resume_old_register.set()
            starter.join(timeout=5)
            runner.stop_all()


def test_process_runner_start_stops_own_proc_when_key_claimed_during_spawn():
    ProcessRunner._global_procs.clear()
    runner = ProcessRunner()
    displaced_proc = Mock()
    displaced_proc.poll.return_value = None
    displaced_proc.wait.return_value = 0
    new_proc = Mock()
    new_proc.poll.return_value = None
    new_proc.wait.return_value = 0

    def popen_side_effect(*args, **kwargs):
        # 模拟并发 start 在本次 spawn 期间抢先注册了同名 key。
        runner._procs["device_logcat"] = displaced_proc
        return new_proc

    with patch("core.exec.subprocess.Popen", side_effect=popen_side_effect):
        with pytest.raises(RuntimeError, match="concurrent start"):
            runner.start("device_logcat", ["adb", "logcat"])

    # 本次 start 失败并只停止自身进程，不能把另一调用的句柄伪装为成功结果。
    new_proc.terminate.assert_called_once()
    displaced_proc.terminate.assert_not_called()
    assert runner._procs["device_logcat"] is displaced_proc


@pytest.mark.parametrize("cleanup_scope", ["instance", "global"])
def test_process_runner_concurrent_loser_is_retained_when_cleanup_fails(cleanup_scope):
    """并发失败方的进程无法停止时仍被跟踪，实例及全局清理均可重试。"""
    runner = ProcessRunner()
    winner = Mock(returncode=None)
    loser = Mock(returncode=None)
    deny_stop = True
    winner.poll.side_effect = lambda: winner.returncode
    winner.terminate.side_effect = lambda: setattr(winner, "returncode", 0)
    winner.wait.return_value = 0
    loser.poll.side_effect = lambda: loser.returncode
    loser.wait.return_value = 0

    def stop_loser():
        if deny_stop:
            raise PermissionError("test stop denied")
        loser.returncode = 0

    loser.terminate.side_effect = stop_loser
    spawning_loser = threading.Event()
    resume_loser = threading.Event()
    errors = []

    def spawn(_cmd, **_kwargs):
        if threading.current_thread() is starter:
            spawning_loser.set()
            if not resume_loser.wait(timeout=5):
                raise TimeoutError("test spawn was not released")
            return loser
        return winner

    def start_loser():
        try:
            runner.start("capture", ["test-command"])
        except Exception as error:
            errors.append(error)

    starter = threading.Thread(target=start_loser, daemon=True)
    cleanup = runner.stop_all if cleanup_scope == "instance" else ProcessRunner.stop_all_tracked
    with patch.object(runner, "spawn", side_effect=spawn):
        try:
            starter.start()
            assert spawning_loser.wait(timeout=5)
            assert runner.start("capture", ["test-command"]) is winner
            resume_loser.set()
            starter.join(timeout=5)
            assert not starter.is_alive()
            assert len(errors) == 1
            assert isinstance(errors[0], RuntimeError)
            assert "concurrent start" in str(errors[0])
            winner.terminate.assert_not_called()
            assert runner._procs["capture"] is winner
            residual_keys = [key for key in runner.active_keys if key != "capture"]
            assert len(residual_keys) == 1
            assert runner._procs[residual_keys[0]] is loser
            assert loser in ProcessRunner._global_procs.values()

            cleanup()
            assert runner.active_keys == residual_keys
            assert loser in ProcessRunner._global_procs.values()

            deny_stop = False
            cleanup()
            assert runner.active_keys == []
            assert loser.returncode == 0
            assert loser not in ProcessRunner._global_procs.values()
        finally:
            resume_loser.set()
            starter.join(timeout=5)
            deny_stop = False
            runner.stop_all()


def test_process_runner_active_keys_tolerates_poll_oserror():
    runner = ProcessRunner()
    good = Mock()
    good.poll.return_value = None
    broken = Mock()
    broken.poll.side_effect = OSError("bad handle")

    runner._procs["good"] = good
    runner._procs["broken"] = broken

    assert set(runner.active_keys) == {"good", "broken"}


def test_process_runner_start_forwards_stream_kwargs():
    ProcessRunner._global_procs.clear()
    runner = ProcessRunner()
    proc = Mock()

    with patch("core.exec.subprocess.Popen", return_value=proc) as popen:
        started = runner.start(
            "logcat_device",
            ["adb", "logcat"],
            stdout=Mock(),
            stderr=Mock(),
            cwd="C:/work",
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
            env={"ADB_PATH": "adb-test"},
        )

    assert started is proc
    assert popen.call_args.kwargs["cwd"] == "C:/work"
    assert popen.call_args.kwargs["text"] is True
    assert popen.call_args.kwargs["encoding"] == "utf-8"
    assert popen.call_args.kwargs["errors"] == "ignore"
    assert popen.call_args.kwargs["bufsize"] == 1
    assert popen.call_args.kwargs["env"] == {"ADB_PATH": "adb-test"}


def test_process_runner_spawn_supports_untracked_external_launches():
    ProcessRunner._global_procs.clear()
    runner = ProcessRunner()
    proc = Mock()

    with patch("core.exec.subprocess.Popen", return_value=proc) as popen:
        started = runner.spawn(
            ["cmd.exe", "/K", "echo hi"],
            cwd="C:/work",
            creationflags=123,
        )

    assert started is proc
    assert runner.active_keys == []
    assert popen.call_args.args[0] == ["cmd.exe", "/K", "echo hi"]
    assert popen.call_args.kwargs["cwd"] == "C:/work"
    assert popen.call_args.kwargs["creationflags"] == 123


def test_command_runner_run_to_file_streams_binary_stdout(tmp_path):
    from core.exec import CommandRunner

    output_path = tmp_path / "out.bin"
    proc_result = Mock(returncode=0, stderr=b"")

    with patch("core.exec.subprocess.run", return_value=proc_result) as run:
        result = CommandRunner.run_to_file(["python", "-c", "print('ok')"], str(output_path))

    assert result.success is True
    assert result.output == str(output_path)
    assert run.call_args.kwargs["stdout"].name == str(output_path)
    assert run.call_args.kwargs["stderr"] == subprocess.PIPE


def test_command_runner_logs_slow_sanitized_command():
    from core.exec import CommandRunner

    proc_result = Mock(returncode=0, stdout="ok", stderr="")

    with (
        patch("core.exec.resolve_adb_program", return_value="adb.exe"),
        patch("core.exec.subprocess.run", return_value=proc_result),
        patch("core.exec.perf_counter", side_effect=[1.0, 1.5]),
        patch("core.exec._slow_threshold_ms", return_value=100),
        patch("core.log_service.LogService") as log_service_cls,
    ):
        result = CommandRunner.run(
            ["adb", "-s", "device-1", "shell", "input", "text", "secret text"],
            timeout=5,
        )

    assert result.success is True
    log_service_cls.return_value.log.assert_called_once()
    message = log_service_cls.return_value.log.call_args.args[1]
    assert "adb shell input text" in message
    assert "secret text" not in message


def test_process_runner_stop_all_without_deadlock():
    ProcessRunner._global_procs.clear()
    runner = ProcessRunner()
    old_proc = Mock()
    old_proc.poll.return_value = None
    old_proc.wait.return_value = 0
    runner._procs["device_logcat"] = old_proc

    thread = threading.Thread(target=runner.stop_all, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    old_proc.terminate.assert_called_once()
    assert runner._procs == {}


def test_process_runner_bounded_tree_kill_respects_deadline():
    proc = Mock()
    proc.pid = 4321
    with (
        patch("core.exec.time.monotonic", return_value=50.0),
        patch("core.exec.kill_process_tree", return_value=(True, "terminated")) as kill,
    ):
        assert ProcessRunner._kill_process_tree_bounded(proc, 52.0) is True
    kill.assert_called_once_with(4321, force=True, timeout=2.0)


def test_process_runner_bounded_tree_kill_expired_deadline_skips():
    proc = Mock()
    proc.pid = 4321
    with (
        patch("core.exec.time.monotonic", return_value=60.0),
        patch("core.exec.kill_process_tree") as kill,
    ):
        assert ProcessRunner._kill_process_tree_bounded(proc, 55.0) is False
    kill.assert_not_called()


def test_process_runner_stop_all_tracked_is_global_fallback():
    ProcessRunner._global_procs.clear()
    runner_a = ProcessRunner()
    runner_b = ProcessRunner()
    proc_a = Mock()
    proc_b = Mock()
    for proc in (proc_a, proc_b):
        proc.poll.return_value = None
        proc.wait.return_value = 0
    runner_a._procs["logcat"] = proc_a
    runner_b._procs["scrcpy"] = proc_b
    runner_a._register_global("logcat", proc_a)
    runner_b._register_global("scrcpy", proc_b)

    ProcessRunner.stop_all_tracked()

    proc_a.terminate.assert_called_once()
    proc_b.terminate.assert_called_once()
    assert ProcessRunner._global_procs == {}


def test_process_runner_request_stop_unknown_key_returns_false():
    runner = ProcessRunner()
    assert runner.request_stop("missing") is False


def test_process_runner_request_stop_terminates_running_process():
    runner = ProcessRunner()
    proc = Mock()
    proc.poll.return_value = None
    runner._procs["key"] = proc

    assert runner.request_stop("key") is True
    proc.terminate.assert_called_once()


def test_process_runner_request_stop_skips_terminate_when_exited():
    runner = ProcessRunner()
    proc = Mock()
    proc.poll.return_value = 0
    runner._procs["key"] = proc

    assert runner.request_stop("key") is False
    proc.terminate.assert_not_called()


def test_process_runner_request_stop_returns_false_on_oserror():
    runner = ProcessRunner()
    proc = Mock()
    proc.poll.return_value = None
    proc.terminate.side_effect = OSError("denied")
    runner._procs["key"] = proc

    assert runner.request_stop("key") is False


def test_process_runner_force_stop_unknown_key_returns_false():
    runner = ProcessRunner()
    assert runner.force_stop("missing") is False


def test_process_runner_force_stop_delegates_to_stop_when_exited():
    runner = ProcessRunner()
    proc = Mock()
    proc.poll.return_value = 0
    runner._procs["key"] = proc

    with patch.object(runner, "stop") as stop:
        assert runner.force_stop("key", timeout=0) is False
    stop.assert_called_once_with("key", timeout=0)


def test_process_runner_force_stop_removes_tracking_when_killed():
    ProcessRunner._global_procs.clear()
    runner = ProcessRunner()
    proc = Mock()
    proc.pid = 12345
    proc.poll.side_effect = [None, 0]
    runner._procs["key"] = proc

    with patch.object(ProcessRunner, "_kill_process_tree_bounded", return_value=True):
        assert runner.force_stop("key", timeout=2) is True

    assert "key" not in runner._procs


def test_process_runner_stop_proc_returns_returncode_when_already_exited():
    proc = Mock()
    proc.poll.return_value = 0
    proc.returncode = 0

    assert ProcessRunner._stop_proc(proc) == 0
    proc.terminate.assert_not_called()


def test_process_runner_stop_proc_returns_none_on_terminate_oserror():
    proc = Mock()
    proc.poll.return_value = None
    proc.terminate.side_effect = OSError("denied")
    proc.returncode = None

    assert ProcessRunner._stop_proc(proc) is None


def test_process_runner_stop_proc_kills_when_tree_kill_fails():
    proc = Mock()
    proc.poll.return_value = None
    proc.wait.side_effect = subprocess.TimeoutExpired("adb", 1)
    proc.returncode = None

    with patch.object(ProcessRunner, "_kill_process_tree_bounded", return_value=False):
        assert ProcessRunner._stop_proc(proc, timeout=0.1) is None

    proc.kill.assert_called()


def test_process_runner_tracked_active_count_counts_and_cleans_exited():
    ProcessRunner._global_procs.clear()
    active = Mock()
    active.poll.return_value = None
    exited = Mock()
    exited.poll.return_value = 0
    ProcessRunner._global_procs[(1, "a")] = active
    ProcessRunner._global_procs[(1, "b")] = exited

    assert ProcessRunner.tracked_active_count() == 1
    assert (1, "b") not in ProcessRunner._global_procs
    assert (1, "a") in ProcessRunner._global_procs
    ProcessRunner._global_procs.clear()


def test_process_runner_tracked_active_count_treats_oserror_as_active():
    ProcessRunner._global_procs.clear()
    proc = Mock()
    proc.poll.side_effect = OSError("gone")
    ProcessRunner._global_procs[(1, "a")] = proc

    assert ProcessRunner.tracked_active_count() == 1
    ProcessRunner._global_procs.clear()


def test_process_runner_force_all_tracked_kills_running_process():
    ProcessRunner._global_procs.clear()
    proc = Mock()
    proc.pid = 12345
    proc.poll.side_effect = [None, 0]
    ProcessRunner._global_procs[(1, "a")] = proc

    with patch.object(ProcessRunner, "_kill_process_tree_bounded", return_value=True):
        assert ProcessRunner.force_all_tracked(2.0) is True

    assert ProcessRunner._global_procs == {}


def test_command_runner_run_reports_nonzero_returncode():
    from core.exec import CommandRunner

    completed = Mock()
    completed.returncode = 1
    completed.stderr = "adb: device not found\n"
    completed.stdout = ""
    with patch("core.exec.subprocess.run", return_value=completed):
        r = CommandRunner.run(["adb", "devices"])

    assert r.success is False
    assert "device not found" in r.error


def test_command_runner_run_reports_timeout():
    from core.exec import CommandRunner

    with patch("core.exec.subprocess.run", side_effect=subprocess.TimeoutExpired("adb", 5)):
        r = CommandRunner.run(["adb", "devices"], timeout=5)

    assert r.success is False
    assert "Timeout" in r.error


def test_command_runner_run_reports_exception():
    from core.exec import CommandRunner

    with patch("core.exec.subprocess.run", side_effect=OSError("boom")):
        r = CommandRunner.run(["adb", "devices"])

    assert r.success is False
    assert "boom" in r.error
