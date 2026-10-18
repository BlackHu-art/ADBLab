"""文件数值排序和符号链接的异步类型分派。"""

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt

from gui.dialogs.file_explorer import FileExplorerPage
from gui.dialogs.file_explorer_list import FileTypeItem
from models.file_explorer_worker import ADBWorker, DirectoryListWorker, TransferWorker
from services.file_explorer import DirectoryListing, FileEntry

pytestmark = pytest.mark.ui


@pytest.fixture
def refresh_page(qt_application, monkeypatch):
    started = []
    monkeypatch.setattr(DirectoryListWorker, "start", lambda worker: started.append(worker))
    for worker_type in (ADBWorker, TransferWorker):
        monkeypatch.setattr(
            worker_type, "start", lambda worker: pytest.fail("unexpected device task"),
        )
    page = FileExplorerPage(device_ip="selection-test")
    page.resize(1000, 700)
    page.show()
    qt_application.processEvents()
    try:
        yield page, started
    finally:
        page.request_dispose("test")
        for worker in tuple(page._workers):
            page._prune_worker(worker)
        page.close()


def _listing(*names):
    return DirectoryListing(tuple(
        FileEntry(name, "TXT", "1 KB", "2026-10-15 12:00:00", 1024, False)
        for name in names
    ), {})


