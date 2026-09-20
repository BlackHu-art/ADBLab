"""文件搜索框只筛选当前缓存目录，搜索和清空不会发起设备任务。"""

import pytest
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtTest import QSignalSpy, QTest
from qfluentwidgets import SearchLineEdit

from gui.dialogs.file_explorer import FileExplorerPage
from gui.dialogs.file_explorer_list import FileExplorerList
from models.file_explorer_worker import ADBWorker

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("trigger", ["button", "enter"])
def test_file_search_actions_keep_parent_row_and_clear_without_device_io(
    qt_application, monkeypatch, trigger,
):
    """即时筛选、显式搜索和清空保留父目录项，不导航或启动 ADB/传输 worker。"""
    started = []
    for worker_type in ("ADBWorker", "TransferWorker"):
        monkeypatch.setattr(
            f"models.file_explorer_worker.{worker_type}.start",
            lambda worker: started.append(worker),
        )
    filtered = []
    original_filter = FileExplorerList._filter

    def filter_and_record(controller, text):
        filtered.append(text)
        return original_filter(controller, text)

    monkeypatch.setattr(FileExplorerList, "_filter", filter_and_record)
    page = FileExplorerPage(device_ip="search-demo")
    try:
        page._on_ls_result("\n".join([
            "drwxr-xr-x 2 shell shell 4096 Sep 05 Documents",
            "-rw-r--r-- 1 shell shell 2048 Sep 05 sample.apk",
            "-rw-r--r-- 1 shell shell 1024 Sep 05 notes.txt",
        ]), False)
        page.resize(1000, 800)
        page.show()
        qt_application.processEvents()
        search = page.search_field
        assert isinstance(search, SearchLineEdit)
        assert not isinstance(page.path_field, SearchLineEdit)
        initial_path = page.current_path

        def visible_names():
            return {
                page._file_name_at(row) for row in range(page.table.rowCount())
                if not page.table.isRowHidden(row)
            }

        search.setText("  APK ")
        assert visible_names() == {"..", "sample.apk"}
        with QSignalBlocker(search):
            search.setText(" notes ")
        assert visible_names() == {"..", "sample.apk"}
        searched = QSignalSpy(search.searchSignal)
        if trigger == "button":
            QTest.mouseClick(search.searchButton, Qt.MouseButton.LeftButton)
        else:
            search.setFocus()
            QTest.keyClick(search, Qt.Key.Key_Return)
        assert searched.count() == 1
        assert visible_names() == {"..", "notes.txt"}
        filtered.clear()
        QTest.mouseClick(search.clearButton, Qt.MouseButton.LeftButton)
        assert search.text() == ""
        assert visible_names() == {"..", "Documents", "sample.apk", "notes.txt"}
        assert filtered == [""]
        assert started == []
        assert page.current_path == initial_path
        assert page.history == [] and page.forward_stack == []
    finally:
        page.close()


@pytest.mark.parametrize("order", [Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder])
@pytest.mark.parametrize("new_names,visible", [
    (["zeta.keep", "aardvark.txt", "middle.keep", "delta.txt"], {"..", "zeta.keep", "middle.keep"}),
    (["new.keep", "other.txt"], {"..", "new.keep"}),
    ([], {".."}),
])
def test_directory_refresh_reapplies_latest_search_after_reordering_rows(
    qt_application, monkeypatch, order, new_names, visible,
):
    """刷新期间的新搜索词作用于新目录项，行数变化和排序不能复用旧行的隐藏状态。"""
    started = []
    monkeypatch.setattr(ADBWorker, "start", lambda worker: started.append(worker))
    page = FileExplorerPage(device_ip="search-demo")
    try:
        page._on_ls_result("\n".join(
            f"-rw-r--r-- 1 shell shell 1024 Sep 05 {name}"
            for name in ("alpha.keep", "beta.txt", "gamma.keep")
        ), False)
        page.table.sortByColumn(page.NAME_COL, order)
        page._refresh()
        assert len(started) == 1 and page._directory_loading
        page.search_field.setText("alpha")
        page.search_field.setText("  KEEP ")
        started[0].result_ready.emit("\n".join(
            f"-rw-r--r-- 1 shell shell 1024 Sep 05 {name}" for name in new_names
        ), False)
        qt_application.processEvents()
        assert not page._directory_loading
        assert page.search_field.text() == "  KEEP "
        assert [page._file_name_at(row) for row in range(page.table.rowCount())] == sorted(
            ["..", *new_names], reverse=order == Qt.SortOrder.DescendingOrder,
        )
        assert {
            page._file_name_at(row) for row in range(page.table.rowCount())
            if not page.table.isRowHidden(row)
        } == visible
        page.search_field.clear()
        assert all(not page.table.isRowHidden(row) for row in range(page.table.rowCount()))
        assert page.history == [] and page.forward_stack == []
        assert len(started) == 1
    finally:
        page.close()


@pytest.mark.parametrize("result_kind", ["failed", "stale"])
def test_rejected_directory_result_preserves_filtered_cached_rows(
    qt_application, monkeypatch, result_kind,
):
    """失败和过期结果不改变已经按最新搜索词筛选的缓存目录。"""
    started = []
    monkeypatch.setattr(ADBWorker, "start", lambda worker: started.append(worker))
    page = FileExplorerPage(device_ip="search-demo")
    try:
        page._on_ls_result("\n".join([
            "-rw-r--r-- 1 shell shell 1024 Sep 05 old.keep",
            "-rw-r--r-- 1 shell shell 1024 Sep 05 other.txt",
        ]), False)
        page._refresh()
        if result_kind == "stale":
            page._refresh()
        page.search_field.setText("keep")
        before = [
            (page._file_name_at(row), page.table.isRowHidden(row))
            for row in range(page.table.rowCount())
        ]
        started[0].result_ready.emit(
            "permission denied" if result_kind == "failed"
            else "-rw-r--r-- 1 shell shell 1024 Sep 05 stale.keep",
            result_kind == "failed",
        )
        qt_application.processEvents()
        assert [
            (page._file_name_at(row), page.table.isRowHidden(row))
            for row in range(page.table.rowCount())
        ] == before
        assert page.search_field.text() == "keep"
        assert page._directory_loading is (result_kind == "stale")
    finally:
        page.close()
