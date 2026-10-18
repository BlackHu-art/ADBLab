"""应用页面必须以成功快照绑定 Android 用户，排队操作不得跟随用户切换。"""

import pytest
from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QIcon

from gui.dialogs.app_manager import AppManagerPage
from gui.dialogs.app_manager_details import AppDetailsPage
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui
PACKAGE = "org.example.shared"
APPS = [("Shared", PACKAGE, "Enabled", "User")]


class UserWorker(QObject):
    user_context_loaded = Signal(int)
    apps_loaded = Signal(list)
    app_details_loaded = Signal(dict)
    app_detail_batch = Signal(str, str, str, str)
    app_metadata_loaded = Signal(dict)
    app_icon_loaded = Signal(str, bytes, str)
    permissions_loaded = Signal(list, list, list)
    log_message = Signal(str)
    backup_progress = Signal(str, str)
    operation_done = Signal(str)
    operation_feedback = Signal(str, str)
    finished = Signal()

    def __init__(self, device, operation, **kwargs):
        super().__init__()
        self.device_ip = device
        self.operation = operation
        self.kwargs = kwargs
        self.user_id = kwargs.get("user_id")
        self.running = False
        self.aborted = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def wait(self, _timeout=0):
        return not self.running

    def abort(self):
        self.aborted = True

    def finish(self):
        self.running = False
        self.finished.emit()


