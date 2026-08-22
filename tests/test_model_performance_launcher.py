# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import os
import time
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel

from gui.dialogs.performance_launcher import PerformanceLauncherDialog
from gui.styles import BaseStyles, theme
from gui.styles.typography import FontRole


def test_performance_launcher_perfetto_button_opens_perfetto_home():
    _app = QApplication.instance() or QApplication([])
    with patch("gui.dialogs.performance_launcher.QDesktopServices.openUrl") as open_url:
        PerformanceLauncherDialog.open_perfetto()

    open_url.assert_called_once()
    assert open_url.call_args.args[0].toString() == "https://ui.perfetto.dev/"


def test_performance_launcher_get_current_package_updates_package_field():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")

    with (
        patch("gui.dialogs.performance_launcher.detect_current_package") as detect,
        patch("gui.dialogs.performance_launcher.CurrentPackageWorker.start") as start_worker,
    ):
        detect.return_value = {
            "success": True,
            "device_ip": "device-1",
            "package_name": "com.example.app",
        }
        dialog.fetch_current_package()
        start_worker.assert_called_once_with()
        dialog._package_worker.run()
        dialog._package_worker.finished.emit()
        _app.processEvents()

    assert dialog.package_edit.text() == "com.example.app"
    assert dialog.get_package_btn.isEnabled() is True
    dialog.close()


def test_performance_launcher_build_config_uses_title_device_and_device_save_dir(tmp_path):
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="127.0.0.1:5555", package_name="com.example.app")
    dialog.save_path_edit.setText(str(tmp_path / "mobileperf"))

    cfg = dialog.build_config()

    assert cfg.device_id == "127.0.0.1:5555"
    assert cfg.package == "com.example.app"
    assert cfg.mailbox == ""
    assert not hasattr(dialog, "mailbox_edit")
    assert "mailbox" not in [label.text() for label in dialog.findChildren(QLabel)]
    assert Path(cfg.save_path).name == "127.0.0.1_5555"
    assert dialog.serialnum_label.text() == "127.0.0.1:5555"
    assert dialog.serialnum_label.objectName() == "onlineDeviceLabel"
    assert BaseStyles.color("LOG_SUCCESS") in dialog.styleSheet()
    dialog.close()


def test_performance_launcher_collects_monkey_config_from_controls():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1", package_name="com.example.app")
    try:
        dialog.monkey_check.setChecked(True)
        dialog.monkey_throttle_input.setValue(1000)
        dialog.monkey_seed_input.setValue(42)
        dialog.monkey_ignore_crashes.setChecked(False)
        dialog.monkey_ignore_timeouts.setChecked(True)
        dialog.monkey_ignore_security.setChecked(False)
        dialog.monkey_kill_after_error.setChecked(True)
        dialog.monkey_pct_inputs["pct_touch"].setValue(40)
        dialog.monkey_pct_inputs["pct_motion"].setValue(20)
        dialog.monkey_pct_inputs["pct_nav"].setValue(30)
        dialog.monkey_pct_inputs["pct_anyevent"].setValue(10)
        for key in [
            "pct_trackball",
            "pct_majornav",
            "pct_syskeys",
            "pct_appswitch",
            "pct_flip",
            "pct_pinchzoom",
        ]:
            dialog.monkey_pct_inputs[key].setValue(0)

        cfg = dialog.build_config()

        assert cfg.monkey_enabled is True
        assert cfg.monkey_config.throttle_ms == 1000
        assert cfg.monkey_config.seed == 42
        assert cfg.monkey_config.ignore_crashes is False
        assert cfg.monkey_config.ignore_timeouts is True
        assert cfg.monkey_config.ignore_security is False
        assert cfg.monkey_config.kill_after_error is True
        assert cfg.monkey_config.total_percentage == 100
        assert dialog.monkey_total_label.text() == "Total: 100%"
        assert dialog.monkey_total_label.accessibleName() == "Total: 100%"
    finally:
        dialog.close()


