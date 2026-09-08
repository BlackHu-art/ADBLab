"""独立快速 ADB 入口的分帧、错误、目标和清理契约。"""

import io
import struct

import pytest

from core import adb_transport
from scripts import adb_fast


def frame(channel, data):
    return struct.pack("<BI", channel, len(data)) + data


def adb_string(data):
    return f"{len(data):04x}".encode() + data


class FakeSocket:
    def __init__(self, response):
        self.response = bytearray(response)
        self.sent = []
        self.closed = False
        self.timeouts = []

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        # 强制跨包读取，覆盖 TCP 不保留消息边界的情况。
        size = min(size, 2)
        data = bytes(self.response[:size])
        del self.response[:size]
        return data

    def close(self):
        self.closed = True


@pytest.fixture
def connect(monkeypatch):
    for name in (
        "ANDROID_SERIAL",
        "ADB_SERVER_SOCKET",
        "ANDROID_ADB_SERVER_ADDRESS",
        "ANDROID_ADB_SERVER_PORT",
    ):
        monkeypatch.delenv(name, raising=False)
    calls = []

    def install(response):
        sock = FakeSocket(response)

        def create(address, timeout):
            calls.append((address, timeout))
            return sock

        monkeypatch.setattr(adb_transport.socket, "create_connection", create)
        return sock

    return install, calls


