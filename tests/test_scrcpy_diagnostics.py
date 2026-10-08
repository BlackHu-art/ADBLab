"""用冻结启动计划和内存管道验证投屏诊断，不读取用户文件或访问设备。"""

import io
import threading
from dataclasses import replace

import pytest
from PySide6.QtCore import QThread

from services.remote import ScrcpyService
from tests.test_logging_contract import create_log_service  # noqa: F401
from tests.test_remote_sessions import _wait, remote_session  # noqa: F401

pytestmark = pytest.mark.ui

_EXE = r"C:\Private Tools\scrcpy.exe"
_ADB = r"C:\Private Tools\adblab-adb.exe"
_SERVER = r"C:\Private Tools\scrcpy-server"
_OVERRIDE = r"D:\Private Override\custom-server"
_RECORD = r"D:\Private Recordings\session.mkv"
_DEVICE = "synthetic-private-device"


def _launch_with_captured_readers(remote, service, app, monkeypatch, *, backend="direct"):
    original = service.build_launch_plan
    plans, readers = [], []

    def build(config, **options):
        plan = replace(
            original(config, **options),
            args=[_EXE, "-s", config.device, "--record", _RECORD],
            version="4.1", backend=backend,
            env={"ADB": _ADB, "ADBLAB_SCRCPY_SERVER": _SERVER,
                 "SCRCPY_SERVER_PATH": _OVERRIDE},
        )
        plans.append(plan)
        return plan

    def capture(target, argument, *extra):
        if target.__name__ in {"_read_process_stderr", "_read_process_stdout"}:
            readers.append((target, (argument, *extra)))
        return True

    monkeypatch.setattr(service, "build_launch_plan", build)
    monkeypatch.setattr(remote._scrcpy_controller, "_start_process_task", capture)
    remote.set_target_devices([_DEVICE, "other-private-device"])
    remote._scrcpy_controller._start_scrcpy([_DEVICE])
    assert _wait(app, lambda: len(readers) == 2)
    assert service.configs[0].exe == ""
    return plans[0], readers


@pytest.mark.parametrize(("path", "suffix", "expected_level"), [
    (_SERVER, ": 1 file pushed, 0 skipped. 12.0 MB/s (100 bytes in 0.001s)", "DEBUG"),
    (_SERVER.replace("\\", "/"), ": Permission denied", "ERROR"),
    (_EXE, ": Access is denied", "ERROR"),
    (_ADB, ": Permission denied", "ERROR"),
    (_OVERRIDE, ": No such file or directory", "ERROR"),
    (_RECORD, ": Permission denied", "ERROR"),
])
def test_scrcpy_reader_keeps_known_path_suffix_after_plan_and_selection_change(
    request, qt_application, monkeypatch, path, suffix, expected_level,
):
    remote, service = request.getfixturevalue("remote_session")
    plan, readers = _launch_with_captured_readers(remote, service, qt_application, monkeypatch)
    records = []
    remote.signals.log_message.connect(lambda level, text: records.append((level, text)))
    # 旧 reader 可晚于当前选择和计划对象的变动，不能重新读取这些可变状态。
    plan.args[0] = r"C:\New Tools\scrcpy.exe"
    plan.env.clear()
    remote.set_target_devices(["replacement-device"])
    remote._device_sessions.clear()
    target, arguments = readers[0]
    prefix = "ERROR: " if expected_level == "ERROR" else ""
    arguments[0].stderr = io.StringIO(
        f"{prefix}{path}{suffix}; device={_DEVICE} other-private-device token=private-token\n",
    )
    target(*arguments)
    qt_application.processEvents()
    assert len(records) == 1
    level, text = records[0]
    assert level == expected_level
    assert f"<path>{suffix}" in text
    assert "Private" not in text and _DEVICE not in text and "private-token" not in text
    assert "other-private-device" not in text
    assert "<device>" in text and "<redacted>" in text


