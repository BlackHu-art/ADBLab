"""应用元数据批量协议、缓存身份与临时 helper 生命周期。"""

import base64
import json
import re
import shlex
import threading

import pytest

from core.exec import CommandResult
from services import app_icons, app_metadata


def metadata_line(package="com.example.app", **changes):
    payload = {
        "user": 10,
        "label": "应用\t名称\n示例 🌟",
        "version_name": "1.2",
        "version_code": "4294967296",
        "installed": "2026-09-25",
        "updated": 1780000000000,
        "source": "/data/app/example/base.apk",
        "configuration": "zh_CN density=420 night=32",
    }
    payload.update(changes)
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    return f"META\t{package}\t{encoded}"


@pytest.fixture
def transport(monkeypatch, tmp_path):
    helper = tmp_path / "helper.jar"
    helper.write_bytes(b"small-metadata-helper")
    monkeypatch.setattr(app_icons, "resource_path", lambda _path: str(helper))
    calls = []
    outputs = [CommandResult(True, metadata_line() + app_icons._CLEANED)]

    def run(command, timeout, **kwargs):
        calls.append((command, timeout, kwargs))
        result = outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result() if callable(result) else result

    monkeypatch.setattr(app_icons.CommandRunner, "run", run)
    return helper, calls, outputs


def collect(packages=None, cancelled=lambda: False, device="synthetic-device"):
    return app_metadata.load_app_metadata(
        device, ["com.example.app"] if packages is None else packages, cancelled,
    )


def test_unicode_metadata_reads_all_fields_in_one_cleaned_shell(transport):
    _helper, calls, _outputs = transport
    result = collect()
    record = result.records["com.example.app"]
    assert record.package == "com.example.app"
    assert record.label == "应用\t名称\n示例 🌟"
    assert record.version == "1.2 (4294967296)"
    assert record.installed == "2026-09-25"
    assert re.fullmatch(r"[0-9a-f]{64}", record.fingerprint)
    assert not result.unsupported
    assert len(calls) == 1
    command, timeout, kwargs = calls[0]
    script = shlex.split(command[-1])[0]
    assert "Main --metadata com.example.app" in script
    assert f"head -c {app_metadata.MAX_OUTPUT_BYTES + 1}" in script
    assert "trap " in script and "rm -f -- /data/local/tmp/adblab-icons-" in script
    assert timeout == 30 and callable(kwargs["cancelled"])


@pytest.mark.parametrize("field,value", [
    ("user", 11), ("version_name", "1.3"), ("version_code", "4294967297"),
    ("updated", 1780000000001), ("source", "/data/app/new/base.apk"),
    ("configuration", "en_US density=420 night=16"),
])
def test_cache_identity_tracks_user_package_version_resources_and_update(transport, field, value):
    _helper, _calls, outputs = transport
    initial = collect().records["com.example.app"]
    outputs.append(CommandResult(True, metadata_line(**{field: value}) + app_icons._CLEANED))
    changed = collect().records["com.example.app"]
    assert initial.fingerprint != changed.fingerprint
    outputs.append(CommandResult(True, metadata_line(**{field: value}) + app_icons._CLEANED))
    assert collect().records["com.example.app"].fingerprint == changed.fingerprint


def test_name_and_install_date_do_not_change_icon_identity(transport):
    _helper, _calls, outputs = transport
    initial = collect().records["com.example.app"].fingerprint
    outputs.append(CommandResult(True, metadata_line(label="new label", installed="2020-01-01")
                                 + app_icons._CLEANED))
    assert collect().records["com.example.app"].fingerprint == initial


def test_android_and_duplicate_packages_keep_single_exact_result(transport):
    _helper, calls, outputs = transport
    outputs[0] = CommandResult(True, metadata_line("android") + app_icons._CLEANED)
    assert set(collect(["android", "android"]).records) == {"android"}
    assert "Main --metadata android" in calls[0][0][-1]


def test_missing_helper_is_explicitly_unsupported(transport):
    helper, calls, _outputs = transport
    helper.unlink()
    assert collect().unsupported
    assert not calls


def test_only_complete_context_unavailable_response_is_unsupported(transport):
    _helper, _calls, outputs = transport
    outputs[0] = CommandResult(True, "META_ERROR\tcom.example.app\tCONTEXT_UNAVAILABLE"
                               + app_icons._CLEANED)
    result = collect()
    assert result.unsupported and not result.records


def test_partial_context_failure_does_not_request_another_query(transport):
    _helper, _calls, outputs = transport
    outputs[0] = CommandResult(True, "META_ERROR\tcom.example.app\tCONTEXT_UNAVAILABLE"
                               + app_icons._CLEANED)
    result = collect(["com.example.app", "com.example.other"])
    assert not result.unsupported and not result.records


def test_null_version_name_preserves_existing_blank_version_display(transport):
    _helper, _calls, outputs = transport
    outputs[0] = CommandResult(True, metadata_line(version_name="") + app_icons._CLEANED)
    assert collect().records["com.example.app"].version == ""


