"""验证看板移除后的异常保留、凭据边界、原子导出和关闭排空。"""

import io
import sys
import threading
from unittest.mock import patch

import pytest

from core.diagnostics import DiagnosticJournal
from gui.run_library import _LibraryQueue
from tests.test_logging_contract import create_log_service  # noqa: F401  复用隔离单例的 fixture。


def test_diagnostic_journal_is_bounded_and_excludes_normal_output():
    journal = DiagnosticJournal()
    journal.private_values = ("synthetic-device",)
    assert not journal.accept([("10:00:00", "INFO", "normal command output")])
    for index in range(230):
        journal.accept(
            [
                (
                    "10:00:00",
                    "ERROR",
                    f"{index}: synthetic-device token=example 192.0.2.1 C:\\Users\\demo\\file.txt",
                )
            ]
        )
    assert len(journal.entries) == 200
    text = journal.text()
    assert "synthetic-device" not in text
    assert "example" not in text
    assert "192.0.2.1" not in text
    assert "Users" not in text
    assert "229:" in text


def test_shutdown_delivers_last_application_error_to_journal(request):
    service = request.getfixturevalue("create_log_service")()
    notices = []
    service.diagnostics_changed.connect(lambda: notices.append(service.diagnostics.text()))
    service.log("ERROR", "Configuration save failed")
    service.shutdown()
    assert len(notices) == 1
    assert "Configuration save failed" in notices[0]
    service.log("ERROR", "late error")
    assert "late error" not in service.diagnostics.text()


def test_diagnostic_journal_accepts_only_explicit_runtime_info():
    journal = DiagnosticJournal()
    assert not journal.accept([("10:00:00", "INFO", "normal command output")])
    assert journal.accept(
        [("10:00:00", "INFO", "ADB capability status=ready token=example")],
        include_info=True,
    )
    assert "status=ready" in journal.text()
    assert "example" not in journal.text()
    assert not journal.accept([("10:00:00", "INFO", "later command output")])
    assert not journal.accept([("10:00:00", "DEBUG", "debug detail")], include_info=True)
    assert len(journal.entries) == 1


@pytest.mark.ui
def test_frozen_runtime_diagnostic_is_saved_without_user_log(request, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    service = request.getfixturevalue("create_log_service")()
    batches, singles, snapshots, errors = [], [], [], []
    service.logs_received.connect(batches.append)
    service.log_received.connect(lambda level, message: singles.append((level, message)))
    queue = _LibraryQueue(None, lambda _: None, errors.append, lambda _: None)
    target = tmp_path / "logs" / "application-diagnostics.log"

    def persist_snapshot():
        snapshot = service.diagnostics.text()
        snapshots.append(snapshot)
        assert queue.submit("write_diagnostics", str(target), snapshot)

    service.diagnostics_changed.connect(persist_snapshot)
    try:
        service.record_runtime_diagnostic("ADB probe devices native_status=timeout")
        service._flush_buffer()
    finally:
        assert queue.close(2)
    assert len(snapshots) == 1
    assert "[INFO] ADB probe devices native_status=timeout" in snapshots[0]
    assert target.read_text(encoding="utf-8") == snapshots[0]
    assert errors == []
    assert batches == singles == []
    assert stream.getvalue() == ""


@pytest.mark.ui
@pytest.mark.parametrize("worker_request", [False, True])
def test_runtime_diagnostics_keep_source_console_and_reject_after_shutdown(
    request, monkeypatch, worker_request,
):
    monkeypatch.delattr(sys, "frozen", raising=False)
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    service = request.getfixturevalue("create_log_service")()
    notices = []
    service.diagnostics_changed.connect(lambda: notices.append(service.diagnostics.text()))
    service.record_runtime_diagnostic("ADB environment status=ready")
    if worker_request:
        worker = threading.Thread(target=service.request_shutdown)
        worker.start()
        worker.join(1)
        assert not worker.is_alive()
    else:
        service.shutdown()
    try:
        service.record_runtime_diagnostic("late runtime diagnostic")
        assert len(notices) == 1
        assert "status=ready" in service.diagnostics.text()
        assert "late runtime diagnostic" not in service.diagnostics.text()
        assert "[DEBUG]" in stream.getvalue()
        assert "status=ready" in stream.getvalue()
        assert "late runtime diagnostic" not in stream.getvalue()
    finally:
        service.shutdown()


@pytest.mark.ui
def test_runtime_diagnostics_reject_calls_from_worker_thread(request):
    service = request.getfixturevalue("create_log_service")()
    failures, notices = [], []
    service.diagnostics_changed.connect(lambda: notices.append(True))

    def call_from_worker():
        try:
            service.record_runtime_diagnostic("ADB environment status=ready")
        except Exception as error:
            failures.append(error)

    worker = threading.Thread(target=call_from_worker)
    worker.start()
    worker.join(1)
    assert not worker.is_alive()
    assert len(failures) == 1 and isinstance(failures[0], RuntimeError)
    assert "owner thread" in str(failures[0])
    assert notices == []
    assert service.diagnostics.text() == ""


def test_atomic_export_reports_success_only_after_full_write(tmp_path):
    exported, errors = [], []
    target = tmp_path / "result.txt"
    text = "完整正文\n" * 20000
    queue = _LibraryQueue(None, lambda _: None, errors.append, lambda _: None, exported.append)
    assert queue.submit("export_text", str(target), text)
    assert queue.close(2)
    assert target.read_text(encoding="utf-8") == text
    assert exported == [str(target)]
    assert errors == []


def test_export_failure_preserves_existing_file_and_cleans_temporary(tmp_path):
    target = tmp_path / "result.txt"
    target.write_text("previous content", encoding="utf-8")
    exported, errors = [], []
    queue = _LibraryQueue(None, lambda _: None, errors.append, lambda _: None, exported.append)
    with patch("gui.run_library.os.replace", side_effect=OSError("replace refused")):
        queue.submit("export_text", str(target), "replacement")
        assert queue.close(2)
    assert target.read_text(encoding="utf-8") == "previous content"
    assert exported == []
    assert errors == ["export_text:OSError"]
    assert list(tmp_path.iterdir()) == [target]


def test_diagnostic_snapshot_is_saved_without_mutating_test_library(tmp_path):
    events = []
    queue = _LibraryQueue(None, events.append, events.append, events.append)
    target = tmp_path / "logs" / "application-diagnostics.log"
    assert queue.submit("write_diagnostics", str(target), "bounded diagnostic snapshot")
    assert queue.close(2)
    assert target.read_text(encoding="utf-8") == "bounded diagnostic snapshot"
    assert events == []
    assert not queue.submit("write_diagnostics", str(target), "late write")
