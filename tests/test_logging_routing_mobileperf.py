"""验证主界面、Remote 和 MobilePerf 的日志分流契约。"""

from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QEvent

from core.exec import ProcessRunner
from gui.main_frame import MainFrame
from gui.panels.remote_panel import RemotePanel
from mobileperf.common import log as mobileperf_log
from mobileperf.common.utils import FileUtils
from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner


def _feedback_controller() -> SimpleNamespace:
    return SimpleNamespace(
        devices_updated=Mock(),
        record_finished=Mock(),
        record_target_finished=Mock(),
        monkey_target_finished=Mock(),
        operation_completed=Mock(),
        current_package_received=Mock(),
        device_info_updated=Mock(),
    )


def test_main_frame_routes_business_log_signal_to_log_service():
    log_service = Mock()
    frame = SimpleNamespace(
        log_service=log_service,
        log_panel=Mock(),
        left_panel=Mock(),
        _on_devices_updated=Mock(),
    )
    left_panel = SimpleNamespace(log_message=Mock())
    controller = _feedback_controller()

    MainFrame._connect_controller_feedback(frame, left_panel, controller)

    left_panel.log_message.connect.assert_called_once_with(log_service.log)
    assert frame.log_panel._append_log.call_count == 0
    device_info_handler = controller.device_info_updated.connect.call_args.args[0]
    device_info_handler("device-secret", {"serial": "device-secret", "model": "secret"})
    level, message = log_service.log.call_args.args
    assert level == "INFO"
    assert message == "Device information updated: field_count=2"
    assert "device-secret" not in message


def test_main_frame_local_status_messages_use_log_service():
    frame = SimpleNamespace(log_service=Mock(), log_panel=Mock())

    MainFrame.clear_log(frame)

    frame.log_panel.clear.assert_called_once_with()
    assert [call.args for call in frame.log_service.log.call_args_list] == [
        ("DEBUG", "ui.toolbar action=clear_log phase=requested"),
        ("INFO", "Log cleared"),
    ]
    frame.log_panel._append_log.assert_not_called()


def test_main_frame_toolbar_window_controls_emit_structured_debug():
    frame = SimpleNamespace(
        log_service=Mock(),
        showMinimized=Mock(),
        close=Mock(),
    )

    with (
        patch("gui.main_frame.BaseStyles.current_theme", return_value="Light"),
        patch("gui.main_frame.BaseStyles.toggle_theme") as toggle_theme,
    ):
        MainFrame._toggle_theme(frame)
    MainFrame._minimize_window(frame)
    MainFrame._request_application_close(frame)

    assert [call.args for call in frame.log_service.log.call_args_list] == [
        (
            "DEBUG",
            "ui.toolbar action=theme current_theme=Light phase=requested",
        ),
        ("DEBUG", "ui.toolbar action=minimize phase=requested"),
        ("DEBUG", "ui.toolbar action=exit phase=requested"),
    ]
    toggle_theme.assert_called_once_with()
    frame.showMinimized.assert_called_once_with()
    frame.close.assert_called_once_with()


def test_secondary_window_destroyed_debug_excludes_target_identity():
    dialog = object()
    frame = SimpleNamespace(
        log_service=Mock(),
        _active_dialogs=[dialog],
    )
    frame._forget_dialog = lambda target: MainFrame._forget_dialog(frame, target)

    MainFrame._on_dialog_destroyed(frame, dialog, "LiveLogcatDialog")

    frame.log_service.log.assert_called_once_with(
        "DEBUG",
        "ui.secondary_window active_count=0 dialog=LiveLogcatDialog phase=closed",
    )
    assert frame._active_dialogs == []


def test_secondary_window_close_request_is_captured_by_main_event_filter():
    frame = SimpleNamespace(log_service=Mock())
    watched = Mock()
    watched.property.return_value = "FileExplorerDialog"
    event = Mock()
    event.type.return_value = QEvent.Type.Close

    handled = MainFrame.eventFilter(frame, watched, event)

    assert handled is False
    frame.log_service.log.assert_called_once_with(
        "DEBUG",
        "ui.secondary_window dialog=FileExplorerDialog phase=close_requested",
    )


def test_remote_diagnostic_redacts_active_device_and_limits_length():
    panel = SimpleNamespace(_active_device="device-secret")

    result = RemotePanel._redact_remote_diagnostic(
        panel,
        "device-secret:" + ("x" * 1200),
    )

    assert "device-secret" not in result
    assert "<device>" in result
    assert len(result) == 1000


