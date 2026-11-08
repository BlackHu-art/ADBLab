"""本地 C stdio 替身验证投屏就绪输出实时交付，不启动 scrcpy、设备或原生窗口。"""

import errno
import io
import os
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.exec import ProcessRunner
from gui.panels.remote_panel_scrcpy import RemoteDeviceSession
from services.remote import ScrcpyService
from services.remote.types import ScrcpyLaunchPlan
from tests.test_scrcpy_process_release import _reader


def _plan(code):
    return ScrcpyLaunchPlan(
        args=[getattr(sys, "_base_executable", sys.executable), "-c", code, "--port=32100"],
        device_info="", version="4.1", backend="native",
    )


@pytest.mark.skipif(os.name != "posix", reason="PTY 仅用于 POSIX 长进程输出")
@pytest.mark.parametrize("ending", ["success", "failure", "cancel"])
def test_c_stdout_texture_reaches_original_reader_while_process_alive(tmp_path, ending):
    from tests.test_task_session_busy import _RemoteHolder

    gate = tmp_path / "exit-gate"
    code = (
        "import ctypes,os,time;from pathlib import Path;"
        "libc=ctypes.CDLL(None);libc.printf.argtypes=[ctypes.c_char_p];"
        "libc.printf(b'INFO: Texture: 460x1024\\n');os.write(2,b'WROTE\\n');"
        f"gate=Path({str(gate)!r});"
        "\nwhile not gate.exists(): time.sleep(.005)\n"
        "libc.fflush(None);"
        f"raise SystemExit({7 if ending == 'failure' else 0})"
    )
    runner = ProcessRunner()
    service = ScrcpyService(process_runner=runner)
    reader = _reader()
    wrote, ready = threading.Event(), threading.Event()
    process = service.start_plan("mirror", _plan(code))
    session = service._bridge_sessions["mirror"]
    member = RemoteDeviceSession(
        SimpleNamespace(device="synthetic", no_window=False), state="connecting",
        process=process, resource_owned=True,
    )
    reader._frame._device_sessions = {"synthetic": member}
    owner = _RemoteHolder()
    owner._device_sessions = reader._frame._device_sessions
    before = owner.task_snapshot()
    assert before.resource_owned and before.busy
    reader._refresh_sessions = Mock()

    def deliver(original, line):
        reader._on_scrcpy_output(original, line)
        if line == "WROTE":
            wrote.set()
        if member.state == "ready":
            ready.set()

    reader._frame._scrcpy_output_requested.emit.side_effect = deliver
    threads = [threading.Thread(target=reader._read_process_output, args=(process, stream))
               for stream in (process.stdout, process.stderr)]
    try:
        for thread in threads:
            thread.start()
        assert wrote.wait(2), "合成子进程必须先执行 C printf，再检验父 reader"
        assert process.poll() is None
        assert ready.wait(1), "真实 Texture 必须在子进程仍存活时交付，不能等停止才刷新"
        assert process.poll() is None and member.state == "ready" and member.resource_owned
        after = owner.task_snapshot()
        assert after.resource_owned and not after.busy and after.revision == before.revision
        assert runner._procs["mirror"] is process
        if ending == "cancel":
            service.stop("mirror", timeout=3)
        else:
            gate.touch()
        process.wait(timeout=3)
        session.thread.join(3)
        assert not session.thread.is_alive() and not service.is_active("mirror")
        assert "mirror" not in runner.active_keys
        assert (runner._instance_id, "mirror") not in runner._global_procs
    finally:
        gate.touch()
        service.stop("mirror", timeout=3)
        for thread in threads:
            thread.join(3)
            assert not thread.is_alive()
        assert process.stdout.closed and process.stderr.closed


def _assert_closed(descriptors):
    for descriptor in descriptors:
        with pytest.raises(OSError) as error:
            os.fstat(descriptor)
        assert error.value.errno == errno.EBADF


@pytest.mark.skipif(os.name != "posix", reason="PTY 仅用于 POSIX 长进程输出")
def test_pty_eio_is_eof_and_other_read_errors_remain_visible(monkeypatch):
    from services.remote import scrcpy_service as module

    for error_code in (errno.EIO, errno.EBADF):
        read_fd, write_fd = os.pipe()
        stream = module._PtyStdout(read_fd)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(os, "read", Mock(side_effect=OSError(error_code, "synthetic")))
                if error_code == errno.EIO:
                    assert stream.readinto(bytearray(16)) == 0
                else:
                    with pytest.raises(OSError) as error:
                        stream.readinto(bytearray(16))
                    assert error.value.errno == errno.EBADF
        finally:
            stream.close()
            stream.close()
            os.close(write_fd)
        _assert_closed((read_fd, write_fd))


@pytest.mark.skipif(os.name != "posix", reason="PTY 仅用于 POSIX 长进程输出")
def test_failed_spawn_closes_preconstructed_stdout_and_slave(monkeypatch):
    import pty

    from services.remote import scrcpy_service as module

    descriptors = []
    original_open = pty.openpty

    def open_pair():
        pair = original_open()
        descriptors.extend(pair)
        return pair

    runner = Mock(active_keys=[])
    runner.start.side_effect = OSError("synthetic spawn failure")
    service = ScrcpyService(process_runner=runner)
    monkeypatch.setattr(pty, "openpty", open_pair)
    with pytest.raises(OSError, match="synthetic spawn failure"):
        service.start_plan("mirror", _plan("pass"))
    assert len(descriptors) == 2
    _assert_closed(descriptors)
    assert not service._bridge_sessions
    assert runner.start.call_args.kwargs["stderr"] == -1
    assert module._reserved_ports == set()


