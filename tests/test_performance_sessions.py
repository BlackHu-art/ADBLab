"""验证各设备采集状态与固定会话的路由、准入和清理边界。"""

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyleOptionViewItem, QWidget
from qfluentwidgets import FluentIcon
from shiboken6 import isValid

from core.settings_manager import DEFAULTS, AppSettings
from gui.dialogs.performance_launcher import PerformancePage
from gui.pages.workspace_features import WorkspaceFeatureHost
from gui.styles import BaseStyles


@pytest.fixture
def host(monkeypatch, tmp_path):
    values = dict(DEFAULTS, save_directory=str(tmp_path))
    settings = SimpleNamespace(
        get=values.get, set=lambda key, value: values.update({key: value}),
        save_directory=str(tmp_path),
    )
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    result = WorkspaceFeatureHost("system", "系统工具", QWidget())

    def factory(key):
        page = PerformancePage(key.device_id, "com.example.demo")
        runner = Mock()
        runner.is_running.return_value = False
        runner.latest_result_dir.return_value = ""
        runner.latest_report_file.return_value = ""
        runner.last_config = None
        runner.last_exit_code = 0

        def start(config, **_callbacks):
            runner.last_config = config
            runner.is_running.return_value = True

        runner.start.side_effect = start
        runner.stop.side_effect = lambda: setattr(runner.is_running, "return_value", False)
        page._runner = runner
        return page

    result.register_feature(
        "performance", "性能采集", FluentIcon.SPEED_HIGH, factory, show_close_action=False,
    )
    result.set_external_device_controls(True)
    result.resize(850, 760)
    result.show()
    yield result
    for page in result.registry.pages():
        page._runner.is_running.return_value = False
    result.shutdown()
    result.close()
    result.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _choose(host, qt_application, row):
    table = host.performance_sessions.table
    qt_application.processEvents()
    item = table.item(row, 0)
    QTest.mouseClick(
        table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualItemRect(item).center(),
    )
    qt_application.processEvents()
    return host.stack.currentWidget()


def test_multiple_selection_lists_idle_devices_without_creating_or_starting_sessions(
    host, qt_application,
):
    host.set_device_context(["demo-a", "demo-b"], ["demo-a", "demo-b"])
    host.open_feature("performance", payload={"package_name": "com.example.pending"})
    assert host.registry.pages() == ()
    assert host.performance_sessions.isVisible()
    assert host.performance_sessions.table.rowCount() == 2
    assert host.close_session_button.isHidden()
    page = _choose(host, qt_application, 1)
    assert page.device_ip == "demo-b"
    assert page.package_edit.text() == "com.example.pending"
    page._runner.start.assert_not_called()
    assert host._selected_devices == ("demo-a", "demo-b")
    assert len(host.registry.pages()) == 1
    assert host.close_session_button.isHidden()


def test_two_collectors_keep_separate_progress_parameters_and_stop_target(host, qt_application):
    host.set_device_context(["demo-a", "demo-b"], ["demo-a", "demo-b"])
    host.open_feature("performance", preferred_device="demo-a")
    first = host.stack.currentWidget()
    first.timeout_input.setValue(10)
    first.start_btn.click()
    first.start_btn.click()
    assert first._runner.start.call_count == 1
    first._run_started_at = time.monotonic() - 120
    first._update_progress()
    second = _choose(host, qt_application, 1)
    second.timeout_input.setValue(20)
    second.package_edit.setText("com.example.second")
    second.start_btn.click()
    second._run_started_at = time.monotonic() - 120
    second._update_progress()
    assert first._runner.is_running() and second._runner.is_running()
    table = host.performance_sessions.table
    assert table.item(0, 2).text().startswith("20%")
    assert table.item(1, 2).text().startswith("10%")
    assert "02:00" in table.item(0, 2).text()
    assert "02:00 / 10:00" in table.item(0, 2).toolTip()
    assert "02:00 / 20:00" in table.item(1, 2).toolTip()
    assert first.build_config().package == "com.example.demo"
    assert second.build_config().package == "com.example.second"
    assert first.performance_snapshot().duration == 600
    assert second.performance_snapshot().duration == 1200

    assert _choose(host, qt_application, 0) is first
    first.stop_btn.click()
    first._stop_thread.join(timeout=2)
    qt_application.processEvents()
    assert first._runner.stop.call_count == 1
    second._runner.stop.assert_not_called()
    assert second._runner.is_running()
    assert first.performance_snapshot().state == "cancelled"
    assert second.performance_snapshot().state == "running"
    assert table.item(0, 1).text() == first.status_label.text()
    assert "10%" in table.item(1, 2).text()


