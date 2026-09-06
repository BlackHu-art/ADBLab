# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import ctypes
import os
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gui import window_effects
from gui.dialogs.live_logcat import CurrentPackageWorker
from gui.features.logcat import LiveLogcatPage
from gui.styles import BaseStyles, theme
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
            patch.object(window_effects.ctypes, "WinDLL", Mock(return_value=DwmApi()), create=True),
        ):
            theme.apply_dark_title_bar(window)
    finally:
        if had_wintypes:
            ctypes.wintypes = original_wintypes

    assert len(calls) == 1
    assert calls[0][:2] == (12345, 20)
    assert ctypes.cast(calls[0][2], ctypes.POINTER(ctypes.c_int)).contents.value == int(
        BaseStyles.resolved_theme() == "Dark"
    )


def test_apply_dark_title_bar_on_other_platforms_does_not_create_a_native_handle():
    window = Mock()
    with patch.object(theme.sys, "platform", "linux"):
        theme.apply_dark_title_bar(window)
    window.winId.assert_not_called()


def test_live_logcat_worker_finished_during_close_does_not_touch_deleted_buttons():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatPage(device_ip="device-1")
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

    class CountingLiveLogcatPage(LiveLogcatPage):
        def __init__(self, *args, **kwargs):
            self.theme_calls = 0
            super().__init__(*args, **kwargs)

        def _apply_theme(self, *args, **kwargs):
            self.theme_calls += 1
            return super()._apply_theme(*args, **kwargs)

    dialog = CountingLiveLogcatPage(device_ip="device-1")
    try:
        BaseStyles.switch_theme("Dark")
        BaseStyles.switch_theme("Light")

        assert dialog.theme_calls == 3
    finally:
        dialog.close()


def test_live_logcat_ignores_queued_status_after_close():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatPage(device_ip="device-1")
    dialog._closing = True
    dialog.status_bar = Mock()

    try:
        dialog._on_status("采集已停止")

        dialog.status_bar.setText.assert_not_called()
    finally:
        dialog.close()


def test_live_logcat_ignores_queued_line_after_close():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatPage(device_ip="device-1")
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
    dialog = LiveLogcatPage(device_ip="device-1")
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
    dialog = LiveLogcatPage(device_ip="device-1")

    try:
        assert not hasattr(dialog, "tag_input")
        assert not hasattr(dialog, "_tag_label")
    finally:
        dialog.close()


def test_live_logcat_manual_package_filter_only_applies_after_enter():
    """编辑包名不会改变运行中 worker，按 Enter 后才建立新的过滤代次。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatPage(device_ip="device-1")
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
        assert dialog.status_bar.text() == ("正在切换应用过滤：com.example.manual")
    finally:
        dialog.worker = None
        dialog.close()


def test_live_logcat_enter_applies_manual_package_filter_clear():
    """清空包名后按 Enter 仅切回全部日志，不触发任何对话框默认按钮。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatPage(device_ip="device-1")
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
        assert dialog.status_bar.text() == "正在显示全部设备日志"
    finally:
        dialog.worker = None
        dialog.close()


def test_live_logcat_enter_rejects_invalid_manual_package_without_changing_worker():
    """非法包名在 Enter 提交边界被拒绝，不改变正在运行的过滤条件。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatPage(device_ip="device-1")
    worker = Mock()
    worker.is_active.return_value = True
    dialog.worker = worker

    try:
        dialog.pkg_input.setText("not a package")
        QTest.keyClick(dialog.pkg_input, Qt.Key.Key_Return)

        worker.update_package.assert_not_called()
        assert dialog.status_bar.text() == "包名格式无效，请输入有效包名后按 Enter"
    finally:
        dialog.worker = None
        dialog.close()


def test_live_logcat_manual_enter_supersedes_running_current_package_probe():
    """手动提交优先于尚未完成的 Current Package 查询，避免晚到结果覆盖输入。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatPage(device_ip="device-1")
    package_worker = Mock()
    package_worker.isRunning.return_value = True
    dialog._pkg_worker = package_worker

    try:
        dialog.pkg_input.setText("com.example.manual")
        QTest.keyClick(dialog.pkg_input, Qt.Key.Key_Return)

        package_worker.requestInterruption.assert_called_once_with()
        package_worker.package_ready.disconnect.assert_called_once_with(dialog._on_current_pkg)
        assert dialog.status_bar.text() == ("应用过滤已就绪：com.example.manual")
    finally:
        dialog._pkg_worker = None
        dialog.close()


def test_live_logcat_ignores_current_package_result_from_older_manual_revision():
    """已经排队的旧查询结果也不能覆盖较新的 Enter 手动提交。"""

    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatPage(device_ip="device-1")
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
    dialog = LiveLogcatPage(device_ip="device-1")
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
    dialog = LiveLogcatPage(device_ip="device-1")
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
        assert dialog.status_bar.text() == ("下次采集将显示全部设备日志")
    finally:
        dialog.worker = None
        dialog.close()


