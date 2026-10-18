"""大目录在事件循环分批提交，未完成的行不能成为文件操作目标。"""

import pytest
from PySide6.QtCore import QItemSelectionModel, QObject, Qt, QTimer, Signal

from gui.dialogs.file_explorer import FileExplorerPage
from models.file_explorer_worker import ADBWorker, DirectoryListWorker, TransferWorker
from services.file_explorer import DirectoryListing, FileEntry

pytestmark = pytest.mark.ui


def test_selecting_device_on_active_unloaded_page_starts_first_browse(
    qt_application, monkeypatch,
):
    page = FileExplorerPage(device_ip="demo-a")
    page._active = True
    page._device_selected = False
    page._device_connected = True
    page._loaded_once = False
    calls = []
    monkeypatch.setattr(page, "_refresh", lambda *args, **kwargs: calls.append((args, kwargs)))
    try:
        page.set_device_selected(True)
        assert page._loaded_once is True
        assert calls
    finally:
        page.request_dispose("test")
        page.close()
        qt_application.processEvents()


@pytest.fixture
def page(qt_application, monkeypatch):
    monkeypatch.setattr(DirectoryListWorker, "start", lambda worker: None)
    for worker_type in (ADBWorker, TransferWorker):
        monkeypatch.setattr(worker_type, "start", lambda worker: pytest.fail("device task"))
    widget = FileExplorerPage(device_ip="population-test")
    widget._loaded_once = True
    try:
        yield widget
    finally:
        widget.request_dispose("test")
        widget.close()
        qt_application.processEvents()


def listing(count, prefix="file"):
    return DirectoryListing(tuple(
        FileEntry(f"{prefix}-{index:05}.txt", "TXT", "1 KB", "2026-10-15 12:00:00", 1024, False)
        for index in range(count)
    ), {})


def respond(page, result, *, path=None):
    page._refresh(requested_path=path, navigation_action="push" if path else "refresh")
    request_id, requested_path = page._active_refresh
    page._on_ls_result(result, False, request_id=request_id, requested_path=requested_path)


def drain(app, predicate):
    for _ in range(2000):
        if predicate():
            return
        app.processEvents()
    pytest.fail("directory work did not settle")


