"""本机替身验证投屏自然退出的进程与输出流归属，不使用设备或端口。"""

import io
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.exec import ProcessRunner
from gui.panels.remote_panel_scrcpy import RemotePanelScrcpy
from services.remote import ScrcpyService
from services.remote.types import ScrcpyLaunchPlan


def _reader():
    return RemotePanelScrcpy(SimpleNamespace(
        _closing=False, _device_sessions={}, _scrcpy_output_requested=Mock(),
        _scrcpy_service=ScrcpyService(), _should_ignore_scrcpy_log_line=lambda _line: False,
        _redact_remote_diagnostic=lambda line: line, _log=Mock(),
    ))


@pytest.mark.parametrize("ending", ["success", "failure", "manual"])
def test_finished_scrcpy_releases_tracking_and_reader_owned_streams(ending):
    runner = ProcessRunner()
    service = ScrcpyService(process_runner=runner)
    reader = _reader()
    processes = []
    threads = []
    try:
        for sequence in range(3):
            key = f"mirror-{sequence}"
            code = (
                "import os,time,sys;os.write(1,b'OUT\\n');os.write(2,b'ERR\\n');"
                + ("time.sleep(30)" if ending == "manual" else
                   f"sys.exit({7 if ending == 'failure' else 0})")
            )
            plan = ScrcpyLaunchPlan(
                args=[getattr(sys, "_base_executable", sys.executable), "-c", code,
                      "--port=32100"], device_info="", version="4.1", backend="native",
            )
            process = service.start_plan(key, plan)
            processes.append(process)
            session = service._bridge_sessions[key]
            for stream in (process.stdout, process.stderr):
                thread = threading.Thread(
                    target=reader._read_process_output, args=(process, stream),
                )
                threads.append(thread)
                thread.start()
            if ending == "manual":
                service.stop(key, timeout=3)
            process.wait(timeout=3)
            session.thread.join(3)
            assert not session.thread.is_alive()
            assert not service.is_active(key)
            assert key not in runner._procs
            assert (runner._instance_id, key) not in runner._global_procs
            for thread in threads:
                thread.join(3)
                assert not thread.is_alive()
            assert process.stdout.closed and process.stderr.closed
    finally:
        runner.stop_all()
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
        for thread in threads:
            thread.join(3)
        for process in processes:
            process.stdout.close()
            process.stderr.close()


def test_release_finished_keeps_active_or_replaced_process(monkeypatch):
    runner = ProcessRunner()
    old = Mock(returncode=0)
    old.poll.return_value = 0
    new = Mock(returncode=None)
    new.poll.return_value = None
    monkeypatch.setattr(runner, "spawn", Mock(side_effect=[old, new]))
    runner.start("mirror", ["synthetic"])
    assert runner.release_finished("mirror", old)
    runner.start("mirror", ["synthetic"])
    assert not runner.release_finished("mirror", old)
    assert not runner.release_finished("mirror", new)
    assert runner.active_keys == ["mirror"]
    assert runner._global_procs[(runner._instance_id, "mirror")] is new
    new.returncode = 0
    new.poll.return_value = 0
    assert runner.release_finished("mirror", new)
    assert not runner._procs
    assert (runner._instance_id, "mirror") not in runner._global_procs


@pytest.mark.parametrize("ending", ["eof", "closing", "read_error"])
def test_reader_closes_its_stream_on_every_exit(ending):
    class FailedStream(io.StringIO):
        def __next__(self):
            raise OSError("synthetic reader failure")

    reader = _reader()
    reader._frame._closing = ending == "closing"
    stream = FailedStream() if ending == "read_error" else io.StringIO("ready\n")
    if ending == "read_error":
        with pytest.raises(OSError):
            reader._read_process_output(object(), stream)
    else:
        reader._read_process_output(object(), stream)
    assert stream.closed


def test_failed_launch_closes_streams_before_readers_can_claim_them(monkeypatch):
    runner = ProcessRunner()
    service = ScrcpyService(process_runner=runner)
    plan = ScrcpyLaunchPlan(
        args=[getattr(sys, "_base_executable", sys.executable), "-c",
              "import time;time.sleep(30)", "--port=32100"],
        device_info="", version="4.1", backend="native",
    )
    try:
        with monkeypatch.context() as patch:
            patch.setattr(threading.Thread, "start", Mock(side_effect=RuntimeError("no thread")))
            with pytest.raises(RuntimeError):
                service.start_plan("mirror", plan)
        process = service._bridge_sessions["mirror"].process
        assert service.is_active("mirror")
        service.stop("mirror", timeout=3)
        assert not service.is_active("mirror")
        assert process.stdout.closed and process.stderr.closed
    finally:
        runner.stop_all()
        for stream in (process.stdout, process.stderr):
            stream.close()
