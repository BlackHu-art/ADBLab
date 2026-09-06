"""验证性能采集的实际阶段、估算进度与切页动画边界。"""

import gc
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtGui import QIcon
from qfluentwidgets import ProgressRing

from core.settings_manager import DEFAULTS, AppSettings
from gui.dialogs.performance_launcher import PerformancePage


@pytest.fixture
def page(monkeypatch, tmp_path):
    values = dict(DEFAULTS, save_directory=str(tmp_path))
    settings = SimpleNamespace(
        get=values.get, set=lambda key, value: values.update({key: value}),
        save_directory=str(tmp_path),
    )
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    result = PerformancePage(device_ip="demo-device", package_name="com.example.demo")
    runner = Mock()
    runner.is_running.return_value = False
    runner.latest_result_dir.return_value = ""
    runner.latest_report_file.return_value = ""
    runner.last_config = object()
    runner.last_exit_code = 0
    result._runner = runner
    yield result
    runner.is_running.return_value = False
    result.close()


def test_running_ring_renders_percentage_and_waits_after_planned_duration(page, qt_application):
    page.show()
    page._set_running(True)
    page._runner.is_running.return_value = True
    page._run_duration_seconds = 100
    page._run_started_at = time.monotonic() - 25
    page._update_progress()
    display = page.progress_display
    assert isinstance(page.progress_bar, ProgressRing)
    assert page.progress_bar.isTextVisible()
    assert page.progress_bar.format() == "25%"
    assert display.indicators.currentWidget() is page.progress_bar
    assert "00:00:25" in display.detail_label.text()
    assert "00:01:40" in display.detail_label.text()
    assert display.busy_ring.aniGroup.state() == QAbstractAnimation.State.Stopped

    page._run_started_at = time.monotonic() - 120
    page._update_progress()
    assert page.progress_bar.value() == 99
    assert display.indicators.currentWidget() is display.busy_ring
    assert display.busy_ring.aniGroup.state() == QAbstractAnimation.State.Running
    # 单纯进程退出还没有确认报告，计时更新不得提前显示完成。
    page._runner.is_running.return_value = False
    page._update_progress()
    assert page.progress_bar.value() == 99


def test_waiting_animation_pauses_on_deactivate_and_stops_on_dispose(page, qt_application):
    page.activate()
    page._set_running(True)
    page._set_status("Stopping", "stopping")
    animation = page.progress_display.busy_ring.aniGroup
    assert animation.state() == QAbstractAnimation.State.Running
    page.deactivate()
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert page._configuration_locked
    page.activate()
    assert animation.state() == QAbstractAnimation.State.Running
    page.hide()
    assert animation.state() == QAbstractAnimation.State.Stopped
    page.show()
    assert animation.state() == QAbstractAnimation.State.Running
    page.request_dispose("test")
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert page._closing
    page._runner.start.assert_not_called()


def test_hidden_collection_still_updates_value_without_restarting_animation(page):
    page.activate()
    page._set_running(True)
    page._run_duration_seconds = 100
    page._run_started_at = time.monotonic() - 25
    page._update_progress()
    page.deactivate()
    page._run_started_at = time.monotonic() - 50
    page._update_progress()
    assert page.progress_bar.value() == 50
    assert page.progress_bar.ani.state() == QAbstractAnimation.State.Stopped
    page.activate()
    assert page.progress_bar.isUseAni()
    page.hide()
    page._run_started_at = time.monotonic() - 60
    page._update_progress()
    assert page.progress_bar.value() == 60
    assert page.progress_bar.ani.state() == QAbstractAnimation.State.Stopped


