"""启动尚无界面日志时的有界诊断，以及失败清理的错误优先级。"""

from types import SimpleNamespace

import pytest


def test_startup_diagnostics_replays_once_and_persists_redacted_failure(tmp_path):
    from core.startup_diagnostics import StartupDiagnostics

    trace = StartupDiagnostics()
    trace.record("settings", detail="token=hidden C:/private/config.json")
    received = []
    trace.bind(received.append)
    trace.record("splash-painted")
    assert len(received) == 2
    assert all("hidden" not in line and "private" not in line for line in received)
    with pytest.raises(RuntimeError):
        trace.bind(received.append)
    for _ in range(240):
        trace.record("stage")
    trace.record("failed", detail="RuntimeError")
    target = tmp_path / "logs" / "startup-diagnostics.log"
    trace.save_failure(target)
    lines = target.read_text("utf-8").splitlines()
    assert len(lines) == 200
    assert "failed" in lines[-1] and "RuntimeError" in lines[-1]
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.parametrize("primary", [None, ValueError("original startup error")])
def test_cleanup_failure_still_shuts_logger_and_preserves_primary(primary):
    import main
    from core.startup_diagnostics import StartupDiagnostics

    events = []
    cleanup_error = RuntimeError("splash still alive")

    def broken_shutdown():
        events.append("splash")
        raise cleanup_error

    startup = SimpleNamespace(is_settled=True, error=primary)
    splash = SimpleNamespace(shutdown=broken_shutdown)
    logger = SimpleNamespace(shutdown=lambda: events.append("logger"))
    trace = StartupDiagnostics()
    if primary is None:
        with pytest.raises(RuntimeError) as caught:
            main._finish_gui(startup, splash, logger, trace)
        assert caught.value is cleanup_error
    else:
        main._finish_gui(startup, splash, logger, trace)
        assert startup.error is primary
    assert events == ["splash", "logger"]
    assert "cleanup-failed" in trace.text()


def test_gui_failure_before_application_is_persisted(tmp_path, monkeypatch):
    import main
    from core.settings_manager import AppSettings

    failure = ValueError("token=private-error")

    def fail():
        from core.settings_manager import _log_error

        _log_error("WARNING", "synthetic settings warning token=hidden")
        raise failure

    monkeypatch.setattr(AppSettings, "instance", fail)
    monkeypatch.setattr("core.settings_manager._error_sink", None)
    monkeypatch.setattr("utils.user_data.user_data_root", lambda: tmp_path)
    with pytest.raises(ValueError) as caught:
        main._run_gui()
    assert caught.value is failure
    report = (tmp_path / "logs" / "startup-diagnostics.log").read_text("utf-8")
    assert "failed" in report and "ValueError" in report
    assert "synthetic settings warning" in report
    assert "hidden" not in report
    assert "private-error" not in report


def test_failure_report_write_error_does_not_mask_startup_error(monkeypatch):
    import main
    from core.settings_manager import AppSettings
    from core.startup_diagnostics import StartupDiagnostics

    failure = ValueError("original settings failure")

    def fail_settings():
        raise failure

    def fail_report(_trace):
        raise OSError("synthetic read-only destination")

    monkeypatch.setattr("core.settings_manager._error_sink", None)
    monkeypatch.setattr(AppSettings, "instance", fail_settings)
    monkeypatch.setattr(StartupDiagnostics, "save_failure", fail_report)
    with pytest.raises(ValueError) as caught:
        main._run_gui()
    assert caught.value is failure
    assert any("OSError" in note for note in caught.value.__notes__)
