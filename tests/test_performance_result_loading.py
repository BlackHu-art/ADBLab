"""性能结果发现、图表解析和关闭的真实 Qt 生命周期回归。"""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QTimer

from gui.dialogs.performance_launcher import PerformancePage
from services.mobileperf_runner import PerformanceArtifacts
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def test_completed_run_discovers_artifacts_off_gui_and_unlocks_before_slow_io(
    monkeypatch, qt_application,
):
    entered, release = threading.Event(), threading.Event()

    def discover():
        entered.set()
        assert release.wait(3)
        return PerformanceArtifacts()

    page = PerformancePage("test-device", "com.example.app")
    monkeypatch.setattr(
        page._runner, "freeze_result_query", lambda: SimpleNamespace(discover=discover),
    )
    monkeypatch.setattr(page._runner, "latest_result_dir", Mock(return_value=""))
    monkeypatch.setattr(page._runner, "latest_report_file", Mock(return_value=""))
    page._runner_finished_handled = False
    page._set_running(True)
    try:
        page._mark_runner_finished()
        assert entered.wait(1)
        assert not page._configuration_locked
        assert page.start_btn.isEnabled()
        assert page.status_label.text() == "Idle"
        heartbeat = threading.Event()
        QTimer.singleShot(0, heartbeat.set)
        wait_until(qt_application, heartbeat.is_set)
        assert not release.is_set()
        page._runner.latest_result_dir.assert_not_called()
    finally:
        release.set()
        page.request_dispose()
        wait_until(qt_application, lambda: page._dispose_ready_state)
        page.close()


def test_close_retains_finished_qthread_until_join_barrier(monkeypatch, qt_application):
    page = PerformancePage("test-device", "com.example.app")
    loader = page._result_loader
    entered, release = threading.Event(), threading.Event()
    joined = threading.Event()

    def discover():
        entered.set()
        assert release.wait(3)
        return PerformanceArtifacts()

    loader.submit(SimpleNamespace(discover=discover), present_result=False)
    worker = loader._workers[0]
    original_wait = worker.wait
    monkeypatch.setattr(worker, "wait", lambda timeout: joined.is_set() and original_wait(timeout))
    try:
        assert entered.wait(1)
        assert not page.request_dispose()
        release.set()
        wait_until(qt_application, lambda: not worker.isRunning())
        loader._poll()
        assert loader.is_running()
        assert not page._dispose_ready_state
        assert worker in loader._workers
        joined.set()
        wait_until(qt_application, lambda: page._dispose_ready_state)
        assert not loader.is_running()
    finally:
        release.set()
        joined.set()
        page.request_dispose()
        wait_until(qt_application, lambda: page._dispose_ready_state)
        page.close()


def test_old_generation_archives_own_run_and_chart_failure_keeps_business_success(
    monkeypatch, qt_application,
):
    from gui.dialogs import performance_result_tasks as module
    from services.mobileperf_runner import MobilePerfRunConfig
    from tests.test_performance_library import _Library

    page = PerformancePage("test-device", "com.example.app")
    page.set_run_library(_Library())
    controller = page._library_controller
    controller.begin(MobilePerfRunConfig(package="com.example.old"))
    previous = controller._active
    entered, release = threading.Event(), threading.Event()

    def discover():
        entered.set()
        assert release.wait(3)
        return PerformanceArtifacts("old-results", "old-report.xlsx")

    loader = page._result_loader
    loader.submit(SimpleNamespace(discover=discover), active=previous, exit_code=0)
    assert entered.wait(1)
    loader.invalidate()
    controller.begin(MobilePerfRunConfig(package="com.example.new"))
    current = controller._active
    monkeypatch.setattr(module, "load_result_metrics", Mock(side_effect=OSError("bad csv")))
    loader.submit(SimpleNamespace(discover=lambda: PerformanceArtifacts("new", "new.xlsx")),
                  active=current, exit_code=0)
    try:
        release.set()
        wait_until(qt_application, lambda: not loader.is_running())
        records = controller._library.records
        assert len(records) == 2
        assert {record.state for record in records} == {"succeeded"}
        assert {record.package_name for record in records} == {
            "com.example.old", "com.example.new",
        }
        assert page._last_result_root == "new"
        assert page.chart_status.text()
        assert not page.chart_view.has_data()
        assert module.load_result_metrics.call_count == 1
    finally:
        release.set()
        page.request_dispose()
        wait_until(qt_application, lambda: page._dispose_ready_state)
        page.close()


