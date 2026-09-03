# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import ctypes
import os
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gui.dialogs import live_logcat_form
from gui.dialogs.live_logcat import CurrentPackageWorker, LiveLogcatDialog
from gui.styles import BaseStyles, FontRole, theme
from gui.styles.fluent import apply_label_role
from main import windows_app_user_model_id
from utils.app_metadata import APP_RELEASE_TAG, APP_VERSION


def test_app_metadata_derives_release_tag_and_windows_app_id():
    assert APP_RELEASE_TAG == f"v{APP_VERSION}"
    major_minor = APP_VERSION.rsplit(".", 1)[0]
    assert windows_app_user_model_id() == f"ADBLab.Frankie.{major_minor}"


def test_apply_dark_title_bar_calls_dwm_without_ctypes_side_effect_imports():
    had_wintypes = hasattr(ctypes, "wintypes")
    original_wintypes = getattr(ctypes, "wintypes", None)
    if had_wintypes:
        delattr(ctypes, "wintypes")

    window = Mock()
    window.winId.return_value = 12345
    calls = []

    class DwmApi:
        @staticmethod
        def DwmSetWindowAttribute(*args):
            calls.append(args)
            return 0

    try:
        with (
            patch.object(theme.sys, "platform", "win32"),
            patch.object(theme.ctypes, "windll", Mock(dwmapi=DwmApi()), create=True),
        ):
            theme.apply_dark_title_bar(window)
    finally:
        if had_wintypes:
            ctypes.wintypes = original_wintypes

    assert len(calls) == 1


def test_dialog_status_uses_direct_reference_label(qt_application):
    from qfluentwidgets import CaptionLabel

    bar = apply_label_role(CaptionLabel("Ready"), FontRole.UI_SMALL)

    assert type(bar) is CaptionLabel
    assert bar.text() == "Ready"
    assert bar.property("fontRole") == FontRole.UI_SMALL.value


def test_live_logcat_worker_finished_during_close_does_not_touch_deleted_buttons():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    dialog._closing = True
    dialog.start_btn = Mock()
    dialog.stop_btn = Mock()

    try:
        dialog._on_worker_finished()

        dialog.start_btn.setEnabled.assert_not_called()
        dialog.stop_btn.setEnabled.assert_not_called()
        assert dialog.worker is None
    finally:
        dialog.close()


def test_live_logcat_apply_theme_does_not_reconnect_theme_signal():
    _app = QApplication.instance() or QApplication([])

    class CountingLiveLogcatDialog(LiveLogcatDialog):
        def __init__(self, *args, **kwargs):
            self.theme_calls = 0
            super().__init__(*args, **kwargs)

        def _apply_theme(self, *args, **kwargs):
            self.theme_calls += 1
            return super()._apply_theme(*args, **kwargs)

    dialog = CountingLiveLogcatDialog(device_ip="device-1")
    try:
        BaseStyles.switch_theme("Dark")
        BaseStyles.switch_theme("Light")

        assert dialog.theme_calls == 3
    finally:
        dialog.close()


def test_live_logcat_ignores_queued_status_after_close():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    dialog._closing = True
    dialog.status_bar = Mock()

    try:
        dialog._on_status("Logcat stopped")

        dialog.status_bar.setText.assert_not_called()
    finally:
        dialog.close()


def test_live_logcat_ignores_queued_line_after_close():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    dialog._closing = True
    dialog.output = Mock()

    try:
        dialog._on_line("05-27 12:00:00.000 1 1 I Tag: message", "I")

        dialog.output.appendPlainText.assert_not_called()
        assert not dialog.entries
    finally:
        dialog.close()


