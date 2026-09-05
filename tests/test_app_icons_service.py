"""应用图标的设备协议、取消与资源清理回归。"""

import base64
import hashlib
import re
import struct
import threading
import zipfile
import zlib
from pathlib import Path

import pytest

from core.exec import CommandResult
from services import app_icons


def chunk(kind, data):
    return (
        struct.pack(">I", len(data)) + kind + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def make_png(*, width=96, pixels=None, depth=8, color=6):
    header = struct.pack(">IIBBBBB", width, 96, depth, color, 0, 0, 0)
    raw = pixels if pixels is not None else (b"\0" + b"\x23\x45\x67\xff" * 96) * 96
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    )


def icon_line(package="com.example.app", png=None):
    return f"ICON\t{package}\t{base64.b64encode(png or make_png()).decode()}"


@pytest.fixture
def transport(monkeypatch, tmp_path):
    helper = tmp_path / "icons helper.jar"
    helper.write_bytes(b"bundled-helper")
    monkeypatch.setattr(app_icons, "resource_path", lambda _path: str(helper))
    calls = []
    outputs = [CommandResult(True), CommandResult(True, icon_line()), CommandResult(True)]

    def run(command, timeout):
        calls.append((command, timeout))
        outcome = outputs.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome()
        return outcome

    monkeypatch.setattr(app_icons.CommandRunner, "run", run)
    return calls, outputs


def collect(packages=None, *, cancelled=lambda: False, device="synthetic-device"):
    events = []
    app_icons.load_app_icons(
        device, packages if packages is not None else ["com.example.app"], cancelled,
        lambda *event: events.append(event),
    )
    return events


def test_load_uses_random_readonly_helper_exact_cleanup_and_bounded_output(transport):
    calls, _outputs = transport
    assert collect() == [("com.example.app", make_png(), "")]
    push, render, cleanup = [call[0] for call in calls]
    remote = push[-1]
    assert re.fullmatch(r"/data/local/tmp/adblab-icons-[0-9a-f]{32}\.jar", remote)
    assert push[:4] == ["adb", "-s", "synthetic-device", "push"]
    assert "icons helper.jar" in push[-2]
    assert f"chmod 400 {remote}" in render[-1]
    assert f"CLASSPATH={remote}" in render[-1]
    assert "app_process / com.adblab.icons.Main com.example.app" in render[-1]
    assert f"head -c {app_icons._MAX_OUTPUT_BYTES + 1}" in render[-1]
    assert "2>/dev/null" in render[-1]
    assert cleanup == ["adb", "-s", "synthetic-device", "shell", f"rm -f -- {remote}"]
    assert [timeout for _command, timeout in calls] == [8, 20, 5]


def test_each_batch_uses_its_own_path(transport):
    calls, outputs = transport
    outputs.extend([CommandResult(True), CommandResult(True, icon_line()), CommandResult(True)])
    collect()
    collect()
    assert calls[0][0][-1] != calls[3][0][-1]
    assert calls[0][0][-1] in calls[2][0][-1]
    assert calls[3][0][-1] in calls[5][0][-1]


@pytest.mark.parametrize("package", ["com.app;id", "com.app\nwhoami", "../app", "-p", "x" * 256])
def test_invalid_packages_never_reach_device(transport, package):
    calls, _outputs = transport
    assert collect([package]) == [(package, b"", "包名格式无效")]
    assert not calls


def test_android_and_deduplicated_packages_keep_exact_result_identity(transport):
    calls, outputs = transport
    outputs[1] = CommandResult(True, icon_line("android"))
    assert collect(["android", "android"]) == [("android", make_png(), "")]
    assert calls[1][0][-1].count("Main android") == 1


def test_mixed_invalid_package_does_not_block_valid_package(transport):
    assert collect(["com.bad;id", "com.example.app"]) == [
        ("com.bad;id", b"", "包名格式无效"), ("com.example.app", make_png(), "")
    ]


