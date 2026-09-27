"""验证结构化 Intent 的校验、设备命令边界和兼容路由。"""

import shlex
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from controllers._system import ADBSystemControllerMixin
from core.exec import CommandResult, CommandRunner
from models.adb_model import ADBModelCore
from models.adb_system import ADBSystemMixin


@pytest.fixture
def controller(qt_application):
    controller = ADBSystemControllerMixin.__new__(ADBSystemControllerMixin)
    controller.advanced_model = SimpleNamespace(
        start_activity_async=Mock(), send_broadcast_async=Mock(), open_deep_link_async=Mock(),
    )
    controller._emit_operation = Mock()
    return controller


@pytest.fixture
def command_calls(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return CommandResult(True, output="Status: ok", returncode=0)

    monkeypatch.setattr(CommandRunner, "run", run)
    return calls


def _model():
    return SimpleNamespace(_run=ADBModelCore._run)


@pytest.mark.parametrize("uri", ["https://example.test/path", "demo-app://item/1", "demo:123"])
def test_legacy_activity_routes_uri_before_component(controller, uri):
    controller.start_activity(["device-a", "device-b"], uri)

    assert controller.advanced_model.open_deep_link_async.call_args_list == [
        (("device-a", uri),), (("device-b", uri),),
    ]
    controller.advanced_model.start_activity_async.assert_not_called()


@pytest.mark.parametrize(
    "output",
    [
        "Starting: Intent { dat=demo:secret }\n"
        "Error: Activity not started, unable to resolve Intent",
        "Error type 3\nError: Activity class does not exist.",
        "Exception occurred while executing 'start':\njava.lang.SecurityException: not exported",
        "java.lang.SecurityException: Permission Denial",
        "Status: timeout\nWaitTime: 10000",
    ],
)
def test_activity_rejects_am_business_failure_with_zero_exit(monkeypatch, output):
    monkeypatch.setattr(
        CommandRunner, "run", lambda *args, **kwargs: CommandResult(True, output=output),
    )

    result = ADBSystemMixin.start_activity_async.__wrapped__(
        _model(), "device-a", action="android.intent.action.VIEW",
    )

    assert result["success"] is False
    assert result["error"]


def test_broadcast_rejects_am_exception_with_zero_exit(monkeypatch):
    monkeypatch.setattr(CommandRunner, "run", lambda *args, **kwargs: CommandResult(
        True, output="Exception occurred while executing 'broadcast':\nPermission Denial",
    ))
    result = ADBSystemMixin.send_broadcast_async.__wrapped__(_model(), "device-a", "demo.ACTION")
    assert result["success"] is False


def test_activity_quotes_uri_and_preserves_advanced_arguments(command_calls):
    uri = "demo://item?value=';$(id)&next=2"
    result = ADBSystemMixin.start_activity_async.__wrapped__(
        _model(), "device-a", component="com.example/.MainActivity",
        action="android.intent.action.VIEW", data_uri=uri, mime_type="text/plain",
        flags="0x10000000", wait=True,
    )
    command, options = command_calls[0]
    assert result["success"] is True
    assert shlex.split(" ".join(command[5:-1])) == [
        "start", "-n", "com.example/.MainActivity", "-a", "android.intent.action.VIEW",
        "-d", uri, "-t", "text/plain", "-f", "268435456", "-W",
    ]
    assert command[command.index("-d") + 1] == shlex.quote(uri)
    assert command[:6] == ["adb", "-s", "device-a", "shell", "am", "start"]
    assert command[-1] == "2>&1"
    assert options == {"timeout": 15, "shell": False}


def test_broadcast_preserves_typed_extras_and_quotes_each_dynamic_value(command_calls):
    result = ADBSystemMixin.send_broadcast_async.__wrapped__(
        _model(), "device-a", "demo.ACTION",
        {"enabled": True, "count": -4, "ratio": 1.25, "text' key": "';$(id)& value"},
    )
    command, _options = command_calls[0]
    assert result["success"] is True
    assert shlex.split(" ".join(command[4:-1])) == [
        "am", "broadcast", "-a", "demo.ACTION", "--ez", "enabled", "true",
        "--ei", "count", "-4", "--ef", "ratio", "1.25",
        "--es", "text' key", "';$(id)& value",
    ]


def test_legacy_broadcast_preserves_leading_and_trailing_spaces_in_extra_keys(command_calls):
    result = ADBSystemMixin.send_broadcast_async.__wrapped__(
        _model(), "device-a", "demo.ACTION", {" key ": "spaced", "key": "plain"},
    )

    assert result["success"] is True
    command = command_calls[0][0]
    assert shlex.split(" ".join(command[4:-1])) == [
        "am", "broadcast", "-a", "demo.ACTION",
        "--es", " key ", "spaced", "--es", "key", "plain",
    ]
    assert command[command.index("--es") + 1] == "' key '"


def test_broadcast_rejects_whitespace_only_extra_key_before_adb(command_calls):
    result = ADBSystemMixin.send_broadcast_async.__wrapped__(
        _model(), "device-a", "demo.ACTION", {"   ": "value"},
    )

    assert result["success"] is False
    assert command_calls == []


@pytest.mark.parametrize("kwargs", [
    {}, {"component": "https://example.test"}, {"component": "com.example /.Main"},
    {"action": "demo.ACTION;reboot"},
    {"data_uri": "demo:hi\nreboot"}, {"data_uri": "no-scheme"},
    {"action": "demo.ACTION", "flags": "0x100000000"},
    {"action": "demo.ACTION", "flags": "1;reboot"},
    {"action": "demo.ACTION", "mime_type": "text/plain;reboot"},
])
def test_invalid_activity_is_rejected_before_command(command_calls, kwargs):
    result = ADBSystemMixin.start_activity_async.__wrapped__(_model(), "device-a", **kwargs)
    assert result["success"] is False
    assert command_calls == []


@pytest.mark.parametrize("extras", [{"value": float("nan")}, {"value": 2**31}, {"value": object()}])
def test_invalid_legacy_extra_never_executes(command_calls, extras):
    result = ADBSystemMixin.send_broadcast_async.__wrapped__(
        _model(), "device-a", "demo.ACTION", extras,
    )
    assert result["success"] is False
    assert command_calls == []


def test_deep_link_adds_view_action_and_quotes_custom_scheme(command_calls):
    uri = "demo://item?id=1&label='value'"
    result = ADBSystemMixin.open_deep_link_async.__wrapped__(_model(), "device-a", uri)
    assert result["success"] is True
    assert shlex.split(" ".join(command_calls[0][0][4:-1])) == [
        "am", "start", "-a", "android.intent.action.VIEW", "-d", uri,
    ]


def test_request_validation_normalizes_typed_extras_without_mutating_input():
    from services.intent_request import IntentExtra, IntentRequest, validate_intent_request

    original = IntentRequest(kind="broadcast", action=" demo.ACTION ", extras=(
        IntentExtra("enabled", "bool", "TRUE"), IntentExtra("count", "int", "-4"),
        IntentExtra("ratio", "float", "1.25"), IntentExtra("text", "str", "  keep  "),
    ))
    normalized = validate_intent_request(original)
    assert normalized.action == "demo.ACTION"
    assert normalized.extras[0].value == "true"
    assert normalized.extras[3].value == "  keep  "
    assert original.action == " demo.ACTION "
    assert original.extras[0].value == "TRUE"


@pytest.mark.parametrize("value_type,value", [
    ("bool", "yes"), ("int", "2147483648"), ("int", "1.5"),
    ("float", "nan"), ("float", "inf"), ("float", "1e99"),
    ("str", "line\nnext"), ("unknown", "value"),
])
def test_typed_extra_rejects_invalid_value(value_type, value):
    from services.intent_request import IntentExtra, IntentRequest, validate_intent_request

    with pytest.raises(ValueError):
        validate_intent_request(IntentRequest(
            kind="broadcast", action="demo.ACTION", extras=(IntentExtra("key", value_type, value),),
        ))


@pytest.mark.parametrize("uri", ["", "no-scheme", "2demo:123", "demo:", "demo:a b", "demo:a\x00b"])
def test_uri_validator_rejects_invalid_input(uri):
    from services.intent_request import validate_uri

    with pytest.raises(ValueError):
        validate_uri(uri)


def test_duplicate_extra_keys_are_rejected():
    from services.intent_request import IntentExtra, IntentRequest, validate_intent_request

    with pytest.raises(ValueError):
        validate_intent_request(IntentRequest(kind="broadcast", action="demo.ACTION", extras=(
            IntentExtra("same", "str", "one"), IntentExtra("same", "int", "2"),
        )))


def test_structured_controller_routes_activity_options_for_each_device(controller):
    from services.intent_request import IntentRequest

    request = IntentRequest(
        component="com.example/.Main", data_uri="demo:item", mime_type="text/plain",
        flags="0x10000000", wait=True,
    )
    controller.execute_intent(["device-a", "device-b"], request)
    assert controller.advanced_model.start_activity_async.call_args_list == [
        ((device,), {"component": "com.example/.Main", "action": "", "data_uri": "demo:item",
                     "mime_type": "text/plain", "flags": "268435456", "wait": True})
        for device in ("device-a", "device-b")
    ]


def test_structured_controller_routes_broadcast_extras(controller):
    from services.intent_request import IntentExtra, IntentRequest

    controller.execute_intent(["device-a"], IntentRequest(
        kind="broadcast", action="demo.ACTION", extras=(
            IntentExtra("enabled", "bool", "false"), IntentExtra("count", "int", "-1"),
            IntentExtra("ratio", "float", "0.5"), IntentExtra("text", "str", "hello"),
        ),
    ))
    controller.advanced_model.send_broadcast_async.assert_called_once_with(
        "device-a", "demo.ACTION",
        extras={"enabled": False, "count": -1, "ratio": 0.5, "text": "hello"},
    )


@pytest.mark.parametrize("devices", [[], ["device-a"]])
def test_structured_controller_rejects_empty_devices_or_invalid_request(controller, devices):
    from services.intent_request import IntentRequest

    controller.execute_intent(devices, IntentRequest())
    controller._emit_operation.assert_called_once()
    assert controller._emit_operation.call_args.args[1] is False
    controller.advanced_model.start_activity_async.assert_not_called()
    controller.advanced_model.send_broadcast_async.assert_not_called()


@pytest.mark.parametrize("method", ["start_activity", "send_broadcast", "open_deep_link"])
def test_legacy_controller_rejects_invalid_values(controller, method):
    getattr(controller, method)(["device-a"], "invalid\nvalue")
    controller._emit_operation.assert_called_once()
    assert controller._emit_operation.call_args.args[1] is False
    controller.advanced_model.start_activity_async.assert_not_called()
    controller.advanced_model.send_broadcast_async.assert_not_called()
    controller.advanced_model.open_deep_link_async.assert_not_called()


@pytest.mark.parametrize("method", [
    "_process_start_activity_result", "_process_send_broadcast_result",
    "_process_open_deep_link_result",
])
@pytest.mark.parametrize("success", [True, False])
def test_intent_feedback_does_not_echo_uri_or_extra_values(controller, method, success):
    getattr(controller, method)({
        "success": success, "device_ip": "device-a", "output": "Intent { dat=demo:SECRET }",
        "error": "Error: unable to resolve Intent { dat=demo:SECRET }", "uri": "demo:SECRET",
    })
    assert "SECRET" not in controller._emit_operation.call_args.args[2]


def test_uri_only_request_defaults_view_at_model_boundary(command_calls):
    from services.intent_request import IntentRequest, validate_intent_request

    request = validate_intent_request(IntentRequest(data_uri="demo:item"))
    assert request.action == "android.intent.action.VIEW"
    ADBSystemMixin.start_activity_async.__wrapped__(_model(), "device-a", data_uri="demo:item")
    assert shlex.split(" ".join(command_calls[0][0][4:-1])) == [
        "am", "start", "-a", "android.intent.action.VIEW", "-d", "demo:item",
    ]


@pytest.mark.parametrize("flags,expected", [
    ("0", "0"), ("2147483647", "2147483647"), ("0x80000000", "-2147483648"),
    ("0xffffffff", "-1"), ("-2147483648", "-2147483648"),
])
def test_flags_round_trip_as_android_signed_32_bit_values(command_calls, flags, expected):
    ADBSystemMixin.start_activity_async.__wrapped__(
        _model(), "device-a", action="demo.ACTION", flags=flags,
    )
    command = command_calls[0][0]
    assert command[command.index("-f") + 1] == expected


@pytest.mark.parametrize("extra", [
    {"kind": "invalid"}, {"wait": "true"}, {"extras": []},
    {"kind": "broadcast", "data_uri": "demo:item"},
    {"kind": "broadcast", "wait": True}, {"flags": "-2147483649"},
])
def test_request_rejects_wrong_types_or_unsupported_field_combinations(extra):
    from services.intent_request import IntentRequest, validate_intent_request

    with pytest.raises(ValueError):
        validate_intent_request(IntentRequest(action="demo.ACTION", **extra))


@pytest.mark.parametrize("method,args", [
    ("start_activity_async", {"action": "demo.ACTION"}),
    ("send_broadcast_async", {"action": "demo.ACTION"}),
    ("open_deep_link_async", {"uri": "demo:item"}),
])
@pytest.mark.parametrize("outcome", ["failed", "cancelled", "timed_out", "stale"])
def test_intent_preserves_transport_failures(monkeypatch, method, args, outcome):
    monkeypatch.setattr(CommandRunner, "run", lambda *a, **kw: CommandResult(
        False, error="transport failure", outcome=outcome, stale=outcome == "stale",
    ))
    result = getattr(ADBSystemMixin, method).__wrapped__(_model(), "device-a", **args)
    assert result["success"] is False
    assert result["device_ip"] == "device-a"
    assert bool(result.get("cancelled")) == (outcome == "cancelled")
    assert bool(result.get("stale")) == (outcome == "stale")


def test_success_echo_containing_exception_name_is_not_misclassified(monkeypatch):
    monkeypatch.setattr(CommandRunner, "run", lambda *a, **kw: CommandResult(
        True, output="Starting: Intent { cmp=com.example/.ExceptionActivity }\nStatus: ok",
    ))
    result = ADBSystemMixin.start_activity_async.__wrapped__(
        _model(), "device-a", component="com.example/.ExceptionActivity",
    )
    assert result["success"] is True


def test_system_package_android_is_a_valid_explicit_component(command_calls):
    result = ADBSystemMixin.start_activity_async.__wrapped__(
        _model(), "device-a", component="android/com.android.internal.app.ResolverActivity",
    )
    assert result["success"] is True
    assert "android/com.android.internal.app.ResolverActivity" in command_calls[0][0]


def test_intent_jobs_keep_target_identity_and_settle_partial_results(
    controller, monkeypatch, qt_application,
):
    from adblab.application.action_results import ActionResults, ActionSpec
    from services.intent_request import IntentRequest

    class IntentModel(ADBSystemMixin, ADBModelCore):
        pass

    queued = []
    model = IntentModel()
    model.thread_pool = SimpleNamespace(start=queued.append)
    controller.advanced_model = model
    store = ActionResults(lambda _result: None)
    model.command_finished.connect(lambda _name, envelope: store.complete(
        envelope.job, envelope.payload,
    ))
    monkeypatch.setattr(CommandRunner, "run", lambda command, **kw: CommandResult(
        True, output="Status: ok" if command[2] == "device-a" else "Error: not exported",
    ))

    store.run(ActionSpec("execute_intent", "system.intent", "Intent"),
              ("device-a", "device-b"), lambda: controller.execute_intent(
                  ["device-a", "device-b"], IntentRequest(action="demo.ACTION"),
              ))
    assert store.recent()[0].state == "running"
    for task in reversed(queued):
        task.run()
    result = store.recent()[0]
    assert result.state == "partial"
    assert {item.target: item.state for item in result.items} == {
        "device-a": "succeeded", "device-b": "failed",
    }
    assert store.target_outcomes(result) == {"succeeded": 1, "failed": 1, "cancelled": 0}


def test_queued_intent_cancels_on_model_shutdown_without_adb(qt_application, command_calls):
    from adblab.application.action_results import ActionResults, ActionSpec

    class IntentModel(ADBSystemMixin, ADBModelCore):
        pass

    queued = []
    model = IntentModel()
    model.thread_pool = SimpleNamespace(start=queued.append)
    store = ActionResults(lambda _result: None)
    model.command_finished.connect(lambda _name, envelope: store.complete(
        envelope.job, envelope.payload,
    ))
    store.run(ActionSpec("execute_intent", "system.intent", "Intent"), ("device-a",),
              lambda: model.start_activity_async("device-a", action="demo.ACTION"))
    model.begin_shutdown()
    queued[0].run()
    assert store.recent()[0].state == "cancelled"
    assert store.recent()[0].items[0].target == "device-a"
    assert command_calls == []
    model.start_activity_async("device-a", action="demo.ACTION")
    assert len(queued) == 1
