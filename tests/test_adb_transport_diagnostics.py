"""直连诊断只记录固定阶段、计时和计数，不保存协议内容。"""

from dataclasses import FrozenInstanceError

import pytest

from core import adb_transport as transport


class ScriptedSocket:
    def __init__(self, chunks, fail_send=None):
        self.chunks = list(chunks)
        self.fail_send = fail_send
        self.closed = False

    def settimeout(self, timeout):
        pass

    def sendall(self, payload):
        if self.fail_send:
            raise self.fail_send

    def recv(self, size):
        value = self.chunks.pop(0)
        if isinstance(value, BaseException):
            raise value
        assert len(value) <= size
        return value

    def close(self):
        self.closed = True


def capture(monkeypatch, chunks, fail_send=None, cancelled=None):
    sock = ScriptedSocket(chunks, fail_send)
    monkeypatch.setattr(transport.socket, "create_connection", lambda *a, **k: sock)
    result = transport.capture("devices", [], serial=None, timeout=3, cancelled=cancelled)
    assert sock.closed
    return result


@pytest.mark.parametrize(
    "chunks,send_error,kind,stage,reason,count",
    [
        ([], TimeoutError("private"), "timeout", "send", "timeout", 0),
        ([TimeoutError("private")], None, "timeout", "read_status", "timeout", 0),
        ([b"OKAY", TimeoutError()], None, "timeout", "read_length", "timeout", 4),
        ([b"OKAY", b"0004", b"ab", TimeoutError()], None, "timeout", "read_payload", "timeout", 10),
        ([b"O", b""], None, "protocol", "read_status", "eof", 1),
        ([b"OKAY", b"0", b""], None, "protocol", "read_length", "eof", 5),
        ([b"OKAY", b"0004", b"a", b"b", b""], None, "protocol", "read_payload", "eof", 10),
        ([b"XXXX"], None, "protocol", "read_status", "invalid_status", 4),
        ([b"OKAY", b"zzzz"], None, "protocol", "read_length", "invalid_length", 8),
        ([b"FAIL", b"0007", b"private"], None, "protocol", "read_payload", "server_fail", 15),
        ([OSError(123, "private")], None, "transport", "read_status", "os_error", 0),
    ],
)
def test_failure_diagnostics_are_structured_and_private(
    monkeypatch, chunks, send_error, kind, stage, reason, count
):
    result = capture(monkeypatch, chunks, send_error)
    assert result.kind == kind
    diagnostic = result.diagnostics
    assert diagnostic is not None
    assert (diagnostic.stage, diagnostic.reason, diagnostic.received_bytes) == (
        stage,
        reason,
        count,
    )
    assert diagnostic.budget_ms == 3000
    assert 0 <= diagnostic.stage_ms <= diagnostic.elapsed_ms
    assert "private" not in repr(diagnostic)
    if reason == "os_error":
        assert diagnostic.errno == 123


@pytest.mark.parametrize(
    "error,kind,reason",
    [
        (TimeoutError("private"), "timeout", "timeout"),
        (ConnectionRefusedError(111, "private"), "unavailable", "connection_refused"),
        (OSError(123, "private"), "transport", "os_error"),
    ],
)
def test_constructor_failure_has_diagnostics(monkeypatch, error, kind, reason):
    def fail(*a, **k):
        raise error

    monkeypatch.setattr(transport.socket, "create_connection", fail)
    result = transport.capture("devices", [], serial=None, timeout=3)
    assert result.kind == kind
    assert result.diagnostics.stage == "connect"
    assert result.diagnostics.reason == reason
    assert "private" not in repr(result)


def test_poll_timeout_is_not_a_failure(monkeypatch):
    result = capture(monkeypatch, [TimeoutError(), b"OKAY", b"0000"], cancelled=lambda: False)
    assert result.kind == "completed"
    assert result.diagnostics is None