def test_oversized_batch_is_rejected_without_deployment(transport):
    calls, _outputs = transport
    events = collect([f"com.example.app{i}" for i in range(13)])
    assert len(events) == 13
    assert all(not png and "12" in error for _pkg, png, error in events)
    assert not calls


@pytest.mark.parametrize("device", ["", "device\nother", "a" * 1025])
def test_invalid_device_target_does_not_run(transport, device):
    calls, _outputs = transport
    assert collect(device=device)[0][2] == "设备目标无效"
    assert not calls


def test_missing_helper_returns_safe_failure_without_device_access(
    transport, monkeypatch, tmp_path
):
    calls, _outputs = transport
    monkeypatch.setattr(app_icons, "resource_path", lambda _path: str(tmp_path / "missing.jar"))
    assert collect()[0][2] == "应用图标组件缺失"
    assert not calls


@pytest.mark.parametrize("phase", ["before", "push", "render", "emit"])
def test_cancellation_stops_emissions_and_still_cleans_deployed_helper(transport, phase):
    calls, outputs = transport
    cancel = threading.Event()
    if phase == "before":
        cancel.set()
    elif phase in {"push", "render"}:
        def finish_cancelled():
            cancel.set()
            return CommandResult(True, icon_line())
        outputs[0 if phase == "push" else 1] = finish_cancelled
        if phase == "push":
            outputs.pop(1)
    if phase == "emit":
        outputs[1] = CommandResult(True, icon_line() + "\n" + icon_line("com.example.two"))
        events = []

        def emit(*event):
            events.append(event)
            cancel.set()

        app_icons.load_app_icons(
            "synthetic-device", ["com.example.app", "com.example.two"], cancel.is_set, emit
        )
        assert len(events) == 1
    else:
        assert collect(cancelled=cancel.is_set) == []
    if phase == "before":
        assert not calls
    else:
        assert calls[-1][0][-1] == f"rm -f -- {calls[0][0][-1]}"
        assert len(calls) == (2 if phase == "push" else 3)


@pytest.mark.parametrize("phase", ["push", "render", "cleanup"])
@pytest.mark.parametrize("raises", [False, True])
def test_transport_errors_and_timeouts_are_sanitized_and_cleaned(transport, phase, raises):
    calls, outputs = transport
    failure = RuntimeError("secret-local-path/device") if raises else CommandResult(
        False, error="Timeout(20s) secret-local-path/device"
    )
    outputs[{"push": 0, "render": 1, "cleanup": 2}[phase]] = failure
    if phase == "push":
        outputs.pop(1)
    events = collect()
    assert events[0][1] == b""
    assert events[0][2] and "secret" not in events[0][2]
    assert calls[-1][0][-1] == f"rm -f -- {calls[0][0][-1]}"
    if phase == "cleanup":
        assert "清理失败" in events[0][2]


@pytest.mark.parametrize("output", [
    "", "broken", "ICON\tcom.foreign.app\tAAA=", "ICON\tcom.example.app\t%%%",
    "ERROR\tcom.example.app\t/secret/path/device", "ERROR\tcom.example.app\tRENDER_FAILED\textra",
])
def test_bad_protocol_or_base64_never_becomes_an_icon(transport, output):
    _calls, results = transport
    results[1] = CommandResult(True, output)
    events = collect()
    assert events[0][1] == b""
    assert events[0][2] and "secret" not in events[0][2]


def test_duplicate_results_fail_closed(transport):
    _calls, outputs = transport
    outputs[1] = CommandResult(True, icon_line() + "\n" + icon_line())
    assert collect() == [("com.example.app", b"", "设备图标响应无效")]


def test_valid_icon_and_package_error_are_reported_independently(transport):
    _calls, outputs = transport
    outputs[1] = CommandResult(
        True, icon_line() + "\nERROR\tcom.example.missing\tNOT_FOUND"
    )
    assert collect(["com.example.app", "com.example.missing"]) == [
        ("com.example.app", make_png(), ""),
        ("com.example.missing", b"", "当前用户未安装此应用"),
    ]