def test_live_logcat_batches_visible_line_appends():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    appended = []
    dialog.output = Mock()
    dialog.output.appendPlainText.side_effect = appended.append

    try:
        dialog._on_line("05-27 12:00:00.000 1 1 I Tag: one", "I")
        dialog._on_line("05-27 12:00:00.000 1 1 I Tag: two", "I")

        dialog.output.appendPlainText.assert_not_called()
        dialog._flush_pending_lines()

        assert appended == ["05-27 12:00:00.000 1 1 I Tag: one\n05-27 12:00:00.000 1 1 I Tag: two"]
        assert len(dialog.entries) == 2
    finally:
        dialog.close()


def test_live_logcat_form_has_no_tag_filter():
    """Live Logcat 仅保留等级和包名过滤，不再暴露重复的 Tag 过滤入口。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")

    try:
        assert not hasattr(dialog, "tag_input")
        assert not hasattr(dialog, "_tag_label")
    finally:
        dialog.close()


def test_live_logcat_manual_package_filter_only_applies_after_enter():
    """编辑包名不会改变运行中 worker，按 Enter 后才建立新的过滤代次。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    worker = Mock()
    worker.is_active.return_value = True
    worker.update_package.return_value = True
    dialog.worker = worker

    try:
        dialog.pkg_input.setText("com.example.manual")
        worker.update_package.assert_not_called()

        dialog._pending_visible_lines.append("stale")
        dialog._line_flush_timer.start(1000)
        QTest.keyClick(dialog.pkg_input, Qt.Key.Key_Return)

        worker.update_package.assert_called_once_with("com.example.manual")
        assert not dialog._pending_visible_lines
        assert not dialog._line_flush_timer.isActive()
        assert dialog.status_bar.text() == ("Switching package filter: com.example.manual")
    finally:
        dialog.worker = None
        dialog.close()


def test_live_logcat_enter_applies_manual_package_filter_clear():
    """清空包名后按 Enter 仅切回全部日志，不触发任何对话框默认按钮。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    worker = Mock()
    worker.is_active.return_value = True
    worker.update_package.return_value = True
    dialog.worker = worker
    action_buttons = (
        dialog.btn_get_pkg,
        dialog.start_btn,
        dialog.stop_btn,
        dialog.clear_btn,
        dialog.export_btn,
        dialog.wrap_btn,
    )

    try:
        assert all(not button.autoDefault() for button in action_buttons)
        assert all(not button.isDefault() for button in action_buttons)
        dialog.pkg_input.setText("")
        with patch("gui.dialogs.live_logcat_stream.CurrentPackageWorker") as package_worker:
            QTest.keyClick(dialog.pkg_input, Qt.Key.Key_Return)
            package_worker.assert_not_called()

        worker.update_package.assert_called_once_with("")
        assert dialog.status_bar.text() == "Showing all device logs"
    finally:
        dialog.worker = None
        dialog.close()


def test_live_logcat_enter_rejects_invalid_manual_package_without_changing_worker():
    """非法包名在 Enter 提交边界被拒绝，不改变正在运行的过滤条件。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    worker = Mock()
    worker.is_active.return_value = True
    dialog.worker = worker

    try:
        dialog.pkg_input.setText("not a package")
        QTest.keyClick(dialog.pkg_input, Qt.Key.Key_Return)

        worker.update_package.assert_not_called()
        assert dialog.status_bar.text() == "Invalid package name for logcat filter"
    finally:
        dialog.worker = None
        dialog.close()