@pytest.mark.parametrize("line", [
    r"ERROR: C:\Unknown Private Folder\secret.txt: Access is denied",
    _SERVER + " Private Owner.txt: Permission denied",
    _SERVER + r"\Private Owner\file.txt: Permission denied",
    r'ERROR: password="private credential" token=private-token serial=private-serial',
])
def test_scrcpy_reader_does_not_expose_unknown_paths_or_known_path_prefixes(
    request, qt_application, monkeypatch, line,
):
    remote, service = request.getfixturevalue("remote_session")
    _plan, readers = _launch_with_captured_readers(remote, service, qt_application, monkeypatch)
    records = []
    remote.signals.log_message.connect(lambda _level, text: records.append(text))
    target, arguments = readers[1]
    arguments[0].stdout = io.StringIO(line)
    target(*arguments)
    qt_application.processEvents()
    assert len(records) == 1
    assert "Private" not in records[0]
    assert "private credential" not in records[0]
    assert "private-token" not in records[0] and "private-serial" not in records[0]


@pytest.mark.parametrize(("line", "level"), [
    ("ERROR: Server connection failed", "ERROR"),
    ("[server] ERROR: Exception on main thread", "ERROR"),
    ("WARN: Device disconnected", "WARNING"),
    ("WARNING: Device disconnected", "WARNING"),
    ("adb: error: failed to copy", "ERROR"),
    ("Aborted", "ERROR"),
])
def test_scrcpy_reader_errors_reach_queued_diagnostics_without_remote_feedback(
    request, qt_application, line, level,
):
    remote, _service = request.getfixturevalue("remote_session")
    log_service = request.getfixturevalue("create_log_service")()
    remote.signals.log_message.connect(log_service.log)
    feedback, diagnostic_threads = [], []
    remote._feedback_received.connect(lambda *values: feedback.append(values))
    log_service.diagnostics_changed.connect(
        lambda: diagnostic_threads.append(QThread.currentThread()),
    )
    reader = threading.Thread(
        target=remote._scrcpy_controller._read_process_output,
        args=(object(), io.StringIO(line)),
    )
    reader.start()
    reader.join(1)
    assert not reader.is_alive()
    assert _wait(qt_application, lambda: bool(log_service.diagnostics.entries))
    assert f"[{level}] [scrcpy] {line}" in log_service.diagnostics.text()
    assert diagnostic_threads == [qt_application.thread()]
    assert feedback == []


@pytest.mark.parametrize("backend", ["native", "direct"])
def test_scrcpy_start_logs_only_safe_backend_and_version(
    request, qt_application, monkeypatch, backend,
):
    remote, service = request.getfixturevalue("remote_session")
    records = []
    remote.signals.log_message.connect(lambda level, text: records.append((level, text)))
    _launch_with_captured_readers(remote, service, qt_application, monkeypatch, backend=backend)
    assert ("DEBUG", f"scrcpy launch backend={backend} version=4.1") in records
    assert all("Private" not in text and _DEVICE not in text for _, text in records)


def test_scrcpy_reader_keeps_normal_output_debug_and_drops_output_after_close(
    request, qt_application,
):
    remote, service = request.getfixturevalue("remote_session")
    service.parse_fps = ScrcpyService.parse_fps
    records, feedback, output = [], [], []
    remote.signals.log_message.connect(lambda level, text: records.append((level, text)))
    remote._feedback_received.connect(lambda *values: feedback.append(values))
    remote._scrcpy_output_requested.connect(lambda *values: output.append(values))
    remote._scrcpy_controller._read_process_output(
        object(), io.StringIO("INFO: Renderer ready\n[60 fps]\n"),
    )
    qt_application.processEvents()
    assert records == [("DEBUG", "[scrcpy] INFO: Renderer ready")]
    records.clear()
    output.clear()
    remote._closing = True
    stream = io.StringIO("ERROR: late error\n")
    remote._scrcpy_controller._read_process_output(object(), stream)
    qt_application.processEvents()
    assert stream.closed
    assert records == feedback == output == []
    remote._closing = False