def _select_names(page, names, *, current, column=None):
    table = page.table
    table.clearSelection()
    for row in range(table.rowCount()):
        name = page._file_name_at(row)
        if name in names:
            table.selectionModel().select(
                table.model().index(row, page.NAME_COL),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
        if name == current:
            table.selectionModel().setCurrentIndex(
                table.model().index(row, page.NAME_COL if column is None else column),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )


def _selected_names(page):
    return {page._file_name_at(index.row()) for index in page.table.selectedIndexes()}


@pytest.mark.parametrize("order", [Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder])
def test_refresh_preserves_selected_names_and_current_cell_after_sorting(
    refresh_page, qt_application, order,
):
    page, started = refresh_page
    page._on_ls_result(_listing("alpha.txt", "bravo.txt", "charlie.txt"), False)
    page.table.sortByColumn(page.NAME_COL, order)
    _select_names(page, {"bravo.txt", "charlie.txt"}, current="bravo.txt", column=page.SIZE_COL)

    page._refresh()
    assert not page.table.isEnabled()
    started[-1].result_ready.emit(
        _listing("charlie.txt", "aardvark.txt", "alpha.txt", "bravo.txt"), False,
    )
    qt_application.processEvents()

    assert page.table.isEnabled()
    assert _selected_names(page) == {"bravo.txt", "charlie.txt"}
    assert page._file_name_at(page.table.currentRow()) == "bravo.txt"
    assert page.table.currentColumn() == page.SIZE_COL
    assert [page._file_name_at(row) for row in range(page.table.rowCount())] == sorted(
        ["..", "charlie.txt", "aardvark.txt", "alpha.txt", "bravo.txt"],
        reverse=order == Qt.SortOrder.DescendingOrder,
    )


@pytest.mark.parametrize("remaining,selected", [
    (("alpha.txt", "bravo.txt", "delta.txt"), {"bravo.txt"}),
    (("alpha.txt", "delta.txt", "echo.txt"), set()),
    ((), set()),
])
def test_refresh_drops_missing_selection_and_current_item(
    refresh_page, qt_application, remaining, selected,
):
    page, started = refresh_page
    page._on_ls_result(_listing("alpha.txt", "bravo.txt", "charlie.txt"), False)
    _select_names(page, {"bravo.txt", "charlie.txt"}, current="charlie.txt")

    page._refresh()
    started[-1].result_ready.emit(_listing(*remaining), False)
    qt_application.processEvents()

    assert _selected_names(page) == selected
    assert page.table.currentItem() is None


def test_refresh_keeps_unselected_current_item_without_selecting_it(refresh_page, qt_application):
    page, started = refresh_page
    page._on_ls_result(_listing("alpha.txt", "bravo.txt", "charlie.txt"), False)
    _select_names(page, {"bravo.txt"}, current="alpha.txt")

    page._refresh()
    started[-1].result_ready.emit(_listing("aardvark.txt", "alpha.txt", "bravo.txt"), False)
    qt_application.processEvents()

    assert _selected_names(page) == {"bravo.txt"}
    assert page._file_name_at(page.table.currentRow()) == "alpha.txt"


@pytest.mark.parametrize("failed", [False, True])
def test_navigation_clears_selection_only_when_new_directory_is_committed(
    refresh_page, qt_application, failed,
):
    page, started = refresh_page
    listing = _listing("alpha.txt", "bravo.txt", "charlie.txt")
    page._on_ls_result(listing, False)
    _select_names(page, {"bravo.txt"}, current="bravo.txt")

    page._navigate("/other")
    started[-1].result_ready.emit("permission denied" if failed else listing, failed)
    qt_application.processEvents()

    assert page.current_path == ("/storage/emulated/0" if failed else "/other")
    assert _selected_names(page) == ({"bravo.txt"} if failed else set())
    if failed:
        assert page._file_name_at(page.table.currentRow()) == "bravo.txt"
    else:
        assert page.table.currentItem() is None


def test_stale_navigation_result_does_not_clear_newer_refresh_selection(
    refresh_page, qt_application,
):
    page, started = refresh_page
    page._on_ls_result(_listing("alpha.txt", "bravo.txt", "charlie.txt"), False)
    _select_names(page, {"bravo.txt"}, current="bravo.txt")
    page._navigate("/other")
    page._refresh()
    started[-1].result_ready.emit(_listing("aardvark.txt", "alpha.txt", "bravo.txt"), False)
    started[0].result_ready.emit(_listing("unrelated.txt"), False)
    qt_application.processEvents()

    assert page.current_path == "/storage/emulated/0"
    assert _selected_names(page) == {"bravo.txt"}
    assert page._file_name_at(page.table.currentRow()) == "bravo.txt"
    assert page.history == []
    assert page.table.isEnabled()


@pytest.mark.parametrize("action", ["delete", "copy", "pull"])
def test_actions_after_refresh_use_original_selected_files(
    refresh_page, qt_application, monkeypatch, tmp_path, action,
):
    page, started = refresh_page
    page._on_ls_result(_listing("alpha.txt", "bravo.txt", "charlie.txt"), False)
    _select_names(page, {"bravo.txt", "charlie.txt"}, current="bravo.txt")
    page._refresh()
    started[-1].result_ready.emit(
        _listing("aardvark.txt", "alpha.txt", "bravo.txt", "charlie.txt"), False,
    )
    qt_application.processEvents()
    queued = []
    monkeypatch.setattr(
        page._ops_controller, "_enqueue_batch",
        lambda kind, items, origin: queued.append((kind, items, origin)),
    )
    monkeypatch.setattr(page._ops_controller, "_global_save_dir", lambda: "")
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.QFileDialog.getExistingDirectory",
        lambda *args: str(tmp_path),
    )

    if action == "copy":
        page._copy_items(True)
        assert set(page.clipboard) == {
            "/storage/emulated/0/bravo.txt", "/storage/emulated/0/charlie.txt",
        }
        assert queued == []
    else:
        if action == "delete":
            page._delete_selected()
        else:
            page._pull_selected()
        assert len(queued) == 1
        kind, items, origin = queued[0]
        assert kind == action
        assert origin == "/storage/emulated/0"
        assert set(items) == {
            ("bravo.txt", "/storage/emulated/0/bravo.txt",
             str(tmp_path / "bravo.txt") if action == "pull" else ""),
            ("charlie.txt", "/storage/emulated/0/charlie.txt",
             str(tmp_path / "charlie.txt") if action == "pull" else ""),
        }


@pytest.mark.parametrize("order,files", [
    (Qt.SortOrder.AscendingOrder, ["empty.txt", "small.txt", "medium.txt", "big.txt"]),
    (Qt.SortOrder.DescendingOrder, ["big.txt", "medium.txt", "small.txt", "empty.txt"]),
])
def test_size_sort_uses_bytes_and_keeps_parent_and_directory_first(qt_application, order, files):
    page = FileExplorerPage(device_ip="sort-test")
    try:
        listing = "drwxr-xr-x 2 shell shell 4096 Sep 05 Folder\n" + "\n".join(
            f"-rw-r--r-- 1 shell shell {size} Sep 05 {name}"
            for name, size in [("small.txt", 900), ("big.txt", 1048576),
                               ("medium.txt", 2048), ("empty.txt", 0)]
        )
        page._on_ls_result(listing, False)
        page.table.sortByColumn(page.SIZE_COL, order)
        assert [page._file_name_at(i) for i in range(page.table.rowCount())] == [
            "..", "Folder", *files,
        ]
    finally:
        page.close()


