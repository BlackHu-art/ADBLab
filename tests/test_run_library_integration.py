"""验证任务历史参数路由和应用关闭的结果保存顺序。"""

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gui.close_controller import CloseController
from gui.main_frame import MainFrame
from gui.run_library import RunLibraryController
from services.run_library import RunLibrary, RunRecord


def test_history_reuse_does_not_choose_old_device_or_start_test():
    panel = Mock()
    frame = SimpleNamespace(
        left_panel=SimpleNamespace(_apps_tab=panel),
        _open_workspace_feature=Mock(),
        _on_run_library_error=Mock(),
    )
    record = RunRecord(
        "one",
        "performance",
        "com.example",
        1,
        2,
        "succeeded",
        {"package": "com.example", "timeout_minutes": 2},
    )
    MainFrame._reuse_test_run(frame, record)
    frame._open_workspace_feature.assert_called_once_with(
        "system",
        "performance",
        payload={"run_parameters": record.parameters},
    )
    panel.assert_not_called()
    record = RunRecord(
        "two",
        "monkey",
        "com.example",
        1,
        2,
        "cancelled",
        {"package_name": "com.example", "seed": 41},
    )
    MainFrame._reuse_test_run(frame, record)
    panel.apply_run_parameters.assert_called_once_with(record.parameters)
    panel._on_start_monkey.assert_not_called()
    frame._open_workspace_feature.assert_called_with("apps", "overview")


def test_busy_monkey_reuse_does_not_change_navigation():
    panel = Mock()
    panel.apply_run_parameters.side_effect = ValueError("busy")
    frame = SimpleNamespace(
        left_panel=SimpleNamespace(_apps_tab=panel),
        _open_workspace_feature=Mock(),
        _on_run_library_error=Mock(),
    )
    record = RunRecord("one", "monkey", "com.example", 1, 2, "cancelled", {"seed": 41})
    MainFrame._reuse_test_run(frame, record)
    frame._open_workspace_feature.assert_not_called()
    frame._on_run_library_error.assert_called_once()


def test_finalizer_drains_last_result_before_returning(tmp_path, monkeypatch, qt_application):
    library = RunLibraryController(RunLibrary(tmp_path / "runs.json"))
    record = RunRecord("one", "monkey", "com.example", 1, 2, "cancelled", {"seed": 41})
    library.record_run(record)
    frame = SimpleNamespace(run_library=library, _shutdown_deadline_at=time.monotonic() + 3)
    settings = Mock()
    settings._save_timer = None
    monkeypatch.setattr("core.settings_manager.AppSettings.instance", lambda: settings)
    CloseController(frame)._flush_shutdown_state()
    restored = RunLibrary(tmp_path / "runs.json")
    restored.load()
    assert restored.records == (record,)
    settings._save_atomic.assert_called_once()


def test_library_failure_does_not_skip_other_settings_finalization(monkeypatch):
    frame = SimpleNamespace(
        run_library=SimpleNamespace(shutdown=lambda _timeout: False),
        _shutdown_deadline_at=time.monotonic() + 3,
    )
    settings = Mock()
    settings._save_timer = None
    monkeypatch.setattr("core.settings_manager.AppSettings.instance", lambda: settings)
    try:
        CloseController(frame)._flush_shutdown_state()
    except RuntimeError as error:
        assert "结果库" in str(error)
    else:
        raise AssertionError("保存失败必须报告收尾失败")
    settings._save_atomic.assert_called_once()


def test_archive_failure_does_not_block_other_archives_or_settings(monkeypatch):
    failed_archive = Mock(side_effect=PermissionError("private-output-path"))
    next_archive = Mock()
    page_host = SimpleNamespace(
        registry=SimpleNamespace(
            pages=lambda: (
                SimpleNamespace(archive_finished_run=failed_archive),
                SimpleNamespace(archive_finished_run=next_archive),
            )
        )
    )
    frame = SimpleNamespace(
        _close_started=True,
        _close_ready=False,
        _shutdown_finalizer_started=False,
        _workspace_feature_hosts={"system": page_host},
        log_service=Mock(),
        adb_controller=SimpleNamespace(archive_finished_monkey_runs=Mock()),
        _shutdown_deadline_at=time.monotonic() + 3,
        _shutdown_handles=[],
        _shutdown_owner_id="close-test",
        task_supervisor=Mock(),
        run_library=SimpleNamespace(shutdown=Mock(return_value=True)),
    )
    close = CloseController(frame)
    frame._flush_shutdown_state = close._flush_shutdown_state
    monkeypatch.setattr("gui.close_controller.ThreadedShutdownTask", Mock())
    close._on_application_stopped((), ())
    close._on_application_stopped((), ())
    failed_archive.assert_called_once()
    next_archive.assert_called_once()
    frame.adb_controller.archive_finished_monkey_runs.assert_called_once()
    frame.log_service.shutdown.assert_called_once()
    frame.task_supervisor.stop_finalizer_async.assert_called_once()
    assert "private-output-path" not in str(frame.log_service.log.call_args_list)
    settings = Mock()
    settings._save_timer = None
    monkeypatch.setattr("core.settings_manager.AppSettings.instance", lambda: settings)
    with pytest.raises(RuntimeError):
        close._flush_shutdown_state()
    frame.run_library.shutdown.assert_called_once()
    settings._save_atomic.assert_called_once()