def test_result_preserves_positional_comparison_and_matching():
    diagnostic = transport.ExecutionDiagnostics("connect", "timeout", 1, 1, 3000)
    result = transport.ExecutionResult(b"a", b"b", 1, "timeout", diagnostics=diagnostic)
    assert result == transport.ExecutionResult(b"a", b"b", 1, "timeout")
    assert transport.ExecutionResult.__match_args__ == ("stdout", "stderr", "returncode", "kind")
    with pytest.raises(FrozenInstanceError):
        diagnostic.stage = "send"


def test_preconnect_cancellation_has_diagnostic_without_opening_socket(monkeypatch):
    def unexpected(*a, **k):
        pytest.fail("cancelled command must not connect")

    monkeypatch.setattr(transport.socket, "create_connection", unexpected)
    result = transport.capture("devices", [], serial=None, timeout=3, cancelled=lambda: True)
    assert result.kind == "cancelled"
    assert result.diagnostics.stage == "connect"
    assert result.diagnostics.reason == "cancelled"


def test_cancelled_during_poll_keeps_read_stage(monkeypatch):
    state = [False]
    sock = ScriptedSocket([])

    def recv(size):
        state[0] = True
        raise TimeoutError()

    sock.recv = recv
    monkeypatch.setattr(transport.socket, "create_connection", lambda *a, **k: sock)
    result = transport.capture("devices", [], serial=None, timeout=3, cancelled=lambda: state[0])
    assert result.kind == "cancelled"
    assert result.diagnostics.stage == "read_status"
    assert result.diagnostics.reason == "cancelled"
    assert sock.closed


def test_shell_invalid_frame_has_private_diagnostic(monkeypatch):
    import struct

    sock = ScriptedSocket([b"OKAY", b"OKAY", struct.pack("<BI", 99, 0)])
    monkeypatch.setattr(transport.socket, "create_connection", lambda *a, **k: sock)
    result = transport.capture("shell", ["private-command"], serial="private-serial", timeout=3)
    assert result.kind == "protocol"
    assert result.diagnostics.stage == "shell_frame"
    assert result.diagnostics.reason == "invalid_frame"
    assert "private" not in repr(result)
    assert sock.closed


def test_diagnostic_measures_stage_and_total_time(monkeypatch):
    now = [0.0]
    sock = ScriptedSocket([b"OKAY", b"0004", b"a", b""])
    original_recv = sock.recv

    def recv(size):
        now[0] += 0.1
        return original_recv(size)

    sock.recv = recv

    def connect(*a, **k):
        now[0] += 0.2
        return sock

    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport.socket, "create_connection", connect)
    result = transport.capture("devices", [], serial=None, timeout=3)
    assert result.diagnostics.elapsed_ms == pytest.approx(600)
    assert result.diagnostics.stage_ms == pytest.approx(200)
    assert result.diagnostics.received_bytes == 9
    assert sock.closed


def test_windows_error_number_is_preserved_without_exception_text(monkeypatch):
    error = OSError(22, "private-device")
    error.winerror = 10054
    result = capture(monkeypatch, [error])
    assert result.diagnostics.errno == 22
    assert result.diagnostics.winerror == 10054
    assert "private" not in repr(result)


@pytest.mark.parametrize(
    "error,kind,reason",
    [
        (OSError(123, "private"), "transport", "os_error"),
        (ConnectionRefusedError(111, "private"), "protocol", "connection_refused"),
    ],
)
def test_send_failure_keeps_no_replay_classification(monkeypatch, error, kind, reason):
    result = capture(monkeypatch, [], fail_send=error)
    assert result.kind == kind
    assert result.diagnostics.stage == "send"
    assert result.diagnostics.reason == reason
    assert result.diagnostics.errno == error.errno


def test_receive_polling_reaches_total_deadline_with_diagnostics(monkeypatch):
    now = [0.0]
    sock = ScriptedSocket([])

    def recv(size):
        now[0] += 0.1
        raise TimeoutError()

    sock.recv = recv
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport.socket, "create_connection", lambda *a, **k: sock)
    result = transport.capture("devices", [], serial=None, timeout=0.25, cancelled=lambda: False)
    assert result.kind == "timeout"
    assert result.diagnostics.stage == "read_status"
    assert result.diagnostics.elapsed_ms == pytest.approx(300)
    assert result.diagnostics.reason == "timeout"
    assert sock.closed