@pytest.mark.parametrize("body", [
    "", "broken", "META\tcom.example.app\t%%%", "ICON\tcom.example.app\tAAAA",
    "META_ERROR\tcom.example.app\tNOT_FOUND", "META_ERROR\tcom.example.app\tUSER_CHANGED",
    "META_ERROR\tcom.example.app\tREAD_FAILED", "META_ERROR\tcom.example.app\tunknown",
    "META_ERROR\tcom.other.app\tCONTEXT_UNAVAILABLE", metadata_line("com.other.app"),
    metadata_line() + "\n" + metadata_line(), "非 ASCII",
    "x" * (256 * 1024 + 1),
], ids=["empty", "broken", "base64", "icon-mode", "missing", "user-changed", "read-failed",
        "unknown-error", "foreign-error", "foreign-package", "duplicate", "unicode", "oversized"])
def test_failed_or_malformed_response_never_enables_fallback(transport, body):
    _helper, _calls, outputs = transport
    outputs[0] = CommandResult(True, body + app_icons._CLEANED)
    result = collect()
    assert not result.records and not result.unsupported


@pytest.mark.parametrize("changes", [
    {"user": True}, {"user": -1}, {"label": 12}, {"label": "x" * 8193},
    {"version_code": "bad"}, {"updated": -1}, {"updated": False},
    {"installed": "2026-13-32"}, {"installed": "2026-9-25"},
    {"configuration": "x" * 8193}, {"source": "x" * 8193},
])
def test_bad_metadata_fields_are_rejected(transport, changes):
    _helper, _calls, outputs = transport
    outputs[0] = CommandResult(True, metadata_line(**changes) + app_icons._CLEANED)
    result = collect()
    assert not result.records and not result.unsupported


def test_invalid_unicode_scalar_is_rejected_before_gui_delivery(transport):
    _helper, _calls, outputs = transport
    raw = base64.b64decode(metadata_line().split("\t")[2]).decode()
    invalid = raw.replace('"1.2"', '"\\ud800"').encode()
    outputs[0] = CommandResult(True, "META\tcom.example.app\t"
                               + base64.b64encode(invalid).decode() + app_icons._CLEANED)
    assert not collect().records


def test_missing_package_result_retains_valid_records_without_fallback(transport):
    result = collect(["com.example.app", "com.example.missing"])
    assert set(result.records) == {"com.example.app"} and not result.unsupported


@pytest.mark.parametrize("package", ["com.bad;id", "com.bad\napp", "../app", "-p", "x" * 256])
def test_invalid_package_never_reaches_device(transport, package):
    _helper, calls, _outputs = transport
    result = collect([package])
    assert not result.records and not result.unsupported and not calls


def test_metadata_batch_limit_is_thirty_and_command_line_stays_bounded(transport):
    helper, calls, outputs = transport
    helper.write_bytes(b"x" * app_icons._MAX_INLINE_HELPER_BYTES)
    packages = [f"com.example.app{index:02d}" + "x" * 238 for index in range(30)]
    outputs[0] = CommandResult(True, "\n".join(metadata_line(pkg) for pkg in packages)
                               + app_icons._CLEANED)
    assert len(collect(packages).records) == 30
    assert len(" ".join(calls[0][0])) < 32767
    assert not collect(packages + ["com.example.overflow"]).records
    assert len(calls) == 1


@pytest.mark.parametrize("device", ["", "device\nother", "x" * 1025])
def test_invalid_device_never_reaches_transport(transport, device):
    _helper, calls, _outputs = transport
    assert not collect(device=device).records and not calls


@pytest.mark.parametrize("failure", [CommandResult(False, error="Timeout"), RuntimeError("secret")])
def test_transport_failure_cleans_exact_path_without_retry_or_fallback(transport, failure):
    _helper, calls, outputs = transport
    outputs[:] = [failure, CommandResult(True)]
    result = collect()
    assert not result.records and not result.unsupported
    assert len(calls) == 2
    remote = re.search(r"/data/local/tmp/adblab-icons-[0-9a-f]{32}\.jar", calls[0][0][-1]).group()
    assert calls[1][0][-1] == f"rm -f -- {remote}"
    assert "cancelled" not in calls[1][2]


def test_cleanup_failure_discards_even_valid_metadata(transport):
    _helper, _calls, outputs = transport
    outputs[:] = [CommandResult(True, metadata_line()), CommandResult(False)]
    result = collect()
    assert not result.records and not result.unsupported


@pytest.mark.parametrize("before", [False, True])
def test_cancelled_metadata_is_not_published_and_cleanup_ignores_cancellation(transport, before):
    _helper, calls, outputs = transport
    stop = threading.Event()
    if before:
        stop.set()
    else:
        def interrupted():
            stop.set()
            return CommandResult(False, error="Cancelled")
        outputs[:] = [interrupted, CommandResult(True)]
    result = collect(cancelled=stop.is_set)
    assert not result.records and not result.unsupported
    assert len(calls) == (0 if before else 2)
    if not before:
        assert calls[0][2]["cancelled"] is stop.is_set or calls[0][2]["cancelled"]()
        assert "cancelled" not in calls[1][2]


def test_large_helper_retains_push_and_independent_cleanup(transport):
    helper, calls, outputs = transport
    helper.write_bytes(b"x" * (app_icons._MAX_INLINE_HELPER_BYTES + 1))
    outputs[:] = [CommandResult(True), CommandResult(True, metadata_line()), CommandResult(True)]
    assert collect().records["com.example.app"].label.startswith("应用")
    assert calls[0][0][3] == "push" and len(calls) == 3
    assert "Main --metadata com.example.app" in calls[1][0][-1]
    assert calls[2][0][-1] == f"rm -f -- {calls[0][0][-1]}"
