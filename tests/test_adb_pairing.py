"""无线配对仅在离线命令边界验证，不访问真实 ADB 或网络。"""

from __future__ import annotations

import dataclasses
import re
import struct
import threading

import pytest

from core.exec import CommandResult
from services.adb_pairing import (
    PairingContext,
    PairingService,
    create_continuation_request,
    create_manual_request,
    create_qr_request,
    parse_mdns_services,
    parse_pair_result,
)

GUID = "adb-fixture-A1b2"
TRANSPORT = f"{GUID}._adb-tls-connect._tcp"
PAIR_ENDPOINT = "192.0.2.1:37001"
CONNECT_ENDPOINT = "192.0.2.1:37002"
HEADER = "List of discovered mdns services"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def wait(self, event, seconds):
        self.now += seconds
        return event.is_set()


class Scope:
    running = False

    def is_running(self):
        return self.running


class Script:
    def __init__(self, rows, clock):
        self.rows = list(rows)
        self.clock = clock
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        expected, result = self.rows.pop(0)
        assert argv[1:] == expected
        if callable(result):
            return result(kwargs)
        return result


def ok(output=""):
    return CommandResult(True, output=output)


def paired(guid=GUID):
    suffix = f" [guid={guid}]" if guid else ""
    return ok(f"Enter pairing code: Successfully paired to {PAIR_ENDPOINT}{suffix}")


@pytest.fixture
def context(tmp_path):
    return PairingContext(
        str(tmp_path / "adb.exe"), {"ADB_SERVER_SOCKET": "tcp:example:5037", "ADB_TRACE": "all"}, 7
    )


def run(rows, context, request=None, *, clock=None, cancel=None, scope=None, on_qr=None):
    clock = clock or Clock()
    runner = Script(rows, clock)
    events, images = [], []

    def display(request_id, png, module_count, timeout_seconds):
        images.append((request_id, png, module_count))
        return True

    service = PairingService(command_runner=runner, clock=clock, wait=clock.wait)
    outcome = service.run(
        request or create_manual_request(1, PAIR_ENDPOINT, "012345"),
        context,
        cancel or threading.Event(),
        scope or Scope(),
        events.append,
        on_qr or display,
    )
    return outcome, runner.calls, events, images, clock


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "Enter pairing code: Successfully paired to 192.0.2.1:37001 [guid=adb-fixture-A1b2]",
            (True, GUID),
        ),
        ("Successfully paired to 192.0.2.1:37001", (True, "")),
        ("Enter pairing code: Failed to pair: wrong code", (False, "")),
        ("failed pairing", (False, "")),
        ("pairing completed maybe", (None, "")),
        ("Successfully paired to 192.0.2.1:37001 [guid=../../bad]", (True, "")),
    ],
)
def test_pair_parser_requires_explicit_body_and_preserves_full_guid(text, expected):
    assert parse_pair_result(ok(text)) == expected


def test_mdns_parser_deduplicates_and_only_accepts_known_valid_services():
    services = parse_mdns_services(
        "\n".join(
            [
                HEADER,
                f"studio-Test _adb-tls-pairing._tcp. {PAIR_ENDPOINT}",
                f"studio-Test _adb-tls-pairing._tcp. {PAIR_ENDPOINT}",
                f"{GUID}._adb-tls-connect._tcp.local. _adb-tls-connect._tcp. {CONNECT_ENDPOINT}",
                "ignored _http._tcp. 192.0.2.2:80",
                "invalid _adb-tls-pairing._tcp. hostname:55",
                "error diagnostic line",
            ]
        )
    )
    assert {(row.name, row.service_type, row.endpoint) for row in services} == {
        ("studio-Test", "_adb-tls-pairing._tcp", PAIR_ENDPOINT),
        (GUID, "_adb-tls-connect._tcp", CONNECT_ENDPOINT),
    }


@pytest.mark.parametrize(
    "body", ["error: mdns disabled", "mDNS discovery disabled", "unexpected response"]
)
def test_mdns_unavailable_and_unrecognized_do_not_look_like_empty_list(body):
    with pytest.raises(ValueError):
        parse_mdns_services(body)