@pytest.mark.parametrize(
    ("report", "exit_code", "expected_state", "expected_progress"),
    [(True, 0, "completed", 100), (True, 1, "warning", 25), (False, 1, "failed", 25)],
)
def test_terminal_icon_requires_confirmed_report(
    page, tmp_path, report, exit_code, expected_state, expected_progress,
):
    page._runner_finished_handled = False
    page._set_running(True)
    page._set_progress(25)
    page._runner.last_exit_code = exit_code
    if report:
        artifact = tmp_path / "report.html"
        artifact.write_text("report", encoding="utf-8")
        page._runner.latest_report_file.return_value = str(artifact)
    page._on_runner_finished()
    assert page._status_state == expected_state
    assert page.progress_bar.value() == expected_progress
    assert page.progress_display.indicators.currentIndex() == 0
    assert page.progress_display.busy_ring.aniGroup.state() == QAbstractAnimation.State.Stopped
    assert page.progress_bar.ani.state() == QAbstractAnimation.State.Stopped
    assert page.start_btn.isEnabled() and not page.stop_btn.isEnabled()
    assert not page._configuration_locked


def test_start_error_shows_failure_icon_and_restores_actions(page):
    page._runner.start.side_effect = RuntimeError("synthetic start failure")
    page.start_btn.click()
    assert page._runner.start.call_count == 1
    assert page._status_state == "failed"
    assert page.progress_display.indicators.currentIndex() == 0
    assert page.progress_bar.ani.state() == QAbstractAnimation.State.Stopped
    assert page.progress_bar.value() == 0
    assert page.start_btn.isEnabled() and not page.stop_btn.isEnabled()
    assert not page._configuration_locked


def test_stop_waits_without_advancing_then_shows_stopped_with_results(
    page, monkeypatch, tmp_path,
):
    page._runner_finished_handled = False
    page._runner.is_running.return_value = True
    page._set_running(True)
    page._run_duration_seconds = 100
    page._run_started_at = time.monotonic() - 25
    worker = Mock()
    worker.is_alive.return_value = False
    monkeypatch.setattr(
        "gui.dialogs.performance_launcher_run.threading.Thread", lambda **kw: worker
    )
    page.stop_btn.click()
    assert worker.start.call_count == 1
    assert page._status_state == "stopping"
    assert page.progress_display.indicators.currentWidget() is page.progress_display.busy_ring
    assert not page.start_btn.isEnabled() and not page.stop_btn.isEnabled()
    assert not page._poll_timer.isActive()
    page.stop_btn.click()
    assert worker.start.call_count == 1
    page._runner.is_running.return_value = False
    report = tmp_path / "report.html"
    report.write_text("partial report", encoding="utf-8")
    page._runner.latest_report_file.return_value = str(report)
    page._runner.latest_result_dir.return_value = str(tmp_path)
    page._on_runner_finished()
    assert page._status_state == "cancelled"
    assert page.progress_bar.value() < 100
    assert page.result_btn.isEnabled()
    assert page.start_btn.isEnabled() and not page.stop_btn.isEnabled()
    assert page.progress_display.indicators.currentIndex() == 0


def test_failed_stop_keeps_live_progress_and_retry_action(page):
    page._runner_finished_handled = False
    page._runner.is_running.return_value = True
    page._set_running(True)
    page._run_duration_seconds = 100
    page._run_started_at = time.monotonic() - 25
    page._stopping = True
    page._on_runner_finished()
    page._update_progress()
    assert page._status_state == "warning"
    assert page.stop_btn.isEnabled()
    assert not page.start_btn.isEnabled()
    assert page.progress_display.indicators.currentWidget() is page.progress_bar
    assert "25%" in page.progress_display.detail_label.text()
    assert page._configuration_locked


def test_status_icon_qt_value_can_be_copied_and_released_after_rendering(page):
    """Qt 图标属性允许复制后分离；回收副本不能重复释放状态图标的引擎。"""
    page.show()
    for state in ("idle", "completed", "warning", "failed", "cancelled"):
        page._set_status(state, state)
        assert not page.progress_display.icon.grab().isNull()
        source = page.progress_display.icon.getIcon()
        copied = QIcon(source)
        copied.setIsMask(True)
        assert not copied.pixmap(24, 24).isNull()
        del copied, source
        gc.collect()