def test_remote_launch_log_does_not_expose_command_arguments():
    panel = SimpleNamespace(
        _closing=False,
        _launch_worker=None,
        _active_device="device-secret",
        _device_info=Mock(),
        _update_status=Mock(),
        _set_running=Mock(),
        _log=Mock(),
        _scrcpy_service=Mock(),
        _remote_control=Mock(),
        _focus_scrcpy_window=Mock(),
        _warm_remote_input_session=Mock(),
        _read_stderr=Mock(),
        _process_key="scrcpy-test",
        _watchdog=Mock(),
        _process=None,
    )
    panel._scrcpy_service.start.return_value = Mock()

    with patch("gui.panels.remote_panel.threading.Thread"):
        RemotePanel._on_launch_ready(
            panel,
            ["scrcpy.exe", "-s", "device-secret", "--window-title", "secret"],
            "1080x2400",
        )

    messages = [call.args[1] for call in panel._log.call_args_list]
    assert "Launching scrcpy" in messages
    assert all("device-secret" not in message for message in messages)
    assert all("--window-title" not in message for message in messages)


def test_mobileperf_source_logger_splits_debug_and_business_streams(monkeypatch):
    stdout = io.StringIO()
    stderr = io.StringIO()
    target = logging.getLogger("test.mobileperf.source")
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("MOBILEPERF_LOG_DIR", raising=False)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    mobileperf_log._configure_logger(target)
    try:
        target.debug("diagnostic")
        target.info("progress")
    finally:
        mobileperf_log._remove_owned_handlers(target)

    assert "diagnostic" in stderr.getvalue()
    assert "diagnostic" not in stdout.getvalue()
    assert "progress" in stdout.getvalue()
    assert "progress" not in stderr.getvalue()


def test_mobileperf_frozen_logger_disables_debug(monkeypatch):
    stdout = io.StringIO()
    stderr = io.StringIO()
    target = logging.getLogger("test.mobileperf.frozen")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("MOBILEPERF_LOG_DIR", raising=False)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    mobileperf_log._configure_logger(target)
    try:
        target.debug("hidden")
        target.info("visible")
    finally:
        mobileperf_log._remove_owned_handlers(target)

    assert "hidden" not in stdout.getvalue()
    assert "hidden" not in stderr.getvalue()
    assert "visible" in stdout.getvalue()
    assert not stderr.getvalue()


def test_mobileperf_logger_tolerates_windowed_runtime_without_standard_streams(monkeypatch):
    target = logging.getLogger("test.mobileperf.windowed")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("MOBILEPERF_LOG_DIR", raising=False)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    mobileperf_log._configure_logger(target)
    try:
        target.debug("hidden")
        target.info("no-stream")
        assert [
            handler
            for handler in target.handlers
            if getattr(handler, mobileperf_log._HANDLER_MARKER, False)
        ] == []
    finally:
        mobileperf_log._remove_owned_handlers(target)


def test_mobileperf_formatter_redacts_runtime_values(monkeypatch):
    monkeypatch.setenv(
        "MOBILEPERF_REDACT_VALUES",
        json.dumps(["device-secret", "mail@example.test"]),
    )
    formatter = mobileperf_log._RedactingFormatter("%(message)s")
    record = logging.LogRecord(
        "mobileperf",
        logging.DEBUG,
        __file__,
        1,
        "device-secret mail@example.test",
        (),
        None,
    )

    rendered = formatter.format(record)

    assert "device-secret" not in rendered
    assert "mail@example.test" not in rendered
    assert rendered == "<redacted> <redacted>"


def test_mobileperf_runner_separates_child_stderr_from_ui_stream(tmp_path):
    process_runner = Mock(spec=ProcessRunner)
    proc = Mock()
    proc.stdout = []
    proc.stderr = []
    proc.poll.return_value = None
    process_runner.start.return_value = proc
    runner = MobilePerfRunner(
        process_runner=process_runner,
        project_root=tmp_path,
        python_executable="python-test",
    )
    config = MobilePerfRunConfig(
        device_id="device-secret",
        package="com.example.secret",
        save_path=str(tmp_path / "results"),
        mailbox="mail@example.test",
    )

    runner.start(config)
    kwargs = process_runner.start.call_args.kwargs
    runner._cleanup_config_dir()

    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    redacted_values = json.loads(kwargs["env"]["MOBILEPERF_REDACT_VALUES"])
    assert "device-secret" in redacted_values
    assert "mail@example.test" in redacted_values


def test_mobileperf_diagnostic_stream_is_redacted_before_ide_output(monkeypatch):
    stderr = io.StringIO()
    runner = MobilePerfRunner(process_runner=Mock(spec=ProcessRunner))
    runner._last_config = MobilePerfRunConfig(
        device_id="device-secret",
        mailbox="mail@example.test",
    )
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "stderr", stderr)

    runner._write_diagnostic("device-secret mail@example.test diagnostic")

    assert "device-secret" not in stderr.getvalue()
    assert "mail@example.test" not in stderr.getvalue()
    assert "<redacted> <redacted> diagnostic" in stderr.getvalue()


def test_file_utils_get_top_dir_does_not_print(capsys):
    result = FileUtils.get_top_dir()

    captured = capsys.readouterr()
    assert result
    assert captured.out == ""
    assert captured.err == ""
