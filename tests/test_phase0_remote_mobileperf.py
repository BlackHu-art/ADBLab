from unittest.mock import Mock, patch

import pytest
from PySide6.QtWidgets import QApplication

from gui.dialogs.performance_launcher import PerformanceLauncherDialog
from gui.panels.remote_panel import RemotePanel
from models.base.process_runner import ProcessRunner
from models.mobileperf.runner import MobilePerfRunConfig, MobilePerfRunner


def _remote_panel(*, active_device, selected_devices, process_running=True):
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=selected_devices)
    panel._active_device = active_device
    panel._process = Mock() if process_running else None
    if panel._process is not None:
        panel._process.poll.return_value = None
    panel._running = process_running
    panel._remote_control = Mock()
    panel._remote_executor = Mock()
    panel._emit_remote_queue_status = Mock()
    panel._remote_submitted = 0
    panel._remote_completed = 0
    panel._log = Mock()
    return panel


def test_remote_input_stays_bound_to_active_session_device_after_selection_changes():
    panel = _remote_panel(
        active_device="device-a",
        selected_devices=["device-b"],
    )

    RemotePanel._send_remote_action(panel, "swipe_up")
    queued_task = panel._remote_executor.submit.call_args.args[0]
    queued_task()

    panel._remote_control.perform_action.assert_called_once_with("device-a", "swipe_up")


def test_remote_input_is_rejected_without_a_running_active_session():
    panel = _remote_panel(
        active_device=None,
        selected_devices=["device-b"],
        process_running=False,
    )

    RemotePanel._send_keyevent(panel, "HOME")

    panel._remote_executor.submit.assert_not_called()
    panel._remote_control.send_keyevent.assert_not_called()
    level, message = panel._log.call_args.args
    assert level == "WARNING"
    assert "not running" in message.lower()


def test_remote_multi_device_start_warns_and_binds_first_device():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["device-a", "device-b"])
    panel._process = None
    panel._launch_worker = None
    panel._scrcpy_service = Mock()
    panel._scrcpy_service.resolve_executable.return_value = "C:/tools/scrcpy.exe"
    panel._set_running = Mock()
    panel._update_status = Mock()
    panel._scrcpy_config = Mock(return_value=Mock())
    panel._log = Mock()

    worker = Mock()
    worker.isRunning.return_value = False
    with (
        patch("gui.panels.remote_panel.os.path.isfile", return_value=True),
        patch(
            "gui.panels.remote_panel.ScrcpyLaunchWorker",
            return_value=worker,
        ),
    ):
        RemotePanel._start_scrcpy(panel)

    assert panel._active_device == "device-a"
    assert any(
        call.args[0] == "WARNING"
        and "1 additional selection" in call.args[1]
        and "device-a" not in call.args[1]
        and "device-b" not in call.args[1]
        for call in panel._log.call_args_list
    )


def test_mobileperf_result_lookup_excludes_artifacts_that_predate_current_start(tmp_path):
    result_root = tmp_path / "mobileperf"
    package_root = result_root / "com.example.app"
    old_dir = package_root / "2026_07_25_10_00_00"
    old_dir.mkdir(parents=True)
    old_report = old_dir / "summary_old.xlsx"
    old_report.write_text("old", encoding="utf-8")

    process_runner = Mock(spec=ProcessRunner)
    proc = Mock()
    proc.stdout = []
    proc.poll.return_value = None
    proc.wait.return_value = None
    proc.returncode = 0
    process_runner.start.return_value = proc
    runner = MobilePerfRunner(
        process_runner=process_runner,
        project_root=tmp_path,
        python_executable="python-test",
    )
    config = MobilePerfRunConfig(
        package="com.example.app",
        save_path=str(result_root),
    )

    runner.start(config)
    try:
        assert runner.latest_result_dir() == ""
        assert runner.latest_report_file() == ""

        new_dir = package_root / "2026_07_25_10_05_00"
        new_dir.mkdir()
        new_report = new_dir / "summary_new.xlsx"
        new_report.write_text("new", encoding="utf-8")

        assert runner.latest_result_dir() == str(new_dir)
        assert runner.latest_report_file() == str(new_report)
    finally:
        runner.stop(timeout=0)


def test_mobileperf_runner_records_natural_nonzero_exit_code():
    runner = MobilePerfRunner(process_runner=Mock(spec=ProcessRunner))
    proc = Mock()
    proc.stdout = iter([])
    proc.poll.return_value = 7
    runner._proc = proc

    runner._read_logs()

    assert runner.last_exit_code == 7


@pytest.mark.parametrize(
    ("exit_code", "report_path", "expected_status", "expected_progress"),
    [
        (0, "D:/results/current/summary.xlsx", "Completed", 100),
        (0, "", "Warning", 99),
        (3, "", "Failed", 99),
        (3, "D:/results/current/summary.xlsx", "Warning", 99),
        (None, "D:/results/current/summary.xlsx", "Warning", 99),
    ],
)
def test_performance_launcher_completion_state_requires_current_successful_report(
    exit_code,
    report_path,
    expected_status,
    expected_progress,
):
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._runner = Mock()
        dialog._runner.last_config = Mock()
        dialog._runner.last_exit_code = exit_code
        dialog._runner.latest_result_dir.return_value = "D:/results/current"
        dialog._runner.latest_report_file.return_value = report_path
        dialog._runner_finished_handled = False
        dialog._run_started_at = None
        dialog._run_duration_seconds = 60
        dialog._set_progress(99)

        dialog._mark_runner_finished()

        assert dialog.status_label.text() == expected_status
        assert dialog.progress_bar.value() == expected_progress
        if expected_status != "Completed":
            assert dialog.progress_bar.value() < 100
    finally:
        dialog.close()
