"""验证专用 worker 的标准流准备时机与输出句柄所有权。"""

from __future__ import annotations

import ctypes
import importlib
import io
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_worker_prepares_streams_before_argument_parser(monkeypatch):
    import main

    prepared = False
    original_parser = main.argparse.ArgumentParser

    def prepare():
        nonlocal prepared
        prepared = True

    def parser(*args, **kwargs):
        assert prepared, "worker must prepare output before argparse can print help or errors"
        return original_parser(*args, **kwargs)

    monkeypatch.setitem(
        sys.modules, "core.worker_stdio", SimpleNamespace(prepare_worker_stdio=prepare),
    )
    monkeypatch.setattr(main, "argparse", SimpleNamespace(ArgumentParser=parser))
    with pytest.raises(SystemExit) as error:
        main._run_mobileperf_worker(["--help"])
    assert error.value.code == 0


class _WindowsPipeHandles:
    """用真实 POSIX/CRT 管道观察句柄转交和关闭，仅替换 Windows 系统调用。"""

    STD_OUTPUT_HANDLE = -11
    STD_ERROR_HANDLE = -12
    DUPLICATE_SAME_ACCESS = 2

    def __init__(self):
        self.pipes = {code: os.pipe() for code in (-11, -12)}
        self.standard = {code: pair[1] for code, pair in self.pipes.items()}
        self.duplicates = []
        self.closed_handles = []
        self.closed_descriptors = []
        self.opened_flags = []
        self.failure = None

    def GetStdHandle(self, code):
        return self.standard[code]

    def GetCurrentProcess(self):
        return 700

    def DuplicateHandle(self, source, original, target, access, inherit, options):
        assert (source, target, access, inherit, options) == (700, 700, 0, False, 2)
        if self.failure == "duplicate":
            raise OSError("duplicate failed")
        duplicate = os.dup(original)
        self.duplicates.append(duplicate)
        return duplicate

    def CloseHandle(self, handle):
        self.closed_handles.append(handle)
        os.close(handle)

    def open_osfhandle(self, handle, flags):
        self.opened_flags.append(flags)
        if self.failure == "open":
            raise OSError("CRT conversion failed")
        return handle

    def fdopen(self, *args, **kwargs):
        if self.failure == "text":
            raise OSError("text wrapper failed")
        return os.fdopen(*args, **kwargs)

    def close(self, descriptor):
        self.closed_descriptors.append(descriptor)
        os.close(descriptor)


@pytest.fixture
def windows_pipes(monkeypatch):
    worker = importlib.import_module("core.worker_stdio")
    handles = _WindowsPipeHandles()
    streams = SimpleNamespace(platform="win32", stdout=None, stderr=None, stdin=object())
    monkeypatch.setattr(worker, "sys", streams)
    monkeypatch.setattr(
        worker, "os", SimpleNamespace(
            O_WRONLY=os.O_WRONLY, O_BINARY=0x8000,
            fdopen=handles.fdopen, close=handles.close,
        ),
    )
    monkeypatch.setitem(sys.modules, "_winapi", handles)
    monkeypatch.setitem(sys.modules, "msvcrt", handles)
    try:
        yield worker, handles, streams
    finally:
        for stream in (streams.stdout, streams.stderr):
            if stream is not None:
                stream.close()
        # 失败用例也必须释放尚未转交的测试资源。
        originals = [fd for pair in handles.pipes.values() for fd in pair]
        for descriptor in [*handles.duplicates, *originals]:
            try:
                os.fstat(descriptor)
            except OSError:
                continue
            os.close(descriptor)


def test_windows_streams_preserve_unicode_and_leave_original_handles_open(windows_pipes):
    worker, handles, streams = windows_pipes
    original_stdin = streams.stdin

    worker.prepare_worker_stdio()
    first_streams = streams.stdout, streams.stderr
    worker.prepare_worker_stdio()

    assert (streams.stdout, streams.stderr) == first_streams
    assert streams.stdin is original_stdin
    assert len(handles.duplicates) == 2
    assert handles.opened_flags == [os.O_WRONLY | 0x8000, os.O_WRONLY | 0x8000]
    for stream, code in ((streams.stdout, -11), (streams.stderr, -12)):
        stream.write("采样完成🙂\n")
        assert stream.line_buffering
        assert os.read(handles.pipes[code][0], 200).decode("utf-8").strip() == "采样完成🙂"
        stream.close()
        os.write(handles.standard[code], b"still open\n")
        assert os.read(handles.pipes[code][0], 200) == b"still open\n"
    assert handles.closed_handles == []
    assert handles.closed_descriptors == []


