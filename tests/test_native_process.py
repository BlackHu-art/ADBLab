"""原生工具隔离入口的参数、标准流和取消契约。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

# venv 的 Windows python.exe 是转发器；原生工具替身必须直接运行基础解释器。
NATIVE_PYTHON = getattr(sys, "_base_executable", sys.executable)


def test_source_process_keeps_binary_streams_and_exit_code():
    from core import native_process

    result = native_process.run_native(
        [sys.executable, "-c", "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read());"
         "sys.stderr.buffer.write(b'ERR\\0');sys.exit(7)"],
        isolate=True, input=b"INPUT\0", capture_output=True, timeout=10,
    )
    assert (result.stdout, result.stderr, result.returncode) == (b"INPUT\0", b"ERR\0", 7)


@pytest.fixture
def frozen_launcher(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows 原生工具隔离")
    from core import native_process

    pythonw = Path(NATIVE_PYTHON).with_name("pythonw.exe")
    if not pythonw.is_file():
        pytest.skip("当前解释器未提供 pythonw.exe")
    root = str(Path(__file__).resolve().parents[1])
    code = (
        f"import sys;sys.path.insert(0,{root!r});"
        "from core.native_launcher import launch;sys.exit(launch(sys.argv[1:]))"
    )
    monkeypatch.setattr(
        native_process, "_should_isolate", lambda isolate, shell: isolate and not shell,
    )
    monkeypatch.setattr(native_process, "_launcher_prefix", lambda: [str(pythonw), "-c", code])
    return native_process


def test_windowed_launcher_preserves_argv_binary_input_and_separate_error(frozen_launcher):
    argument = '中文 space "quote" & $literal'
    result = frozen_launcher.run_native(
        [NATIVE_PYTHON, "-c", "import sys,json;"
         "sys.stdout.buffer.write(json.dumps(sys.argv[1:],ensure_ascii=False).encode()+b'\\n');"
         "sys.stdout.buffer.write(sys.stdin.buffer.read());sys.stderr.buffer.write(b'ERR\\0');"
         "sys.exit(7)", argument],
        isolate=True, capture_output=True, input=b"DATA\0\xff", timeout=10,
    )
    head, data = result.stdout.split(b"\n", 1)
    assert json.loads(head) == [argument]
    assert data == b"DATA\0\xff"
    assert result.stderr == b"ERR\0"
    assert result.returncode == 7


def test_windowed_launcher_preserves_redirected_file_and_merged_error(frozen_launcher, tmp_path):
    path = tmp_path / "output.bin"
    with path.open("wb") as output:
        result = frozen_launcher.run_native(
            [NATIVE_PYTHON, "-c", "import os;os.write(1,b'OUT\\0');os.write(2,b'ERR\\xff')"],
            isolate=True, stdout=output, stderr=subprocess.STDOUT, timeout=10,
        )
    assert result.returncode == 0
    assert path.read_bytes() == b"OUT\0ERR\xff"


def _wait_for_pid(path: Path, process: subprocess.Popen) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.is_file() and path.read_text().strip():
            return int(path.read_text())
        if process.poll() is not None:
            pytest.fail(f"启动入口提前退出：{process.returncode}")
        time.sleep(0.01)
    pytest.fail("原生替身未进入就绪状态")


@pytest.mark.parametrize("operation", ["terminate", "kill", "bounded_stop"])
def test_cancel_reaps_native_client_before_launcher_exit(frozen_launcher, tmp_path, operation):
    marker = tmp_path / "native.pid"
    command = [NATIVE_PYTHON, "-c", "import os,time,pathlib;"
               f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(30)"]
    process = frozen_launcher.popen_native(
        command, isolate=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    pid = None
    try:
        pid = _wait_for_pid(marker, process)
        if operation == "bounded_stop":
            assert frozen_launcher.stop_native_process(process, timeout=3)
        else:
            getattr(process, operation)()
        process.communicate(timeout=5)
        assert process.returncode == 130
        assert not psutil.pid_exists(pid)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        if pid is not None and psutil.pid_exists(pid):
            psutil.Process(pid).kill()


def test_cancel_before_launcher_ready_never_starts_native_client(frozen_launcher, tmp_path):
    marker = tmp_path / "should-not-exist"
    process = frozen_launcher.popen_native(
        [NATIVE_PYTHON, "-c", f"from pathlib import Path;Path({str(marker)!r}).touch()"],
        isolate=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    process.terminate()
    process.communicate(timeout=10)
    assert process.returncode == 130
    assert not marker.exists()


def test_native_run_timeout_reaps_client(frozen_launcher, tmp_path):
    marker = tmp_path / "native.pid"
    with pytest.raises(subprocess.TimeoutExpired):
        frozen_launcher.run_native(
            [NATIVE_PYTHON, "-c", "import os,time,pathlib;"
             f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(30)"],
            isolate=True, capture_output=True, timeout=2,
        )
    if marker.exists():
        assert not psutil.pid_exists(int(marker.read_text()))


def test_application_worker_and_non_windows_remain_unwrapped(monkeypatch):
    from core import native_process

    sentinel = object()
    observed = []
    monkeypatch.setattr(
        native_process.subprocess, "Popen",
        lambda command, **kw: observed.append(command) or sentinel,
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    command = [sys.executable, "--mobileperf-worker"]
    assert native_process.popen_native(command, isolate=False) is sentinel
    monkeypatch.setattr(sys, "platform", "linux")
    assert native_process.popen_native(command, isolate=True) is sentinel
    assert observed == [command, command]


def test_unresponsive_launcher_is_stopped_without_killing_independent_server(
    frozen_launcher, monkeypatch, tmp_path,
):
    client_marker = tmp_path / "client.pid"
    server_marker = tmp_path / "server.pid"
    server_code = "import time;time.sleep(30)"
    client_code = (
        "import os,time,subprocess,pathlib;"
        f"server=subprocess.Popen([{NATIVE_PYTHON!r},'-c',{server_code!r}],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        f"pathlib.Path({str(server_marker)!r}).write_text(str(server.pid));"
        f"pathlib.Path({str(client_marker)!r}).write_text(str(os.getpid()));time.sleep(30)"
    )
    launcher_code = (
        f"import subprocess,time;subprocess.Popen([{NATIVE_PYTHON!r},'-c',{client_code!r}]);"
        "time.sleep(30)"
    )
    monkeypatch.setattr(
        frozen_launcher, "_launcher_prefix", lambda: [NATIVE_PYTHON, "-c", launcher_code],
    )
    process = frozen_launcher.popen_native(
        [NATIVE_PYTHON], isolate=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    client = server = None
    try:
        client = _wait_for_pid(client_marker, process)
        server = int(server_marker.read_text())
        started = time.monotonic()
        assert frozen_launcher.stop_native_process(process, timeout=1.5)
        assert time.monotonic() - started < 2.0
        assert not psutil.pid_exists(client)
        assert psutil.pid_exists(server)
        process.communicate(timeout=1)
    finally:
        for pid in (client, server):
            if pid is not None and psutil.pid_exists(pid):
                psutil.Process(pid).kill()
        if process.poll() is None:
            subprocess.Popen.kill(process)
        process.communicate(timeout=3)


def test_timeout_does_not_wait_for_independent_server_to_close_pipe(frozen_launcher, tmp_path):
    marker = tmp_path / "server.pid"
    daemon = "import time;time.sleep(5)"
    command = [
        NATIVE_PYTHON, "-c", "import subprocess,time,pathlib;"
        f"server=subprocess.Popen([{NATIVE_PYTHON!r},'-c',{daemon!r}]);"
        f"pathlib.Path({str(marker)!r}).write_text(str(server.pid));time.sleep(30)",
    ]
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            frozen_launcher.run_native(command, isolate=True, capture_output=True, timeout=1)
        assert time.monotonic() - started < 4
    finally:
        if marker.exists():
            pid = int(marker.read_text())
            if psutil.pid_exists(pid):
                psutil.Process(pid).kill()


@pytest.mark.parametrize("isolated", [False, True])
@pytest.mark.parametrize("ending", ["timeout", "cancelled", "client_exited"])
def test_native_capture_bounds_cleanup_when_descendant_holds_pipes(
    request, monkeypatch, tmp_path, isolated, ending,
):
    from core import adb_runtime, native_process

    if isolated:
        request.getfixturevalue("frozen_launcher")
    else:
        monkeypatch.setattr(native_process, "_should_isolate", lambda *_args: False)
    processes = []
    spawn = adb_runtime.popen_native

    def capture_process(*args, **kwargs):
        process = spawn(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(adb_runtime, "popen_native", capture_process)
    # 连续调用覆盖取消后的 reader 归属，不让上一轮资源污染下一轮。
    for attempt in range(2):
        marker = tmp_path / f"server-{attempt}.pid"
        daemon = "import time;time.sleep(3)"
        command = [
            NATIVE_PYTHON, "-c", "import subprocess,time,pathlib;"
            f"server=subprocess.Popen([{NATIVE_PYTHON!r},'-c',{daemon!r}]);"
            f"pathlib.Path({str(marker)!r}).write_text(str(server.pid));"
            + ("time.sleep(30)" if ending != "client_exited" else ""),
        ]
        started = time.monotonic()
        server = None
        try:
            result = adb_runtime.native_capture(
                command, 0.5, lambda: ending == "cancelled" and marker.exists(),
            )
            elapsed = time.monotonic() - started
            assert result.kind == ("cancelled" if ending == "cancelled" else "timeout")
            assert elapsed < 1.5
            assert marker.exists(), "合成后代必须已启动才能验证管道继承"
            server = psutil.Process(int(marker.read_text()))
            assert server.is_running(), "短命令取消不能杀死独立服务"
            assert processes[-1].poll() is not None
        finally:
            if server is None and marker.exists():
                try:
                    server = psutil.Process(int(marker.read_text()))
                except psutil.NoSuchProcess:
                    server = None
            if server is not None:
                server.kill()
                server.wait(timeout=3)
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)
                for name in ("stdout", "stderr"):
                    reader = getattr(process, name + "_thread", None)
                    if reader is not None:
                        reader.join(timeout=2)
                        assert not reader.is_alive()
                    stream = getattr(process, name, None)
                    if stream is not None:
                        assert stream.closed


def test_native_capture_reports_unconfirmed_cleanup_as_transport_failure(monkeypatch):
    from core import adb_runtime

    class UnconfirmedProcess:
        killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            assert self.killed and 0 <= timeout <= 0.5
            raise subprocess.TimeoutExpired("test-client", timeout)

    process = UnconfirmedProcess()
    monkeypatch.setattr(adb_runtime, "popen_native", lambda *_args, **_kwargs: process)
    cancellation = iter((False, True))
    result = adb_runtime.native_capture(["test-client"], 1, lambda: next(cancellation))
    assert result.kind == "transport"
    assert result.stderr == b"ADB process failed"
