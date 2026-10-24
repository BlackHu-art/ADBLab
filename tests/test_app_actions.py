import shlex
from types import SimpleNamespace

import pytest

from services.apps import actions


def result(success=True, output="", error="", stdout=None):
    return SimpleNamespace(
        success=success, output=output, error=error, stdout=output if stdout is None else stdout
    )


def callbacks(events):
    return dict(
        log=lambda text: events.append(("log", text)),
        failure=lambda text: events.append(("failure", text)),
        completed=lambda text: events.append(("done", text)),
    )


@pytest.mark.parametrize(
    "action,argv",
    [
        ("disable", ("shell", "pm", "disable-user")),
        ("enable", ("shell", "pm", "enable")),
        ("uninstall", ("uninstall",)),
        ("force_stop", ("shell", "am", "force-stop")),
    ],
)
@pytest.mark.parametrize("success", [True, False])
def test_modify_actions_preserve_argv_and_feedback_order(action, argv, success):
    events, calls = [], []

    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return result(success, error=" failure ")

    actions.modify_app(
        action,
        "org.example.app",
        12,
        execute=execute,
        feedback=lambda *args: events.append(args),
        **callbacks(events),
    )
    assert calls == [(argv + ("--user", "12", "org.example.app"), {})]
    assert events == [
        ("log", f"{'OK' if success else 'FAIL'}: {action} org.example.app"),
        ("done", action) if success else ("error", "failure"),
    ]


@pytest.mark.parametrize(
    "kind,args,message",
    [
        ("modify_app", ("unknown", "bad;pkg", 0), "Invalid package: bad;pkg"),
        ("modify_app", ("unknown", "org.example.app", 0), "Invalid app action: unknown"),
        ("launch_app", ("bad;pkg", 0), "Invalid package: bad;pkg"),
        ("clear_app", ("bad;pkg", 0), "Invalid package: bad;pkg"),
        ("modify_permission", ("bad;pkg", "invalid", "bad", 0), "Invalid package: bad;pkg"),
        (
            "modify_permission",
            ("org.example.app", "invalid", "bad", 0),
            "Invalid permission action: bad",
        ),
        (
            "modify_permission",
            ("org.example.app", "bad permission", "grant", 0),
            "权限标识无效，请刷新应用详情后重试。",
        ),
    ],
)
def test_action_validation_rejects_before_execute(kind, args, message):
    events = []
    options = callbacks(events)
    if kind == "modify_app":
        options["feedback"] = lambda *_: pytest.fail("unexpected feedback")
    if kind == "clear_app":
        options["permission_denied"] = lambda: pytest.fail("unexpected denial")
    getattr(actions, kind)(*args, execute=lambda *_: pytest.fail("unexpected write"), **options)
    assert events == [("failure", message)]


@pytest.mark.parametrize(
    "permission", ["org.example.权限", "org.example.Custom$Permission", "org.example.some-perm"]
)
def test_permission_is_one_literal_argument(permission):
    events, calls = [], []

    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return result()

    actions.modify_permission(
        "org.example.app", permission, "grant", 0, execute=execute, **callbacks(events)
    )
    assert calls[0][0][:-1] == ("shell", "pm", "grant", "--user", "0", "org.example.app")
    assert shlex.split(calls[0][0][-1]) == [permission]
    assert calls[0][1] == {}
    assert events == [
        ("log", f"Permission grant: {permission} — OK"),
        ("done", "permissions_changed"),
    ]


@pytest.mark.parametrize(
    "success,output,failed",
    [
        (False, "offline", True),
        (True, "Error: missing", True),
        (True, "status\nERROR missing", True),
        (True, "Warning: existing task", False),
    ],
)
def test_launch_error_output_and_warning_keep_existing_semantics(success, output, failed):
    events, calls = [], []

    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return result(success, output)

    actions.launch_app("org.example.app", 0, execute=execute, **callbacks(events))
    assert calls == [
        (
            (
                "shell",
                "am",
                "start",
                "--user",
                "0",
                "-a",
                "android.intent.action.MAIN",
                "-p",
                "org.example.app",
                "-c",
                "android.intent.category.LAUNCHER",
                "-f",
                "0x10200000",
                "2>&1",
            ),
            {},
        )
    ]
    assert events == (
        [("failure", f"Failed to launch org.example.app: {output}")]
        if failed
        else [("log", "Launched org.example.app"), ("done", "launch")]
    )


@pytest.mark.parametrize(
    "output,error",
    [
        ("SecurityException: denied", "SecurityException: denied"),
        ("Permission Denial: denied", "extra diagnostic"),
    ],
)
def test_clear_denial_logs_before_lazy_hint_callback(output, error):
    events = []
    actions.clear_app(
        "org.example.app",
        0,
        execute=lambda *args: result(False, output, error),
        permission_denied=lambda: events.append(("hint",)),
        **callbacks(events),
    )
    diagnostic = "\n".join(dict.fromkeys((output, error)))
    assert events == [("log", f"Failed to clear data for org.example.app: {diagnostic}"), ("hint",)]


@pytest.mark.parametrize("success", [True, False])
def test_clear_ordinary_result_has_no_permission_hint(success):
    events = []
    actions.clear_app(
        "org.example.app",
        4,
        execute=lambda *args: result(success, " Success ", "offline"),
        permission_denied=lambda: pytest.fail("unexpected hint"),
        **callbacks(events),
    )
    assert events == (
        [("log", "Cleared data: org.example.app — Success"), ("done", "clear")]
        if success
        else [("failure", "Failed to clear data for org.example.app: offline")]
    )


@pytest.mark.parametrize(
    "error,output,expected",
    [
        (" error ", " output ", "error"),
        (None, " output ", "output"),
        (" ", None, "fallback"),
    ],
)
def test_command_error_preserves_priority_and_stripping(error, output, expected):
    assert (
        actions.command_error(result(False, output, error, stdout="ignored"), "fallback")
        == expected
    )


def test_modify_reads_success_again_after_log_callback():
    events = []
    response = result()

    def log(text):
        events.append(("log", text))
        response.success = False
        response.error = "changed synchronously"

    options = callbacks(events)
    options["log"] = log
    actions.modify_app(
        "enable",
        "org.example.app",
        0,
        execute=lambda *args: response,
        feedback=lambda *args: events.append(args),
        **options,
    )
    assert events == [("log", "OK: enable org.example.app"), ("error", "changed synchronously")]


@pytest.mark.parametrize("kind", ["modify_app", "launch_app", "clear_app", "modify_permission"])
def test_action_callback_exception_propagates_without_later_notification(kind):
    events = []

    def log(_):
        raise RuntimeError("callback failed")

    options = callbacks(events)
    options["log"] = log
    args = {
        "modify_app": ("enable", "org.example.app", 0),
        "launch_app": ("org.example.app", 0),
        "clear_app": ("org.example.app", 0),
        "modify_permission": ("org.example.app", "org.example.permission", "grant", 0),
    }[kind]
    if kind == "modify_app":
        options["feedback"] = lambda *args: events.append(args)
    if kind == "clear_app":
        options["permission_denied"] = lambda: events.append(("hint",))
    with pytest.raises(RuntimeError, match="callback failed"):
        getattr(actions, kind)(*args, execute=lambda *args: result(), **options)
    assert events == []