def test_performance_launcher_monkey_total_uses_committed_values_and_accessible_labels():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1", package_name="com.example.app")
    try:
        dialog.monkey_check.setChecked(True)
        values = {
            "pct_touch": 35,
            "pct_motion": 15,
            "pct_trackball": 0,
            "pct_nav": 20,
            "pct_majornav": 10,
            "pct_syskeys": 5,
            "pct_appswitch": 5,
            "pct_anyevent": 10,
            "pct_flip": 0,
            "pct_pinchzoom": 0,
        }
        for key, value in values.items():
            dialog.monkey_pct_inputs[key].setValue(value)

        cfg = dialog.build_config()
        assert all(label.text() == "Total: 100%" for label in dialog._monkey_total_labels)
        assert all(label.accessibleName() == "Total: 100%" for label in dialog._monkey_total_labels)
        assert cfg.monkey_config.total_percentage == 100
        assert cfg.monkey_config.pct_touch == 35
        assert cfg.monkey_config.pct_appswitch == 5
        expected_event_names = {
            "pct_touch": "Touch events percentage",
            "pct_motion": "Motion events percentage",
            "pct_trackball": "Trackball events percentage",
            "pct_nav": "Navigation events percentage",
            "pct_majornav": "Major navigation events percentage",
            "pct_syskeys": "System key events percentage",
            "pct_appswitch": "App switch events percentage",
            "pct_anyevent": "Any events percentage",
            "pct_flip": "Keyboard flip events percentage",
            "pct_pinchzoom": "Pinch/zoom events percentage",
        }
        assert {
            key: field.accessibleName() for key, field in dialog.monkey_pct_inputs.items()
        } == expected_event_names
        expected_flag_names = {
            "Ignore application crashes",
            "Ignore application timeouts",
            "Ignore security exceptions",
            "Kill Monkey after error",
        }
        flag_checkboxes = {
            dialog.monkey_ignore_crashes,
            dialog.monkey_ignore_timeouts,
            dialog.monkey_ignore_security,
            dialog.monkey_kill_after_error,
        }
        assert {checkbox.accessibleName() for checkbox in flag_checkboxes} == expected_flag_names
        assert all(checkbox.toolTip().strip() for checkbox in flag_checkboxes)
    finally:
        dialog.close()


def test_performance_launcher_monkey_throttle_width_fits_largest_value_after_font_change():
    _app = QApplication.instance() or QApplication([])
    old_ui_size = BaseStyles.DEFAULT_FONT_SIZE
    BaseStyles.DEFAULT_FONT_SIZE = 20
    dialog = PerformanceLauncherDialog(device_ip="device-1", package_name="com.example.app")
    try:
        dialog._apply_theme()
        metrics = dialog.fontMetrics()

        assert dialog.monkey_throttle_combo.minimumWidth() >= metrics.horizontalAdvance("2000") + 54
        assert dialog.monkey_seed_edit.minimumWidth() >= metrics.horizontalAdvance("1000000") + 28
        assert all(
            combo.minimumWidth() >= metrics.horizontalAdvance("100") + 50
            for combo in dialog.monkey_pct_combos.values()
        )
    finally:
        BaseStyles.DEFAULT_FONT_SIZE = old_ui_size
        dialog.close()


def test_performance_launcher_normalizes_mixed_separator_save_path():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="emulator-5554", package_name="com.example.app")
    dialog.save_path_edit.setText("E:/Download")

    try:
        cfg = dialog.build_config()

        assert cfg.save_path == os.path.normpath(r"E:\Download\emulator-5554")
        assert "E:/Download\\" not in cfg.save_path
    finally:
        dialog.close()


def test_performance_launcher_batches_logs_and_uses_log_font_size():
    _app = QApplication.instance() or QApplication([])
    old_ui_size = BaseStyles.DEFAULT_FONT_SIZE
    old_log_size = BaseStyles.LOG_FONT_SIZE_VAR
    BaseStyles.DEFAULT_FONT_SIZE = 17
    BaseStyles.LOG_FONT_SIZE_VAR = 11
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._apply_theme()

        dialog._append_log("INFO", "first")
        dialog._append_log("ERROR", "second")

        font = dialog.log_view.font()
        assert font.pointSize() == 11 or font.pixelSize() == 11
        assert "first" not in dialog.log_view.toPlainText()

        dialog._flush_pending_logs()

        text = dialog.log_view.toPlainText()
        assert "first" in text
        assert "second" in text
        assert "[INFO] first" in text
    finally:
        BaseStyles.DEFAULT_FONT_SIZE = old_ui_size
        BaseStyles.LOG_FONT_SIZE_VAR = old_log_size
        dialog.close()


