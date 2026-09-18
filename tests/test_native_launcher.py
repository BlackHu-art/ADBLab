"""独立原生启动器只交付目标进程的字节流，并遵守取消与父进程归属。"""

import ctypes
import importlib
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from ctypes import wintypes
from pathlib import Path

import pytest


def test_launcher_is_available_without_gui_dependencies():
    assert importlib.util.find_spec("core.native_launcher") is not None
    module = importlib.import_module("core.native_launcher")
    assert callable(module.launch)


def test_environment_removes_only_extraction_tree_and_preserves_frozen_metadata():
    module = importlib.import_module("core.native_launcher")
    original = {
        "Path": r'C:\Windows;"C:\TEMP\_MEI123";c:\temp\_mei123\bin;C:\TEMP\_MEI123-other;;D:\tools',
        "_PYI_APPLICATION_HOME_DIR": r"C:\TEMP\_MEI123",
        "CUSTOM": "kept",
    }
    cleaned = module.sanitize_environment(original, r"C:\temp\_MEI123")
    assert cleaned["Path"] == r"C:\Windows;C:\TEMP\_MEI123-other;;D:\tools"
    assert cleaned["_PYI_APPLICATION_HOME_DIR"] == original["_PYI_APPLICATION_HOME_DIR"]
    assert cleaned["CUSTOM"] == "kept"
    assert original["Path"].count("_MEI123") == 2


@pytest.fixture
def windows_events():
    if sys.platform != "win32":
        pytest.skip("需要 Windows 具名 Event 与 pythonw 标准句柄")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.SetEvent.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    handles = []

    def create():
        name = "Local\\ADBLab-test-" + uuid.uuid4().hex
        handle = kernel.CreateEventW(None, True, False, name)
        assert handle
        handles.append(handle)
        return name, handle

    yield kernel, create
    for handle in handles:
        kernel.CloseHandle(handle)


def _helper_command(event_name, owner, arguments):
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    assert pythonw.is_file()
    script = (
        "import sys; from core.native_launcher import launch; "
        "assert not any(n.startswith(('PySide6', 'gui.')) for n in sys.modules); "
        "raise SystemExit(launch(sys.argv[1:]))"
    )
    return [str(pythonw), "-B", "-c", script, "--cancel-event", event_name,
            "--owner", str(owner), "--", *arguments]


def _read_ready(process):
    result = queue.Queue()
    reader = threading.Thread(target=lambda: result.put(process.stdout.readline()), daemon=True)
    reader.start()
    line = result.get(timeout=10)
    reader.join(timeout=1)
    assert line, "目标进程必须在取消前实际启动"
    return tuple(int(value) for value in line.split())


@pytest.mark.parametrize("exit_code", [2, 7])
def test_pythonw_preserves_binary_streams_arguments_and_exit_code(windows_events, exit_code):
    _kernel, create = windows_events
    name, _handle = create()
    argument = '空 格 "quoted" trailing\\'
    script = (
        "import json,sys; data=sys.stdin.buffer.read(); "
        "sys.stdout.buffer.write(data+b'\\x00'+json.dumps(sys.argv[1:]).encode()); "
        f"sys.stderr.buffer.write(b'ERR\\x00\\xff'); raise SystemExit({exit_code})"
    )
    result = subprocess.run(
        _helper_command(name, os.getpid(), [sys.executable, "-B", "-c", script, argument]),
        input=b"IN\x00\xff\r\n", capture_output=True, timeout=15,
    )
    assert result.returncode == exit_code
    assert result.stdout == b"IN\x00\xff\r\n\x00" + json.dumps([argument]).encode()
    assert result.stderr == b"ERR\x00\xff"


def test_pythonw_preserves_high_bit_windows_exit_code(windows_events):
    _kernel, create = windows_events
    name, _handle = create()
    script = (
        "import ctypes; exit_process=ctypes.WinDLL('kernel32').ExitProcess; "
        "exit_process.argtypes=[ctypes.c_uint]; exit_process.restype=None; "
        "exit_process(0xC0000005)"
    )
    result = subprocess.run(
        _helper_command(name, os.getpid(), [sys.executable, "-c", script]),
        capture_output=True, timeout=15,
    )
    assert result.returncode == 0xC0000005
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize(
    "case", ["cancelled", "missing_event", "missing_owner", "relative", "not_exe", "invalid_exe"],
)
def test_invalid_or_cancelled_request_never_starts_native_child(windows_events, tmp_path, case):
    kernel, create = windows_events
    name, handle = create()
    marker = tmp_path / "started"
    owner = os.getpid()
    program = sys.executable
    if case == "cancelled":
        assert kernel.SetEvent(handle)
    elif case == "missing_event":
        name += "-missing"
    elif case == "missing_owner":
        owner = 0xFFFFFFFE
    elif case == "relative":
        program = "python.exe"
    else:
        program = str(tmp_path / ("program.txt" if case == "not_exe" else "program.exe"))
        Path(program).write_text("not an executable")
    script = f"from pathlib import Path; Path({str(marker)!r}).write_text('started')"
    result = subprocess.run(
        _helper_command(name, owner, [program, "-c", script]),
        capture_output=True, timeout=15,
    )
    assert result.returncode == (130 if case == "cancelled" else 2)
    assert not marker.exists()
    assert result.stdout == b""
    assert result.stderr == (
        b"" if case == "cancelled"
        else b"ADBLab native launcher: setup or process creation failed.\n"
    )


