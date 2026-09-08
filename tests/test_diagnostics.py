"""验证看板移除后的异常保留、凭据边界、原子导出和关闭排空。"""

from unittest.mock import patch

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
