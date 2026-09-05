"""验证固定会话的全部新操作服从当前设备选择，已启动资源仍可收尾。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QPushButton, QWidget
from qfluentwidgets import FluentIcon

from gui.dialogs.app_manager import AppManagerPage
from gui.dialogs.file_explorer import FileExplorerPage
from gui.dialogs.fluent_dialog import FluentDialog
from gui.pages.workspace_features import WorkspaceFeatureHost
from models.app_manager_worker import AppManagerWorker
from models.file_explorer_worker import ADBWorker, TransferWorker


@pytest.fixture
def submitted_workers(monkeypatch):
    submitted = []
    for worker_class in (ADBWorker, TransferWorker, AppManagerWorker):
        monkeypatch.setattr(worker_class, "start", lambda worker: submitted.append(worker))
    monkeypatch.setattr("core.exec.CommandRunner.run", Mock(side_effect=AssertionError("real ADB")))
    monkeypatch.setattr(
        "core.exec.ProcessRunner.start", Mock(side_effect=AssertionError("real process"))
    )
    return submitted


def _host_page(page_class):
    host = WorkspaceFeatureHost("audit", "Audit", QWidget())
    host.register_feature("feature", "Feature", FluentIcon.FOLDER,
                          lambda key: page_class(device_ip=key.device_id))
    host.set_device_context(["device-a"], ["device-a", "device-b"])
    host.open_feature("feature")
    page = host.stack.currentWidget()
    if isinstance(page, FileExplorerPage):
        page._on_ls_result("", False, request_id=page._refresh_request_id,
                           requested_path=page.current_path)
        page._show_text_preview("note.txt", "cached content", page.current_path + "/note.txt")
    else:
        page._populate([("Demo", "com.example.demo", "Enabled", "User")],
                       request_id=page._active_load_request)
        page._on_load_worker_finished(page._active_load_request)
        page.selected_packages.add("com.example.demo")
        page._sync_selection_views()
        page.open_details("com.example.demo")
        page.details_page._op([], ["android.permission.CAMERA"], [])
        page.details_page.requested_list.item(0).setCheckState(Qt.CheckState.Checked)
    return host, page


@pytest.mark.parametrize("selected,connected", [
    ([], ["device-a", "device-b"]),
    (["device-b"], ["device-a", "device-b"]),
    (["device-a"], ["device-b"]),
])
@pytest.mark.parametrize("page_class", [FileExplorerPage, AppManagerPage])
def test_fixed_page_rejects_new_operations_without_selected_online_target(
    page_class, selected, connected, submitted_workers
):
    host, page = _host_page(page_class)
    assert submitted_workers
    host.set_device_context(selected, connected)
    submitted_workers.clear()
    assert page.device_ip == "device-a"
    assert not page.refresh_btn.isEnabled()
    if isinstance(page, FileExplorerPage):
        assert not page.preview_save_device_btn.isEnabled()
        assert page.preview_save_as_btn.isEnabled()
        page.preview_save_device_btn.click()
        page.path_field.setText("/sdcard/other")
        page.path_field.returnPressed.emit()
        page._save_preview_to_device()
        page._view_file("note.txt")
        page._delete_item("note.txt")
        page._install_apk("demo.apk")
        page._exec_script("demo.sh")
        page._show_props("note.txt", False)
        assert page._run_adb("shell", "id") is None
        assert page._run_transfer("pull", "/sdcard/note.txt", "unused") is None
        assert page.preview_text_edit.toPlainText() == "cached content"
    else:
        page._launch("com.example.demo")
        page._modify_one("clear", "com.example.demo")
        page._modify_selected("disable")
        page._load_apps()
        page._load_visible_details()
        page._view_mode = True
        page._icons_controller._visible_packages = lambda: ["com.example.demo"]
        page._icons_controller._load_visible()
        page.details_page._mp("grant")
        page.details_page._rp()
        assert page.model.rowCount() == 1
        assert not page.details_page.grant_btn.isEnabled()
    assert submitted_workers == []


@pytest.mark.parametrize("page_class", [FileExplorerPage, AppManagerPage])
def test_fixed_page_uses_only_its_selected_device_in_multi_selection(page_class, submitted_workers):
    host, page = _host_page(page_class)
    host.set_device_context(["device-a", "device-b"], ["device-a", "device-b"])
    submitted_workers.clear()
    if isinstance(page, FileExplorerPage):
        page._save_preview_to_device()
    else:
        page._launch("com.example.demo")
    assert len(submitted_workers) == 1
    assert submitted_workers[0].device_ip == "device-a"


@pytest.mark.parametrize("page_class,action,args,dialog_path,result", [
    (FileExplorerPage, "_push_file", (),
     "gui.dialogs.file_explorer_ops.QFileDialog.getOpenFileNames",
     (["demo.txt"], "")),
    (FileExplorerPage, "_mkdir", (), "gui.dialogs.file_explorer_ops.FluentInputDialog.getText",
     ("new-folder", True)),
    (AppManagerPage, "_restore_apps", (),
     "gui.dialogs.app_manager_batch.QFileDialog.getOpenFileNames",
     (["demo.zip"], "")),
    (AppManagerPage, "_backup_selected", (),
     "gui.dialogs.app_manager_batch.QFileDialog.getExistingDirectory", "unused"),
    (AppManagerPage, "_backup_one", ("com.example.demo",),
     "gui.dialogs.app_manager_batch.QFileDialog.getExistingDirectory", "unused"),
])
def test_modal_submission_rechecks_device_after_dialog_returns(
    page_class, action, args, dialog_path, result, submitted_workers, monkeypatch
):
    host, page = _host_page(page_class)
    submitted_workers.clear()

    def choose(*_args, **_kwargs):
        host.set_device_context([], ["device-a", "device-b"])
        return result

    monkeypatch.setattr(dialog_path, choose)
    if isinstance(page, AppManagerPage):
        monkeypatch.setattr(page, "_global_save_dir", lambda: "unused")
    getattr(page, action)(*args)
    assert submitted_workers == []


def test_root_pull_stops_next_transfer_but_cleans_prepared_file(submitted_workers):
    host, page = _host_page(FileExplorerPage)
    host.set_device_context([], ["device-a", "device-b"])
    submitted_workers.clear()
    page._finish_root_pull("", False, "note.txt", "/data/local/tmp/note.txt", "unused")
    assert len(submitted_workers) == 1
    worker = submitted_workers[0]
    assert isinstance(worker, ADBWorker)
    assert worker.device_ip == "device-a"
    assert "rm " in worker.args[1]


def test_started_transfer_finishes_on_original_device_without_refresh_after_deselection(
    submitted_workers
):
    host, page = _host_page(FileExplorerPage)
    submitted_workers.clear()
    page._finish_root_pull("", False, "note.txt", "/data/local/tmp/note.txt", "unused")
    transfer = submitted_workers[-1]
    assert isinstance(transfer, TransferWorker)
    callback = page._worker_ui_bindings[transfer][-1][1]
    host.set_device_context(["device-b"], ["device-a", "device-b"])
    submitted_workers.clear()
    callback("", False, "unused")
    assert len(submitted_workers) == 1
    cleanup = submitted_workers[0]
    assert cleanup.device_ip == "device-a"
    assert "rm " in cleanup.args[1]
    assert not transfer._aborted.is_set()


def test_finished_app_batch_does_not_schedule_unselected_device_refresh(submitted_workers):
    host, page = _host_page(AppManagerPage)
    submitted_workers.clear()
    page._modify_selected("disable")
    worker = submitted_workers[-1]
    host.set_device_context(["device-b"], ["device-a", "device-b"])
    assert not worker._aborted.is_set()
    submitted_workers.clear()
    page._on_batch_worker_finished(worker)
    assert page._batch_workers == set()
    assert submitted_workers == []


def test_embedded_pages_wait_for_host_selection_before_initial_load(submitted_workers):
    for page_class in (FileExplorerPage, AppManagerPage):
        page = page_class(device_ip="device-a")
        page.prepare_for_workspace()
        page.activate()
    assert submitted_workers == []


@pytest.mark.parametrize("page_class", [FileExplorerPage, AppManagerPage])
def test_open_context_menu_rechecks_before_action_trigger(
    page_class, submitted_workers, monkeypatch
):
    host, page = _host_page(page_class)
    menu = page._create_context_menu()
    monkeypatch.setattr(page, "_create_context_menu", lambda: menu)
    if isinstance(page, FileExplorerPage):
        page.table.setRowCount(1)
        page._set_file_row(0, "note.txt", "TXT", "1", "-")
        monkeypatch.setattr(page.table, "indexAt", lambda _pos: page.table.model().index(0, 0))
        action_text = "Delete"
    else:
        monkeypatch.setattr(page.tree, "indexAt", lambda _pos: page.proxy.index(0, 0))
        action_text = "卸载"

    def execute(_pos):
        action = next(action for action in menu.actions() if action.text() == action_text)
        host.set_device_context(["device-b"], ["device-a", "device-b"])
        action.trigger()

    monkeypatch.setattr(menu, "exec", execute)
    submitted_workers.clear()
    page._context_menu(QPoint())
    assert submitted_workers == []


@pytest.mark.parametrize("page_class", [FileExplorerPage, AppManagerPage])
def test_double_click_does_not_start_unselected_session_and_reselection_restores_actions(
    page_class, submitted_workers
):
    host, page = _host_page(page_class)
    host.set_device_context([], ["device-a", "device-b"])
    submitted_workers.clear()
    if isinstance(page, FileExplorerPage):
        page.table.setRowCount(1)
        page._set_file_row(0, "folder", "Folder", "-", "-")
        page.table.cellDoubleClicked.emit(0, 0)
    else:
        page.close_details()
        page._icon_double_click(page.icon_list.item(0))
        assert not page._details_open
    assert submitted_workers == []
    host.set_device_context(["device-a"], ["device-a", "device-b"])
    assert page.refresh_btn.isEnabled()
    page.refresh_btn.click()
    assert len(submitted_workers) == 1
    assert submitted_workers[0].device_ip == "device-a"


def test_permission_dialog_tracks_access_change_and_rejects_stale_apply(
    submitted_workers, monkeypatch
):
    host, page = _host_page(FileExplorerPage)
    submitted_workers.clear()

    def execute(dialog):
        worker = submitted_workers[-1]
        callback = page._worker_ui_bindings[worker][0][1]
        callback("644", False)
        apply = next(button for button in dialog.findChildren(QPushButton)
                     if button.text() == "Apply")
        assert apply.isEnabled()
        host.set_device_context([], ["device-a", "device-b"])
        assert not apply.isEnabled()
        submitted_workers.clear()
        apply.clicked.emit()
        assert submitted_workers == []
        return 0

    monkeypatch.setattr(FluentDialog, "exec", execute)
    page._show_chmod("note.txt", False)


@pytest.mark.parametrize("page_class", [FileExplorerPage, AppManagerPage])
def test_page_badge_distinguishes_selection_from_connection_across_theme_refresh(
    page_class, submitted_workers
):
    page = page_class(device_ip="device-a")
    assert page.status_badge.text() == "就绪"
    page.prepare_for_workspace()
    assert page.status_badge.text() == "未选为操作目标"
    for connected, selected, expected in (
        (True, True, "就绪"),
        (True, False, "未选为操作目标"),
        (False, False, "离线"),
        (True, False, "未选为操作目标"),
        (True, True, "就绪"),
        (False, True, "离线"),
    ):
        page.set_device_selected(selected)
        page.set_device_connected(connected)
        assert page.status_badge.text() == expected
        page._apply_theme()
        assert page.status_badge.text() == expected
    assert submitted_workers == []