@pytest.mark.parametrize("trigger", ["cancel", "owner_exit"])
def test_control_signal_reaps_only_owned_native_client(windows_events, trigger):
    kernel, create = windows_events
    name, handle = create()
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    client = (
        "import os,subprocess,sys,time; "
        "server=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP); "
        "print(os.getpid(),server.pid,flush=True); time.sleep(60)"
    )
    helper = subprocess.Popen(
        _helper_command(name, owner.pid, [sys.executable, "-u", "-c", client]),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    native_handle = None
    server_handle = None
    try:
        native_pid, server_pid = _read_ready(helper)
        native_handle = kernel.OpenProcess(0x00100000, False, native_pid)
        server_handle = kernel.OpenProcess(0x00100001, False, server_pid)
        assert native_handle
        assert server_handle
        if trigger == "cancel":
            assert kernel.SetEvent(handle)
        else:
            owner.terminate()
            owner.wait(timeout=5)
        helper.communicate(timeout=10)
        assert helper.returncode == 130
        assert kernel.WaitForSingleObject(native_handle, 0) == 0
        assert kernel.WaitForSingleObject(server_handle, 0) == 258
    finally:
        if native_handle:
            kernel.CloseHandle(native_handle)
        if server_handle:
            kernel.TerminateProcess(server_handle, 1)
            assert kernel.WaitForSingleObject(server_handle, 5000) == 0
            kernel.CloseHandle(server_handle)
        for process in (helper, owner):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def test_non_windows_launch_fails_closed(monkeypatch):
    module = importlib.import_module("core.native_launcher")
    monkeypatch.setattr(module.sys, "platform", "linux")
    assert module.launch([]) == 2


@pytest.mark.parametrize("control_result, expected", [(0, 130), (0xFFFFFFFF, 2)])
def test_cancel_during_spawn_or_monitor_failure_cleans_child(monkeypatch, control_result, expected):
    module = importlib.import_module("core.native_launcher")
    if sys.platform != "win32":
        pytest.skip("需要 Windows 启动参数")
    closed = []
    states = iter([258, control_result])

    class Kernel:
        OpenEventW = staticmethod(lambda *_args: 11)
        OpenProcess = staticmethod(lambda *_args: 12)
        SetDllDirectoryW = staticmethod(lambda _path: True)
        CloseHandle = staticmethod(closed.append)
        WaitForMultipleObjects = staticmethod(lambda *_args: next(states))

    class Child:
        stopped = False
        waited = False

        def poll(self):
            return 1 if self.stopped else None

        def kill(self):
            self.stopped = True

        def wait(self, **_kwargs):
            assert self.stopped
            self.waited = True
            return 1

    child = Child()
    monkeypatch.setattr(module, "_kernel", Kernel)
    monkeypatch.setattr(module, "_startup_info", lambda _resources: None)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: child)
    result = module.launch(["--cancel-event", "test", "--owner", "1", "--", sys.executable])
    assert result == expected
    assert child.stopped and child.waited
    assert sorted(closed) == [11, 12]


def test_pythonw_uses_devnull_when_standard_handles_are_missing(windows_events, tmp_path):
    _kernel, create = windows_events
    name, _handle = create()
    marker = tmp_path / "stdio-result.json"
    child = (
        "import json,sys; from pathlib import Path; data=sys.stdin.buffer.read(); "
        "sys.stdout.buffer.write(b'output'); sys.stderr.buffer.write(b'error'); "
        f"Path({str(marker)!r}).write_text(json.dumps(list(data)))"
    )
    command = _helper_command(name, os.getpid(), [sys.executable, "-c", child])
    command[3] = (
        "import ctypes; from ctypes import wintypes; "
        "kernel=ctypes.WinDLL('kernel32',use_last_error=True); "
        "kernel.SetStdHandle.argtypes=[wintypes.DWORD,wintypes.HANDLE]; "
        "[kernel.SetStdHandle(code,None) for code in (-10,-11,-12)]; "
    ) + command[3]
    result = subprocess.run(command, capture_output=True, timeout=15)
    assert result.returncode == 0
    assert result.stdout == result.stderr == b""
    assert json.loads(marker.read_text()) == []


@pytest.mark.parametrize("stderr_handle", [None, 123456789])
def test_setup_failure_with_bad_stderr_keeps_failure_code(windows_events, stderr_handle):
    _kernel, create = windows_events
    name, _handle = create()
    command = _helper_command(name, os.getpid(), ["relative.exe"])
    command[3] = (
        "import ctypes; from ctypes import wintypes; "
        "kernel=ctypes.WinDLL('kernel32',use_last_error=True); "
        "kernel.SetStdHandle.argtypes=[wintypes.DWORD,wintypes.HANDLE]; "
        f"kernel.SetStdHandle(-12,{stderr_handle!r}); "
    ) + command[3]
    result = subprocess.run(command, capture_output=True, timeout=15)
    assert result.returncode == 2
    assert result.stdout == result.stderr == b""


def test_pythonw_cleans_extraction_environment_before_native_start(windows_events, tmp_path):
    _kernel, create = windows_events
    name, _handle = create()
    extraction = str(tmp_path / "_MEI-probe")
    preserved = str(tmp_path / "_MEI-probe-other")
    environment = dict(os.environ)
    environment["PATH"] = ";".join([extraction, extraction + "\\bin", preserved])
    environment["_PYI_PROBE"] = "preserved"
    child = (
        "import ctypes,json,os; b=ctypes.create_unicode_buffer(32768); "
        "ctypes.windll.kernel32.GetDllDirectoryW(len(b),b); "
        "print(json.dumps([os.environ['PATH'],os.environ['_PYI_PROBE'],b.value]))"
    )
    command = _helper_command(name, os.getpid(), [sys.executable, "-c", child])
    command[3] = (
        f"import ctypes,sys; sys._MEIPASS={extraction!r}; "
        "ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS); "
    ) + command[3]
    result = subprocess.run(command, env=environment, capture_output=True, timeout=15)
    assert result.returncode == 0
    assert json.loads(result.stdout) == [preserved, "preserved", ""]