def test_live_logcat_no_wrap_flush_preserves_horizontal_position_and_follows_tail():
    app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatPage(device_ip="device-1")
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


def test_live_logcat_fluent_action_icons_follow_theme():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatPage(device_ip="device-1")
    try:
        icons = []
        for theme_name in ("Light", "Dark"):
            BaseStyles.switch_theme(theme_name)
            buttons = (dialog.btn_get_pkg, dialog.start_btn, dialog.stop_btn,
                       dialog.clear_btn, dialog.export_btn, dialog.wrap_btn)
            assert all(not button.icon().isNull() for button in buttons)
            icons.append([button.icon().pixmap(24, 24).toImage() for button in buttons])
        assert all(light != dark for light, dark in zip(*icons))
    finally:
        dialog.close()


def _bounded_logcat_page(monkeypatch, *, maximum=100):
    """用真实文档的小缓存复现淘汰，不启动设备 worker。"""

    monkeypatch.setattr(LiveLogcatPage, "MAX_BUFFER", maximum)
    page = LiveLogcatPage(device_ip="demo-buffer-device")
    page.resize(700, 430)
    page.show()
    QApplication.processEvents()
    return page


def test_live_logcat_evicted_error_disappears_when_only_info_arrives(
    qt_application, monkeypatch
):
    """稀疏等级视图必须淘汰已离开原始缓存的错误，不能永久保留旧正文。"""

    page = _bounded_logcat_page(monkeypatch)
    error = "09-06 18:00:00.000 1 1 E Demo: oldest error"
    try:
        page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
        page._on_line(error, "E", 1)
        page._flush_pending_lines()
        assert page.output.toPlainText().splitlines() == [error]
        for index in range(100):
            page._on_line(f"09-06 18:00:01.000 1 1 I Demo: info {index}", "I", 1)
        page._flush_pending_lines()
        assert page.output.toPlainText() == ""
        assert not page.export_btn.isEnabled()
    finally:
        page.close()


def test_live_logcat_evicted_pending_error_never_reaches_output(qt_application, monkeypatch):
    """尚未落屏的错误被原始缓存淘汰后，后续刷新不得重新显示它。"""

    page = _bounded_logcat_page(monkeypatch)
    try:
        page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
        page._on_line("09-06 18:00:00.000 1 1 E Demo: pending error", "E", 1)
        for index in range(100):
            page._on_line(f"09-06 18:00:01.000 1 1 I Demo: info {index}", "I", 1)
        assert page.output.toPlainText() == ""
        page._flush_pending_lines()
        assert page.output.toPlainText() == ""
        assert not page.export_btn.isEnabled()
    finally:
        page.close()


def test_live_logcat_duplicate_messages_are_evicted_one_record_at_a_time(
    qt_application, monkeypatch
):
    """相同文本代表不同日志条目，淘汰一条不得保留或删除全部同文记录。"""

    page = _bounded_logcat_page(monkeypatch)
    error = "09-06 18:00:00.000 1 1 E Demo: repeated error"
    try:
        page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
        for _index in range(3):
            page._on_line(error, "E", 1)
        page._flush_pending_lines()
        assert page.output.toPlainText().splitlines() == [error] * 3
        for index in range(98):
            page._on_line(f"09-06 18:00:01.000 1 1 I Demo: info {index}", "I", 1)
        page._flush_pending_lines()
        assert page.output.toPlainText().splitlines() == [error] * 2
        for remaining in (1, 0):
            page._on_line(f"09-06 18:00:02.000 1 1 I Demo: next {remaining}", "I", 1)
            page._flush_pending_lines()
            assert page.output.toPlainText().splitlines() == [error] * remaining
    finally:
        page.close()


def test_live_logcat_full_buffer_preserves_retained_history_anchor(
    qt_application, monkeypatch
):
    """缓冲区已满时，上翻阅读仍留在未被淘汰的首条可见日志。"""

    page = _bounded_logcat_page(monkeypatch, maximum=200)
    try:
        for index in range(200):
            page._on_line(f"09-06 18:00:00.000 1 1 I Demo: history {index}", "I", 1)
        page._flush_pending_lines()
        qt_application.processEvents()
        scrollbar = page.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() // 2)
        first_visible = page.output.firstVisibleBlock().text()
        assert not page.follow_btn.isChecked()
        for index in range(10):
            page._on_line(f"09-06 18:00:01.000 1 1 I Demo: new {index}", "I", 1)
        page._flush_pending_lines()
        qt_application.processEvents()
        assert page.output.firstVisibleBlock().text() == first_visible
        assert not page.follow_btn.isChecked()
    finally:
        page.close()