def test_empty_mdns_header_is_valid():
    assert parse_mdns_services(HEADER) == ()


@pytest.mark.parametrize(
    "endpoint,code",
    [
        ("host:12", "012345"),
        (PAIR_ENDPOINT, "12345"),
        (PAIR_ENDPOINT, "１２３４５６"),
        (PAIR_ENDPOINT, "123456\n"),
    ],
)
def test_manual_validation_rejects_invalid_endpoint_and_code(endpoint, code):
    with pytest.raises(ValueError):
        create_manual_request(1, endpoint, code)


def test_qr_factories_create_distinct_safe_ascii_secrets():
    first, second = create_qr_request(1), create_qr_request(2)
    assert first.service_name != second.service_name
    assert first.secret != second.secret
    assert re.fullmatch(r"studio-[A-Za-z0-9]+", first.service_name)
    assert len(first.service_name.encode("ascii")) <= 63
    assert re.fullmatch(r"[A-Za-z0-9]{24}", first.secret)
    assert first.secret not in repr(first)


def test_manual_rc_zero_failure_does_not_run_discovery_or_connect(context):
    outcome, calls, events, _, _ = run(
        [(["pair", PAIR_ENDPOINT], ok("Enter pairing code: failed pairing 012345"))], context
    )
    assert outcome.paired is False
    assert not outcome.connected
    assert outcome.state == "Failed"
    assert outcome.reason == "pair_failed"
    assert len(calls) == 1
    assert "012345" not in repr(events) + repr(outcome)


def test_manual_ipv6_pairs_without_mdns_and_accepts_existing_wireless(context):
    endpoint = "[2001:db8::1]:37001"
    request = create_manual_request(3, endpoint, "012345")
    outcome, calls, _, _, _ = run(
        [
            (["pair", endpoint], paired()),
            (
                ["devices"],
                ok(f"List of devices attached\nusb-fixture\tdevice\n{TRANSPORT}.local.\tdevice\n"),
            ),
        ],
        context,
        request,
    )
    assert outcome.connected and outcome.device_id == f"{TRANSPORT}.local."
    assert outcome.guid == GUID and outcome.context_revision == 7
    assert not any(argv[1] == "connect" for argv, _ in calls)


def test_qr_exact_service_to_guid_identity_chain_uses_stdin_and_frozen_context(context):
    request = create_qr_request(9)
    outcome, calls, events, images, _ = run(
        [
            (["mdns", "check"], ok("mdns daemon version [Openscreen discovery 0.0.0]")),
            (
                ["mdns", "services"],
                ok(f"{HEADER}\n{request.service_name}-other _adb-tls-pairing._tcp. 192.0.2.9:12"),
            ),
            (
                ["mdns", "services"],
                ok(f"{HEADER}\n{request.service_name} _adb-tls-pairing._tcp. {PAIR_ENDPOINT}"),
            ),
            (["pair", PAIR_ENDPOINT], paired()),
            (["devices"], ok("List of devices attached\nusb-fixture\tdevice")),
            (
                ["mdns", "services"],
                ok(f"{HEADER}\n{GUID} _adb-tls-connect._tcp. {CONNECT_ENDPOINT}"),
            ),
            (["connect", TRANSPORT], ok("failed to connect")),
            (["devices"], ok(f"List of devices attached\n{TRANSPORT}\tdevice")),
        ],
        context,
        request,
    )
    assert outcome.connected and outcome.connection_endpoint == CONNECT_ENDPOINT
    pair_call = next((argv, kwargs) for argv, kwargs in calls if argv[1] == "pair")
    assert pair_call[1]["input_bytes"] == (request.secret + "\n").encode("ascii")
    for argv, kwargs in calls:
        assert argv[0] == context.adb_path
        assert kwargs["native_only"] is True and kwargs["shell"] is False
        assert kwargs["env"] == {"ADB_SERVER_SOCKET": "tcp:example:5037"}
        assert request.secret not in " ".join(argv)
    assert request.secret not in repr(events) + repr(outcome) + repr(context)
    assert images[0][1].startswith(b"\x89PNG\r\n\x1a\n")
    assert images[0][2] >= 29


