"""应用列表默认铺满视口，手工列宽与末列补齐面板宽度共同生效。"""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHeaderView, QTreeWidgetItem

from gui.dialogs.app_manager import AppManagerPage
from gui.dialogs.app_manager_rows import AppManagerIconView, AppManagerRowDelegate
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def icon_view(qt_application):
    view = AppManagerIconView()
    view.setColumnCount(4)
    view.setHeaderLabels(["图标", "应用名称", "包名", "状态"])
    view.setFont(QFont("Arial", 12))
    view.setItemDelegate(AppManagerRowDelegate(view))
    view.setRootIsDecorated(False)
    view.setIndentation(0)
    view.setUniformRowHeights(True)
    view.setHorizontalScrollMode(view.ScrollMode.ScrollPerPixel)
    header = view.header()
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(48)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for column, width in enumerate((64, 220, 320, 110)):
        view.setColumnWidth(column, width)
    view.enable_auto_column_fill()
    yield view
    view.close()


def widths(view):
    return [view.columnWidth(column) for column in range(4)]


@pytest.mark.parametrize("app_count", [0, 30])
def test_default_columns_fill_viewport_and_follow_resize(icon_view, qt_application, app_count):
    """空列表和带竖向滚动条的列表均铺满，扩大窗口时名称与包名共同扩展。"""
    view = icon_view
    for row in range(app_count):
        view.addTopLevelItem(QTreeWidgetItem([
            "", f"应用 {row}", f"com.example.app{row}", "已启用",
        ]))
    view.resize(1000, 330)
    view.show()
    wait_until(qt_application, lambda: sum(widths(view)) == view.viewport().width())
    before = widths(view)
    assert view.horizontalScrollBar().maximum() == 0
    view.resize(1250, 330)
    wait_until(qt_application, lambda: sum(widths(view)) == view.viewport().width())
    after = widths(view)
    assert after[0] == before[0] and after[3] == before[3]
    assert after[1] > before[1] and after[2] > before[2]
    assert view.horizontalScrollBar().maximum() == 0


def test_default_columns_remain_readable_in_narrow_viewport(icon_view, qt_application):
    """窄窗口保留四列及可读最小宽度，最后一列通过横滚可完整到达。"""
    view = icon_view
    view.addTopLevelItem(QTreeWidgetItem(["", "示例", "com.example.app", "已停用"]))
    view.resize(400, 330)
    view.show()
    wait_until(qt_application, lambda: view.horizontalScrollBar().maximum() > 0)
    assert all(not view.isColumnHidden(column) for column in range(4))
    assert view.columnWidth(0) >= 48
    assert view.columnWidth(1) >= 160
    assert view.columnWidth(2) >= 240
    metrics = QFontMetrics(view.font())
    assert view.columnWidth(3) >= metrics.horizontalAdvance("已停用") + 24
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
    qt_application.processEvents()
    assert view.viewport().rect().contains(view.visualRect(view.model().index(0, 3)))


def test_default_columns_reflow_after_font_and_scrollbar_changes(icon_view, qt_application):
    """字号和竖向滚动条改变有效宽度时，默认布局仍填满且状态文案留有净空。"""
    view = icon_view
    view.resize(1250, 330)
    view.show()
    wait_until(qt_application, lambda: sum(widths(view)) == view.viewport().width())
    before_status = view.columnWidth(3)
    view.setFont(QFont("Arial", 34))
    for row in range(30):
        view.addTopLevelItem(QTreeWidgetItem([
            "", f"应用 {row}", f"com.example.app{row}", "已停用",
        ]))
    wait_until(qt_application, lambda: (
        view.verticalScrollBar().maximum() > 0
        and sum(widths(view)) == view.viewport().width()
    ))
    assert view.columnWidth(3) > before_status
    assert view.columnWidth(3) >= QFontMetrics(view.font()).horizontalAdvance("已停用") + 24
    assert view.verticalScrollBar().maximum() > 0
    view.clear()
    wait_until(qt_application, lambda: (
        view.verticalScrollBar().maximum() == 0
        and sum(widths(view)) == view.viewport().width()
    ))


