"""模拟器补注册只使用本机候选，并由真实设备列表确认发现结果。"""

import socket
import time
from types import SimpleNamespace

import psutil
import pytest

from core import adb_discovery, adb_transport
from core.adb_discovery import _listening_emulator_ports as real_listening_emulator_ports
from core.adb_transport import ExecutionResult


def test_registers_late_emulator_without_waiting_for_notification_ack(monkeypatch):
    module = adb_discovery
    monkeypatch.setattr(module, "_listening_emulator_ports", lambda: {5555})
    sent = []
    closed = []

    class NotificationSocket:
        def setsockopt(self, *_):
            pass

        def settimeout(self, timeout):
            assert 0 < timeout <= 1

        def sendall(self, payload):
            sent.append(payload)

        def recv(self, _size):
            raise AssertionError("模拟器注册协议不返回 ACK")

        def close(self):
            closed.append(True)

    def connect(address, timeout):
        assert address == ("127.0.0.1", 5037)
        assert 0 < timeout <= 1
        return NotificationSocket()

    monkeypatch.setattr("core.adb_transport.socket.create_connection", connect)
    discovered = ExecutionResult(stdout=b"List of devices attached\nemulator-5554\tdevice\n")

    def capture(command, args, *, serial, timeout, cancelled):
        assert (command, args, serial) == ("devices", ["-l"], None)
        assert 0 < timeout <= 1
        return discovered

    monkeypatch.setattr(module, "capture", capture)
    monkeypatch.delenv("ADBHOST", raising=False)
    original = ExecutionResult(stdout=b"List of devices attached\n\n")

    result = module.recover_local_emulators(original, timeout=1)

    assert result == discovered
    assert sent == [b"0012host:emulator:5555"]
    assert closed == [True]


def _listing(rows=b""):
    return ExecutionResult(stdout=b"List of devices attached\n" + rows + b"\n")


class DiscoveryBoundary:
    def __init__(self, monkeypatch):
        self.clock = 100.0
        self.ports = {5555}
        self.snapshots = 0
        self.snapshot_error = None
        self.snapshot_action = lambda: None
        self.send_action = lambda: None
        self.capture_action = lambda: None
        self.connect_action = lambda: None
        self.send_errors = set()
        self.sent = []
        self.sockets = []
        self.queries = []
        self.responses = [_listing(b"emulator-5554\tdevice\n")]
        self.cancelled = False
        self.diagnostics = []
        monkeypatch.delenv("ADBHOST", raising=False)
        monkeypatch.setattr(adb_discovery, "_listening_emulator_ports", self.listening)
        monkeypatch.setattr(time, "monotonic", lambda: self.clock)
        monkeypatch.setattr(time, "sleep", self.advance)
        monkeypatch.setattr(adb_transport.socket, "create_connection", self.connect)
        monkeypatch.setattr(adb_discovery, "capture", self.capture)

    def advance(self, seconds):
        assert seconds >= 0
        self.clock += seconds

    def listening(self):
        self.snapshots += 1
        self.snapshot_action()
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return set(self.ports)

    def connect(self, address, timeout):
        assert address == ("127.0.0.1", 5037)
        assert 0 < timeout <= 1
        self.connect_action()
        boundary = self

        class NotificationSocket:
            closed = False

            def setsockopt(self, *_):
                pass

            def settimeout(self, value):
                assert value > 0

            def sendall(self, payload):
                boundary.sent.append(payload)
                boundary.send_action()
                port = int(payload.rsplit(b":", 1)[1])
                if port in boundary.send_errors:
                    raise OSError("sensitive-path-and-device")

            def recv(self, _size):
                raise AssertionError("通知不能等待 ACK")

            def close(self):
                self.closed = True

        connection = NotificationSocket()
        self.sockets.append(connection)
        return connection

    def capture(self, command, args, *, serial, timeout, cancelled):
        assert (command, args, serial) == ("devices", ["-l"], None)
        assert timeout > 0
        self.queries.append((self.clock, timeout))
        self.advance(min(0.01, timeout))
        self.capture_action()
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    def recover(self, listing=None, timeout=1):
        return adb_discovery.recover_local_emulators(
            listing if listing is not None else _listing(), timeout=timeout,
            cancelled=lambda: self.cancelled, diagnostic=self.diagnostics.append,
        )