def test_qr_conflicting_matching_services_never_pair(context):
    request = create_qr_request(10)
    outcome, calls, _, _, _ = run(
        [
            (["mdns", "check"], ok("mdns daemon version [Bonjour 1.0]")),
            (
                ["mdns", "services"],
                ok(
                    f"{HEADER}\n{request.service_name} _adb-tls-pairing._tcp. {PAIR_ENDPOINT}\n"
                    f"{request.service_name} _adb-tls-pairing._tcp. 192.0.2.2:37001"
                ),
            ),
        ],
        context,
        request,
    )
    assert outcome.reason == "service_conflict" and not outcome.connected
    assert len(calls) == 2


def test_ip_transport_requires_exact_guid_property(context):
    outcome, _, _, _, _ = run(
        [
            (["pair", PAIR_ENDPOINT], paired()),
            (["devices"], ok(f"List of devices attached\n{CONNECT_ENDPOINT}\tdevice\n")),
            (
                ["mdns", "services"],
                ok(f"{HEADER}\n{GUID} _adb-tls-connect._tcp. {CONNECT_ENDPOINT}"),
            ),
            (["-s", CONNECT_ENDPOINT, "shell", "getprop", "persist.adb.wifi.guid"], ok(GUID)),
        ],
        context,
    )
    assert outcome.connected and outcome.device_id == CONNECT_ENDPOINT


def test_pair_without_guid_is_paired_only_without_continuation(context):
    outcome, calls, _, _, _ = run([(["pair", PAIR_ENDPOINT], paired(""))], context)
    assert outcome.paired is True and not outcome.connected
    assert outcome.state == "PairedOnly" and outcome.reason == "guid_unavailable"
    assert outcome.continuation is None and len(calls) == 1


@pytest.mark.parametrize(
    "result",
    [
        ok("unrecognized 012345"),
        CommandResult(False, error="Timeout(15s) 012345", outcome="timed_out"),
    ],
)
def test_unknown_pair_result_is_uncertain_and_never_replayed(context, result):
    outcome, calls, events, _, _ = run([(["pair", PAIR_ENDPOINT], result)], context)
    assert outcome.paired is None and outcome.state == "Uncertain"
    assert len(calls) == 1
    assert "012345" not in repr(outcome) + repr(events)


def test_cancel_before_run_never_starts_command(context):
    cancel = threading.Event()
    cancel.set()
    outcome, calls, _, _, _ = run([], context, cancel=cancel)
    assert outcome.reason == "cancelled" and calls == []


def test_uncleared_client_takes_priority_over_result(context):
    scope = Scope()

    def leak(kwargs):
        scope.running = True
        return paired()

    outcome, calls, _, _, _ = run([(["pair", PAIR_ENDPOINT], leak)], context, scope=scope)
    assert outcome.state == "CleanupFailed" and outcome.reason == "cleanup_failed"
    assert len(calls) == 1


def test_context_copies_environment_and_hides_identifiers(context):
    source = {"ADB_SERVER_SOCKET": "tcp:original:5037", "ADB_TRACE": "all"}
    ctx = PairingContext(context.adb_path, source, 1)
    source["ADB_SERVER_SOCKET"] = "tcp:changed:5037"
    assert ctx.env["ADB_SERVER_SOCKET"] == "tcp:original:5037"
    assert "ADB_TRACE" not in ctx.env
    assert "original" not in repr(ctx) and context.adb_path not in repr(ctx)
    with pytest.raises(TypeError):
        ctx.env["ADB_SERVER_SOCKET"] = "changed"


