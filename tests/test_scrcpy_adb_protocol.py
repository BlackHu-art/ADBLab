"""scrcpy 专用传输的固定目标、帧协议与会话终止回归。"""

import importlib
import io
import socket
import struct
import threading

import pytest

from core import adb_transport


def protocol_module():
    return importlib.import_module("core.scrcpy_adb_protocol")


def adb_string(data):
    return f"{len(data):04x}".encode() + data


def frame(channel, data):
    return struct.pack("<BI", channel, len(data)) + data


SHELL = [
    "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
    "app_process",
    "/",
    "com.genymobile.scrcpy.Server",
    "4.1",
    "scid=1234abcd",
    "log_level=info",
]
SESSION_TOKEN = "0123456789abcdef0123456789abcdef"
PRIVATE_SERVER = f"/data/local/tmp/adblab-scrcpy-{SESSION_TOKEN}.jar"


class FakeSocket:
    def __init__(self, response):
        self.response = bytearray(response)
        self.sent = []
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        size = min(size, 2)
        data = bytes(self.response[:size])
        del self.response[:size]
        return data

    def close(self):
        self.closed = True


@pytest.fixture
def connect(monkeypatch):
    sockets = []
    calls = []

    def install(*responses):
        sockets.extend(FakeSocket(response) for response in responses)
        return sockets

    def create(address, timeout):
        calls.append((address, timeout))
        return sockets[len(calls) - 1]

    monkeypatch.setattr(adb_transport.socket, "create_connection", create)
    return install, calls


def client(tmp_path, **kwargs):
    server = tmp_path / "scrcpy-server"
    server.write_bytes(b"jar-content")
    return protocol_module().ScrcpyAdbProtocol(
        "test-device",
        server,
        scid="1234abcd",
        port_range=(27183, 27199),
        session_token=kwargs.pop("session_token", SESSION_TOKEN),
        **kwargs,
    )