def test_live_logcat_manual_enter_supersedes_running_current_package_probe():
    """手动提交优先于尚未完成的 Current Package 查询，避免晚到结果覆盖输入。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    package_worker = Mock()
    package_worker.isRunning.return_value = True
    dialog._pkg_worker = package_worker

    try:
        dialog.pkg_input.setText("com.example.manual")
        QTest.keyClick(dialog.pkg_input, Qt.Key.Key_Return)

        package_worker.requestInterruption.assert_called_once_with()
        package_worker.package_ready.disconnect.assert_called_once_with(dialog._on_current_pkg)
        assert dialog.status_bar.text() == ("Package filter ready: com.example.manual")
    finally:
        dialog._pkg_worker = None
        dialog.close()


def test_live_logcat_ignores_current_package_result_from_older_manual_revision():
    """已经排队的旧查询结果也不能覆盖较新的 Enter 手动提交。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    source = CurrentPackageWorker("device-1")
    source._package_filter_revision = 0
    dialog._package_filter_revision = 1
    source.package_ready.connect(dialog._on_current_pkg)

    try:
        dialog.pkg_input.setText("com.example.manual")
        source.package_ready.emit("com.example.stale")

        assert dialog.pkg_input.text() == "com.example.manual"
    finally:
        source.package_ready.disconnect(dialog._on_current_pkg)
        source.deleteLater()
        dialog.close()


def test_live_logcat_current_package_updates_the_running_filter_generation():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    worker = Mock()
    worker.is_active.return_value = True
    dialog.worker = worker

    try:
        dialog._on_current_pkg("com.example.current")

        assert dialog.pkg_input.text() == "com.example.current"
        worker.update_package.assert_called_once_with("com.example.current")
    finally:
        dialog.worker = None
        dialog.close()


def test_live_logcat_stopping_rejects_new_or_late_package_switches():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    worker = Mock()
    worker.is_active.return_value = True
    dialog.worker = worker

    try:
        dialog._set_running_actions(True, stopping=True)
        assert not dialog.btn_get_pkg.isEnabled()

        with patch("gui.dialogs.live_logcat_stream.CurrentPackageWorker") as package_worker:
            dialog._fetch_current_pkg()
        package_worker.assert_not_called()

        dialog._on_current_pkg("com.example.next")
        assert dialog.pkg_input.text() == "com.example.next"
        worker.update_package.assert_not_called()

        dialog.pkg_input.setText("")
        QTest.keyClick(dialog.pkg_input, Qt.Key.Key_Return)
        worker.update_package.assert_not_called()
        assert dialog.status_bar.text() == ("All device logs will be shown on next start")
    finally:
        dialog.worker = None
        dialog.close()


def test_live_logcat_no_wrap_flush_preserves_horizontal_position_and_follows_tail():
    app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    dialog.show()
    app.processEvents()

    try:
        dialog.wrap_btn.setChecked(False)
        dialog._toggle_wrap()
        long_line = "0123456789" * 120
        dialog.output.setPlainText("\n".join(f"{index:03d} {long_line}" for index in range(100)))
        app.processEvents()
        horizontal = dialog.output.horizontalScrollBar()
        vertical = dialog.output.verticalScrollBar()
        assert horizontal.maximum() > 3
        preserved_position = horizontal.maximum() // 3
        horizontal.setValue(preserved_position)
        vertical.setValue(vertical.maximum())

        dialog._on_line(
            f"08-25 12:00:00.000 111 111 I Demo: {long_line}",
            "I",
            111,
        )
        dialog._line_flush_timer.stop()
        dialog._flush_pending_lines()
        app.processEvents()

        assert horizontal.value() == preserved_position
        assert vertical.value() == vertical.maximum()
    finally:
        dialog.close()


def test_live_logcat_theme_refresh_explicitly_rebinds_action_icons():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    current_theme = BaseStyles.current_theme()
    next_theme = "Dark" if current_theme != "Dark" else "Light"

    try:
        with patch.object(
            live_logcat_form,
            "get_themed_icon",
            wraps=live_logcat_form.get_themed_icon,
        ) as load_icon:
            BaseStyles.switch_theme(next_theme)

        rebound = {call.args[0] for call in load_icon.call_args_list}
        assert {
            "scroll.svg",
            "target.svg",
            "play.svg",
            "stop-circle.svg",
            "broom.svg",
            "file-arrow-down.svg",
            "arrows-left-right.svg",
        } <= rebound
    finally:
        BaseStyles.switch_theme(current_theme)
        dialog.close()
