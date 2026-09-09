"""scrcpy CLI 的入口、会话绑定、父进程收口与环境限制回归。"""

import importlib
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scrcpy_adb_bridge.py"


def bridge():
    return importlib.import_module("scripts.scrcpy_adb_bridge")


@pytest.fixture
def environment(tmp_path, monkeypatch):
    server = tmp_path / "scrcpy-server"
    server.write_bytes(b"jar")
    directory = tmp_path / "session"
    directory.mkdir()
    env = {
        "ADBLAB_SCRCPY_SERIAL": "test-device",
        "ADBLAB_SCRCPY_SERVER": str(server),
        "ADBLAB_SCRCPY_OWNER_PID": str(os.getpid()),
        "ADBLAB_SCRCPY_PORT_RANGE": "27183:27199",
        "ADBLAB_SCRCPY_SESSION_FILE": str(directory / "session.json"),
    }
    for key in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


def test_self_check_executes_offline_without_qt():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--self-check"],
        capture_output=True,
        timeout=10,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"scrcpy-adb-bridge: ready\n"
    assert result.stderr == b""


def test_module_does_not_import_qt():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import scripts.scrcpy_adb_bridge,sys; "
            "assert not any(x.startswith(('PySide6','qfluentwidgets')) for x in sys.modules)",
        ],
        capture_output=True,
        timeout=10,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_session_is_bound_once_then_all_commands_use_same_scid(environment):
    module = bridge()
    args = ["localabstract:scrcpy_1234abcd", "tcp:27183"]
    assert module.session_scid(environment, "reverse", args) == "1234abcd"
    assert module.session_scid(environment, "reverse", ["--remove", args[0]]) == "1234abcd"
    with pytest.raises(ValueError):
        module.session_scid(environment, "forward", ["tcp:27184", "localabstract:scrcpy_deadbeef"])
    state = json.loads(Path(environment["ADBLAB_SCRCPY_SESSION_FILE"]).read_text())
    assert state["scid"] == "1234abcd"


@pytest.mark.parametrize(
    "command,args",
    [
        ("reverse", ["--remove", "localabstract:scrcpy_1234abcd"]),
        ("forward", ["--remove", "tcp:27183"]),
        ("reverse", ["localabstract:scrcpy_1234abcd", "tcp:1234"]),
        (
            "shell",
            [
                "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
                "app_process",
                "/",
                "com.genymobile.scrcpy.Server",
                "4.1",
                "scid=1234abcd",
            ],
        ),
    ],
)
def test_invalid_or_cleanup_command_cannot_initialize_session(environment, command, args):
    with pytest.raises(ValueError):
        bridge().session_scid(environment, command, args)
    assert not Path(environment["ADBLAB_SCRCPY_SESSION_FILE"]).exists()


def test_session_file_cannot_be_reused_for_different_target(environment):
    module = bridge()
    args = ["localabstract:scrcpy_1234abcd", "tcp:27183"]
    module.session_scid(environment, "reverse", args)
    environment["ADBLAB_SCRCPY_SERIAL"] = "other-test-device"
    with pytest.raises(ValueError):
        module.session_scid(environment, "reverse", args)


@pytest.mark.parametrize(
    "args",
    [
        ["-s", "other-device", "shell", "getprop"],
        ["kill-server"],
        ["devices", "-x"],
        ["-s", "test-device", "shell", "getprop"],
        ["-H", "remote", "devices"],
        ["-s", "test-device", "push", "private-file", "/data/local/tmp/scrcpy-server.jar"],
    ],
)
def test_cli_rejects_unrelated_commands_before_network(environment, monkeypatch, capsys, args):
    module = bridge()

    def fail(*args, **kwargs):
        raise AssertionError("invalid request reached network")

    monkeypatch.setattr(module.ScrcpyAdbProtocol, "execute", fail)
    assert module.main(args) == 2
    output = capsys.readouterr()
    assert "test-device" not in output.err and "private-file" not in output.err


@pytest.mark.parametrize(
    "key,value",
    [
        ("ADB_SERVER_SOCKET", "tcp:10.1.2.3:5037"),
        ("ANDROID_ADB_SERVER_ADDRESS", "adb.example.invalid"),
        ("ANDROID_ADB_SERVER_PORT", "5038"),
    ],
)
def test_nonlocal_environment_is_rejected_before_probe(monkeypatch, capsys, key, value):
    module = bridge()
    monkeypatch.setenv(key, value)

    def fail(**kwargs):
        raise AssertionError("nonlocal environment reached probe")

    monkeypatch.setattr(module, "host_version", fail)
    assert module.main(["--probe-server"]) == 2
    assert value not in capsys.readouterr().err