def run(subject, command, args):
    stdout, stderr = io.BytesIO(), io.BytesIO()
    code = subject.execute(command, args, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_host_probe_validates_actual_response_and_never_starts_server(connect):
    install, calls = connect
    sock = install(b"OKAY00040029")[0]
    assert protocol_module().host_version(timeout=2) == 41
    assert sock.sent == [adb_string(b"host:version")]
    assert sock.closed and len(calls) == 1


@pytest.mark.parametrize("reply", [b"OKAY0000", b"OKAY0004oops", b"OKAY00040000", b"FAIL0004oops"])
def test_invalid_host_probe_fails_without_replay(connect, reply):
    install, calls = connect
    sock = install(reply)[0]
    with pytest.raises(adb_transport.AdbError):
        protocol_module().host_version(timeout=2)
    assert sock.closed and len(calls) == 1


def test_devices_stdout_remains_native_compatible(connect, tmp_path):
    install, _ = connect
    payload = b"test-device\tdevice product:test model:Test transport_id:2\n"
    sock = install(b"OKAY" + adb_string(payload))[0]
    assert run(client(tmp_path), "devices", ["-l"]) == (
        0,
        b"List of devices attached\n" + payload + b"\n",
        b"",
    )
    assert sock.sent == [adb_string(b"host:devices-l")] and sock.closed


def test_push_sends_only_trusted_jar_in_bounded_sync_chunks(connect, tmp_path):
    install, _ = connect
    sock = install(b"OKAYOKAY" + struct.pack("<4sI", b"OKAY", 0))[0]
    subject = client(tmp_path)
    payload = b"x" * (65536 + 5)
    subject.server_path.write_bytes(payload)
    assert (
        run(subject, "push", [str(subject.server_path), "/data/local/tmp/scrcpy-server.jar"])[0]
        == 0
    )
    assert sock.sent[:2] == [adb_string(b"host:transport:test-device"), adb_string(b"sync:")]
    sent = b"".join(sock.sent[2:])
    path = (PRIVATE_SERVER + ",33188").encode()
    assert sent.startswith(struct.pack("<4sI", b"SEND", len(path)) + path)
    offset = 8 + len(path)
    assert sent[offset : offset + 8] == struct.pack("<4sI", b"DATA", 65536)
    offset += 8 + 65536
    assert sent[offset : offset + 13] == struct.pack("<4sI", b"DATA", 5) + b"xxxxx"
    assert sent[offset + 13 : offset + 17] == b"DONE"
    assert sock.closed


def test_sync_failure_does_not_report_success_or_replay(connect, tmp_path):
    install, calls = connect
    sock = install(b"OKAYOKAY" + struct.pack("<4sI", b"FAIL", 7) + b"private")[0]
    subject = client(tmp_path)
    with pytest.raises(adb_transport.AdbError) as error:
        run(subject, "push", [str(subject.server_path), "/data/local/tmp/scrcpy-server.jar"])
    assert "private" not in str(error.value)
    assert sock.closed and len(calls) == 1


@pytest.mark.parametrize(
    "command,args,requests",
    [
        (
            "forward",
            ["tcp:27183", "localabstract:scrcpy_1234abcd"],
            [b"host-serial:test-device:forward:norebind:tcp:27183;localabstract:scrcpy_1234abcd"],
        ),
        (
            "reverse",
            ["localabstract:scrcpy_1234abcd", "tcp:27183"],
            [
                b"host:transport:test-device",
                b"reverse:forward:norebind:localabstract:scrcpy_1234abcd;tcp:27183",
            ],
        ),
        (
            "reverse",
            ["--remove", "localabstract:scrcpy_1234abcd"],
            [b"host:transport:test-device", b"reverse:killforward:localabstract:scrcpy_1234abcd"],
        ),
    ],
)
def test_tunnel_requests_preserve_target_and_never_rebind(
    connect, tmp_path, command, args, requests
):
    install, _ = connect
    sock = install(b"OKAY" * (len(requests) + 1))[0]
    assert run(client(tmp_path), command, args) == (0, b"", b"")
    assert sock.sent == [adb_string(request) for request in requests]
    assert sock.closed


@pytest.mark.parametrize(
    "mapping,allowed",
    [
        (b"test-device tcp:27183 localabstract:scrcpy_1234abcd\n", True),
        (b"test-device tcp:27183 localabstract:scrcpy_deadbeef\n", False),
        (b"another-device tcp:27183 localabstract:scrcpy_1234abcd\n", False),
        (b"", False),
    ],
)
def test_forward_remove_requires_live_mapping_owned_by_session(connect, tmp_path, mapping, allowed):
    install, calls = connect
    socks = install(b"OKAY" + adb_string(mapping), b"OKAYOKAY")
    subject = client(tmp_path)
    if allowed:
        assert run(subject, "forward", ["--remove", "tcp:27183"])[0] == 0
        assert socks[1].sent == [adb_string(b"host-serial:test-device:killforward:tcp:27183")]
    else:
        with pytest.raises(adb_transport.AdbError):
            run(subject, "forward", ["--remove", "tcp:27183"])
    assert len(calls) == (2 if allowed else 1)
    assert socks[0].sent == [adb_string(b"host:list-forward")]


def test_tunnel_second_status_failure_is_not_success(connect, tmp_path):
    install, calls = connect
    sock = install(b"OKAYFAIL" + adb_string(b"private bind failure"))[0]
    with pytest.raises(adb_transport.AdbError):
        run(client(tmp_path), "forward", ["tcp:27183", "localabstract:scrcpy_1234abcd"])
    assert sock.closed and len(calls) == 1


def test_shell_preserves_both_streams_exit_code_and_closes_stdin(connect, tmp_path):
    install, calls = connect
    sock = install(b"OKAYOKAY" + frame(1, b"a\x00\xff") + frame(2, b"warning") + frame(3, b"\x07"))[
        0
    ]
    assert run(client(tmp_path), "shell", SHELL) == (7, b"a\x00\xff", b"warning")
    assert sock.sent == [
        adb_string(b"host:transport:test-device"),
        adb_string(
            ("shell,v2,raw:CLASSPATH=" + PRIVATE_SERVER + " " + " ".join(SHELL[1:])).encode()
        ),
        frame(4, b""),
    ]
    assert sock.closed and len(calls) == 1


def test_same_device_launches_use_distinct_jar_paths_without_changing_native_argv(
    connect, tmp_path,
):
    install, _ = connect
    sockets = install(*(b"OKAYOKAY" + frame(3, b"\0") for _ in range(2)))
    second_token = "fedcba9876543210fedcba9876543210"
    original = list(SHELL)
    first = client(tmp_path)
    second = client(tmp_path, session_token=second_token)
    assert run(first, "shell", SHELL)[0] == run(second, "shell", SHELL)[0] == 0
    assert SHELL == original
    assert SESSION_TOKEN.encode() in sockets[0].sent[1]
    assert second_token.encode() in sockets[1].sent[1]
    assert sockets[0].sent[1] != sockets[1].sent[1]


@pytest.mark.parametrize("token", ["", "../other", "a" * 31, "A" * 32, "a" * 33])
def test_private_server_token_cannot_escape_the_fixed_path(connect, tmp_path, token):
    _, calls = connect
    with pytest.raises(ValueError):
        client(tmp_path, session_token=token)
    assert not calls


def test_owner_cleanup_removes_only_private_jar_and_does_not_expose_rm_to_cli(connect, tmp_path):
    install, calls = connect
    sock = install(b"OKAYOKAY" + frame(3, b"\0"))[0]
    subject = client(tmp_path)
    subject.cleanup_server()
    assert sock.sent == [
        adb_string(b"host:transport:test-device"),
        adb_string(("shell,v2,raw:rm -f " + PRIVATE_SERVER).encode()),
        frame(4, b""),
    ]
    with pytest.raises(ValueError):
        run(subject, "shell", ["rm", "-f", PRIVATE_SERVER])
    with pytest.raises(ValueError):
        run(subject, "shell", ["CLASSPATH=" + PRIVATE_SERVER, *SHELL[1:]])
    assert len(calls) == 1 and sock.closed


def test_private_jar_cleanup_failure_is_not_success_or_replayed(connect, tmp_path):
    install, calls = connect
    sock = install(b"OKAYOKAY" + frame(2, b"private-device-info") + frame(3, b"\x01"))[0]
    with pytest.raises(adb_transport.AdbError) as error:
        client(tmp_path).cleanup_server()
    assert "private-device-info" not in str(error.value)
    assert len(calls) == 1 and sock.closed


def test_private_jar_cleanup_retains_total_deadline(connect, tmp_path, monkeypatch):
    install, calls = connect
    sock = install(b"OKAYOKAY" + frame(3, b"\0"))[0]
    now = [0.0]
    original = sock.recv

    def recv(size):
        if len(sock.sent) == 3:
            now[0] = 4.0
        return original(size)

    sock.recv = recv
    monkeypatch.setattr(adb_transport.time, "monotonic", lambda: now[0])
    with pytest.raises(TimeoutError):
        client(tmp_path, timeout=3).cleanup_server()
    assert len(calls) == 1 and sock.closed


def test_shell_running_stream_has_no_short_command_deadline(connect, tmp_path, monkeypatch):
    install, _ = connect
    sock = install(b"OKAYOKAY" + frame(1, b"still running") + frame(3, b"\0"))[0]
    original = sock.recv
    now = [0.0]

    def receive(size):
        if len(sock.sent) == 3:
            now[0] += 31
        return original(size)

    monkeypatch.setattr(adb_transport.time, "monotonic", lambda: now[0])
    sock.recv = receive
    assert run(client(tmp_path, timeout=1), "shell", SHELL) == (0, b"still running", b"")


@pytest.mark.parametrize(
    "tail",
    [b"", frame(1, b"partial"), frame(3, b""), frame(99, b""), struct.pack("<BI", 1, 1048577)],
)
def test_bad_shell_stream_fails_without_replay(connect, tmp_path, tail):
    install, calls = connect
    sock = install(b"OKAYOKAY" + tail)[0]
    with pytest.raises(adb_transport.AdbError):
        run(client(tmp_path), "shell", SHELL)
    assert sock.closed and len(calls) == 1


@pytest.mark.parametrize(
    "command,args",
    [
        ("kill-server", []),
        ("shell", ["getprop"]),
        ("shell", SHELL + ["audio=false;id"]),
        ("shell", SHELL + ["scid=deadbeef"]),
        ("shell", SHELL[:4] + ["4.0"] + SHELL[5:]),
        ("forward", ["--remove-all"]),
        ("forward", ["tcp:28000", "localabstract:scrcpy_1234abcd"]),
        ("reverse", ["--remove", "localabstract:scrcpy_deadbeef"]),
        ("push", ["private-file", "/data/local/tmp/scrcpy-server.jar"]),
    ],
)
def test_invalid_command_is_rejected_before_connect(connect, tmp_path, command, args):
    _, calls = connect
    with pytest.raises(ValueError):
        run(client(tmp_path), command, args)
    assert not calls


def test_idle_shell_checks_cancellation_and_closes_real_tcp_socket(tmp_path, monkeypatch):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    cancelled = threading.Event()
    finished = threading.Event()
    errors = []
    original_connect = socket.create_connection

    def server():
        try:
            conn, _ = listener.accept()
            conn.settimeout(3)
            with conn:
                for _ in range(2):
                    length = int(_read(conn, 4), 16)
                    _read(conn, length)
                    conn.sendall(b"OKAY")
                assert _read(conn, 5) == frame(4, b"")
                cancelled.set()
                assert conn.recv(1) == b""
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    def redirect(address, timeout):
        assert address == ("127.0.0.1", 5037)
        return original_connect(listener.getsockname(), timeout)

    monkeypatch.setattr(adb_transport.socket, "create_connection", redirect)
    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    try:
        with pytest.raises(adb_transport.CommandCancelled):
            run(client(tmp_path, cancelled=cancelled.is_set), "shell", SHELL)
        assert finished.wait(3)
        assert not errors
    finally:
        listener.close()
        thread.join(3)


def _read(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise AssertionError("premature EOF")
        data += chunk
    return data


def test_cancelled_before_admission_never_connects(connect, tmp_path):
    _, calls = connect
    with pytest.raises(adb_transport.CommandCancelled):
        run(client(tmp_path, cancelled=lambda: True), "shell", SHELL)
    assert not calls


def test_push_cancellation_closes_without_done_or_replay(connect, tmp_path):
    install, calls = connect
    sock = install(b"OKAYOKAY")[0]
    subject = client(tmp_path, cancelled=lambda: len(sock.sent) >= 4)
    with pytest.raises(adb_transport.CommandCancelled):
        run(subject, "push", [str(subject.server_path), "/data/local/tmp/scrcpy-server.jar"])
    assert not any(data.startswith(b"DONE") for data in sock.sent)
    assert sock.closed and len(calls) == 1


def test_shell_handshake_timeout_remains_bounded(connect, tmp_path, monkeypatch):
    install, calls = connect
    sock = install(b"OKAYOKAY")[0]
    original = sock.recv
    now = [0.0]

    def recv(size):
        result = original(size)
        now[0] += 2.0
        return result

    monkeypatch.setattr(adb_transport.time, "monotonic", lambda: now[0])
    sock.recv = recv
    with pytest.raises(TimeoutError):
        run(client(tmp_path, timeout=1), "shell", SHELL)
    assert sock.closed and len(calls) == 1
    assert len(sock.sent) == 1


def test_shell_output_failure_closes_socket_without_replay(connect, tmp_path):
    install, calls = connect
    sock = install(b"OKAYOKAY" + frame(1, b"payload"))[0]

    class BrokenSink(io.BytesIO):
        def write(self, data):
            raise OSError("private-output-path")

    with pytest.raises(adb_transport.OutputError) as error:
        client(tmp_path).execute("shell", SHELL, stdout=BrokenSink(), stderr=io.BytesIO())
    assert "private" not in str(error.value)
    assert sock.closed and len(calls) == 1
