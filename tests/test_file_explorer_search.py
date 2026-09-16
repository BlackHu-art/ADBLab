"""文件搜索框只筛选当前缓存目录，搜索和清空不会发起设备任务。"""

import pytest
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtTest import QSignalSpy, QTest
from qfluentwidgets import SearchLineEdit

from gui.dialogs.file_explorer import FileExplorerPage
from gui.dialogs.file_explorer_list import FileExplorerList

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
