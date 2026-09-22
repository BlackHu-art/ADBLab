"""文件数值排序和符号链接的异步类型分派。"""

import pytest
from PySide6.QtCore import Qt

from gui.dialogs.file_explorer import FileExplorerPage
from models.file_explorer_worker import ADBWorker

pytestmark = pytest.mark.ui


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