def test_performance_launcher_config_and_log_use_distinct_font_roles():
    def effective_size(widget_or_font):
        font = widget_or_font if isinstance(widget_or_font, QFont) else widget_or_font.font()
        return font.pointSize() if font.pointSize() > 0 else font.pixelSize()

    _app = QApplication.instance() or QApplication([])
    old_ui_size = BaseStyles.DEFAULT_FONT_SIZE
    old_log_size = BaseStyles.LOG_FONT_SIZE_VAR
    BaseStyles.DEFAULT_FONT_SIZE = 18
    BaseStyles.LOG_FONT_SIZE_VAR = 10
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._apply_theme()

        assert effective_size(dialog.package_edit) == 18
        assert effective_size(dialog.frequency_combo) == 18
        assert effective_size(dialog.monkey_check) == 18
        assert effective_size(dialog.log_view) == 10
        hints = [w for w in dialog.findChildren(QLabel) if w.objectName() == "configHint"]
        assert hints
        assert all(label.text().strip() for label in hints)
        assert all(effective_size(label) == 18 for label in hints)
        expected_ui_font = BaseStyles.font_for_role(FontRole.UI)
        ui_described_fields = (
            dialog.frequency_input,
            dialog.timeout_input,
            dialog.dumpheap_input,
        )
        described_fields = (
            dialog.package_edit,
            *ui_described_fields,
            dialog.exception_edit,
            dialog.save_path_edit,
            dialog.phone_log_edit,
        )
        assert all(
            field.font().family() == expected_ui_font.family()
            and effective_size(field) == effective_size(expected_ui_font)
            for field in ui_described_fields
        )
        assert all(field.toolTip().strip() for field in described_fields)
        assert all(field.accessibleDescription().strip() for field in described_fields)
    finally:
        BaseStyles.DEFAULT_FONT_SIZE = old_ui_size
        BaseStyles.LOG_FONT_SIZE_VAR = old_log_size
        dialog.close()


def test_performance_launcher_log_follows_log_font_size():
    def effective_font_size(font):
        return font.pointSize() if font.pointSize() > 0 else font.pixelSize()

    _app = QApplication.instance() or QApplication([])
    old_ui_size = BaseStyles.DEFAULT_FONT_SIZE
    old_log_size = BaseStyles.LOG_FONT_SIZE_VAR
    BaseStyles.DEFAULT_FONT_SIZE = 18
    BaseStyles.LOG_FONT_SIZE_VAR = 10
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._append_log("INFO", "before")
        dialog._flush_pending_logs()

        BaseStyles.LOG_FONT_SIZE_VAR = 14
        BaseStyles.DEFAULT_FONT_SIZE = 16
        dialog._apply_theme()

        assert effective_font_size(dialog.log_view.font()) == 14
        assert effective_font_size(dialog.log_view.document().defaultFont()) == 14
        assert effective_font_size(dialog.log_view.viewport().font()) == 14
        assert dialog.log_view.toPlainText().strip()
    finally:
        BaseStyles.DEFAULT_FONT_SIZE = old_ui_size
        BaseStyles.LOG_FONT_SIZE_VAR = old_log_size
        dialog.close()


def test_performance_launcher_syncs_theme_when_signal_was_missed():
    _app = QApplication.instance() or QApplication([])
    old_theme = BaseStyles.current_theme()
    BaseStyles.switch_theme("Light")
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    dialog._theme_sync_timer.stop()
    try:
        light_style = dialog.styleSheet()

        theme._current_theme = "Dark"
        dialog._sync_theme_state()

        assert dialog._applied_theme_signature[0] == "Dark"
        assert BaseStyles.color("PANEL_BG") in dialog.styleSheet()
        assert dialog.styleSheet() != light_style
    finally:
        theme._current_theme = old_theme
        BaseStyles.switch_theme(old_theme)
        dialog.close()