def test_listening_snapshot_only_keeps_local_standard_emulator_ports(monkeypatch):
    def connection(ip, port, status=psutil.CONN_LISTEN):
        return SimpleNamespace(
            fd=-1, family=socket.AF_INET, type=socket.SOCK_STREAM,
            laddr=SimpleNamespace(ip=ip, port=port), raddr=(), status=status, pid=123,
        )

    calls = []

    def snapshot(*, kind):
        calls.append(kind)
        return [
            connection("127.0.0.1", 5555), connection("0.0.0.0", 5585),
            connection("0.0.0.0", 5555), connection("192.0.2.1", 5557),
            connection("127.0.0.2", 5559), connection("127.0.0.1", 5554),
            connection("127.0.0.1", 5587), connection("127.0.0.1", 5037),
            connection("127.0.0.1", 5557, psutil.CONN_ESTABLISHED),
            SimpleNamespace(fd=-1, family=socket.AF_INET, type=socket.SOCK_STREAM,
                            laddr=(), raddr=(), status=psutil.CONN_LISTEN, pid=None),
        ]

    monkeypatch.setattr(psutil, "net_connections", snapshot)

    assert real_listening_emulator_ports() == {5555, 5585}
    assert calls == ["tcp4"]


@pytest.mark.parametrize("listing", [
    ExecutionResult(kind="timeout"), ExecutionResult(kind="cancelled"),
    ExecutionResult(kind="transport"), ExecutionResult(returncode=1),
    ExecutionResult(stdout=b"not a device listing"),
])
def test_failed_or_invalid_listing_never_triggers_registration(monkeypatch, listing):
    boundary = DiscoveryBoundary(monkeypatch)

    assert boundary.recover(listing) is listing
    assert boundary.snapshots == 0
    assert boundary.sent == []


