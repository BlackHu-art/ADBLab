"""图标缓存身份必须来自同次渲染，不能沿用此前元数据查询的身份。"""

import base64
import shlex
import threading

import pytest

from core.exec import CommandResult
from services import app_icons, app_metadata
from tests.test_app_icons_service import icon_line, make_png
from tests.test_app_metadata import metadata_line


def verified_line(package="com.example.app", **changes):
    encoded = metadata_line(package, **changes).split("\t")[2]
    png = base64.b64encode(make_png()).decode()
    return f"ICON_META\t{package}\t{encoded}\t{png}"


def fingerprint(package="com.example.app", **changes):
    result = app_metadata._parse_output(metadata_line(package, **changes), [package])
    return result.records[package].fingerprint


@pytest.fixture
def transport(monkeypatch, tmp_path):
    helper = tmp_path / "helper.jar"
    helper.write_bytes(b"small-helper")
    monkeypatch.setattr(app_icons, "resource_path", lambda _path: str(helper))
    calls = []
    outputs = [CommandResult(True, verified_line() + app_icons._CLEANED)]

    def run(command, timeout, **kwargs):
        calls.append((command, timeout, kwargs))
        result = outputs.pop(0)
        return result() if callable(result) else result

    monkeypatch.setattr(app_icons.CommandRunner, "run", run)
    return helper, calls, outputs


def collect(packages=None, *, expected=None, cancelled=lambda: False):
    events = []
    app_icons.load_app_icons(
        "synthetic-device", packages or ["com.example.app"], cancelled,
        lambda *event: events.append(event), expected_fingerprints=expected,
    )
    return events


def test_matching_render_identity_delivers_png_with_one_cleaned_shell(transport):
    _helper, calls, _outputs = transport
    assert collect(expected={"com.example.app": fingerprint()}) == [
        ("com.example.app", make_png(), ""),
    ]
    assert len(calls) == 1
    script = shlex.split(calls[0][0][-1])[0]
    assert "Main --icons-metadata com.example.app" in script
    assert f"head -c {app_icons._MAX_ICON_METADATA_OUTPUT_BYTES + 1}" in script


@pytest.mark.parametrize("change", [
    {"user": 11}, {"version_code": "4294967297"}, {"updated": 1780000000001},
    {"configuration": "en_US density=420 night=16"}, {"source": "/data/app/new/base.apk"},
])
def test_metadata_a_then_render_b_never_labels_b_pixels_as_a(transport, change):
    _helper, calls, outputs = transport
    outputs[0] = CommandResult(True, verified_line(**change) + app_icons._CLEANED)
    events = collect(expected={"com.example.app": fingerprint()})
    assert events == [("com.example.app", b"", "应用或设备配置已变化，请刷新应用列表")]
    assert len(calls) == 1


@pytest.mark.parametrize("expected", [None, {}, {"com.example.app": ""},
                                      {"com.other.app": "a" * 64}])
def test_no_valid_expected_identity_keeps_existing_icon_protocol(transport, expected):
    _helper, calls, outputs = transport
    outputs[0] = CommandResult(True, icon_line() + app_icons._CLEANED)
    assert collect(expected=expected) == [("com.example.app", make_png(), "")]
    script = shlex.split(calls[0][0][-1])[0]
    assert "Main com.example.app" in script and "--icons-metadata" not in script


def test_invalid_nonempty_identity_is_rejected_without_weakening_to_legacy(transport):
    _helper, calls, _outputs = transport
    assert collect(expected={"com.example.app": "not-a-fingerprint"}) == [
        ("com.example.app", b"", "应用缓存身份无效，请刷新应用列表"),
    ]
    assert not calls


def test_mixed_batch_allows_current_pixels_without_reusable_identity_for_unverified_package(
    transport,
):
    _helper, _calls, outputs = transport
    outputs[0] = CommandResult(True, verified_line() + "\n"
                               + verified_line("com.example.other", user=11) + app_icons._CLEANED)
    assert collect(["com.example.app", "com.example.other"],
                   expected={"com.example.app": fingerprint()}) == [
        ("com.example.app", make_png(), ""), ("com.example.other", make_png(), ""),
    ]


@pytest.mark.parametrize("body", [
    icon_line(), verified_line() + "\n" + verified_line(),
    verified_line("com.other.app"), "ICON_META\tcom.example.app\t%%%\t%%%",
    verified_line().rsplit("\t", 1)[0] + "\t%%%",
    "ICON_META\tcom.example.app\tAAAA",
], ids=["old-protocol", "duplicate", "foreign-package", "bad-metadata", "bad-png", "truncated"])
def test_verified_protocol_failures_do_not_deliver_png_or_retry(transport, body):
    _helper, calls, outputs = transport
    outputs[0] = CommandResult(True, body + app_icons._CLEANED)
    events = collect(expected={"com.example.app": fingerprint()})
    assert not events[0][1] and events[0][2] and len(calls) == 1


@pytest.mark.parametrize("error", ["IDENTITY_CHANGED", "USER_CHANGED"])
def test_device_detected_change_during_render_is_an_actionable_failure(transport, error):
    _helper, _calls, outputs = transport
    outputs[0] = CommandResult(True, f"ERROR\tcom.example.app\t{error}" + app_icons._CLEANED)
    events = collect(expected={"com.example.app": fingerprint()})
    assert not events[0][1] and "刷新" in events[0][2]


def test_valid_identity_never_bypasses_cleanup_failure(transport):
    _helper, calls, outputs = transport
    outputs[:] = [CommandResult(True, verified_line()), CommandResult(False)]
    events = collect(expected={"com.example.app": fingerprint()})
    assert events == [("com.example.app", b"", "应用图标临时文件清理失败")]
    assert len(calls) == 2 and calls[-1][0][-1].startswith("rm -f -- ")


def test_cancelled_verified_icons_do_not_publish_after_confirmed_cleanup(transport):
    _helper, calls, outputs = transport
    stop = threading.Event()

    def cancel():
        stop.set()
        return CommandResult(True, verified_line() + app_icons._CLEANED)

    outputs[0] = cancel
    assert collect(expected={"com.example.app": fingerprint()}, cancelled=stop.is_set) == []
    assert len(calls) == 1


def test_large_helper_verified_mode_preserves_push_and_precise_cleanup(transport):
    helper, calls, outputs = transport
    helper.write_bytes(b"x" * (app_icons._MAX_INLINE_HELPER_BYTES + 1))
    outputs[:] = [CommandResult(True), CommandResult(True, verified_line()), CommandResult(True)]
    assert collect(expected={"com.example.app": fingerprint()})[0][1] == make_png()
    assert calls[0][0][3] == "push"
    assert "Main --icons-metadata" in calls[1][0][-1]
    assert calls[2][0][-1] == f"rm -f -- {calls[0][0][-1]}"
