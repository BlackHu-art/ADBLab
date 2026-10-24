"""文件列表不弹出重复内容提示，操作及错误提示仍然可用。"""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolTip
from qfluentwidgets import ToolTip

from gui.features.file_explorer import FileExplorerPage

pytestmark = pytest.mark.ui

LISTING = "\n".join([
    "drwxr-xr-x 2 shell shell 4096 Oct 24 10:20 Documents",
    "-rw-r--r-- 1 shell shell 2048 Oct 24 10:21 notes.txt",
    "lrwxrwxrwx 1 shell shell 4 Oct 24 10:22 shortcut -> Documents",
])


@pytest.fixture
def tooltip_page(qt_application, monkeypatch):
    def unexpected_start(_worker):
        pytest.fail("列表提示测试不应启动设备请求")

    monkeypatch.setattr("gui.workers.file_explorer.ADBWorker.start", unexpected_start)
    monkeypatch.setattr("gui.workers.file_explorer.TransferWorker.start", unexpected_start)
    page = FileExplorerPage(device_ip="synthetic-device")
    page.resize(1000, 650)
    page._on_ls_result(LISTING, False)
    page.show()
    qt_application.processEvents()
    try:
        yield page
    finally:
        page.close()
        qt_application.processEvents()


def test_file_list_items_have_no_hover_tip_and_keep_accessible_data(tooltip_page):
    page = tooltip_page
    expected = {"..": "Folder", "Documents": "Folder", "notes.txt": "TXT", "shortcut": "Link"}
    assert page.table.rowCount() == len(expected)
    for row in range(page.table.rowCount()):
        name = page._file_name_at(row)
        assert page._file_type_at(row) == expected[name]
        type_item = page.table.item(row, page.TYPE_COL)
        assert type_item.data(Qt.ItemDataRole.AccessibleTextRole)
        assert not type_item.icon().isNull()
        for column in range(page.table.columnCount()):
            item = page.table.item(row, column)
            assert not item.data(Qt.ItemDataRole.ToolTipRole), (name, column)


@pytest.mark.parametrize("column", [0, 1, 2, 3])
def test_file_list_help_event_does_not_show_a_tip(tooltip_page, qt_application, column):
    page = tooltip_page
    row = next(
        row for row in range(page.table.rowCount()) if page._file_name_at(row) == "Documents"
    )
    item = page.table.item(row, column)
    point = page.table.visualItemRect(item).center()
    viewport = page.table.viewport()
    assert viewport.rect().contains(point)
    event = QHelpEvent(QEvent.Type.ToolTip, point, viewport.mapToGlobal(point))
    qt_application.sendEvent(viewport, event)
    # Fluent 的真实 item 提示在 100ms 后显示，不能只检查原生 QToolTip。
    QTest.qWait(150)
    assert not QToolTip.isVisible()
    assert not any(tip.isVisible() for tip in page.findChildren(ToolTip))


def test_file_operation_and_directory_error_tips_are_retained(tooltip_page):
    page = tooltip_page
    assert page.up_btn.toolTip()
    assert page.root_cb.toolTip()
    assert page.preview_close_btn.toolTip()
    page._on_ls_result("synthetic directory permission failure", True)
    assert page.status_bar.toolTip() == "synthetic directory permission failure"