def test_connection_timeout_retains_secret_free_continuation_and_does_not_replay(context):
    clock = Clock()

    def consume_connection_budget(kwargs):
        clock.now += 30
        return ok("List of devices attached\nunrelated\tdevice")

    outcome, calls, events, _, _ = run(
        [
            (["pair", PAIR_ENDPOINT], paired()),
            (["devices"], consume_connection_budget),
        ],
        context,
        clock=clock,
    )
    assert outcome.state == "PairedOnly" and outcome.continuation is not None
    assert outcome.continuation.guid == GUID
    assert outcome.continuation.context is context
    assert not hasattr(outcome.continuation, "secret")
    assert "012345" not in repr(outcome.continuation) + repr(events)
    assert len(calls) == 2


def test_continuation_uses_new_id_and_verifies_manual_endpoint(context):
    from services.adb_pairing import PairingContinuation

    request = create_continuation_request(4, PairingContinuation(GUID, context), CONNECT_ENDPOINT)
    outcome, calls, _, _, _ = run(
        [
            (
                ["connect", CONNECT_ENDPOINT],
                CommandResult(False, error="Timeout(10s)", outcome="timed_out"),
            ),
            (["devices"], ok(f"List of devices attached\n{CONNECT_ENDPOINT}\tdevice")),
            (["-s", CONNECT_ENDPOINT, "shell", "getprop", "persist.adb.wifi.guid"], ok(GUID)),
        ],
        context,
        request,
    )
    assert outcome.connected and outcome.request_id == 4
    assert request.secret == ""
    assert sum(argv[1] == "connect" for argv, _ in calls) == 1


def test_continuation_rejects_changed_server_context_before_connect(context):
    from services.adb_pairing import PairingContinuation

    request = create_continuation_request(4, PairingContinuation(GUID, context), CONNECT_ENDPOINT)
    changed = dataclasses.replace(
        context, env={"ADB_SERVER_SOCKET": "tcp:changed:5037"}, context_revision=8
    )
    outcome, calls, _, _, _ = run([], changed, request)
    assert outcome.reason == "context_changed" and calls == []


def test_scan_budget_begins_after_qr_display_ack(context):
    clock = Clock()
    request = create_qr_request(5)

    def display(*args):
        clock.now += 10
        return True

    def expire(kwargs):
        clock.now += 120
        return ok(HEADER)

    outcome, calls, events, _, _ = run(
        [
            (["mdns", "check"], ok("mdns daemon version [Openscreen discovery 0.0.0]")),
            (["mdns", "services"], expire),
        ],
        context,
        request,
        clock=clock,
        on_qr=display,
    )
    assert outcome.reason == "scan_timeout" and clock.now == 130
    scan = next(event for event in events if event.state == "WaitingForScan")
    assert scan.remaining_seconds == 120
    assert calls[-1][1]["timeout"] <= 5


def test_qr_not_displayed_never_starts_discovery(context):
    outcome, calls, _, _, _ = run(
        [
            (["mdns", "check"], ok("mdns daemon version [Bonjour 1.0]")),
        ],
        context,
        create_qr_request(6),
        on_qr=lambda *args: False,
    )
    assert outcome.reason == "cancelled" and len(calls) == 1


@pytest.mark.parametrize(
    "device",
    [
        GUID,
        "fixture-A1b2._adb-tls-connect._tcp",
        "adb-other._adb-tls-connect._tcp",
        "192.0.2.1:37003",
    ],
)
def test_usb_prefix_match_unrelated_device_and_different_port_never_prove_identity(context, device):
    clock = Clock()

    def expire(kwargs):
        clock.now += 30
        return ok(f"List of devices attached\n{device}\tdevice")

    outcome, _, _, _, _ = run(
        [
            (["pair", PAIR_ENDPOINT], paired()),
            (["devices"], ok(f"List of devices attached\n{device}\tdevice")),
            (["mdns", "services"], ok(HEADER)),
            (["devices"], expire),
        ],
        context,
        clock=clock,
    )
    assert outcome.state == "PairedOnly" and not outcome.connected


