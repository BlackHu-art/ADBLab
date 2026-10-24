"""纯文件事务直接验证字节、通知时点、清理归属与异常边界。"""

import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from core.exec import CommandResult


def test_pure_service_import_and_fake_transactions_without_qt(tmp_path):
    env = os.environ.copy()
    for name in (
        "LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
        "XDG_DATA_HOME", "MOBILEPERF_LOG_DIR",
    ):
        env[name] = str(tmp_path / name)
    script = r'''
import importlib.abc
import sys
from pathlib import Path

forbidden = ("PySide6", "PyQt5", "PyQt6", "qfluentwidgets", "gui", "models",
             "adblab.presentation", "core.log_service")
def blocked(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
assert not any(blocked(name) for name in sys.modules)
class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if blocked(fullname):
            raise AssertionError("Forbidden dependency: " + fullname)
sys.meta_path.insert(0, NoQt())
from core.exec import CommandResult, CommandRunner
from services import file_operations as service
def unexpected(*args, **kwargs):
    raise AssertionError("Real executor called")
CommandRunner.run = unexpected
CommandRunner.run_to_file = unexpected
captures, calls, results, decoded, warnings = [], [], [], [], []
def cancelled():
    return False
def capture(cmd, output_path, *, timeout, cancelled):
    assert cmd[:3] == ["adb", "-s", "synthetic-device"] and cmd[3] == "exec-out"
    assert timeout == 30 and cancelled() is False
    path = Path(output_path)
    captures.append(path)
    if "ADBLAB_LIST_END_" in cmd[-1]:
        raw = b"ADBLAB_LIST_V1\0ADBLAB_LIST_END_probe"
    elif "ADBLAB_TEXT_END_" in cmd[-1]:
        raw = b"\xef\xbb\xbf raw \r\nADBLAB_TEXT_END_probe"
    else:
        raw = b"ADBLAB_TARGET:/device/target.txt\n:END"
    path.write_bytes(raw)
    return CommandResult(True)
def run(cmd, *, timeout, cancelled):
    assert cmd[:3] == ["adb", "-s", "synthetic-device"]
    calls.append((cmd, timeout, cancelled))
    if cmd[3] == "push":
        assert timeout == 120 and cancelled() is False
        assert Path(cmd[4]).read_bytes() == b"remote payload"
    elif timeout == 15:
        assert cancelled is None
    else:
        assert timeout == 30 and cancelled() is False
    return CommandResult(True)
service.read_directory("synthetic-device", "/device", False, b"ADBLAB_LIST_END_probe",
    timeout=30, capture=capture, cancelled=cancelled,
    publish=lambda value, failed: results.append((value, failed)))
assert len(results) == 1 and results[0][1] is False
assert results[0][0].entries == () or results[0][0].entries == []
assert not captures[-1].exists()
args = service.text_read_arguments("/device/text", False, 128, b"ADBLAB_TEXT_END_probe")
def publish_text(value, failed):
    assert captures[-1].exists() and len(decoded) == 1
    results.append((value, failed))
service.read_text("synthetic-device", args, 128, b"ADBLAB_TEXT_END_probe",
    timeout=30, capture=capture, cancelled=cancelled,
    decoded=decoded.append, publish=publish_text)
assert results[-1] == (b"\xef\xbb\xbf raw \r\n", False)
assert not captures[-1].exists()
service.save_device_text("synthetic-device", "/device/link", b"remote payload", True,
    timeout=120, run=run, capture=capture, cancelled=cancelled,
    publish=lambda *value: results.append(value), warning=warnings.append)
assert results[-1] == ("OK", False) and warnings == []
assert [entry[1] for entry in calls] == [30, 30, 120, 30, 15, 15]
assert "/data/local/tmp/adblab-save-" in calls[-2][0][-1]
assert "/device/.adblab-save-" in calls[-1][0][-1]
assert all(not path.exists() for path in captures)
assert not Path(calls[2][0][4]).exists()
target = Path(sys.argv[1]) / "copy.txt"
service.save_local_text(str(target), b"local payload", cancelled=cancelled,
    publish=lambda *value: results.append(value))
assert target.read_bytes() == b"local payload" and results[-1] == ("OK", False)
assert not list(target.parent.glob(".adblab-save-*"))
assert not any(blocked(name) for name in sys.modules)
print("four fake transactions completed without Qt")
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "four fake transactions completed without Qt" in result.stdout


@pytest.fixture
def service():
    from services import file_operations

    return file_operations


@pytest.fixture
def temporary_scope(service, monkeypatch):
    original = service.tempfile.TemporaryDirectory
    state = {"paths": [], "events": [], "failure": False}

    @contextmanager
    def temporary(*args, **kwargs):
        with original(*args, **kwargs) as directory:
            state["paths"].append(Path(directory))
            yield directory
        state["events"].append("cleanup")
        if state["failure"]:
            raise OSError("temporary cleanup failed")

    monkeypatch.setattr(service.tempfile, "TemporaryDirectory", temporary)
    return state


def _capture_bytes(raw, *, result=None, paths=None):
    def capture(cmd, output_path, *, timeout, cancelled):
        if paths is not None:
            paths.append(Path(output_path))
        Path(output_path).write_bytes(raw)
        return result if result is not None else CommandResult(True)

    return capture


def test_directory_success_publishes_after_temporary_cleanup(service, temporary_scope):
    results = []

    def publish(value, failed):
        assert not temporary_scope["paths"][-1].exists()
        temporary_scope["events"].append("publish")
        results.append((value, failed))

    service.read_directory(
        "synthetic-device", "/", False, b"END", timeout=30,
        capture=_capture_bytes(b"ADBLAB_LIST_V1\0END"), cancelled=lambda: False,
        publish=publish,
    )
    assert results[0][0].entries == () and results[0][1] is False
    assert temporary_scope["events"] == ["cleanup", "publish"]


@pytest.mark.parametrize("cancel_during_publish", [False, True])
def test_directory_failure_precedes_cleanup_and_preserves_cleanup_error(
    service, temporary_scope, cancel_during_publish,
):
    temporary_scope["failure"] = True
    aborted = threading.Event()
    results = []

    def publish(value, failed):
        results.append((value, failed))
        if len(results) == 1:
            assert temporary_scope["paths"][-1].exists()
            if cancel_during_publish:
                aborted.set()
        else:
            assert not temporary_scope["paths"][-1].exists()

    service.read_directory(
        "synthetic-device", "/", False, b"END", timeout=30,
        capture=_capture_bytes(b"", result=CommandResult(False, error="permission denied private")),
        cancelled=aborted.is_set, publish=publish,
    )
    assert results[0] == ("目录读取被拒绝，请检查设备授权、目录访问权限及本机临时目录权限。", True)
    assert len(results) == (1 if cancel_during_publish else 2)
    if not cancel_during_publish:
        assert results[-1] == ("无法读写目录列表临时文件，请检查本机可用空间和临时目录权限。", True)


@pytest.mark.parametrize("cancel_on_decoded", [False, True])
def test_text_callbacks_precede_cleanup_and_preserve_synchronous_cancel(
    service, temporary_scope, cancel_on_decoded,
):
    temporary_scope["failure"] = True
    aborted = threading.Event()
    results = []

    def decoded(value):
        assert temporary_scope["paths"][-1].exists()
        temporary_scope["events"].append("decoded")
        if cancel_on_decoded:
            aborted.set()

    def publish(value, failed):
        temporary_scope["events"].append("error" if failed else "raw")
        results.append((value, failed))

    service.read_text(
        "synthetic-device", ["exec-out", "synthetic"], 128, b"END", timeout=30,
        capture=_capture_bytes(b"raw\r\nEND"), cancelled=aborted.is_set,
        decoded=decoded, publish=publish,
    )
    assert results[0] == (b"raw\r\n", False)
    assert temporary_scope["events"] == ["decoded", "raw", "cleanup"] + (
        [] if cancel_on_decoded else ["error"]
    )
    if not cancel_on_decoded:
        assert results[-1] == ("temporary cleanup failed", True)


@pytest.mark.parametrize("case", [
    "bounded", "missing_marker", "decode_failure", "runner_cancelled",
])
def test_text_read_preserves_marker_read_bound_and_decode_failure(
    service, monkeypatch, case,
):
    bounds, results, previews = [], [], []
    original = Path.open

    @contextmanager
    def open_path(path, mode="r", *args, **kwargs):
        with original(path, mode, *args, **kwargs) as stream:
            if mode == "rb":
                class Reader:
                    def read(self, count):
                        bounds.append(count)
                        return stream.read(count)

                yield Reader()
            else:
                yield stream

    monkeypatch.setattr(Path, "open", open_path)
    if case == "decode_failure":
        def decode(*args):
            raise ValueError("decode refused")

        monkeypatch.setattr(service.explorer_service, "decode_text_preview", decode)
    raw = b"12345END" if case == "bounded" else b"rawEND"
    if case == "missing_marker":
        raw = b"raw"
    result = (
        CommandResult(False, error="cancelled result", outcome="cancelled")
        if case == "runner_cancelled" else None
    )
    service.read_text(
        "synthetic-device", ["exec-out", "synthetic"], 4, b"END", timeout=30,
        capture=_capture_bytes(raw, result=result), cancelled=lambda: False,
        decoded=previews.append, publish=lambda *value: results.append(value),
    )
    if case == "runner_cancelled":
        assert bounds == [] and results == [("cancelled result", True)]
    else:
        assert bounds == [8]
        if case == "missing_marker":
            assert results == [("Unable to read complete text preview", True)]
        else:
            assert results == [(raw[:-3], False)]
            assert len(previews) == (0 if case == "decode_failure" else 1)


@pytest.mark.parametrize("raw,expected", [
    (b"ADBLAB_TARGET:/target \n:END", "/target "),
    (b"ADBLAB_TARGET:relative\n:END", "Invalid text file target"),
    (b"ADBLAB_TARGET:/bad\xff\n:END", "Invalid text file target"),
    (b"ADBLAB_TARGET:/bad\0\n:END", "Invalid text file target"),
    (b"ADBLAB_TARGET:/bad\r\n:END", "Invalid text file target"),
    (b"ADBLAB_TARGET:/bad\n\n:END", "Invalid text file target"),
    (b"WRONG:/target\n:END", "Unable to resolve writable text file"),
    (b"ADBLAB_TARGET:/target\nWRONG", "Unable to resolve writable text file"),
    (b"ADBLAB_TARGET:/" + b"a" * 8172 + b"\n:END", "/" + "a" * 8172),
    (b"ADBLAB_TARGET:/" + b"a" * 8173 + b"\n:END", "Unable to resolve writable text file"),
])
def test_resolve_target_cleans_before_parse_and_wraps_cancel(
    service, temporary_scope, raw, expected,
):
    if expected.startswith("/"):
        assert service._resolve_text_target(
            "synthetic-device", "/link", True, capture=_capture_bytes(raw), cancelled=lambda: False,
        ) == expected
    else:
        with pytest.raises(OSError, match=expected):
            service._resolve_text_target(
                "synthetic-device", "/link", True,
                capture=_capture_bytes(raw), cancelled=lambda: False,
            )
    assert temporary_scope["events"] == ["cleanup"]
    assert not temporary_scope["paths"][-1].exists()
    with pytest.raises(OSError, match="Unable to resolve writable text file") as error:
        service._resolve_text_target(
            "synthetic-device", "/link", False, capture=_capture_bytes(raw), cancelled=lambda: True,
        )
    assert isinstance(error.value.__cause__, InterruptedError)


@pytest.mark.parametrize("use_root", [False, True])
@pytest.mark.parametrize("stage", [
    "success", "resolve", "resolve_cancel", "prepare", "prepare_cancel",
    "push", "push_cancel", "publish", "publish_cancel",
])
def test_remote_save_registers_before_prepare_and_cleans_in_reverse(service, use_root, stage):
    calls, results, captured = [], [], []
    aborted = threading.Event()
    prepares = 0

    def run(cmd, *, timeout, cancelled):
        nonlocal prepares
        assert cmd[:3] == ["adb", "-s", "synthetic-device"]
        assert "secret body" not in " ".join(cmd)
        calls.append((cmd, timeout, cancelled))
        if timeout == 15:
            assert cancelled is None
            return CommandResult(True)
        assert cancelled == aborted.is_set
        if cmd[3] == "push":
            assert timeout == 120 and Path(cmd[4]).read_bytes() == b"secret body"
            if stage == "push_cancel":
                aborted.set()
            return CommandResult(stage != "push", error="push failed")
        assert timeout == 30
        if "mkdir" in cmd[-1]:
            prepares += 1
            if stage == "prepare_cancel":
                aborted.set()
            return CommandResult(stage != "prepare", error="prepare failed")
        if stage == "publish_cancel":
            aborted.set()
        return CommandResult(stage != "publish", error="publish failed")

    def capture(cmd, output_path, **kwargs):
        result = _capture_bytes(
            b"ADBLAB_TARGET:/dir/target\n:END",
            result=CommandResult(stage != "resolve"), paths=captured,
        )(cmd, output_path, **kwargs)
        if stage == "resolve_cancel":
            aborted.set()
        return result

    def publish(*value):
        assert all(not path.exists() for path in captured)
        assert stage in ("resolve", "resolve_cancel") or calls[-1][1] == 15
        for command, _, _ in calls:
            if command[3] == "push":
                assert not Path(command[4]).exists()
        results.append(value)

    service.save_device_text(
        "synthetic-device", "/link", b"secret body", use_root, timeout=120, run=run,
        capture=capture,
        cancelled=aborted.is_set, publish=publish,
        warning=lambda message: pytest.fail(message),
    )
    cleanup = [entry for entry in calls if entry[1] == 15]
    assert len(cleanup) == prepares
    prepared = [entry[0][-1] for entry in calls if entry[1] == 30 and "mkdir" in entry[0][-1]]
    for (cmd, _, _), preparation in zip(cleanup, reversed(prepared), strict=True):
        import re

        directory = re.search(
            r"(?:/data/local/tmp/adblab-save-|/dir/\.adblab-save-)[a-f0-9]+", preparation,
        )[0]
        assert directory in cmd[-1]
    assert all(not path.exists() for path in captured)
    for cmd, _, _ in calls:
        if cmd[3] == "push":
            assert not Path(cmd[4]).exists()
    if stage.endswith("_cancel"):
        assert results == []
    elif stage == "success":
        assert results == [("OK", False)]
    else:
        assert len(results) == 1 and results[0][1] is True


@pytest.mark.parametrize("mode", ["failure", "cleanup_raise", "warning_raise", "body_raise"])
def test_remote_cleanup_warning_preserves_result_and_exception_boundary(service, mode):
    results, warnings, cleanup = [], [], []

    def run(cmd, *, timeout, cancelled):
        if timeout == 15:
            cleanup.append(cmd)
            if mode == "cleanup_raise":
                raise RuntimeError("cleanup exception")
            return CommandResult(mode != "failure" and mode != "warning_raise")
        if cmd[3] == "push" and mode == "body_raise":
            raise RuntimeError("body exception")
        return CommandResult(True)

    def warning(message):
        warnings.append(message)
        if mode == "warning_raise":
            raise RuntimeError("warning exception")

    def execute():
        service.save_device_text(
            "synthetic-device", "/link", b"content", True, timeout=120, run=run,
            capture=_capture_bytes(b"ADBLAB_TARGET:/target\n:END"), cancelled=lambda: False,
            publish=lambda *value: results.append(value), warning=warning,
        )

    if mode == "failure":
        execute()
        assert warnings == ["文本保存临时文件清理失败，请检查设备连接。"] * 2
        assert len(cleanup) == 2 and results == [("OK", False)]
    else:
        with pytest.raises(RuntimeError):
            execute()
        if mode == "body_raise":
            assert len(cleanup) == 2 and results == [("OK", False)]
        else:
            assert len(cleanup) == 1 and results == []


@pytest.mark.parametrize("mode", [
    "success", "cancel", "replace_error", "unlink_error", "both_errors", "body_raise",
])
def test_local_save_preserves_replace_cleanup_and_error_precedence(
    service, tmp_path, monkeypatch, mode,
):
    target = tmp_path / "target.txt"
    target.write_bytes(b"old")
    aborted = threading.Event()
    temporary, results, events = [], [], []
    original_temp = service.tempfile.mkstemp
    original_unlink = Path.unlink
    original_replace = service.os.replace

    def mkstemp(*, prefix, dir):
        assert Path(dir) == target.parent
        fd, path = original_temp(prefix=prefix, dir=dir)
        temporary.append(Path(path))
        if mode == "cancel":
            aborted.set()
        return fd, path

    def replace(source, destination):
        events.append("replace")
        assert Path(source).read_bytes() == b"new"
        if mode in ("replace_error", "both_errors"):
            raise OSError("replace failed")
        if mode == "body_raise":
            raise RuntimeError("replace exception")
        original_replace(source, destination)

    def unlink(path, **kwargs):
        events.append("unlink")
        original_unlink(path, **kwargs)
        if mode in ("unlink_error", "both_errors"):
            raise OSError("unlink failed")

    def publish(*value):
        assert not temporary[0].exists()
        events.append("publish")
        results.append(value)

    monkeypatch.setattr(service.tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(service.os, "replace", replace)
    monkeypatch.setattr(Path, "unlink", unlink)

    def execute():
        service.save_local_text(str(target), b"new", cancelled=aborted.is_set, publish=publish)

    if mode == "body_raise":
        with pytest.raises(RuntimeError, match="replace exception"):
            execute()
    else:
        execute()
    assert target.read_bytes() == (b"new" if mode in ("success", "unlink_error") else b"old")
    assert results == {
        "success": [("OK", False)], "cancel": [],
        "replace_error": [("replace failed", True)], "unlink_error": [("unlink failed", True)],
        "both_errors": [("replace failed", True)], "body_raise": [("OK", False)],
    }[mode]
    assert events == (["unlink"] if mode == "cancel" else ["replace", "unlink", "publish"])


def test_resolve_target_reads_bounded_bytes_and_parses_after_cleanup(
    service, temporary_scope, monkeypatch,
):
    original = Path.open
    observed = []

    class CheckedBytes(bytes):
        def startswith(self, prefix):
            assert not temporary_scope["paths"][-1].exists()
            observed.append("parse")
            return super().startswith(prefix)

    @contextmanager
    def open_path(path, mode="r", *args, **kwargs):
        with original(path, mode, *args, **kwargs) as stream:
            if mode == "rb":
                class Reader:
                    def read(self, count):
                        assert count == 8193
                        observed.append("read")
                        return CheckedBytes(stream.read(count))

                yield Reader()
            else:
                yield stream

    monkeypatch.setattr(Path, "open", open_path)
    assert service._resolve_text_target(
        "synthetic-device", "/link", False,
        capture=_capture_bytes(b"ADBLAB_TARGET:/target \n:END"), cancelled=lambda: False,
    ) == "/target "
    assert observed == ["read", "parse"]


@pytest.mark.parametrize("boundary", [
    "directory_success", "directory_failure", "decoded", "raw", "remote", "local",
])
def test_callbacks_keep_original_oserror_boundary(
    service, temporary_scope, tmp_path, boundary,
):
    results = []

    def publish(value, failed):
        results.append((value, failed))
        if len(results) == 1:
            raise OSError("callback failed")

    if boundary.startswith("directory"):
        service.read_directory(
            "synthetic-device", "/", False, b"END", timeout=30,
            capture=_capture_bytes(
                b"ADBLAB_LIST_V1\0END",
                result=CommandResult(boundary == "directory_success", error="command failed"),
            ),
            cancelled=lambda: False, publish=publish,
        )
        assert len(results) == 2
        assert results[-1] == ("无法读写目录列表临时文件，请检查本机可用空间和临时目录权限。", True)
    elif boundary in ("decoded", "raw"):
        def decoded(preview):
            if boundary == "decoded":
                raise OSError("decode callback failed")

        service.read_text(
            "synthetic-device", ["exec-out", "synthetic"], 128, b"END", timeout=30,
            capture=_capture_bytes(b"rawEND"), cancelled=lambda: False,
            decoded=decoded, publish=(
                (lambda *value: results.append(value)) if boundary == "decoded" else publish
            ),
        )
        assert results == (
            [("decode callback failed", True)] if boundary == "decoded"
            else [(b"raw", False), ("callback failed", True)]
        )
    else:
        with pytest.raises(OSError, match="callback failed"):
            if boundary == "local":
                service.save_local_text(
                    str(tmp_path / "copy"), b"data", cancelled=lambda: False, publish=publish,
                )
            else:
                service.save_device_text(
                    "synthetic-device", "/link", b"content", False, timeout=120,
                    run=lambda *args, **kwargs: CommandResult(True),
                    capture=_capture_bytes(b"ADBLAB_TARGET:/target\n:END"),
                    cancelled=lambda: False, publish=publish,
                    warning=lambda message: pytest.fail(message),
                )
        assert results == [("OK", False)]
    assert all(not path.exists() for path in temporary_scope["paths"])