@pytest.mark.skipif(os.name != "posix", reason="PTY 仅用于 POSIX 长进程输出")
def test_reader_construction_failure_closes_pair_before_spawn(monkeypatch):
    import pty

    from services.remote import scrcpy_service as module

    descriptors = []
    original_open = pty.openpty

    def open_pair():
        pair = original_open()
        descriptors.extend(pair)
        return pair

    runner = Mock(active_keys=[])
    service = ScrcpyService(process_runner=runner)
    monkeypatch.setattr(pty, "openpty", open_pair)
    with monkeypatch.context() as patch:
        patch.setattr(io, "TextIOWrapper", Mock(side_effect=OSError("synthetic wrap failure")))
        with pytest.raises(OSError, match="synthetic wrap failure"):
            service.start_plan("mirror", _plan("pass"))
    runner.start.assert_not_called()
    _assert_closed(descriptors)
    assert not service._bridge_sessions
    assert module._reserved_ports == set()


def test_windows_start_plan_retains_exact_pipe_transport(monkeypatch):
    from services.remote import scrcpy_service as module

    runner = Mock(active_keys=[])
    process = runner.start.return_value
    original_stdout = process.stdout
    service = ScrcpyService(process_runner=runner)
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", lambda _thread: None)
        assert service.start_plan("mirror", _plan("pass")) is process
    assert process.stdout is original_stdout
    assert runner.start.call_args.kwargs == {
        "stdout": -1, "stderr": -1, "text": True, "encoding": "utf-8", "errors": "ignore",
        "bufsize": 1, "env": None, "native_tool": True,
    }


@pytest.mark.skipif(os.name != "posix", reason="PTY 仅用于 POSIX 长进程输出")
def test_cleanup_thread_failure_retains_process_and_closes_unclaimed_pty(monkeypatch):
    runner = ProcessRunner()
    service = ScrcpyService(process_runner=runner)
    process = None
    try:
        with monkeypatch.context() as patch:
            patch.setattr(threading.Thread, "start", Mock(side_effect=RuntimeError("no thread")))
            with pytest.raises(RuntimeError, match="no thread"):
                service.start_plan("mirror", _plan("import time;time.sleep(30)"))
        session = service._bridge_sessions["mirror"]
        process = session.process
        descriptor = process.stdout.fileno()
        assert session.output_unclaimed and service.is_active("mirror")
        assert service.stop("mirror", timeout=3) is not None
        assert not service.is_active("mirror")
        assert process.stdout.closed and process.stderr.closed
        _assert_closed((descriptor,))
        assert "mirror" not in runner.active_keys
    finally:
        runner.stop_all()
        if process is not None:
            process.stdout.close()
            process.stderr.close()


@pytest.mark.skipif(os.name != "posix", reason="PTY 仅用于 POSIX 长进程输出")
def test_post_spawn_stdout_assignment_failure_keeps_original_stop_ownership(monkeypatch):
    import pty

    class RejectingProcess:
        stderr = io.StringIO()

        @property
        def stdout(self):
            return None

        @stdout.setter
        def stdout(self, _value):
            raise RuntimeError("synthetic stdout assignment failure")

        def wait(self, timeout=None):
            return 0

    descriptors = []
    original_open = pty.openpty

    def open_pair():
        pair = original_open()
        descriptors.extend(pair)
        return pair

    process = RejectingProcess()
    runner = Mock(active_keys=[])

    def start(*_args, **_kwargs):
        runner.active_keys = ["mirror"]
        return process

    def stop(*_args, **_kwargs):
        runner.active_keys = []
        return 0

    runner.start.side_effect = start
    runner.stop.side_effect = stop
    service = ScrcpyService(process_runner=runner)
    monkeypatch.setattr(pty, "openpty", open_pair)
    with pytest.raises(RuntimeError, match="synthetic stdout assignment failure"):
        service.start_plan("mirror", _plan("pass"))
    session = service._bridge_sessions["mirror"]
    assert session.process is process and session.cleanup_failed and session.output_unclaimed
    assert service.is_active("mirror")
    runner.request_stop.assert_called_once_with("mirror")
    _assert_closed(descriptors)
    assert service.stop("mirror", timeout=3) == 0
    assert not service.is_active("mirror")
    assert process.stderr.closed


@pytest.mark.skipif(os.name != "posix", reason="PTY 仅用于 POSIX 长进程输出")
def test_parent_slave_close_error_keeps_live_process_owned_for_stop(monkeypatch):
    import pty

    original_open, original_close = pty.openpty, os.close
    pair = []
    failed = False

    def open_pair():
        pair.extend(original_open())
        return tuple(pair)

    def close(descriptor):
        nonlocal failed
        original_close(descriptor)
        if descriptor == pair[1] and not failed:
            failed = True
            raise OSError(errno.EINTR, "synthetic close failure")

    runner = ProcessRunner()
    service = ScrcpyService(process_runner=runner)
    process = None
    try:
        with monkeypatch.context() as patch:
            patch.setattr(pty, "openpty", open_pair)
            patch.setattr(os, "close", close)
            with pytest.raises(OSError, match="synthetic close failure"):
                service.start_plan("mirror", _plan("import time;time.sleep(30)"))
        session = service._bridge_sessions["mirror"]
        process = session.process
        assert session.cleanup_failed and session.output_unclaimed and not session.starting
        assert service.is_active("mirror")
        assert service.stop("mirror", timeout=3) is not None
        assert not service.is_active("mirror")
        _assert_closed(pair)
    finally:
        runner.stop_all()
        if process is None:
            session = service._bridge_sessions.get("mirror")
            process = session.process if session is not None else None
        if process is not None:
            process.stdout.close()
            process.stderr.close()
