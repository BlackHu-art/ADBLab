# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import subprocess
import threading
import warnings
from unittest.mock import Mock, patch

from gui.dialogs.lifecycle import WorkerSignalBinding, safe_disconnect
from gui.panels.remote_panel import ScrcpyLaunchWorker
from models.base.process_runner import ProcessRunner


def test_scrcpy_launch_args_include_selected_ui_options():
    cfg = {
        "exe": "scrcpy.exe",
        "device": "device-1",
        "maxsize": "1080p",
        "fps": "60",
        "bitrate": "12",
        "codec": "h265",
        "buffer": "50",
        "orientation": "1",
        "fullscreen": True,
        "always_on_top": True,
        "no_audio": True,
        "show_touches": True,
        "stay_awake": True,
        "turn_screen_off": True,
        "record_path": "C:/tmp/out.mp4",
        "no_window": True,
    }

    args = ScrcpyLaunchWorker._build_args(cfg, "OMX.test.encoder")

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

    args = ScrcpyLaunchWorker._build_args(cfg, None)

    assert "-m" not in args
    assert "--video-codec" not in args
    assert "--video-encoder" not in args
    assert "--video-buffer=0" not in args
    assert not any(arg.startswith("--lock-video-orientation") for arg in args)
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


def test_worker_signal_binding_connects_and_disconnects_handlers():
    class FakeSignal:
        def __init__(self):
            self.connected = []
            self.disconnected = []

        def connect(self, handler):
            self.connected.append(handler)

        def disconnect(self, handler=None):
            self.disconnected.append(handler)

    class FakeWorker:
        def __init__(self):
            self.finished = FakeSignal()

    worker = FakeWorker()
    result_signal = FakeSignal()
    result_handler = Mock()
    finished_handler = Mock()
    binding = WorkerSignalBinding(
        worker=worker,
        handlers=((result_signal, result_handler),),
        finished_handler=finished_handler,
    )

    binding.connect()
    binding.disconnect()
    binding.disconnect()

    assert result_signal.connected == [result_handler]
    assert worker.finished.connected == [finished_handler]
    assert result_signal.disconnected == [result_handler]
    assert worker.finished.disconnected == [finished_handler]


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
        with patch("models.base.process_runner.subprocess.Popen", return_value=new_proc):
            started.append(runner.start("device_logcat", ["adb", "logcat"]))

    thread = threading.Thread(target=start_process, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert started == [new_proc]
    old_proc.terminate.assert_called_once()
    assert runner._procs["device_logcat"] is new_proc


def test_process_runner_start_stops_process_registered_during_start():
    ProcessRunner._global_procs.clear()
    runner = ProcessRunner()
    displaced_proc = Mock()
    displaced_proc.poll.return_value = None
    displaced_proc.wait.return_value = 0
    new_proc = Mock()

    def popen_side_effect(*args, **kwargs):
        runner._procs["device_logcat"] = displaced_proc
        return new_proc

    with patch("models.base.process_runner.subprocess.Popen", side_effect=popen_side_effect):
        started = runner.start("device_logcat", ["adb", "logcat"])

    assert started is new_proc
    displaced_proc.terminate.assert_called_once()
    assert runner._procs["device_logcat"] is new_proc


def test_process_runner_start_forwards_stream_kwargs():
    ProcessRunner._global_procs.clear()
    runner = ProcessRunner()
    proc = Mock()

    with patch("models.base.process_runner.subprocess.Popen", return_value=proc) as popen:
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

    with patch("models.base.process_runner.subprocess.Popen", return_value=proc) as popen:
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
    from models.base.command_runner import CommandRunner

    output_path = tmp_path / "out.bin"
    proc_result = Mock(returncode=0, stderr=b"")

    with patch("models.base.command_runner.subprocess.run", return_value=proc_result) as run:
        result = CommandRunner.run_to_file(["python", "-c", "print('ok')"], str(output_path))

    assert result.success is True
    assert result.output == str(output_path)
    assert run.call_args.kwargs["stdout"].name == str(output_path)
    assert run.call_args.kwargs["stderr"] == subprocess.PIPE


def test_command_runner_logs_slow_sanitized_command():
    from models.base.command_runner import CommandRunner

    proc_result = Mock(returncode=0, stdout="ok", stderr="")

    with (
        patch("models.base.command_runner._get_adb_path", return_value="adb.exe"),
        patch("models.base.command_runner.subprocess.run", return_value=proc_result),
        patch("models.base.command_runner.perf_counter", side_effect=[1.0, 1.5]),
        patch("models.base.command_runner._slow_threshold_ms", return_value=100),
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