def test_ip_transport_wrong_guid_is_not_promoted_to_success(context):
    outcome, _, _, _, _ = run(
        [
            (["pair", PAIR_ENDPOINT], paired()),
            (["devices"], ok(f"List of devices attached\n{CONNECT_ENDPOINT}\tdevice")),
            (
                ["mdns", "services"],
                ok(f"{HEADER}\n{GUID} _adb-tls-connect._tcp. {CONNECT_ENDPOINT}"),
            ),
            (
                ["-s", CONNECT_ENDPOINT, "shell", "getprop", "persist.adb.wifi.guid"],
                ok("adb-other"),
            ),
        ],
        context,
    )
    assert outcome.reason == "identity_mismatch" and outcome.continuation is not None


def test_connect_is_not_replayed_after_timeout_and_offline_state(context):
    clock = Clock()

    def expire(kwargs):
        clock.now += 30
        return ok(f"List of devices attached\n{TRANSPORT}\toffline")

    outcome, calls, _, _, _ = run(
        [
            (["pair", PAIR_ENDPOINT], paired()),
            (["devices"], ok(f"List of devices attached\n{TRANSPORT}\toffline")),
            (
                ["mdns", "services"],
                ok(f"{HEADER}\n{GUID} _adb-tls-connect._tcp. {CONNECT_ENDPOINT}"),
            ),
            (["connect", TRANSPORT], CommandResult(False, outcome="timed_out")),
            (["devices"], expire),
        ],
        context,
        clock=clock,
    )
    assert outcome.state == "PairedOnly"
    assert sum(argv[1] == "connect" for argv, _ in calls) == 1
    assert next(kwargs["timeout"] for argv, kwargs in calls if argv[1] == "connect") == 10


def test_total_budget_caps_connection_after_long_prepare_scan_and_pair(context):
    clock = Clock()
    request = create_qr_request(11)

    def delayed(seconds, value):
        def execute(kwargs):
            clock.now += seconds
            return value

        return execute

    def display(*args):
        clock.now += 14
        return True

    def spend_remaining(kwargs):
        clock.now += kwargs["timeout"]
        return ok("List of devices attached")

    rows = [
        (["mdns", "check"], ok("mdns daemon version [Bonjour 1.0]")),
        (
            ["mdns", "services"],
            delayed(
                119, ok(f"{HEADER}\n{request.service_name} _adb-tls-pairing._tcp. {PAIR_ENDPOINT}")
            ),
        ),
        # 模拟已确认成功后的额外客户端清理时间，后续阶段仍受整轮截止时间约束。
        (["pair", PAIR_ENDPOINT], delayed(25, paired())),
        (["devices"], spend_remaining),
        (["mdns", "services"], CommandResult(False, outcome="failed")),
        (["devices"], spend_remaining),
        (["devices"], spend_remaining),
        (["devices"], spend_remaining),
        (["devices"], spend_remaining),
        (["devices"], spend_remaining),
    ]
    outcome, calls, _, _, _ = run(rows, context, request, clock=clock, on_qr=display)
    assert outcome.state == "PairedOnly"
    assert clock.now <= 180
    assert all(kwargs["timeout"] <= 5 for argv, kwargs in calls if argv[1] in ("devices", "mdns"))
    assert calls[-1][1]["timeout"] < 5


def test_expired_qr_display_ack_cannot_start_scan(context):
    clock = Clock()

    def display(request_id, png, module_count, timeout_seconds):
        assert timeout_seconds == 15
        clock.now += timeout_seconds
        return True

    outcome, calls, _, _, _ = run(
        [
            (["mdns", "check"], ok("mdns daemon version [Bonjour 1.0]")),
        ],
        context,
        create_qr_request(12),
        clock=clock,
        on_qr=display,
    )
    assert outcome.reason == "prepare_timeout" and len(calls) == 1