def test_total_response_bound_rejects_before_parsing(transport):
    _calls, outputs = transport
    outputs[1] = CommandResult(True, "x" * (app_icons._MAX_OUTPUT_BYTES + 1))
    assert collect() == [("com.example.app", b"", "设备图标响应无效")]


@pytest.mark.parametrize("png", [
    b"fake PNG", make_png(width=4096), make_png(depth=16), make_png(color=3),
    make_png()[:-1], make_png() + b"trailing", make_png(pixels=b"x" * 200_000),
    make_png(pixels=(b"\x05" + b"\x00" * 384) * 96),
    make_png()[:-5] + b"\x00" * 5,
])
def test_png_format_canvas_crc_and_decompression_boundaries(transport, png):
    _calls, outputs = transport
    outputs[1] = CommandResult(True, icon_line(png=png))
    assert collect() == [("com.example.app", b"", "应用图标数据无效")]


def test_individual_image_byte_limit_is_enforced(transport):
    _calls, outputs = transport
    outputs[1] = CommandResult(True, icon_line(png=b"x" * (app_icons.MAX_PNG_BYTES + 1)))
    assert collect()[0][2] == "应用图标数据无效"


def test_bundled_dex_matches_source_hash_and_fixed_archive_metadata():
    from scripts.build_app_icon_helper import verify_helper

    root = Path(__file__).resolve().parents[1]
    archive_path = root / "resources/app-icon-helper.jar"
    verify_helper(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert archive.read("META-INF/adblab-source.sha256").decode().strip() == hashlib.sha256(
            (root / "tools/app_icons/Main.java").read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()


def test_source_digest_is_stable_across_windows_checkout_newlines(monkeypatch, tmp_path):
    from scripts import build_app_icon_helper

    source = tmp_path / "Main.java"
    monkeypatch.setattr(build_app_icon_helper, "_SOURCE", source)
    source.write_bytes(b"one\ntwo\n")
    digest = build_app_icon_helper._source_digest()
    source.write_bytes(b"one\r\ntwo\r\n")
    assert build_app_icon_helper._source_digest() == digest


def test_icon_worker_dispatches_packages_and_relays_png(monkeypatch):
    from models import app_manager_worker

    received = []
    calls = []

    def load(device_id, packages, cancelled, emit):
        calls.append((device_id, packages, cancelled()))
        emit(packages[0], b"png", "")

    monkeypatch.setattr(app_manager_worker, "load_app_icons", load)
    worker = app_manager_worker.AppManagerWorker(
        "synthetic-device", "load_icon_batch", packages=["com.example.app"]
    )
    worker.app_icon_loaded.connect(lambda *args: received.append(args))
    worker.run()
    assert calls == [("synthetic-device", ["com.example.app"], False)]
    assert received == [("com.example.app", b"png", "")]


def test_icon_worker_aborted_before_start_has_no_device_work(monkeypatch):
    from models import app_manager_worker

    calls = []
    monkeypatch.setattr(app_manager_worker, "load_app_icons", lambda *args: calls.append(args))
    worker = app_manager_worker.AppManagerWorker(
        "synthetic-device", "load_icon_batch", packages=["com.example.app"]
    )
    worker.abort()
    worker.run()
    assert not calls


def test_icon_worker_runs_in_background_and_abort_reaches_service(monkeypatch):
    from models import app_manager_worker

    entered = threading.Event()
    abort_seen = threading.Event()
    thread_ids = []
    observations = []

    def load(_device, _packages, cancelled, _emit):
        thread_ids.append(threading.get_ident())
        entered.set()
        observations.append((abort_seen.wait(2), cancelled()))

    monkeypatch.setattr(app_manager_worker, "load_app_icons", load)
    worker = app_manager_worker.AppManagerWorker(
        "synthetic-device", "load_icon_batch", packages=["com.example.app"]
    )
    worker.start()
    try:
        assert entered.wait(2)
        worker.abort()
    finally:
        abort_seen.set()
        assert worker.wait(2000)
    assert thread_ids and thread_ids[0] != threading.get_ident()
    assert observations == [(True, True)]