def test_performance_launcher_monkey_parameter_text_follows_dark_theme_colors():
    _app = QApplication.instance() or QApplication([])
    old_theme = BaseStyles.current_theme()
    BaseStyles.switch_theme("Dark")
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    dialog._theme_sync_timer.stop()
    try:
        dialog.monkey_check.setChecked(True)
        style = dialog.styleSheet()

        assert "QLabel#inlineLabel" in style
        assert "QLineEdit, QComboBox, QSpinBox" in style
        assert BaseStyles.color("TEXT_PRIMARY") in style
        assert BaseStyles.color("INPUT_BG") in style
        assert "color: #000" not in style
        assert "color: black" not in style.lower()
        assert "monkeyOptionCheck" not in style
        assert "monkeyOption" not in style
        assert "QCheckBox::indicator" not in style
        assert dialog.monkey_check.property("monkeyOption") is None
        for checkbox in (
            dialog.monkey_ignore_crashes,
            dialog.monkey_ignore_timeouts,
            dialog.monkey_ignore_security,
            dialog.monkey_kill_after_error,
        ):
            assert checkbox.property("monkeyOption") is None
            assert checkbox.objectName() == ""
    finally:
        BaseStyles.switch_theme(old_theme)
        dialog.close()


def test_performance_launcher_raw_mobileperf_logs_are_not_reprefixed():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        raw_line = "[2026-06-13 10:00:00,000]INFO:mobileperf:startup:time is up"

        dialog._append_log("RAW", raw_line)
        dialog._flush_pending_logs()

        text = dialog.log_view.toPlainText().strip()
        assert text == raw_line
        assert "[RAW]" not in text
    finally:
        dialog.close()


def test_performance_launcher_running_status_is_green_and_progress_updates():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._set_running(True)
        dialog._run_duration_seconds = 100
        dialog._run_started_at = time.monotonic() - 25
        dialog._runner.is_running = Mock(return_value=True)

        dialog._update_progress()

        assert dialog.status_label.text() == "Running"
        assert BaseStyles.color("LOG_SUCCESS") in dialog.status_label.styleSheet()
        assert 20 <= dialog.progress_bar.value() <= 30
        assert dialog.progress_bar.format() == f"{dialog.progress_bar.value()}%"

        dialog._run_started_at = time.monotonic() - 500
        dialog._update_progress()

        assert dialog.progress_bar.value() == 99
    finally:
        dialog._runner.is_running = Mock(return_value=False)
        dialog.close()


def test_performance_launcher_finished_sets_progress_to_complete():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._runner_finished_handled = False
        dialog._run_started_at = time.monotonic()
        dialog._run_duration_seconds = 100
        dialog._runner.latest_result_dir = Mock(return_value="")
        dialog._runner.latest_report_file = Mock(return_value="")

        dialog._mark_runner_finished()

        assert dialog.progress_bar.value() == 100
        assert dialog.progress_bar.format() == "100%"
        assert dialog.status_label.text() == "Idle"
    finally:
        dialog.close()


def test_performance_launcher_stopping_status_is_warning_color():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._set_status("Stopping", "stopping")

        assert dialog.status_label.text() == "Stopping"
        assert BaseStyles.color("LOG_WARNING") in dialog.status_label.styleSheet()
    finally:
        dialog.close()


def test_performance_launcher_runner_finished_restores_buttons_once():
    _app = QApplication.instance() or QApplication([])
    dialog = PerformanceLauncherDialog(device_ip="device-1")
    try:
        dialog._set_running(True)
        dialog._runner_finished_handled = False
        dialog._poll_timer.start()

        dialog._on_runner_finished()
        dialog._on_runner_finished()

        assert dialog.start_btn.isEnabled() is True
        assert dialog.stop_btn.isEnabled() is False
        assert dialog.status_label.text() == "Idle"
        assert dialog._poll_timer.isActive() is False
        assert dialog.log_view.toPlainText().count("MobilePerf ended") == 1
    finally:
        dialog.close()
