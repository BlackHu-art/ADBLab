"""验证开放分区没有结构底板，原生控件和布局接口保持可用。"""

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import HeaderCardWidget, LineEdit, PushButton

from gui.styles import BaseStyles
from gui.widgets.content_section import ContentSection
from tests.ui_geometry_helpers import wait_for_stable_geometry


@pytest.mark.parametrize("width", [380, 760])
def test_section_header_follows_wrapped_title_and_action_height(qt_application, width):
    host = QWidget()
    layout = QVBoxLayout(host)
    section = ContentSection("需要在狭窄窗口中完整显示的功能分区标题", host)
    action = PushButton("执行", section.headerView)
    section.headerLayout.addWidget(action)
    field = LineEdit(section)
    field.setText("保留输入")
    section.viewLayout.addWidget(field)
    layout.addWidget(section)
    host.resize(width, 360)
    host.show()
    for size in (12, 22, 12):
        font = QFont("Microsoft YaHei", size)
        section.headerLabel.setFont(font)
        action.setFont(font)
        action.setMinimumHeight(action.fontMetrics().height() + 12)
        wait_for_stable_geometry(qt_application, (
            section, section.headerView, section.headerLabel, action,
        ))
        label = section.headerLabel
        required = max(
            label.heightForWidth(label.width()), action.sizeHint().height(), action.minimumHeight(),
        )
        assert required <= section.headerView.height() <= required + 2
        for widget in (label, action):
            bounds = QRect(widget.mapTo(section.headerView, QPoint()), widget.size())
            assert section.headerView.rect().contains(bounds)
        assert label.height() >= label.heightForWidth(label.width())
        assert not label.geometry().intersects(action.geometry())
        assert host.width() == width
        assert field.text() == "保留输入"
    host.close()


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_content_section_blends_with_parent_and_preserves_controls(qt_application, theme):
    BaseStyles.switch_theme(theme)
    host = QWidget()
    host.setObjectName("sectionTestHost")
    host.resize(520, 320)
    background = QColor("#E7EBEF" if theme == "Light" else "#25292D")
    host.setStyleSheet(f"QWidget#sectionTestHost {{ background: {background.name()}; }}")
    layout = QVBoxLayout(host)
    section = ContentSection("测试功能", host)
    field = LineEdit(section)
    field.setText("保留输入")
    button = PushButton("执行", section)
    clicked = QSignalSpy(button.clicked)
    section.viewLayout.addWidget(field)
    section.viewLayout.addWidget(button)
    layout.addWidget(section)
    host.show()
    qt_application.processEvents()
    try:
        assert isinstance(section, HeaderCardWidget)
        assert section.title == "测试功能"
        assert section.separator.isHidden()
        assert section.headerLabel.isVisible()
        assert section.viewLayout.indexOf(field) >= 0
        assert section.viewLayout.indexOf(button) >= 0
        assert (
            section.headerLabel.mapTo(section, QPoint()).x()
            == field.mapTo(section, QPoint()).x()
        )

        QTest.mouseMove(section, QPoint(section.width() - 3, 3))
        qt_application.processEvents()
        image = host.grab().toImage()
        for point in (
            QPoint(section.width() // 2, 1),
            QPoint(section.width() - 2, section.height() // 2),
            QPoint(section.width() // 2, section.height() - 2),
            QPoint(section.width() // 2, section.headerView.height()),
        ):
            logical_point = section.mapTo(host, point)
            ratio = image.devicePixelRatio()
            physical_point = QPoint(
                round(logical_point.x() * ratio), round(logical_point.y() * ratio),
            )
            assert image.pixelColor(physical_point) == background

        button.click()
        assert clicked.count() == 1
        assert field.text() == "保留输入"
    finally:
        host.close()
        host.deleteLater()
        qt_application.processEvents()
