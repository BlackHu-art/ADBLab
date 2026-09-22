"""权限写入批次的去重、串行、取消和完成刷新契约。"""

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QSignalSpy

from gui.dialogs.app_manager_details import AppDetailsPage

pytestmark = pytest.mark.ui


class PermissionWorker(QObject):
    app_details_loaded = Signal(dict)
    permissions_loaded = Signal(list, list, list)
    operation_done = Signal(str)
    operation_feedback = Signal(str, str)
    log_message = Signal(str)
    finished = Signal()

    def __init__(self, device, operation, **kwargs):
        super().__init__()
        self.device = device
        self.operation = operation
        self.kwargs = kwargs
        self.running = False
        self.aborted = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def abort(self):
        self.aborted = True

    def finish(self, success=True):
        if success and not self.aborted and self.operation == "modify_permission":
            self.operation_done.emit("permissions_changed")
        elif not success:
            self.operation_feedback.emit("error", "Permission denied")
        self.running = False
        self.finished.emit()


@pytest.fixture
def permission_page(qt_application, monkeypatch):
    workers = []

    def create_worker(*args, **kwargs):
        worker = PermissionWorker(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr("gui.dialogs.app_manager_details.AppManagerWorker", create_worker)
    monkeypatch.setattr("gui.dialogs.app_manager_details.report_feedback", lambda *a, **kw: None)
    page = AppDetailsPage(device_ip="permission-test", package_name="com.example.app")
    page._op([], ["android.permission.CAMERA", "android.permission.RECORD_AUDIO"], [
        ("android.permission.CAMERA", False),
    ])
    page._ta(page.requested_list)
    page._ta(page.runtime_list)
    yield page, workers
    page.request_dispose("test")
    for worker in workers:
        if worker.running:
            worker.finish()
    qt_application.processEvents()
    page.close()


@pytest.mark.parametrize("first_success", [True, False])
def test_permissions_are_deduplicated_serial_and_refresh_once(
    permission_page, qt_application, first_success,
):
    page, workers = permission_page
    page._mp("grant")
    page._mp("revoke")
    page.retry_load()
    assert len(workers) == 1
    assert workers[0].kwargs == {
        "package_name": "com.example.app", "permission": "android.permission.CAMERA",
        "action": "grant",
    }
    assert not page.grant_btn.isEnabled() and not page.revoke_btn.isEnabled()
    assert not page.retry_btn.isEnabled()
    workers[0].finish(first_success)
    qt_application.processEvents()
    assert [worker.operation for worker in workers] == ["modify_permission"] * 2
    assert workers[1].kwargs["permission"] == "android.permission.RECORD_AUDIO"
    assert workers[1].kwargs["action"] == "grant"
    workers[1].finish()
    qt_application.processEvents()
    assert [worker.operation for worker in workers] == [
        "modify_permission", "modify_permission", "permissions",
    ]
    assert page.grant_btn.isEnabled() and page.revoke_btn.isEnabled()


@pytest.mark.parametrize("cancel", ["deselect", "disconnect", "close", "switch_package"])
def test_permission_batch_drops_pending_work_at_lifecycle_boundary(
    permission_page, qt_application, cancel,
):
    page, workers = permission_page
    ready = QSignalSpy(page.dispose_ready)
    page._mp("grant")
    assert len(workers) == 1
    if cancel == "deselect":
        page.set_device_selected(False)
        page.set_device_selected(True)
    elif cancel == "disconnect":
        page.set_device_connected(False)
        page.set_device_connected(True)
    elif cancel == "switch_package":
        page.activate({"package_name": "com.example.other"})
        assert workers[0].aborted
    else:
        assert page.request_dispose("close") is False
        assert workers[0].aborted
        assert ready.count() == 0
    workers[0].finish()
    qt_application.processEvents()
    assert [worker.operation for worker in workers].count("modify_permission") == 1
    assert not any(worker.operation == "permissions" for worker in workers)
    if cancel == "close":
        assert ready.count() == 1
    elif cancel == "switch_package":
        assert workers[-1].kwargs["package_name"] == "com.example.other"
    else:
        assert page.grant_btn.isEnabled()


def test_permission_start_failure_does_not_leave_batch_busy(
    permission_page, qt_application, monkeypatch,
):
    page, workers = permission_page
    original = PermissionWorker.start
    errors = []
    monkeypatch.setattr(
        "gui.dialogs.app_manager_details.report_feedback",
        lambda _page, _feature, _title, message, **_kw: errors.append(message),
    )

    def start(worker):
        if worker.kwargs.get("permission") == "android.permission.CAMERA":
            raise RuntimeError("thread unavailable")
        original(worker)

    monkeypatch.setattr(PermissionWorker, "start", start)
    page._mp("grant")
    assert len(workers) == 2 and workers[1].isRunning()
    assert workers[0] not in page._workers
    assert errors == ["无法启动应用任务，请重试。"]
    workers[1].finish()
    qt_application.processEvents()
    assert workers[-1].operation == "permissions"
    assert page.grant_btn.isEnabled()
