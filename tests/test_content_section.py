"""验证开放分区没有结构底板，原生控件和布局接口保持可用。"""

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import HeaderCardWidget, LineEdit, PushButton

from gui.styles import BaseStyles
from gui.widgets.content_section import ContentSection


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
            assert image.pixelColor(section.mapTo(host, point)) == background

        button.click()
        assert clicked.count() == 1
        assert field.text() == "保留输入"
    finally:
        host.close()
        host.deleteLater()
        qt_application.processEvents()