def test_explicit_adbhost_preserves_original_server_target(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    monkeypatch.setenv("ADBHOST", "configured-host")
    listing = _listing()

    assert boundary.recover(listing) is listing
    assert boundary.snapshots == 0


def test_no_listening_ports_keeps_successful_empty_listing(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    boundary.ports = set()
    listing = _listing()

    assert boundary.recover(listing) is listing
    assert boundary.snapshots == 1
    assert boundary.sent == [] and boundary.queries == []


def test_nonempty_listing_only_registers_missing_emulator_ports(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    boundary.ports = {5555, 5557, 5559, 5561}
    existing = b"emulator-5554\toffline\n127.0.0.1:5557\tdevice\nlocalhost:5559\tunauthorized\n"
    discovered = _listing(existing + b"emulator-5560\tdevice\n")
    boundary.responses = [discovered]

    assert boundary.recover(_listing(existing)) == discovered
    assert boundary.sent == [b"0012host:emulator:5561"]


def test_already_registered_emulator_never_receives_duplicate_notification(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    listing = _listing(b"emulator-5554\tdevice\n")

    assert boundary.recover(listing) is listing
    assert boundary.sent == [] and boundary.queries == []


def test_delayed_registration_polls_without_replaying_notification(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    found = _listing(b"emulator-5554\tdevice\n")
    boundary.responses = [_listing(), found]

    assert boundary.recover() == found
    assert len(boundary.queries) == 2
    assert boundary.sent == [b"0012host:emulator:5555"]
    assert all(connection.closed for connection in boundary.sockets)


def test_new_offline_emulator_keeps_polling_until_online(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    online = _listing(b"emulator-5554\tdevice\n")
    boundary.responses = [_listing(b"emulator-5554\toffline\n"), online]

    assert boundary.recover() == online
    assert len(boundary.queries) == 2
    assert boundary.sent == [b"0012host:emulator:5555"]


def test_persistent_offline_emulator_preserves_final_listing_at_deadline(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    offline = _listing(b"emulator-5554\toffline\n")
    boundary.responses = [offline]

    assert boundary.recover(timeout=0.2) == offline
    assert boundary.clock == pytest.approx(100.2)
    assert len(boundary.queries) > 1
    assert boundary.sent == [b"0012host:emulator:5555"]


def test_unauthorized_emulator_finishes_without_waiting_for_user_action(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    unauthorized = _listing(b"emulator-5554\tunauthorized\n")
    boundary.responses = [unauthorized]

    assert boundary.recover() == unauthorized
    assert len(boundary.queries) == 1
    assert boundary.sent == [b"0012host:emulator:5555"]


def test_ipv6_loopback_registration_prevents_duplicate_emulator_identity(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    listing = _listing(b"[::1]:5555\tdevice\n")

    assert boundary.recover(listing) is listing
    assert boundary.sent == [] and boundary.queries == []


def test_windows_crlf_listing_preserves_existing_emulator_identity(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    boundary.ports = {5555, 5557}
    found = _listing(b"emulator-5554\tdevice\nemulator-5556\tdevice\n")
    boundary.responses = [found]
    listing = ExecutionResult(stdout=b"List of devices attached\r\nemulator-5554\tdevice\r\n")

    assert boundary.recover(listing) == found
    assert boundary.sent == [b"0012host:emulator:5557"]


def test_transient_verification_failure_can_recover_within_original_budget(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    found = _listing(b"emulator-5554\tdevice\n")
    boundary.responses = [ExecutionResult(kind="transport"), found]

    assert boundary.recover() == found
    assert boundary.sent == [b"0012host:emulator:5555"]
    assert len(boundary.queries) == 2
    assert boundary.diagnostics


def test_notification_does_not_fabricate_online_device(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    boundary.responses = [_listing()]

    result = boundary.recover(timeout=0.2)

    assert result == _listing()
    assert boundary.sent == [b"0012host:emulator:5555"]
    assert boundary.clock <= 100.2
    assert all(start + budget <= 100.2 for start, budget in boundary.queries)


def test_poll_failure_preserves_last_successful_listing(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    boundary.ports = {5555, 5557}
    partial = _listing(b"emulator-5554\toffline\n")
    boundary.responses = [partial, ExecutionResult(kind="transport")]

    assert boundary.recover(timeout=0.2) == partial
    assert len(boundary.queries) >= 2
    assert boundary.diagnostics
    assert all("sensitive" not in message for message in boundary.diagnostics)


def test_failed_notification_keeps_original_listing_and_closes_socket(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    boundary.send_errors = {5555}
    listing = _listing(b"usb-fixture\tdevice\n")

    assert boundary.recover(listing) is listing
    assert boundary.queries == []
    assert all(connection.closed for connection in boundary.sockets)
    assert boundary.diagnostics and "sensitive" not in " ".join(boundary.diagnostics)


def test_failed_notification_does_not_block_other_candidate(monkeypatch):
    boundary = DiscoveryBoundary(monkeypatch)
    boundary.ports = {5555, 5557}
    boundary.send_errors = {5555}
    found = _listing(b"emulator-5556\tdevice\n")
    boundary.responses = [found]

    assert boundary.recover() == found
    assert boundary.sent == [b"0012host:emulator:5555", b"0012host:emulator:5557"]
    assert len(boundary.queries) == 1


@pytest.mark.parametrize("stage", ["before", "snapshot", "connect", "send", "poll"])
def test_cancellation_stops_remaining_discovery_work(monkeypatch, stage):
    boundary = DiscoveryBoundary(monkeypatch)
    boundary.ports = {5555, 5557}

    def cancel():
        boundary.cancelled = True

    if stage == "before":
        cancel()
    else:
        setattr(boundary, {"snapshot": "snapshot_action", "connect": "connect_action",
                           "send": "send_action", "poll": "capture_action"}[stage], cancel)

    assert boundary.recover().kind == "cancelled"
    assert boundary.snapshots == (0 if stage == "before" else 1)
    if stage in {"before", "snapshot", "connect"}:
        assert boundary.sent == []
    if stage == "send":
        assert boundary.sent == [b"0012host:emulator:5555"]
    if stage != "poll":
        assert boundary.queries == []
    else:
        assert len(boundary.queries) == 1
    assert all(connection.closed for connection in boundary.sockets)


@pytest.mark.parametrize("stage", ["before", "snapshot", "send"])
def test_deadline_prevents_any_new_network_work(monkeypatch, stage):
    boundary = DiscoveryBoundary(monkeypatch)
    boundary.ports = {5555, 5557}
    listing = _listing()
    if stage != "before":
        setattr(boundary, stage + "_action", lambda: boundary.advance(1))

    assert boundary.recover(listing, timeout=0 if stage == "before" else 1) is listing
    assert boundary.sent == ([b"0012host:emulator:5555"] if stage == "send" else [])
    assert boundary.queries == []
    assert all(connection.closed for connection in boundary.sockets)


@pytest.mark.parametrize("error", [psutil.AccessDenied(), OSError("private details")])
def test_listener_snapshot_failure_is_best_effort(monkeypatch, error):
    boundary = DiscoveryBoundary(monkeypatch)
    boundary.snapshot_error = error
    listing = _listing()

    assert boundary.recover(listing) is listing
    assert boundary.sent == [] and boundary.queries == []
    assert boundary.diagnostics and "private" not in " ".join(boundary.diagnostics)