def select(page, *names):
    for row in range(page.table.rowCount()):
        if page._file_name_at(row) in names:
            index = page.table.model().index(row, page.SIZE_COL)
            page.table.selectionModel().select(
                index,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
            page.table.selectionModel().setCurrentIndex(
                index, QItemSelectionModel.SelectionFlag.NoUpdate,
            )


def selected(page):
    return {
        page._file_name_at(index.row()) for index in page.table.selectionModel().selectedIndexes()
    }


def visible(page):
    return {
        page._file_name_at(row) for row in range(page.table.rowCount())
        if not page.table.isRowHidden(row)
    }


def test_large_population_yields_and_commits_latest_filter_and_selection(page, qt_application):
    page._on_ls_result(listing(3), False)
    select(page, "file-00001.txt", "file-00002.txt")
    page.table.sortByColumn(page.NAME_COL, Qt.SortOrder.DescendingOrder)
    heartbeats = []
    QTimer.singleShot(0, lambda: heartbeats.append(page._directory_loading))

    respond(page, listing(2048))

    assert page._directory_loading
    assert not page.table.isEnabled()
    page.search_field.setText("00001")
    page.search_field.setText("00002")
    drain(qt_application, lambda: not page._directory_loading)
    assert heartbeats == [True]
    assert visible(page) == {"..", "file-00002.txt"}
    assert selected(page) == {"file-00001.txt", "file-00002.txt"}
    assert page._file_name_at(page.table.currentRow()) == "file-00002.txt"
    assert page.table.currentColumn() == page.SIZE_COL
    assert page.table.rowCount() == 2049
    assert page.table.isEnabled()


def test_new_navigation_discards_partial_rows_and_only_commits_latest_path(page, qt_application):
    original = page.current_path
    page._on_ls_result(listing(2, "old"), False)
    respond(page, listing(2048, "stale"), path="/stale")
    assert page._directory_loading
    assert page.current_path == original and page.history == []

    respond(page, listing(2, "new"), path="/latest")
    drain(qt_application, lambda: not page._directory_loading)
    for _ in range(4):
        qt_application.processEvents()

    assert page.current_path == "/latest"
    assert page.history == [original]
    assert visible(page) == {"..", "new-00000.txt", "new-00001.txt"}
    assert selected(page) == set()


def test_failed_replacement_restores_large_committed_snapshot_in_batches(page, qt_application):
    respond(page, listing(2048, "old"))
    drain(qt_application, lambda: not page._directory_loading)
    select(page, "old-00007.txt")
    respond(page, listing(2048, "partial"), path="/partial")
    assert page._directory_loading
    page._refresh(requested_path="/denied", navigation_action="push")
    request_id, path = page._active_refresh

    page._on_ls_result("denied", True, request_id=request_id, requested_path=path)

    assert page._directory_loading
    assert not page._can_use_directory_snapshot()
    drain(qt_application, lambda: not page._directory_loading)
    assert page.current_path == "/storage/emulated/0"
    assert page.history == []
    assert page.table.rowCount() == 2049
    assert selected(page) == {"old-00007.txt"}
    assert "denied" in page.status_bar.toolTip()
    assert all(name == ".." or name.startswith("old-") for name in visible(page))


@pytest.mark.parametrize("change", ["offline", "deselect", "close"])
def test_context_loss_cancels_partial_rows_without_exposing_them(page, qt_application, change):
    page._on_ls_result(listing(2, "old"), False)
    select(page, "old-00001.txt")
    respond(page, listing(2048, "partial"), path="/partial")
    assert page._directory_loading
    if change == "offline":
        page.set_device_connected(False)
    elif change == "deselect":
        page.set_device_selected(False)
    else:
        page.request_dispose("test")
    for _ in range(50):
        qt_application.processEvents()
    assert page.current_path == "/storage/emulated/0"
    assert page.history == [] and page._active_refresh is None
    assert not page._can_use_directory_snapshot()
    if change != "close":
        assert visible(page) == {"..", "old-00000.txt", "old-00001.txt"}
        assert selected(page) == {"old-00001.txt"}
        assert page.table.isEnabled()


def test_inactive_page_pauses_population_and_resumes_same_request(page, qt_application):
    respond(page, listing(2048))
    assert page._directory_loading
    page.deactivate()
    populated = sum(page.table.item(row, page.NAME_COL) is not None for row in range(2049))
    for _ in range(50):
        qt_application.processEvents()
    assert sum(page.table.item(row, page.NAME_COL) is not None for row in range(2049)) == populated
    assert page._directory_loading
    page.activate()
    drain(qt_application, lambda: not page._directory_loading)
    assert page.table.rowCount() == 2049


def test_large_filter_yields_and_latest_query_wins_after_sort(page, qt_application):
    respond(page, listing(2048))
    drain(qt_application, lambda: not page._directory_loading)
    select(page, "file-00007.txt")
    page.search_field.setText("00001")
    assert len(visible(page)) > 2
    page._header_clicked(page.NAME_COL)
    page.search_field.setText("00007")
    drain(qt_application, lambda: visible(page) == {"..", "file-00007.txt"})
    assert selected(page) == {"file-00007.txt"}


def test_partial_rows_cannot_be_used_for_device_actions_or_clipboard(page, monkeypatch):
    page.clipboard = ["/previous/kept.txt"]
    respond(page, listing(2048))
    assert page._directory_loading
    select(page, "file-00001.txt")
    assert not page._can_use_directory_snapshot()
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.QFileDialog.getExistingDirectory",
        lambda *args: pytest.fail("partial snapshot opened download picker"),
    )
    page._copy_items(True)
    page._delete_selected()
    page._pull_selected()
    page._on_double_click(1, page.NAME_COL)
    assert page.clipboard == ["/previous/kept.txt"]
    assert not page._transfers.is_running()


