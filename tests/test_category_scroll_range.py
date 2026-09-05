"""分类切换后只用当前页的换行高度计算滚动范围。"""

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea

from gui.widgets.category_stack import AdaptiveCategoryStack
from tests.ui_geometry_helpers import wait_until


@pytest.mark.parametrize("font_size", [12, 22])
def test_hidden_long_category_does_not_add_blank_tail_to_short_page(
    qt_application, font_size,
):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    categories = AdaptiveCategoryStack("scrollRegression")
    categories.set_navigation_visible(False)
    long_label = QLabel("长分类说明")
    long_label.setWordWrap(True)
    long_label.setMinimumHeight(1200)
    long_action = QPushButton("长页操作")
    short_label = QLabel("短分类仍按当前可用宽度显示说明。")
    short_label.setWordWrap(True)
    short_label.setFont(QFont("Microsoft YaHei", font_size))
    action = QPushButton("当前页底部操作")
    action.setFont(short_label.font())
    action.setMinimumHeight(action.fontMetrics().height() + 14)
    categories.add_category("long", "长页", (long_label, long_action))
    page = categories.add_category("short", "短页", (short_label, action))
    scroll.setWidget(categories)
    scroll.resize(420, 360)
    scroll.show()
    try:
        for _ in range(2):
            categories.set_current("long")
            wait_until(qt_application, lambda: scroll.verticalScrollBar().maximum() > 700)
            assert scroll.verticalScrollBar().maximum() > 700
            long_action.setFocus()
            qt_application.processEvents()
            assert long_action.hasFocus()
            categories.set_current("short")
            wait_until(qt_application, lambda: scroll.verticalScrollBar().maximum() == 0)
            measured_height = categories.stack.heightForWidth(page.width())
            assert measured_height == page.heightForWidth(page.width())
            assert scroll.verticalScrollBar().maximum() == 0
            position = action.mapTo(scroll.viewport(), QPoint())
            assert position.y() >= 0
            assert position.y() + action.height() <= scroll.viewport().height()
            assert action.hasFocus()
    finally:
        scroll.close()
