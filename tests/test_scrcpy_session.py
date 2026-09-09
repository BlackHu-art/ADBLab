"""scrcpy helper 租约及绑定会话隧道清理回归。"""

import importlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from core import adb_transport


def module():
    return importlib.import_module("core.scrcpy_session")


def test_lease_is_active_until_release_then_directory_can_be_cleaned(tmp_path):
    session = tmp_path / "session.json"
    subject = module()
    assert not subject.has_active_helpers(session)
    with subject.helper_lease(session):
        assert subject.has_active_helpers(session)
        assert len(list(tmp_path.glob("helper-*.lease"))) == 1
    assert not subject.has_active_helpers(session)
    assert not list(tmp_path.glob("helper-*.lease"))


def test_killed_helper_automatically_releases_os_lease(tmp_path):
    session = tmp_path / "session.json"
    subject = module()
    code = (
        "from pathlib import Path; from core.scrcpy_session import helper_lease; import sys; "
        "lease=helper_lease(Path(sys.argv[1])); lease.__enter__(); print('ready',flush=True); "
        "sys.stdin.buffer.read()"
    )
    process = subprocess.Popen(
        [sys._base_executable, "-c", code, str(session)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    try:
        assert process.stdout.readline().strip() == b"ready"
        assert subject.has_active_helpers(session)
        process.kill()
        process.wait(timeout=5)
        assert not subject.has_active_helpers(session)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()


class ReplySocket:
    def __init__(self, reply):
        self.reply = bytearray(reply)
        self.sent = []
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        size = min(size, 2)
        result = bytes(self.reply[:size])
        del self.reply[:size]
        return result

    def close(self):
        self.closed = True


def adb_string(data):
    return f"{len(data):04x}".encode() + data


@pytest.fixture
def environment(tmp_path):
    server = tmp_path / "scrcpy-server"
    server.write_bytes(b"jar")
    env = {
        "ADBLAB_SCRCPY_SERIAL": "test-device",
        "ADBLAB_SCRCPY_SERVER": str(server),
        "ADBLAB_SCRCPY_OWNER_PID": str(os.getpid()),
        "ADBLAB_SCRCPY_PORT_RANGE": "27183:27199",
        "ADBLAB_SCRCPY_SESSION_FILE": str(tmp_path / "session.json"),
    }
    return env


def test_cleanup_removes_only_current_scid_mappings(environment, monkeypatch):
    subject = module()
    subject.session_scid(environment, "reverse", ["localabstract:scrcpy_1234abcd", "tcp:27183"])
    forwards = (
        b"test-device tcp:27183 localabstract:scrcpy_1234abcd\n"
        b"other-device tcp:27184 localabstract:scrcpy_1234abcd\n"
        b"test-device tcp:27185 localabstract:scrcpy_deadbeef\n"
    )
    reverse = (
        b"host localabstract:scrcpy_1234abcd tcp:27183\n"
        b"host localabstract:scrcpy_deadbeef tcp:27184\n"
    )
    replies = [
        b"OKAY" + adb_string(forwards),
        b"OKAYOKAY" + adb_string(reverse),
        b"OKAY" + adb_string(forwards),
        b"OKAYOKAY",
        b"OKAYOKAYOKAY",
    ]
    sockets = [ReplySocket(reply) for reply in replies]
    connected = []

    def connect(address, timeout):
        sock = sockets[len(connected)]
        connected.append(sock)
        return sock

    monkeypatch.setattr(adb_transport.socket, "create_connection", connect)
    subject.cleanup_session_tunnels(environment, timeout=3)
    requests = [data[4:].decode() for sock in connected for data in sock.sent]
    assert requests == [
        "host:list-forward",
        "host:transport:test-device",
        "reverse:list-forward",
        "host:list-forward",
        "host-serial:test-device:killforward:tcp:27183",
        "host:transport:test-device",
        "reverse:killforward:localabstract:scrcpy_1234abcd",
    ]
    assert all(sock.closed for sock in sockets)


def test_cleanup_missing_state_does_not_touch_server(environment, monkeypatch):
    subject = module()

    def fail(*args, **kwargs):
        pytest.fail("unbound session reached server")

    monkeypatch.setattr(adb_transport.socket, "create_connection", fail)
    subject.cleanup_session_tunnels(environment)


def test_pending_upload_without_tunnel_cleans_only_its_private_jar(environment, monkeypatch):
    subject = module()
    subject.mark_server_pending(environment)
    path = Path(environment["ADBLAB_SCRCPY_SESSION_FILE"])
    assert not path.exists()
    assert path.with_name("server.pending").is_file()
    reply = b"OKAYOKAY" + struct.pack("<BI", 3, 1) + b"\0"
    sock = ReplySocket(reply)
    monkeypatch.setattr(adb_transport.socket, "create_connection", lambda *_args, **_kwargs: sock)
    subject.cleanup_session_tunnels(environment)
    assert sock.sent[:2] == [
        adb_string(b"host:transport:test-device"),
        adb_string((
            "shell,v2,raw:rm -f /data/local/tmp/adblab-scrcpy-"
            + subject.session_token(path) + ".jar"
        ).encode()),
    ]
    assert sock.closed


def test_pending_upload_identity_is_checked_before_cleanup(environment, monkeypatch):
    subject = module()
    subject.mark_server_pending(environment)
    environment["ADBLAB_SCRCPY_SERIAL"] = "different-test-device"

    def fail(*args, **kwargs):
        pytest.fail("untrusted pending upload reached server")

    monkeypatch.setattr(adb_transport.socket, "create_connection", fail)
    with pytest.raises(ValueError):
        subject.cleanup_session_tunnels(environment)


def test_same_device_distinct_session_directories_have_private_tokens(environment, tmp_path):
    subject = module()
    first = Path(environment["ADBLAB_SCRCPY_SESSION_FILE"])
    other = tmp_path / "another-session"
    other.mkdir()
    second = other / "session.json"
    assert subject.session_token(first) == subject.session_token(first.resolve())
    assert subject.session_token(first) != subject.session_token(second)
    assert len(subject.session_token(first)) == 32


def test_cleanup_corrupt_or_different_identity_is_rejected(environment, monkeypatch):
    subject = module()
    path = Path(environment["ADBLAB_SCRCPY_SESSION_FILE"])
    path.write_text(json.dumps({"identity": "unrelated", "scid": "1234abcd"}))

    def fail(*args, **kwargs):
        pytest.fail("untrusted session reached server")

    monkeypatch.setattr(adb_transport.socket, "create_connection", fail)
    with pytest.raises(ValueError):
        subject.cleanup_session_tunnels(environment)


def test_cleanup_connection_error_is_not_reported_as_success(environment, monkeypatch):
    subject = module()
    subject.session_scid(environment, "reverse", ["localabstract:scrcpy_1234abcd", "tcp:27183"])

    def fail(*args, **kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(adb_transport.socket, "create_connection", fail)
    with pytest.raises(ConnectionRefusedError):
        subject.cleanup_session_tunnels(environment)


def test_cleanup_all_queries_share_total_deadline(environment, monkeypatch):
    subject = module()
    subject.session_scid(environment, "reverse", ["localabstract:scrcpy_1234abcd", "tcp:27183"])
    now = [0.0]
    calls = []
    monkeypatch.setattr(adb_transport.time, "monotonic", lambda: now[0])
    sock = ReplySocket(b"OKAY0000")
    original_recv = sock.recv

    def recv(size):
        result = original_recv(size)
        if not sock.reply:
            now[0] = 4.0
        return result

    sock.recv = recv

    def connect(address, timeout):
        calls.append(timeout)
        return sock

    monkeypatch.setattr(adb_transport.socket, "create_connection", connect)
    with pytest.raises(TimeoutError):
        subject.cleanup_session_tunnels(environment, timeout=3)
    assert len(calls) == 1 and sock.closed
