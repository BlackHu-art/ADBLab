"""应用管理表头只允许数据列排序，复选框列保持当前列表顺序。"""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from gui.dialogs.app_manager import AppManagerPage

pytestmark = pytest.mark.ui


@pytest.fixture
def manager_page(qt_application):
    # 页面未激活且没有设备目标，填充与表头交互不会启动设备 worker。
    page = AppManagerPage()
    page._populate([
        ("Zulu", "com.example.b", "Mystery", "Vendor"),
        ("Alpha", "com.example.c", "Disabled", "System"),
        ("Beta", "com.example.a", "Enabled", "User"),
    ])
    for row, version in enumerate(("3", "1", "2")):
        page.model.item(row, 3).setText(version)
    page.resize(1200, 800)
    page.show()
    QTest.mouseClick(page.view_toggle, Qt.MouseButton.LeftButton)
    qt_application.processEvents()
    assert page.tree.isVisible()
    yield page
    page.close()


def _visible_packages(page):
    return [page.proxy.index(row, 2).data() for row in range(page.proxy.rowCount())]


def _header_center(header, column):
    return QPoint(
        header.sectionViewportPosition(column) + header.sectionSize(column) // 2,
        header.height() // 2,
    )


def test_default_application_sort_uses_name_column(manager_page):
    """首屏按应用名升序显示，空的复选框表头不能成为默认排序依据。"""
    page = manager_page
    assert page.tree.header().sortIndicatorSection() == 1
    assert page.tree.header().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
    assert _visible_packages(page) == ["com.example.c", "com.example.a", "com.example.b"]


@pytest.mark.parametrize("column", [1, 2, 4, 5])
@pytest.mark.parametrize("order", [Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder])
@pytest.mark.parametrize("gesture", ["click", "double_click"])
def test_checkbox_header_preserves_sort_and_selection(
    manager_page, qt_application, column, order, gesture,
):
    """点击或双击复选框表头不改变已有排序、显示顺序或批量操作选择。"""
    page = manager_page
    page.model.item(0, 0).setCheckState(Qt.CheckState.Checked)
    page.tree.sortByColumn(column, order)
    qt_application.processEvents()
    header = page.tree.header()
    before_packages = _visible_packages(page)
    position = _header_center(header, 0)
    QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=position)
    if gesture == "double_click":
        QTest.mouseDClick(header.viewport(), Qt.MouseButton.LeftButton, pos=position)
        QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton, pos=position)
    qt_application.processEvents()
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (column, order)
    assert _visible_packages(page) == before_packages
    assert page.selected_packages == {"com.example.b"}
    checked_packages = [
        page.proxy.index(row, 2).data() for row in range(page.proxy.rowCount())
        if page.proxy.index(row, 0).data(Qt.ItemDataRole.CheckStateRole)
        == Qt.CheckState.Checked.value
    ]
    assert checked_packages == ["com.example.b"]


@pytest.mark.parametrize("column,ascending", [
    (1, ["com.example.c", "com.example.a", "com.example.b"]),
    (2, ["com.example.a", "com.example.b", "com.example.c"]),
    (3, ["com.example.c", "com.example.a", "com.example.b"]),
    (4, ["com.example.a", "com.example.c", "com.example.b"]),
    (5, ["com.example.a", "com.example.c", "com.example.b"]),
])
def test_data_header_clicks_toggle_application_sort(
    manager_page, qt_application, column, ascending,
):
    """首列交互限制不影响名称、包名、版本、状态和类型的正常表头排序。"""
    page = manager_page
    page.tree.sortByColumn(column, Qt.SortOrder.AscendingOrder)
    header = page.tree.header()
    position = _header_center(header, column)
    for order, packages in (
        (Qt.SortOrder.DescendingOrder, list(reversed(ascending))),
        (Qt.SortOrder.AscendingOrder, ascending),
    ):
        QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=position)
        qt_application.processEvents()
        assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (column, order)
        assert _visible_packages(page) == packages