def test_result_query_does_not_claim_outputs_created_after_frozen_completion(tmp_path):
    import os

    from services.mobileperf_runner import PerformanceResultQuery

    old = tmp_path / "old"
    old.mkdir()
    report = old / "summary_old.xlsx"
    report.write_bytes(b"report")
    os.utime(report, ns=(100, 100))
    os.utime(old, ns=(100, 100))
    query = PerformanceResultQuery(str(tmp_path), (), (), finished_at_ns=200)
    new = tmp_path / "new"
    new.mkdir()
    (new / "summary_new.xlsx").write_bytes(b"new")
    result = query.discover()
    assert result.result_dir == str(old)
    assert result.report_file == str(report)
    # 新运行在同名目录新增文件，父目录 mtime 不能遮蔽旧运行仍有效的报告。
    (old / "new.csv").write_bytes(b"new")
    assert query.discover().report_file == str(report)


def test_finished_thread_is_retained_until_queued_artifacts_are_delivered(qt_application):
    page = PerformancePage("test-device", "com.example.app")
    loader = page._result_loader
    loader.submit(SimpleNamespace(discover=lambda: PerformanceArtifacts()), present_result=False)
    worker = loader._workers[0]
    assert worker.wait(1000)
    assert not worker.artifacts_delivered
    loader._poll()
    assert worker in loader._workers
    assert not page.request_dispose()
    wait_until(qt_application, lambda: page._dispose_ready_state)
    assert not loader.is_running()
    page.close()


@pytest.mark.parametrize("queued", [False, True])
def test_result_thread_start_failure_archives_error_and_continues_queue(
    queued, monkeypatch, qt_application,
):
    from gui.dialogs.performance_result_tasks import PerformanceResultWorker
    from services.mobileperf_runner import MobilePerfRunConfig
    from tests.test_performance_library import _Library

    page = PerformancePage("test-device", "com.example.app")
    page.set_run_library(_Library())
    loader = page._result_loader
    library = page._library_controller
    discovery = Mock(return_value=PerformanceArtifacts("unexpected", "unexpected.xlsx"))
    real_start = PerformanceResultWorker.start
    failed = []

    def start(worker):
        if worker.query.discover is discovery:
            failed.append(worker)
            raise RuntimeError("thread start failed")
        real_start(worker)

    monkeypatch.setattr(PerformanceResultWorker, "start", start)
    try:
        if queued:
            loader.submit(SimpleNamespace(discover=lambda: PerformanceArtifacts()),
                          present_result=False)
            assert loader._workers[0].wait(1000)
        library.begin(MobilePerfRunConfig(package="com.example.failed"))
        loader.submit(SimpleNamespace(discover=discovery), active=library._active, exit_code=0)
        library.begin(MobilePerfRunConfig(package="com.example.next"))
        loader.submit(SimpleNamespace(discover=lambda: PerformanceArtifacts("next", "next.xlsx")),
                      active=library._active, exit_code=0)
        wait_until(qt_application, lambda: not loader.is_running())
        discovery.assert_not_called()
        assert len(failed) == 1
        assert [(record.package_name, record.state) for record in library._library.records] == [
            ("com.example.failed", "failed"), ("com.example.next", "succeeded"),
        ]
        assert loader.wait(0)
        assert page.request_dispose()
    finally:
        # 红测阶段未启动项没有终态信号，显式释放测试拥有的空闲对象。
        for worker in tuple(loader._workers):
            worker.abort()
            assert worker.wait(1000)
            worker.deleteLater()
        loader._workers.clear()
        page.request_dispose()
        page.close()