@pytest.mark.parametrize("adjustment", ["drag", "programmatic"])
def test_manual_column_widths_survive_resize_show_and_font_changes(
    icon_view, qt_application, adjustment,
):
    """调整后的前三列不被刷新覆盖，末列继续承接面板剩余宽度。"""
    view = icon_view
    view.resize(1000, 330)
    view.show()
    wait_until(qt_application, lambda: sum(widths(view)) == view.viewport().width())
    header = view.header()
    before = view.columnWidth(1)
    if adjustment == "drag":
        boundary = QPoint(header.sectionViewportPosition(1) + before - 1, header.height() // 2)
        QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, pos=boundary)
        QTest.mouseMove(header.viewport(), boundary + QPoint(60, 0))
        QTest.mouseRelease(
            header.viewport(), Qt.MouseButton.LeftButton, pos=boundary + QPoint(60, 0),
        )
    else:
        view.setColumnWidth(1, before + 60)
    assert abs(view.columnWidth(1) - before - 60) <= 2
    expected = widths(view)
    view.hide()
    view.resize(1300, 330)
    view.setFont(QFont("Arial", 22))
    view.clear()
    view.show()
    qt_application.processEvents()
    assert widths(view)[:3] == expected[:3]
    assert view.columnWidth(3) >= expected[3]
    assert sum(widths(view)) == view.viewport().width()


@pytest.mark.parametrize("icon_mode", [False, True])
def test_app_manager_manual_columns_keep_filling_panel(qt_application, icon_mode):
    """两种列表手动调整名称列后仍填满面板，并保留调宽结果及刷新状态。"""
    page = AppManagerPage(device_ip="column-fill-demo")
    try:
        apps = [("示例应用", "com.example.app", "Enabled", "User")]
        page._populate(apps)
        page.resize(1200, 800)
        page.show()
        if not icon_mode:
            QTest.mouseClick(page.view_toggle, Qt.MouseButton.LeftButton)
        qt_application.processEvents()
        view = page.icon_list if icon_mode else page.tree
        assert view.isVisible()
        header = view.header()
        for delta in (-60, 30):
            before = view.columnWidth(1)
            boundary = QPoint(
                header.sectionViewportPosition(1) + before - 1, header.height() // 2,
            )
            QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, pos=boundary)
            QTest.mouseMove(header.viewport(), boundary + QPoint(delta, 0))
            QTest.mouseRelease(
                header.viewport(), Qt.MouseButton.LeftButton, pos=boundary + QPoint(delta, 0),
            )
            qt_application.processEvents()
            assert abs(view.columnWidth(1) - before - delta) <= 2
            assert header.length() == view.viewport().width()

        manual_width = view.columnWidth(1)
        for width in (1500, 1100, 1400):
            page.resize(width, 800)
            qt_application.processEvents()
            assert view.columnWidth(1) == manual_width
            # 面板窄于手工列宽总和时允许横滚，但不能出现未填满的右侧空白。
            assert header.length() >= view.viewport().width()
        page._toggle_view()
        page._populate(apps)
        page._toggle_view()
        qt_application.processEvents()
        assert view.columnWidth(1) == manual_width
        assert header.length() == view.viewport().width()
    finally:
        page.close()


def test_app_manager_default_columns_fill_after_toggle_and_refresh(qt_application):
    """真实应用页接入默认铺满，隐藏期间改窗口宽度和数据刷新后仍生效。"""
    page = AppManagerPage(device_ip="column-fill-demo")
    try:
        apps = [("示例应用", "com.example.app", "Enabled", "User")]
        page._populate(apps)
        page.resize(1000, 800)
        page.show()
        view = page.icon_list
        assert view.isVisible()
        wait_until(qt_application, lambda: sum(widths(view)) == view.viewport().width())
        before = widths(view)
        page._toggle_view()
        page.resize(1250, 800)
        page._populate(apps)
        page._toggle_view()
        wait_until(qt_application, lambda: sum(widths(view)) == view.viewport().width())
        assert view.columnWidth(1) > before[1]
        assert view.columnWidth(2) > before[2]
        assert view.horizontalScrollBar().maximum() == 0
    finally:
        page.close()
