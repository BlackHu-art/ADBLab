"""文件事务适配器保持构造、同步通知和原 Event 取消约定。"""

import re
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from core.exec import CommandResult
from models import file_explorer_worker as workers
from services import file_explorer as explorer

pytestmark = pytest.mark.ui


def _capture(command, output_path, *, timeout, cancelled):
    assert not cancelled()
    if "ADBLAB_LIST_END_" in command[-1]:
        marker = re.search(r"ADBLAB_LIST_END_[a-f0-9]+", command[-1])[0].encode()
        raw = b"ADBLAB_LIST_V1\0" + marker
    elif "ADBLAB_TEXT_END_" in command[-1]:
        marker = re.search(r"ADBLAB_TEXT_END_[a-f0-9]+", command[-1])[0].encode()
        raw = b"\xef\xbb\xbf original \r\n" + marker
    else:
        raw = b"ADBLAB_TARGET:/target.txt\n:END"
    Path(output_path).write_bytes(raw)
    return CommandResult(True)


def test_constructor_preserves_marker_and_command_timing(monkeypatch):
    directory = workers.DirectoryListWorker("synthetic-device", "bad\0path", False)
    errors = []
    directory.result_ready.connect(lambda *args: errors.append(args))
    assert isinstance(directory._completion_marker, bytes) and directory.args == []
    directory.run()
    assert errors and errors[0][1] is True
    with monkeypatch.context() as builder_patch:
        def reject_path(*args):
            raise ValueError("invalid synthetic path")

        builder_patch.setattr(explorer, "head_command", reject_path)
        with pytest.raises(ValueError, match="invalid synthetic path"):
            workers.TextReadWorker("synthetic-device", "/text", False, 128)

    reader = workers.TextReadWorker("synthetic-device", "/text", True, 128)
    marker = reader._completion_marker
    arguments = list(reader.args)
    assert isinstance(marker, bytes)
    assert arguments[0] == "exec-out" and "head" in arguments[1]
    assert "129" in arguments[1] and marker.decode() in arguments[1]
    captures = []

    def capture(command, output_path, **kwargs):
        captures.append(command)
        return _capture(command, output_path, **kwargs)

    monkeypatch.setattr(workers.CommandRunner, "run_to_file", capture)
    reader.run()
    assert captures == [["adb", "-s", "synthetic-device"] + arguments]
    assert reader.args == arguments and reader._completion_marker == marker


def test_decoded_direct_cancel_still_publishes_raw_inside_capture_scope(monkeypatch):
    reader = workers.TextReadWorker("synthetic-device", "/text", False, 128)
    paths = []
    events = []

    def capture(command, output_path, **kwargs):
        paths.append(Path(output_path))
        return _capture(command, output_path, **kwargs)

    def decoded(preview):
        assert reader.decoded_available is True
        assert paths[0].exists() and isinstance(preview, explorer.TextPreview)
        events.append("decoded")
        reader.abort()

    def published(raw, failed):
        assert paths[0].exists()
        assert reader.decoded_available is True
        events.append((raw, failed))

    monkeypatch.setattr(workers.CommandRunner, "run_to_file", capture)
    reader.decoded_ready.connect(decoded, Qt.ConnectionType.DirectConnection)
    reader.result_ready.connect(published, Qt.ConnectionType.DirectConnection)
    reader.run()
    assert events == ["decoded", (b"\xef\xbb\xbf original \r\n", False)]
    assert paths and not paths[0].exists()


@pytest.mark.parametrize("kind", ["directory", "read", "remote", "local"])
@pytest.mark.parametrize("aborted", [False, True])
def test_four_workers_keep_event_only_cancellation(monkeypatch, tmp_path, kind, aborted):
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return CommandResult(True)

    def capture(*args, **kwargs):
        calls.append(args)
        return _capture(*args, **kwargs)

    monkeypatch.setattr(workers.CommandRunner, "run", run)
    monkeypatch.setattr(workers.CommandRunner, "run_to_file", capture)
    target = tmp_path / "copy.txt"
    target.write_bytes(b"old")
    worker = {
        "directory": lambda: workers.DirectoryListWorker("synthetic-device", "/", False),
        "read": lambda: workers.TextReadWorker("synthetic-device", "/text", False, 128),
        "remote": lambda: workers.TextSaveWorker("synthetic-device", "/text", b"new", True),
        "local": lambda: workers.LocalTextSaveWorker(str(target), b"new"),
    }[kind]()
    results = []
    worker.result_ready.connect(lambda *args: results.append(args))
    worker.requestInterruption()
    if aborted:
        worker._aborted.set()
    worker.run()
    assert bool(results) is (not aborted)
    if aborted:
        assert calls == [] and target.read_bytes() == b"old"
    elif kind == "local":
        assert target.read_bytes() == b"new" and results == [("OK", False)]
    else:
        assert calls and results[0][1] is False


@pytest.mark.parametrize("failure", [False, True])
def test_worker_signals_keep_payloads_and_decoded_flag(monkeypatch, failure):
    reader = workers.TextReadWorker("synthetic-device", "/text", False, 128)
    raw = b"\xff\r\n"

    def capture(command, output_path, **kwargs):
        Path(output_path).write_bytes(raw + reader._completion_marker)
        return CommandResult(not failure, error="capture failed")

    monkeypatch.setattr(workers.CommandRunner, "run_to_file", capture)
    results, decoded = [], []
    reader.result_ready.connect(lambda *args: results.append(args))
    reader.decoded_ready.connect(decoded.append)
    reader.run()
    assert results == [("capture failed", True)] if failure else results == [(raw, False)]
    assert reader.decoded_available is (not failure)
    assert len(decoded) == (0 if failure else 1)