@pytest.fixture
def user_page(qt_application, monkeypatch):
    workers = []

    def create(*args, **kwargs):
        worker = UserWorker(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr("gui.dialogs.app_manager.AppManagerWorker", create)
    monkeypatch.setattr("gui.dialogs.app_manager_details.AppManagerWorker", create)
    page = AppManagerPage(device_ip="user-context-test")
    yield page, workers
    page.request_dispose()
    for worker in page._all_workers():
        if worker.isRunning():
            worker.finish()
    qt_application.processEvents()
    page.close()


def snapshot(page, workers, app, user_id, apps=APPS):
    assert page._load_apps()
    worker = workers[-1]
    assert worker.operation == "load_apps"
    assert worker.kwargs.get("user_id") is None
    worker.user_id = user_id
    worker.user_context_loaded.emit(user_id)
    worker.apps_loaded.emit(apps)
    worker.finish()
    wait_until(app, lambda: not page._load_in_progress)
    return worker


def test_unknown_or_incomplete_user_snapshot_cannot_submit_writes(user_page, qt_application):
    page, workers = user_page
    page._populate(APPS)
    page._launch(PACKAGE)
    assert workers == []
    assert page._load_apps()
    load = workers[-1]
    load.user_id = 10
    load.user_context_loaded.emit(10)
    qt_application.processEvents()
    page._launch(PACKAGE)
    assert workers == [load]
    assert page._android_user_id is None
    load.apps_loaded.emit(APPS)
    load.finish()
    wait_until(qt_application, lambda: not page._load_in_progress)
    page._launch(PACKAGE)
    assert workers[-1].operation == "launch_app"
    assert workers[-1].kwargs["user_id"] == 10


def test_failed_refresh_keeps_old_display_but_revokes_writes(user_page, qt_application):
    page, workers = user_page
    snapshot(page, workers, qt_application, 10)
    assert page._load_apps()
    failed = workers[-1]
    failed.user_context_loaded.emit(11)
    failed.finish()
    wait_until(qt_application, lambda: not page._load_in_progress)
    assert page._android_user_id == 10
    assert page.model.item(0, 2).text() == PACKAGE
    page._modify_one("disable", PACKAGE)
    assert workers[-1] is failed


def test_new_user_clears_selection_caches_and_old_detail_generation(user_page, qt_application):
    page, workers = user_page
    snapshot(page, workers, qt_application, 10)
    page.selected_packages.add(PACKAGE)
    page._detail_cache[PACKAGE] = ("Old user label", "1", "today")
    page._icons_controller.cache[PACKAGE] = QIcon()
    page.open_details(PACKAGE)
    old_detail = workers[-1]
    assert old_detail.kwargs["user_id"] == 10
    snapshot(page, workers, qt_application, 11)
    old_detail.app_details_loaded.emit({"App Name": "wrong old result"})
    old_detail.permissions_loaded.emit([], [], [("old.permission", True)])
    qt_application.processEvents()
    assert page._android_user_id == 11
    assert not page.selected_packages
    assert not page._detail_cache
    assert not page._icons_controller.cache
    assert not page.details_page.detail_text.toPlainText()
    assert page.details_page.runtime_list.count() == 0
    assert old_detail.aborted


@pytest.mark.parametrize("action", ["launch", "disable", "clear", "backup", "restore", "batch"])
def test_every_business_entry_freezes_snapshot_user(
    user_page, qt_application, monkeypatch, tmp_path, action,
):
    page, workers = user_page
    snapshot(page, workers, qt_application, 10)
    page.selected_packages.add(PACKAGE)
    monkeypatch.setattr(page, "_global_save_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "gui.dialogs.app_manager_batch.QFileDialog.getExistingDirectory", lambda *a: str(tmp_path),
    )
    monkeypatch.setattr(
        "gui.dialogs.app_manager_batch.QFileDialog.getOpenFileNames",
        lambda *a: ([str(tmp_path / "backup.zip")], ""),
    )
    operations = {
        "launch": lambda: page._launch(PACKAGE),
        "disable": lambda: page._modify_one("disable", PACKAGE),
        "clear": lambda: page._modify_one("clear", PACKAGE),
        "backup": lambda: page._backup_one(PACKAGE),
        "restore": page._restore_apps,
        "batch": lambda: page._modify_selected("disable"),
    }
    operations[action]()
    assert workers[-1].operation != "load_apps"
    assert workers[-1].kwargs["user_id"] == 10


def test_details_adopts_user_only_after_snapshot_and_binds_permission_queue(
    user_page, qt_application,
):
    page, workers = user_page
    detail = page.details_page
    detail.activate(PACKAGE)
    load = workers[-1]
    load.user_id = 10
    load.user_context_loaded.emit(10)
    qt_application.processEvents()
    assert not detail.grant_btn.isEnabled()
    load.app_details_loaded.emit({"Package": PACKAGE})
    load.permissions_loaded.emit([], ["permission.ONE", "permission.TWO"], [])
    load.finish()
    wait_until(qt_application, lambda: detail.load_state == "ready")
    for index in range(detail.requested_list.count()):
        detail.requested_list.item(index).setCheckState(Qt.CheckState.Checked)
    detail._mp("grant")
    first = workers[-1]
    assert first.operation == "modify_permission"
    assert first.kwargs["user_id"] == 10
    detail.set_android_user(11)
    first.finish()
    qt_application.processEvents()
    assert workers[-1] is first
    assert not detail.requested_list.count()


def test_detail_refresh_does_not_flash_error_while_loading(user_page, qt_application):
    page, workers = user_page
    detail = page.details_page
    detail.set_android_user(10)
    detail.activate(PACKAGE)
    load = workers[-1]
    load.user_context_loaded.emit(10)
    qt_application.processEvents()
    assert detail.load_state == "loading"

    detail.set_android_user(10, ready=False)
    qt_application.processEvents()

    assert detail.load_state != "error"
    assert not detail.retry_btn.isVisible()


def test_detail_context_change_reloads_same_package(user_page, qt_application):
    page, workers = user_page
    detail: AppDetailsPage = page.details_page
    detail.set_android_user(10)
    detail.activate(PACKAGE)
    first = workers[-1]
    first.user_context_loaded.emit(10)
    first.app_details_loaded.emit({"Package": PACKAGE})
    first.permissions_loaded.emit([], [], [])
    first.finish()
    wait_until(qt_application, lambda: detail.load_state == "ready")
    detail.set_android_user(11)
    detail.activate(PACKAGE)
    assert workers[-1] is not first
    assert workers[-1].kwargs["user_id"] == 11


@pytest.mark.parametrize("action", ["backup", "backup_selected", "restore"])
def test_file_dialog_return_cannot_retarget_original_user(
    user_page, qt_application, monkeypatch, tmp_path, action,
):
    page, workers = user_page
    snapshot(page, workers, qt_application, 10)
    page.selected_packages.add(PACKAGE)
    monkeypatch.setattr(page, "_global_save_dir", lambda: str(tmp_path))

    def select_directory(*_args):
        snapshot(page, workers, qt_application, 11)
        return str(tmp_path)

    def select_files(*_args):
        select_directory()
        return [str(tmp_path / "backup.zip")], ""

    monkeypatch.setattr(
        "gui.dialogs.app_manager_batch.QFileDialog.getExistingDirectory", select_directory,
    )
    monkeypatch.setattr(
        "gui.dialogs.app_manager_batch.QFileDialog.getOpenFileNames", select_files,
    )
    if action == "backup":
        page._backup_one(PACKAGE)
    elif action == "backup_selected":
        page._backup_selected()
    else:
        page._restore_apps()
    assert page._android_user_id == 11
    assert all(worker.operation == "load_apps" for worker in workers)


def test_user_switch_drops_old_metadata_and_cancels_remaining_batch(user_page, qt_application):
    page, workers = user_page
    snapshot(page, workers, qt_application, 10)
    page._active = True
    page._load_visible_details()
    old_metadata = workers[-1]
    assert old_metadata.operation == "load_metadata_batch"
    assert old_metadata.kwargs["user_id"] == 10
    page.selected_packages.update([PACKAGE, "org.example.other"])
    page._modify_selected("disable")
    pending = workers[-1]
    assert not pending.isRunning()
    snapshot(page, workers, qt_application, 11)
    old_metadata.app_metadata_loaded.emit({
        "package": PACKAGE, "label": "wrong old user", "version": "1", "installed": "today",
        "fingerprint": "a" * 64,
    })
    qt_application.processEvents()
    assert pending.aborted
    assert not pending.running
    assert not page._detail_cache
    assert page.model.item(0, 1).text() == "Shared"


def test_icons_use_the_loaded_user_even_without_metadata_fingerprint(
    user_page, qt_application, monkeypatch,
):
    page, workers = user_page
    snapshot(page, workers, qt_application, 10)
    page._active = True
    page._loaded_detail_packages.add(PACKAGE)
    controller = page._icons_controller
    monkeypatch.setattr(controller, "_visible_packages", lambda: [PACKAGE])
    controller._load_visible()
    assert workers[-1].operation == "load_icon_batch"
    assert workers[-1].kwargs["user_id"] == 10


@pytest.mark.parametrize("view", ["table", "icons"])
def test_open_context_menu_cannot_submit_to_replacement_user(
    user_page, qt_application, monkeypatch, view,
):
    page, workers = user_page
    snapshot(page, workers, qt_application, 10)
    menu = page._create_context_menu()
    monkeypatch.setattr(page, "_create_context_menu", lambda: menu)
    monkeypatch.setattr(page.tree, "indexAt", lambda _pos: page.proxy.index(0, 1))
    monkeypatch.setattr(
        page.icon_list, "itemAt", lambda _pos: page.icon_list.topLevelItem(0),
    )

    def choose(*_args):
        action = next(action for action in menu.actions() if action.text() == "清除数据")
        assert action.isEnabled()
        snapshot(page, workers, qt_application, 11)
        action.trigger()

    monkeypatch.setattr(menu, "exec", choose)
    try:
        if view == "table":
            page._context_menu(QPoint())
        else:
            page._icon_context_menu(QPoint())
        assert all(worker.operation == "load_apps" for worker in workers)
    finally:
        menu.close()


@pytest.mark.parametrize("list_user", [10, 11, None])
def test_first_package_activation_keeps_detail_read_but_waits_for_list_write_admission(
    user_page, qt_application, list_user,
):
    page, workers = user_page
    page.activate({"package_name": PACKAGE})
    assert [worker.operation for worker in workers] == ["load_apps", "app_snapshot"]
    load, detail = workers
    detail.user_context_loaded.emit(10)
    detail.app_details_loaded.emit({"Package": PACKAGE})
    detail.permissions_loaded.emit([], ["permission.ONE"], [])
    detail.finish()
    wait_until(qt_application, lambda: page.details_page.load_state == "ready")
    assert not page.details_page.grant_btn.isEnabled()
    if list_user is not None:
        load.user_context_loaded.emit(list_user)
        load.apps_loaded.emit(APPS)
    load.finish()
    wait_until(qt_application, lambda: not page._load_in_progress)
    if list_user == 10:
        assert page._details_open
        assert page.details_page.grant_btn.isEnabled()
        assert page.details_page.requested_list.count() == 1
    elif list_user is None:
        assert page._details_open
        assert not page.details_page.grant_btn.isEnabled()
        assert page.details_page.requested_list.count() == 1
    else:
        assert not page._details_open
        assert not page.details_page.grant_btn.isEnabled()
        assert page.details_page.requested_list.count() == 0


def test_list_finishing_before_first_detail_restarts_cancelled_read_for_bound_user(
    user_page, qt_application,
):
    page, workers = user_page
    page.activate({"package_name": PACKAGE})
    load, old_detail = workers
    load.user_context_loaded.emit(10)
    load.apps_loaded.emit(APPS)
    load.finish()
    wait_until(qt_application, lambda: not page._load_in_progress)
    old_detail.finish()
    qt_application.processEvents()
    assert workers[-1] is not old_detail
    assert workers[-1].operation == "app_snapshot"
    assert workers[-1].kwargs["user_id"] == 10


def test_failed_list_refresh_leaves_cancelled_detail_retryable_without_reopening_writes(
    user_page, qt_application,
):
    page, workers = user_page
    snapshot(page, workers, qt_application, 10)
    page.open_details(PACKAGE)
    detail = page.details_page
    cancelled_detail = workers[-1]
    assert detail.load_state == "loading"
    assert page._load_apps()
    failed_list = workers[-1]
    assert cancelled_detail.aborted
    cancelled_detail.finish()
    failed_list.finish()
    wait_until(qt_application, lambda: not page._load_in_progress)
    assert page.load_state == "error"
    assert detail.load_state == "error"
    assert not detail.retry_btn.isHidden()
    assert detail.retry_btn.isEnabled()
    assert not detail.grant_btn.isEnabled()
    assert workers[-1] is failed_list

    detail.retry_btn.click()
    retry = workers[-1]
    assert retry is not failed_list
    assert retry.operation == "app_snapshot"
    assert retry.kwargs["user_id"] == 10
    retry.user_context_loaded.emit(10)
    retry.app_details_loaded.emit({"Package": PACKAGE})
    retry.permissions_loaded.emit([], ["permission.ONE"], [])
    retry.finish()
    wait_until(qt_application, lambda: detail.load_state == "ready")
    assert not detail.grant_btn.isEnabled()
    assert not detail.revoke_btn.isEnabled()


def test_same_user_list_refresh_resumes_cancelled_retry_but_keeps_completed_details(
    user_page, qt_application,
):
    page, workers = user_page
    snapshot(page, workers, qt_application, 10)
    page.open_details(PACKAGE)
    detail = page.details_page
    initial = workers[-1]
    initial.user_context_loaded.emit(10)
    initial.app_details_loaded.emit({"Package": PACKAGE})
    initial.permissions_loaded.emit([], ["permission.ONE"], [])
    initial.finish()
    wait_until(qt_application, lambda: detail.load_state == "ready")

    detail.retry_load()
    cancelled_retry = workers[-1]
    assert detail.load_state == "loading"
    completed_list = snapshot(page, workers, qt_application, 10)
    assert cancelled_retry.aborted
    cancelled_retry.finish()
    wait_until(qt_application, lambda: workers[-1] is not completed_list)
    resumed = workers[-1]
    assert resumed.operation == "app_snapshot"
    assert resumed.kwargs["user_id"] == 10
    resumed.user_context_loaded.emit(10)
    resumed.app_details_loaded.emit({"Package": PACKAGE})
    resumed.permissions_loaded.emit([], ["permission.TWO"], [])
    resumed.finish()
    wait_until(qt_application, lambda: detail.load_state == "ready")
    assert detail.requested_list.item(0).text() == "permission.TWO"
    assert detail.grant_btn.isEnabled()

    next_list = snapshot(page, workers, qt_application, 10)
    assert workers[-1] is next_list
    assert detail.load_state == "ready"
    assert detail.requested_list.item(0).text() == "permission.TWO"
    assert detail.grant_btn.isEnabled()