def run_shell(serial="test-device"):
    stdout, stderr = io.BytesIO(), io.BytesIO()
    code = adb_fast.execute(
        "shell",
        ["printf 'a b'"],
        serial=serial,
        timeout=3,
        stdout=stdout,
        stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def test_shell_preserves_binary_streams_exit_code_and_command(connect):
    install, calls = connect
    sock = install(
        b"OKAYOKAY" + frame(1, b"a b\x00\xff") + frame(2, b"failure") + frame(3, b"\x07")
    )
    assert run_shell() == (7, b"a b\x00\xff", b"failure")
    assert calls == [(("127.0.0.1", 5037), 3)]
    assert sock.sent == [
        adb_string(b"host:transport:test-device"),
        adb_string(b"shell,v2,raw:printf 'a b'"),
        frame(4, b""),
    ]
    assert sock.closed


def test_capture_streams_frames_to_caller_file_without_buffering_or_closing(connect, tmp_path):
    install, calls = connect
    payload = b"\x89PNG\r\n\x1a\n\x00\xff\x80"
    sock = install(
        b"OKAYOKAY" + frame(1, payload[:5]) + frame(2, b"warning")
        + frame(1, payload[5:]) + frame(3, b"\0")
    )
    path = tmp_path / "binary.part"
    with path.open("wb") as sink:
        result = adb_transport.capture(
            "shell", ["screencap", "-p"], serial="test-device", timeout=3,
            stdout_sink=sink,
        )
        assert not sink.closed
        assert path.read_bytes() == payload
    assert result.kind == "completed" and result.returncode == 0
    assert result.stdout == b"" and result.stderr == b"warning"
    assert sock.closed and len(calls) == 1


@pytest.mark.parametrize("method", ["write", "flush"])
def test_file_sink_failure_closes_connection_and_remains_local(connect, monkeypatch, method):
    install, calls = connect
    sock = install(b"OKAYOKAY" + frame(1, b"partial") + frame(3, b"\0"))
    sink = io.BytesIO()

    def fail(*args):
        raise OSError("private output path")

    monkeypatch.setattr(sink, method, fail)
    result = adb_transport.capture(
        "shell", ["screencap", "-p"], serial="test-device", timeout=3, stdout_sink=sink,
    )
    assert result.kind == "output"
    assert b"private" not in result.stderr
    assert not sink.closed
    assert sock.closed and len(calls) == 1


@pytest.mark.parametrize("args,service", [([], b"host:devices"), (["-l"], b"host:devices-l")])
def test_devices_output(connect, args, service):
    install, _ = connect
    payload = b"test-device\tdevice\n"
    sock = install(b"OKAY" + adb_string(payload))
    stdout = io.BytesIO()
    assert (
        adb_fast.execute(
            "devices", args, serial=None, timeout=3, stdout=stdout, stderr=io.BytesIO()
        )
        == 0
    )
    assert stdout.getvalue() == b"List of devices attached\n" + payload + b"\n"
    assert sock.sent == [adb_string(service)]
    assert sock.closed


@pytest.mark.parametrize(
    "message,expected",
    [
        (b"more than one device/emulator", "Multiple devices"),
        (b"device offline", "offline"),
        (b"device unauthorized", "unauthorized"),
        (b"device 'test-device' not found", "not found"),
        (b"no devices/emulators found", "No device"),
    ],
)
def test_selection_failure_never_sends_shell_or_leaks_serial(connect, message, expected):
    install, calls = connect
    sock = install(b"FAIL" + adb_string(message))
    with pytest.raises(adb_fast.AdbError, match=expected) as error:
        run_shell(serial=None)
    assert "test-device" not in str(error.value)
    assert sock.sent == [adb_string(b"host:transport-any")]
    assert len(calls) == 1
    assert sock.closed


@pytest.mark.parametrize(
    "tail",
    [
        b"",
        frame(1, b"partial"),
        frame(3, b""),
        frame(3, b"\0\0"),
        frame(99, b""),
        struct.pack("<BI", 1, 1024 * 1024 + 1),
    ],
)
def test_incomplete_or_invalid_shell_response_fails_without_replay(connect, tail):
    install, calls = connect
    sock = install(b"OKAYOKAY" + tail)
    with pytest.raises(adb_fast.AdbError):
        run_shell()
    assert len(calls) == 1
    assert sock.closed


def test_unsupported_shell_does_not_fallback(connect):
    install, calls = connect
    sock = install(b"OKAYFAIL" + adb_string(b"unknown service for test-device"))
    with pytest.raises(adb_fast.AdbError, match="shell v2") as error:
        run_shell()
    assert "test-device" not in str(error.value)
    assert len(calls) == 1
    assert sock.closed


def test_deadline_expires_despite_incoming_data(connect, monkeypatch):
    install, calls = connect
    sock = install(b"OKAYOKAY" + frame(1, b"lots of output") + frame(3, b"\0"))
    ticks = iter(range(100))
    monkeypatch.setattr(adb_transport.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        run_shell()
    assert sock.timeouts == [2, 1]
    assert sock.closed
    assert len(calls) == 1


@pytest.mark.parametrize("failure,code", [(TimeoutError, 124), (KeyboardInterrupt, 130)])
def test_cli_abort_closes_connection_without_retry(connect, monkeypatch, capsys, failure, code):
    install, calls = connect
    sock = install(b"OKAYOKAY")

    def fail_read(size):
        raise failure

    monkeypatch.setattr(sock, "recv", fail_read)
    assert adb_fast.main(["-s", "test-device", "shell", "echo ok"]) == code
    assert "test-device" not in capsys.readouterr().err
    assert sock.closed
    assert len(calls) == 1


@pytest.mark.parametrize(
    "args",
    [
        ["shell"],
        ["shell", "-t", "echo ok"],
        ["shell", " "],
        ["devices", "--bad"],
        ["push", "a", "b"],
        ["--timeout", "nan", "devices"],
        ["--timeout", "0", "devices"],
        ["--timeout", "inf", "devices"],
        ["-s", "bad\nselector", "shell", "echo ok"],
    ],
)
def test_invalid_cli_never_connects(connect, args):
    install, calls = connect
    install(b"")
    with pytest.raises(SystemExit) as error:
        adb_fast.main(args)
    assert error.value.code == 2
    assert not calls


def test_server_environment_cannot_silently_select_wrong_server(connect, monkeypatch):
    install, calls = connect
    install(b"")
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:localhost:5038")
    with pytest.raises(SystemExit):
        adb_fast.main(["devices"])
    assert not calls


def test_cli_honors_explicit_serial_over_environment(connect, monkeypatch, capsys):
    install, _ = connect
    sock = install(b"OKAYOKAY" + frame(1, b"ok\n") + frame(3, b"\0"))
    monkeypatch.setenv("ANDROID_SERIAL", "env-device")
    assert adb_fast.main(["-s", "explicit-device", "shell", "echo", "ok"]) == 0
    assert sock.sent[0] == adb_string(b"host:transport:explicit-device")
    assert capsys.readouterr().out == "ok\n"


def test_missing_server_is_actionable_without_starting_process(connect, monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(adb_transport.socket, "create_connection", refuse)
    assert adb_fast.main(["devices"]) == 1
    assert "adb start-server" in capsys.readouterr().err