def test_population_does_not_cancel_previously_accepted_transfer_queue(page):
    starts = []

    class Worker(QObject):
        finished = Signal()

        def __init__(self, name):
            super().__init__()
            self.name = name
            self.running = False

        def start(self):
            starts.append(self.name)
            self.running = True

        def isRunning(self):
            return self.running

        def abort(self):
            self.running = False

        def wait(self, timeout):
            return not self.running

    first, second = Worker("first"), Worker("second")
    page._transfers.enqueue(first)
    page._transfers.enqueue(second)
    assert starts == ["first"]
    respond(page, listing(2048))
    assert page._directory_loading

    first.running = False
    page._transfers.worker_finished(first)

    assert starts == ["first", "second"]
    second.running = False
    page._transfers.worker_finished(second)


@pytest.mark.parametrize("action,args", [
    ("_view_file", ("file-00001.txt",)),
    ("_pull_file", ("file-00001.txt",)),
    ("_push_file", ()),
    ("_mkdir", ()),
    ("_touch", ()),
    ("_rename_item", ("file-00001.txt",)),
    ("_show_chmod", ("file-00001.txt", False)),
    ("_install_apk", ("file-00001.apk",)),
    ("_exec_script", ("file-00001.sh",)),
    ("_show_props", ("file-00001.txt", False)),
])
def test_partial_snapshot_rejects_new_directory_entry_points(page, monkeypatch, action, args):
    respond(page, listing(2048))
    assert not page._can_use_directory_snapshot()
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.FluentInputDialog.getText",
        lambda *args, **kwargs: pytest.fail("partial snapshot opened input dialog"),
    )
    for method in ("getOpenFileNames", "getSaveFileName"):
        monkeypatch.setattr(
            f"gui.dialogs.file_explorer_ops.QFileDialog.{method}",
            lambda *args, **kwargs: pytest.fail("partial snapshot opened file picker"),
        )
    monkeypatch.setattr(
        page, "_run_adb", lambda *args, **kwargs: pytest.fail("partial snapshot started command"),
    )

    getattr(page, action)(*args)

    assert page._preview_request_id == 0
    assert not page._transfers.is_running()


def test_latest_filter_survives_device_loss_without_reloading(page, qt_application):
    respond(page, listing(2048))
    drain(qt_application, lambda: not page._directory_loading)
    page.search_field.setText("02047")
    assert len(visible(page)) > 2

    page.set_device_connected(False)

    drain(qt_application, lambda: visible(page) == {"..", "file-02047.txt"})
    assert page.table.isEnabled()


def test_same_directory_replacement_keeps_original_selection_across_partial_build(
    page, qt_application,
):
    page._on_ls_result(listing(3), False)
    select(page, "file-00001.txt")
    respond(page, listing(2048))
    assert page._directory_loading
    respond(page, listing(4))

    drain(qt_application, lambda: not page._directory_loading)

    assert selected(page) == {"file-00001.txt"}
    assert page._file_name_at(page.table.currentRow()) == "file-00001.txt"
    assert page.table.rowCount() == 5


def test_failed_refresh_finishes_interrupted_empty_query_on_cached_snapshot(page, qt_application):
    respond(page, listing(2048))
    drain(qt_application, lambda: not page._directory_loading)
    select(page, "file-00007.txt")
    page.search_field.setText("00007")
    drain(qt_application, lambda: visible(page) == {"..", "file-00007.txt"})
    page.search_field.clear()
    assert len(visible(page)) < 2049
    page._refresh()
    request_id, path = page._active_refresh

    page._on_ls_result("denied", True, request_id=request_id, requested_path=path)

    drain(qt_application, lambda: len(visible(page)) == 2049)
    assert page.search_field.text() == ""
    assert selected(page) == {"file-00007.txt"}
    assert "denied" in page.status_bar.toolTip()