def test_running_session_stays_visible_after_deselection_and_disconnect(host, qt_application):
    host.set_device_context(["demo-a", "demo-b"], ["demo-a", "demo-b"])
    host.open_feature("performance", preferred_device="demo-a")
    first = host.stack.currentWidget()
    first.start_btn.click()
    host.set_device_context(["demo-b"], ["demo-b"])
    table = host.performance_sessions.table
    assert host.performance_sessions.isVisible()
    assert [table.item(row, 0).text() for row in range(2)] == ["demo-b", "demo-a"]
    assert "离线" in table.item(1, 1).text()
    assert first.stop_btn.isEnabled()
    assert not first.start_btn.isEnabled()
    assert _choose(host, qt_application, 0).device_ip == "demo-b"
    assert first._runner.is_running()
    assert _choose(host, qt_application, 1) is first
    first._runner.start.assert_called_once()


@pytest.mark.parametrize("font_size", [12, 22])
def test_state_list_bounds_long_devices_and_many_rows(host, qt_application, font_size, monkeypatch):
    monkeypatch.setattr(
        BaseStyles, "font_for_role", lambda *_args: QFont("Microsoft YaHei UI", font_size),
    )
    BaseStyles.fonts_changed.emit(BaseStyles.current_font_config())
    devices = [f"demo-{index}-" + "w" * 90 for index in range(8)]
    host.resize(400, 780)
    host.set_device_context(devices, devices)
    host.open_feature("performance")
    qt_application.processEvents()
    panel = host.performance_sessions
    table = panel.table
    assert table.rowCount() == 8
    assert table.verticalScrollBar().maximum() > 0
    assert table.height() < 300
    assert table.horizontalScrollBar().maximum() == 0
    assert table.item(7, 0).text() == devices[7]
    assert devices[7] in table.item(7, 0).toolTip()
    assert table.geometry().right() < panel.width()
    option = QStyleOptionViewItem()
    table.itemDelegate().initStyleOption(option, table.model().index(0, 0))
    assert option.font.pointSize() == font_size


def test_collapsing_state_list_reclaims_space_without_stopping_collectors(host, qt_application):
    host.set_device_context(["demo-a", "demo-b"], ["demo-a", "demo-b"])
    host.open_feature("performance", preferred_device="demo-a")
    page = host.stack.currentWidget()
    page.start_btn.click()
    qt_application.processEvents()
    panel = host.performance_sessions
    expanded_height = panel.height()
    panel.section.toggle_button.click()
    qt_application.processEvents()
    assert panel.table.isHidden()
    assert panel.height() < expanded_height
    assert page._runner.is_running()
    page._set_progress(25)
    panel.section.toggle_button.click()
    qt_application.processEvents()
    assert not panel.table.isHidden()
    assert panel.table.item(0, 2).text().startswith("25%")


def test_session_disposal_and_feature_navigation_release_or_hide_list(host, qt_application):
    host.set_device_context(["demo-a", "demo-b"], ["demo-a", "demo-b"])
    host.open_feature("performance", preferred_device="demo-a")
    first = host.stack.currentWidget()
    key = host.registry.current_key
    assert host.performance_sessions.isVisible()
    host.show_overview()
    assert not host.performance_sessions.isVisible()
    first._set_status("Failed", "failed")
    assert not host.performance_sessions.isVisible()
    assert host.registry.request_dispose(key)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(first)
    host.open_feature("performance")
    assert host.performance_sessions.table.item(0, 1).text() == "Idle"
