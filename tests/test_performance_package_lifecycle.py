"""以受控原生线程验证包名查询完成、join 与页面释放的顺序。"""

import threading

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from shiboken6 import isValid

from adblab.application.supervision import StopDisposition, TaskSupervisor
from gui.dialogs import performance_launcher
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def _start_controlled_query(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class PackageWorker(performance_launcher.CurrentPackageWorker):
        def run(self):
            entered.set()
            release.wait(3)

    monkeypatch.setattr(performance_launcher, "CurrentPackageWorker", PackageWorker)
    page = performance_launcher.PerformancePage(device_ip="device-test")
    page.fetch_current_package()
    worker = page._package_worker
    assert entered.wait(1)
    return page, worker, release


def test_dispose_after_queued_package_finished_never_reuses_deleted_worker(
    monkeypatch, qt_application,
):
    page, worker, release = _start_controlled_query(monkeypatch)
    disposed = []
    page.dispose_ready.connect(disposed.append)
    try:
        assert not page.request_dispose()
        release.set()
        assert worker.wait(1000)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        page._poll_dispose_ready()
        page._poll_dispose_ready()
        assert page._dispose_ready_state
        assert len(disposed) == 1
        assert not page._disposing_package_workers
    finally:
        release.set()
        if isValid(worker):
            worker.wait(1000)
        if isValid(page):
            page._dispose_poll_timer.stop()
            page.deleteLater()


def test_dispose_waits_for_native_package_thread_join(monkeypatch, qt_application):
    page, worker, release = _start_controlled_query(monkeypatch)
    finishing = threading.Event()
    allow_join = threading.Event()

    def hold_native_finish():
        finishing.set()
        allow_join.wait(3)

    worker.finished.connect(hold_native_finish, Qt.ConnectionType.DirectConnection)
    try:
        assert not page.request_dispose()
        release.set()
        assert finishing.wait(1)
        assert not worker.isRunning()
        assert not worker.wait(0)
        supervisor = TaskSupervisor()
        task_ids = page.register_shutdown_tasks(
            supervisor, owner_id="application", task_prefix="performance",
        )
        assert task_ids == ("performance-package-worker",)
        results = supervisor.stop_all(deadline=0)
        assert results[0].disposition == StopDisposition.TIMED_OUT
        assert supervisor.active_count == 1
        page._poll_dispose_ready()
        assert not page._dispose_ready_state
        assert isValid(worker)
    finally:
        allow_join.set()
        release.set()
        if isValid(worker):
            worker.wait(1000)
        if isValid(page):
            wait_until(qt_application, lambda: page.request_dispose())
            page.deleteLater()


def test_package_completion_keeps_query_busy_until_native_join(monkeypatch, qt_application):
    page, worker, release = _start_controlled_query(monkeypatch)
    finishing = threading.Event()
    allow_join = threading.Event()

    def hold_native_finish():
        finishing.set()
        allow_join.wait(3)

    worker.finished.connect(hold_native_finish, Qt.ConnectionType.DirectConnection)
    try:
        release.set()
        assert finishing.wait(1)
        assert not worker.isRunning()
        assert not worker.wait(0)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
        assert page._package_worker is worker
        assert not page.get_package_btn.isEnabled()
        page.fetch_current_package()
        assert page._package_worker is worker
        allow_join.set()
        assert worker.wait(1000)
        wait_until(qt_application, lambda: page._package_worker is None)
        assert page.get_package_btn.isEnabled()
        assert page.request_dispose()
    finally:
        allow_join.set()
        release.set()
        if isValid(worker):
            worker.wait(1000)
        if isValid(page):
            page._dispose_poll_timer.stop()
            page.deleteLater()