def test_missing_server_probe_fails_and_does_not_fake_start(environment, monkeypatch, capsys):
    module = bridge()

    def fail(**kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(module, "host_version", fail)
    assert module.main(["--probe-server"]) == 1
    assert "unavailable" in capsys.readouterr().err


def test_cli_passes_parent_cancellation_and_exact_streams(environment, monkeypatch):
    module = bridge()
    outputs = []

    def execute(self, command, args, *, stdout, stderr):
        assert self.cancelled is not None and not self.cancelled()
        assert command == "devices" and args == ["-l"]
        outputs.extend((stdout, stderr))
        return 7

    monkeypatch.setattr(module.ScrcpyAdbProtocol, "execute", execute)
    assert module.main(["devices", "-l"]) == 7
    assert outputs == [sys.stdout.buffer, sys.stderr.buffer]


def test_cli_registers_private_upload_before_sending_even_when_transfer_fails(
    environment, monkeypatch, capsys,
):
    module = bridge()
    pending = Path(environment["ADBLAB_SCRCPY_SESSION_FILE"]).with_name("server.pending")

    def execute(self, command, args, *, stdout, stderr):
        assert command == "push"
        assert pending.is_file()
        token = module.session_token(pending.with_name("session.json"))
        assert self.remote_server.endswith(token + ".jar")
        raise TimeoutError

    monkeypatch.setattr(module.ScrcpyAdbProtocol, "execute", execute)
    assert module.main([
        "-s", "test-device", "push", environment["ADBLAB_SCRCPY_SERVER"],
        "/data/local/tmp/scrcpy-server.jar",
    ]) == 124
    assert pending.is_file()
    assert capsys.readouterr().out == ""


def test_cli_invalid_push_never_creates_upload_marker(environment, monkeypatch, capsys):
    module = bridge()
    pending = Path(environment["ADBLAB_SCRCPY_SESSION_FILE"]).with_name("server.pending")
    assert module.main([
        "-s", "test-device", "push", environment["ADBLAB_SCRCPY_SERVER"],
        "/data/local/tmp/unrelated.jar",
    ]) == 2
    assert not pending.exists()
    assert capsys.readouterr().out == ""


def test_lifetime_detects_owner_exit_and_releases_guard(environment):
    module = bridge()
    owner = subprocess.Popen(
        [sys._base_executable, "-c", "import sys;sys.stdin.buffer.read()"],
        stdin=subprocess.PIPE,
    )
    environment["ADBLAB_SCRCPY_OWNER_PID"] = str(owner.pid)
    try:
        with module.helper_lifetime(environment) as cancelled:
            assert not cancelled()
            owner.terminate()
            owner.wait(timeout=5)
            assert cancelled()
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        if owner.stdin:
            owner.stdin.close()


def test_lifetime_rejects_missing_parent_before_work(environment, monkeypatch):
    module = bridge()
    monkeypatch.setattr(module.os, "getppid", lambda: 0)
    with pytest.raises(ValueError):
        with module.helper_lifetime(environment):
            pytest.fail("missing parent admitted work")


def test_cli_idle_shell_exits_when_real_parent_dies(environment):
    module = bridge()
    module.session_scid(environment, "reverse", ["localabstract:scrcpy_1234abcd", "tcp:27183"])
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    shell = [
        "-s",
        "test-device",
        "shell",
        "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
        "app_process",
        "/",
        "com.genymobile.scrcpy.Server",
        "4.1",
        "scid=1234abcd",
    ]
    child_code = (
        "import socket,sys; original=socket.create_connection; "
        "socket.create_connection=lambda address,timeout: "
        f"original({listener.getsockname()!r},timeout); "
        f"from scripts.scrcpy_adb_bridge import main; sys.exit(main({shell!r}))"
    )
    parent_code = (
        "import subprocess,sys; "
        f"child=subprocess.Popen([{sys._base_executable!r},'-c',{child_code!r}]); "
        "print(child.pid,flush=True); child.wait()"
    )
    parent = subprocess.Popen(
        [sys._base_executable, "-c", parent_code],
        cwd=ROOT,
        env=dict(os.environ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child = None
    try:
        child_pid = int(parent.stdout.readline())
        child = module._ProcessWatch(child_pid)
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(5)

            def read(size):
                data = b""
                while len(data) < size:
                    chunk = connection.recv(size - len(data))
                    assert chunk, "helper disconnected before its shell handshake"
                    data += chunk
                return data

            assert read(int(read(4), 16)) == b"host:transport:test-device"
            connection.sendall(b"OKAY")
            assert read(int(read(4), 16)).startswith(b"shell,v2,raw:CLASSPATH=")
            connection.sendall(b"OKAY")
            assert read(5) == b"\x04\0\0\0\0"
            parent.terminate()
            parent.wait(timeout=5)
            assert connection.recv(1) == b""
        deadline = time.monotonic() + 5
        while child.alive() and time.monotonic() < deadline:
            threading.Event().wait(0.02)
        assert not child.alive()
        from core.scrcpy_session import has_active_helpers

        assert not has_active_helpers(Path(environment["ADBLAB_SCRCPY_SESSION_FILE"]))
    finally:
        if parent.poll() is None:
            parent.kill()
        _, diagnostic = parent.communicate(timeout=5)
        if diagnostic:
            print(diagnostic.decode(errors="replace"))
        listener.close()
        if child is not None:
            child.close()


def test_cli_missing_stderr_keeps_stdout_protocol_pure(environment, monkeypatch, capsys):
    module = bridge()

    def execute(self, command, args, *, stdout, stderr):
        stdout.write(b"List of devices attached\ntest-device\tdevice\n\n")
        stderr.write(b"discarded diagnostic\n")
        return 0

    monkeypatch.setattr(module.ScrcpyAdbProtocol, "execute", execute)
    monkeypatch.setattr(sys, "stderr", None)
    assert module.main(["devices", "-l"]) == 0
    assert capsys.readouterr().out == "List of devices attached\ntest-device\tdevice\n\n"


def test_cli_missing_stderr_does_not_redirect_errors_into_stdout(monkeypatch, capsys):
    module = bridge()
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:example.invalid:5037")
    monkeypatch.setattr(sys, "stderr", None)
    assert module.main(["--probe-server"]) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("name", ["stdout", "stderr"])
@pytest.mark.parametrize("closed", [False, True])
def test_cli_absent_or_closed_standard_stream_keeps_exit_status(
    environment,
    monkeypatch,
    capsys,
    name,
    closed,
):
    module = bridge()
    unavailable = None
    if closed:
        unavailable = io.StringIO()
        unavailable.close()

    def execute(self, command, args, *, stdout, stderr):
        stdout.write(b"output\n")
        stderr.write(b"diagnostic\n")
        return 7

    monkeypatch.setattr(module.ScrcpyAdbProtocol, "execute", execute)
    monkeypatch.setattr(sys, name, unavailable)
    assert module.main(["devices", "-l"]) == 7
    output = capsys.readouterr()
    assert output.out == ("" if name == "stdout" else "output\n")
    assert output.err == ("" if name == "stderr" else "diagnostic\n")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows scrcpy inherits only its stdout pipe")
def test_cli_windows_stdout_only_handle_list(environment):
    import msvcrt

    read_fd, write_fd = os.pipe()
    write_handle = msvcrt.get_osfhandle(write_fd)
    os.set_handle_inheritable(write_handle, True)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESTDHANDLES
    startup.hStdInput = 0
    startup.hStdOutput = write_handle
    startup.hStdError = 0
    startup.lpAttributeList = {"handle_list": [write_handle]}
    code = (
        "import sys; assert sys.stderr is None; "
        "from scripts.scrcpy_adb_bridge import main,ScrcpyAdbProtocol; "
        "ScrcpyAdbProtocol.execute=lambda self,command,args,stdout,stderr: "
        "(stdout.write(b'List of devices attached\\n\\n') and 0); "
        "sys.exit(main(['devices','-l']))"
    )
    process = None
    try:
        process = subprocess.Popen(
            [sys._base_executable, "-c", code],
            startupinfo=startup,
            close_fds=True,
            cwd=ROOT,
            env=dict(os.environ),
        )
        os.close(write_fd)
        write_fd = None
        process.wait(timeout=10)
        output = os.read(read_fd, 65536)
        assert process.returncode == 0
        assert output == b"List of devices attached\n\n"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if write_fd is not None:
            os.close(write_fd)
        os.close(read_fd)