def test_type_sort_uses_raw_type_not_localized_display():
    assert FileTypeItem("文件", "File") < FileTypeItem("文件夹", "Folder")
    assert FileTypeItem("文件夹", "Folder") < FileTypeItem("链接", "Link")


@pytest.mark.parametrize("kind", ["directory", "file", "missing", "error"])
def test_symlink_open_queries_type_once_then_dispatches(qt_application, monkeypatch, kind):
    started, navigated, opened = [], [], []
    monkeypatch.setattr(ADBWorker, "start", lambda worker: started.append(worker))
    page = FileExplorerPage(device_ip="link-test")
    try:
        page._on_ls_result(
            "lrwxrwxrwx 1 shell shell 12 Sep 05 alias.txt -> ../target.txt", False,
        )
        monkeypatch.setattr(page._list_controller, "_navigate", navigated.append)
        monkeypatch.setattr(page, "_view_or_pull", opened.append)
        row = next(i for i in range(page.table.rowCount()) if page._file_name_at(i) == "alias.txt")
        page._on_double_click(row, 0)
        page._on_double_click(row, 0)
        assert len(started) == 1
        assert navigated == [] and opened == []
        assert "/storage/emulated/0/alias.txt" in started[0].args[1]
        started[0].result_ready.emit(kind, kind == "error")
        qt_application.processEvents()
        assert navigated == (["/storage/emulated/0/alias.txt/"] if kind == "directory" else [])
        assert opened == (["alias.txt"] if kind == "file" else [])
        if kind in {"missing", "error"}:
            assert "alias.txt" in page.status_bar.text()
    finally:
        page.close()


@pytest.mark.parametrize("change", [
    "directory", "deselect", "reselect", "reconnect", "close", "root",
])
def test_symlink_result_does_not_open_after_context_changes(qt_application, monkeypatch, change):
    started, opened = [], []
    monkeypatch.setattr(ADBWorker, "start", lambda worker: started.append(worker))
    page = FileExplorerPage(device_ip="link-test")
    try:
        page._on_ls_result("lrwxrwxrwx 1 shell shell 12 Sep 05 alias.txt -> target.txt", False)
        monkeypatch.setattr(page, "_view_or_pull", opened.append)
        row = next(i for i in range(page.table.rowCount()) if page._file_name_at(i) == "alias.txt")
        page._on_double_click(row, 0)
        assert len(started) == 1
        if change == "directory":
            page._refresh(requested_path="/different", navigation_action="push")
        elif change == "deselect":
            page.set_device_selected(False)
        elif change == "reselect":
            page.set_device_selected(False)
            page.set_device_selected(True)
        elif change == "reconnect":
            page.set_device_connected(False)
            page.set_device_connected(True)
        elif change == "root":
            page.root_cb.setChecked(True)
        else:
            page.request_dispose("test")
        started[0].result_ready.emit("file", False)
        qt_application.processEvents()
        assert opened == []
    finally:
        page.close()


def test_directory_link_parent_moves_out_of_followed_path(qt_application, monkeypatch):
    page = FileExplorerPage(device_ip="link-test")
    try:
        page.current_path = "/storage/emulated/0/alias/"
        navigated = []
        monkeypatch.setattr(page._list_controller, "_navigate", navigated.append)
        page._go_parent()
        assert navigated == ["/storage/emulated/0"]
    finally:
        page.close()


def test_opening_another_link_rejects_previous_type_result(qt_application, monkeypatch):
    started, opened = [], []
    monkeypatch.setattr(ADBWorker, "start", lambda worker: started.append(worker))
    page = FileExplorerPage(device_ip="link-test")
    try:
        page._on_ls_result("\n".join(
            f"lrwxrwxrwx 1 shell shell 12 Sep 05 {name} -> target.txt"
            for name in ["a.txt", "b.txt"]
        ), False)
        monkeypatch.setattr(page, "_view_or_pull", opened.append)
        for name in ["a.txt", "b.txt"]:
            row = next(i for i in range(page.table.rowCount()) if page._file_name_at(i) == name)
            page._on_double_click(row, 0)
        started[0].result_ready.emit("file", False)
        started[1].result_ready.emit("file", False)
        qt_application.processEvents()
        assert opened == ["b.txt"]
        assert started[0]._aborted.is_set()
    finally:
        page.close()
