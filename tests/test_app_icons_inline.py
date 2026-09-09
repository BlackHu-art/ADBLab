"""小型图标 helper 合并调用的性能与收尾边界。"""

import base64
import re
import shlex
import threading

import pytest

from core.adb_transport import ExecutionResult
from core.exec import CommandResult, _normalise_result
from services import app_icons
from tests.test_app_icons_service import collect, icon_line, make_png

CLEANED = "\n__ADBLAB_ICONS_CLEANED__\n"


@pytest.fixture
def inline(monkeypatch, tmp_path):
    helper = tmp_path / "helper.jar"
    helper.write_bytes(b"small-bundled-helper")
    monkeypatch.setattr(app_icons, "resource_path", lambda _path: str(helper))
    calls = []

    def run(command, timeout, **kwargs):
        calls.append((command, timeout, kwargs))
        return CommandResult(True, icon_line() + CLEANED if "app_process" in command[-1] else "")

    monkeypatch.setattr(app_icons.CommandRunner, "run", run)
    return helper, calls


@pytest.mark.parametrize("normalised", [False, True])
def test_small_helper_needs_one_shell_call_including_confirmed_cleanup(
    inline, monkeypatch, normalised,
):
    _helper, calls = inline
    if normalised:
        original = app_icons.CommandRunner.run

        def run(*args, **kwargs):
            result = original(*args, **kwargs)
            result.output = result.output.strip()
            return result

        monkeypatch.setattr(app_icons.CommandRunner, "run", run)
    assert collect() == [("com.example.app", make_png(), "")]
    assert len(calls) == 1
    command, timeout, kwargs = calls[0]
    assert command[:6] == ["adb", "-s", "synthetic-device", "shell", "sh", "-c"]
    script = shlex.split(command[-1])[0]
    remote = re.search(r"/data/local/tmp/adblab-icons-[0-9a-f]{32}\.jar", script).group()
    assert "trap " in script and f"rm -f -- {remote}" in script
    assert "base64 -d" in script and "umask 077" in script
    assert f"chmod 400 {remote}" in script and f"CLASSPATH={remote}" in script
    assert timeout >= 30 and callable(kwargs["cancelled"])


def test_inline_keeps_binary_payload_complete_and_windows_command_bounded(inline):
    helper, calls = inline
    payload = bytes(range(256)) * 64
    helper.write_bytes(payload)
    assert collect()[0][1] == make_png()
    script = shlex.split(calls[0][0][-1])[0]
    encoded = re.search(r"printf %s ([A-Za-z0-9+/=]+) ", script).group(1)
    assert base64.b64decode(encoded, validate=True) == payload
    assert len(" ".join(calls[0][0])) < 32767


@pytest.mark.parametrize("cancel", [False, True])
def test_unconfirmed_inline_exit_runs_exact_cleanup_without_replaying(inline, monkeypatch, cancel):
    _helper, calls = inline
    stop = threading.Event()

    def run(command, timeout, *, cancelled=None):
        calls.append((command, timeout, {"cancelled": cancelled}))
        if len(calls) == 1:
            if cancel:
                stop.set()
            return CommandResult(False, error="Timeout: private identifier")
        assert cancelled is None
        return CommandResult(True)

    monkeypatch.setattr(app_icons.CommandRunner, "run", run)
    events = collect(cancelled=stop.is_set)
    assert not events if cancel else events == [("com.example.app", b"", "应用图标读取失败")]
    assert len(calls) == 2
    remote = re.search(r"/data/local/tmp/adblab-icons-[0-9a-f]{32}\.jar", calls[0][0][-1]).group()
    assert calls[1][0] == ["adb", "-s", "synthetic-device", "shell", f"rm -f -- {remote}"]


def test_inline_cleanup_failure_never_publishes_icon(inline, monkeypatch):
    _helper, calls = inline

    def run(command, timeout, **kwargs):
        calls.append((command, timeout, kwargs))
        return CommandResult(True, icon_line()) if len(calls) == 1 else CommandResult(False)

    monkeypatch.setattr(app_icons.CommandRunner, "run", run)
    assert collect() == [("com.example.app", b"", "应用图标临时文件清理失败")]


def test_inline_deployment_failure_is_reported_without_native_replay(inline, monkeypatch):
    _helper, calls = inline

    def run(command, timeout, **kwargs):
        calls.append((command, timeout, kwargs))
        assert "exit 0; fi;" in shlex.split(command[-1])[0]
        return _normalise_result(ExecutionResult(
            stdout=("__ADBLAB_ICONS_DEPLOY_FAILED__" + CLEANED).encode(), returncode=0,
        ), timeout)

    monkeypatch.setattr(app_icons.CommandRunner, "run", run)
    assert collect() == [("com.example.app", b"", "应用图标组件传输失败")]
    assert len(calls) == 1 and calls[0][0][3] == "shell"


def test_inline_batches_do_not_share_remote_path(inline):
    _helper, calls = inline
    assert collect()[0][1] and collect()[0][1]
    targets = [re.search(r"/data/local/tmp/adblab-icons-[0-9a-f]{32}\.jar", cmd[-1]).group()
               for cmd, _timeout, _kwargs in calls]
    assert len(targets) == 2 and len(set(targets)) == 2


def test_inline_cancelled_result_does_not_publish_even_when_cleanup_confirmed(inline, monkeypatch):
    _helper, calls = inline
    stopped = threading.Event()

    def run(command, timeout, **kwargs):
        calls.append((command, timeout, kwargs))
        stopped.set()
        return CommandResult(True, icon_line() + CLEANED)

    monkeypatch.setattr(app_icons.CommandRunner, "run", run)
    assert collect(cancelled=stopped.is_set) == []
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body", ["broken", icon_line() + "\n" + icon_line(), "X" * (app_icons._MAX_OUTPUT_BYTES + 1)],
    ids=["malformed", "duplicate", "oversized"],
)
def test_confirmed_cleanup_does_not_weaken_output_validation(inline, monkeypatch, body):
    _helper, calls = inline

    def run(command, timeout, **kwargs):
        calls.append((command, timeout, kwargs))
        return CommandResult(True, body + CLEANED)

    monkeypatch.setattr(app_icons.CommandRunner, "run", run)
    assert collect() == [("com.example.app", b"", "设备图标响应无效")]
    assert len(calls) == 1