@pytest.mark.parametrize("invalid_handle", [None, 0, -1, ctypes.c_void_p(-1).value])
def test_windows_missing_standard_handle_fails_without_discarding_output(
    windows_pipes, invalid_handle,
):
    worker, handles, streams = windows_pipes
    handles.standard[-11] = invalid_handle

    with pytest.raises(OSError, match="stdout"):
        worker.prepare_worker_stdio()

    assert streams.stdout is None
    assert handles.duplicates == []
    assert handles.closed_handles == []


@pytest.mark.parametrize("stage", ["duplicate", "open", "text"])
def test_windows_setup_failure_closes_only_the_current_resource_owner(windows_pipes, stage):
    worker, handles, streams = windows_pipes
    handles.failure = stage

    with pytest.raises(OSError):
        worker.prepare_worker_stdio()

    assert streams.stdout is None
    assert handles.closed_handles == (handles.duplicates if stage == "open" else [])
    assert handles.closed_descriptors == (handles.duplicates if stage == "text" else [])
    for duplicate in handles.duplicates:
        with pytest.raises(OSError):
            os.fstat(duplicate)
    for _, original in handles.pipes.values():
        os.fstat(original)


def test_windows_partial_setup_keeps_installed_stdout_alive_for_failure_output(windows_pipes):
    worker, handles, streams = windows_pipes
    handles.standard[-12] = None

    with pytest.raises(OSError, match="stderr"):
        worker.prepare_worker_stdio()

    stdout = streams.stdout
    stdout.write("准备失败🙂\n")
    assert os.read(handles.pipes[-11][0], 200).decode("utf-8").strip() == "准备失败🙂"
    handles.standard[-12] = handles.pipes[-12][1]
    worker.prepare_worker_stdio()
    assert streams.stdout is stdout
    assert len(handles.duplicates) == 2


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_existing_text_streams_become_utf8_without_windows_handle_access(monkeypatch, platform):
    worker = importlib.import_module("core.worker_stdio")
    output = io.BytesIO()
    stream = io.TextIOWrapper(output, encoding="gbk")
    injected = io.StringIO()
    streams = SimpleNamespace(platform=platform, stdout=stream, stderr=injected, stdin=None)
    monkeypatch.setattr(worker, "sys", streams)
    monkeypatch.setitem(sys.modules, "_winapi", None)
    monkeypatch.setitem(sys.modules, "msvcrt", None)

    try:
        worker.prepare_worker_stdio()
        stream.write("采样完成🙂\n")
        assert output.getvalue() == "采样完成🙂\n".encode()
        assert streams.stdout is stream
        assert streams.stderr is injected
        injected.write("可注入输出")
        assert injected.getvalue() == "可注入输出"
    finally:
        stream.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("arguments", "code", "channel", "expected"),
    [(["--help"], 0, "stdout", "--config"), (["--编码验证"], 2, "stderr", "--编码验证")],
)
def test_worker_cli_uses_utf8_before_parsing_without_starting_collection(
    arguments, code, channel, expected,
):
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, PYTHONIOENCODING="gbk")
    result = subprocess.run(
        [sys.executable, str(root / "main.py"), "--mobileperf-worker", *arguments],
        cwd=root, env=environment, capture_output=True, timeout=15, check=False,
    )
    assert result.returncode == code, result.stderr.decode("utf-8", errors="replace")
    assert expected in getattr(result, channel).decode("utf-8")


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows pythonw.exe pipes")
def test_pythonw_recovers_both_pipes_and_reaches_eof_after_exit():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        pytest.skip("the active Windows interpreter has no pythonw.exe")
    root = Path(__file__).resolve().parents[1]
    script = (
        "import atexit, sys\n"
        "assert sys.stdout is None and sys.stderr is None\n"
        "from core.worker_stdio import prepare_worker_stdio\n"
        "prepare_worker_stdio()\n"
        "prepare_worker_stdio()\n"
        "print('stdout 中文🙂')\n"
        "print('stderr 中文🙂', file=sys.stderr)\n"
        "atexit.register(lambda: print('退出收尾🙂'))\n"
        "raise SystemExit(7)\n"
    )
    result = subprocess.run(
        [str(pythonw), "-c", script], cwd=root, capture_output=True, timeout=15, check=False,
    )
    assert result.returncode == 7
    assert result.stdout.decode("utf-8").splitlines() == ["stdout 中文🙂", "退出收尾🙂"]
    assert result.stderr.decode("utf-8").splitlines() == ["stderr 中文🙂"]