def test_qr_png_is_standard_qr_with_integer_modules_and_opaque_white_quiet_zone(context):
    from PySide6.QtGui import QImage

    def display(request_id, png, module_count, timeout_seconds):
        width, height = struct.unpack(">II", png[16:24])
        assert width == height == module_count * 6
        image = QImage.fromData(png)
        assert image.pixelColor(0, 0).getRgb() == (255, 255, 255, 255)
        assert image.pixelColor(4 * 6, 4 * 6).getRgb() == (0, 0, 0, 255)
        return False

    run(
        [(["mdns", "check"], ok("mdns daemon version [Bonjour 1.0]"))],
        context,
        create_qr_request(13),
        on_qr=display,
    )


def test_pair_exception_with_echoed_secret_is_sanitized_and_uncertain(context, caplog):
    def fail(kwargs):
        raise RuntimeError("malicious echo 012345")

    outcome, _, events, _, _ = run([(["pair", PAIR_ENDPOINT], fail)], context)
    assert outcome.state == "Uncertain" and outcome.paired is None
    assert "012345" not in repr(outcome) + repr(events) + caplog.text


def test_cancel_during_pair_stops_before_identity_queries(context):
    cancel = threading.Event()

    def finish_after_cancel(kwargs):
        cancel.set()
        return paired()

    outcome, calls, _, _, _ = run(
        [(["pair", PAIR_ENDPOINT], finish_after_cancel)], context, cancel=cancel
    )
    assert outcome.reason == "cancelled" and len(calls) == 1


def test_connect_exception_still_permits_bounded_read_only_confirmation(context):
    from services.adb_pairing import PairingContinuation

    def fail(kwargs):
        raise OSError("failed but the server may have accepted connect")

    request = create_continuation_request(14, PairingContinuation(GUID, context), CONNECT_ENDPOINT)
    outcome, calls, _, _, _ = run(
        [
            (["connect", CONNECT_ENDPOINT], fail),
            (["devices"], ok(f"List of devices attached\n{CONNECT_ENDPOINT}\tdevice")),
            (["-s", CONNECT_ENDPOINT, "shell", "getprop", "persist.adb.wifi.guid"], ok(GUID)),
        ],
        context,
        request,
    )
    assert outcome.connected
    assert sum(argv[1] == "connect" for argv, _ in calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        "adb: unknown command pair",
        "adb: usage: unknown command pair",
        "adb.exe: unknown command pair",
        "adb: unsupported command: pair",
    ],
)
def test_explicit_unsupported_pair_client_is_never_reported_as_possible_pairing(context, body):
    outcome, calls, _, _, _ = run(
        [
            (["pair", PAIR_ENDPOINT], CommandResult(False, error=body, returncode=1)),
        ],
        context,
    )
    assert outcome.reason == "unsupported_client"
    assert outcome.paired is False and outcome.state == "Failed"
    assert len(calls) == 1


def test_continuation_cannot_attach_unverified_endpoint_to_existing_named_transport(context):
    from services.adb_pairing import PairingContinuation

    clock = Clock()

    def expire(kwargs):
        clock.now += 30
        return ok(f"List of devices attached\n{TRANSPORT}\tdevice")

    request = create_continuation_request(15, PairingContinuation(GUID, context), CONNECT_ENDPOINT)
    outcome, _, _, _, _ = run(
        [
            (["connect", CONNECT_ENDPOINT], ok("connected")),
            (["devices"], ok(f"List of devices attached\n{TRANSPORT}\tdevice")),
            (["devices"], expire),
        ],
        context,
        request,
        clock=clock,
    )
    assert outcome.state == "PairedOnly" and not outcome.connected


@pytest.mark.parametrize(
    "result",
    [
        CommandResult(False, error="error: protocol fault while reading response", returncode=1),
        ok("Not Successfully paired to 192.0.2.1:37001 [guid=adb-fixture-A1b2]"),
        ok("Successfully paired to 192.0.2.1:37001 [guid=adb-fixture-A1b2] unknown suffix"),
    ],
)
def test_ambiguous_or_partial_success_response_never_claims_pairing_result(context, result):
    outcome, calls, _, _, _ = run([(["pair", PAIR_ENDPOINT], result)], context)
    assert outcome.state == "Uncertain" and outcome.paired is None
    assert len(calls) == 1