def test_live_logcat_explicit_pause_survives_short_filter_wrap_and_resize(
    qt_application, monkeypatch
):
    """明确暂停跟随后，程序引起的滚动范围缩短不能自行恢复跟随。"""

    page = _bounded_logcat_page(monkeypatch, maximum=200)
    try:
        page._on_line("09-06 18:00:00.000 1 1 E Demo: only matching error", "E", 1)
        for index in range(100):
            page._on_line(f"09-06 18:00:01.000 1 1 I Demo: info {index}", "I", 1)
        page._flush_pending_lines()
        assert page.follow_btn.isChecked()
        page.follow_btn.click()
        assert not page.follow_btn.isChecked()
        page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
        qt_application.processEvents()
        assert len(page.output.toPlainText().splitlines()) == 1
        assert not page.follow_btn.isChecked()
        for width, height in ((420, 360), (1000, 760)):
            page.wrap_btn.click()
            page.resize(width, height)
            qt_application.processEvents()
            assert not page.follow_btn.isChecked()
        page.level_combo.setCurrentIndex(0)
        page._on_line("09-06 18:00:03.000 1 1 I Demo: after pause", "I", 1)
        page._flush_pending_lines()
        qt_application.processEvents()
        assert not page.follow_btn.isChecked()
    finally:
        page.close()


def test_live_logcat_wrapped_full_buffer_preserves_visible_line_within_record(
    qt_application, monkeypatch
):
    """长日志换成多行后，淘汰旧记录仍保持当前记录及其中正在阅读的视觉行。"""

    page = _bounded_logcat_page(monkeypatch, maximum=200)
    try:
        if not page.wrap_btn.isChecked():
            page.wrap_btn.click()
        suffix = " ".join(f"segment-{index:02d}" for index in range(50))
        for index in range(200):
            page._on_line(f"09-06 18:00:00.000 1 1 I Demo: {index:03d} {suffix}", "I", 1)
        page._flush_pending_lines()
        qt_application.processEvents()
        scrollbar = page.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() // 2 + 2)
        qt_application.processEvents()
        sample_point = QPoint(4, page.output.fontMetrics().height() // 2)
        visible_cursor = page.output.cursorForPosition(sample_point)
        for _attempt in range(3):
            if visible_cursor.positionInBlock() > 0:
                break
            scrollbar.setValue(scrollbar.value() + 1)
            qt_application.processEvents()
            visible_cursor = page.output.cursorForPosition(sample_point)
        first_visible = page.output.firstVisibleBlock().text()
        visible_offset = visible_cursor.positionInBlock()
        assert visible_offset > 0
        assert not page.follow_btn.isChecked()
        for index in range(10):
            page._on_line(f"09-06 18:00:01.000 1 1 I Demo: new {index:03d} {suffix}", "I", 1)
        page._flush_pending_lines()
        qt_application.processEvents()
        assert page.output.firstVisibleBlock().text() == first_visible
        assert page.output.cursorForPosition(sample_point).positionInBlock() == visible_offset
        assert not page.follow_btn.isChecked()
    finally:
        page.close()


def test_live_logcat_reactivation_applies_eviction_without_matching_new_lines(
    qt_application, monkeypatch
):
    page = _bounded_logcat_page(monkeypatch, maximum=100)
    try:
        page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
        page._on_line("old error", "E")
        page._flush_pending_lines()
        page.deactivate()
        for index in range(100):
            page._on_line(f"info {index}", "I")
        assert page.output.toPlainText() == "old error"
        assert not page._line_flush_timer.isActive()
        page.activate()
        qt_application.processEvents()
        assert page.output.toPlainText() == ""
        assert "100 / 100" in page.reading_status.text()
        assert page.output.placeholderText() == "当前等级下没有匹配的日志，可调整等级或等待新日志。"
        assert not page.export_btn.isEnabled()
    finally:
        page.close()


def test_live_logcat_package_switch_discarded_pending_does_not_delete_new_output(
    monkeypatch,
):
    page = _bounded_logcat_page(monkeypatch, maximum=100)
    worker = Mock()
    worker.is_active.return_value = True
    worker.update_package.return_value = True
    try:
        for index in range(90):
            page._on_line(f"old displayed {index}", "I")
        page._flush_pending_lines()
        for index in range(10):
            page._on_line(f"old pending {index}", "I")
        page.worker = worker
        page._apply_package_filter("com.example.new")
        for index in range(100):
            page._on_line(f"new record {index}", "I")
            page._flush_pending_lines()
        assert page.output.toPlainText().splitlines() == [
            f"new record {index}" for index in range(100)
        ]
    finally:
        page.worker = None
        page.close()
