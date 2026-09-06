"""验证严格整数下拉的文字、原生选择和业务值保持一致。"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.widgets.preset_spin_box import StrictIntComboBox
from tests.ui_geometry_helpers import wait_until


def test_first_preset_can_be_clicked_after_initial_nonfirst_value(qt_application):
    """默认显示 600 后，点击首项 10 必须真实选中并只提交一次。"""
    owner = QWidget()
    field = StrictIntComboBox(
        1, 10000, 600, presets=(10, 30, 60, 120, 600, 4320), parent=owner,
    )
    QVBoxLayout(owner).addWidget(field)
    changed = QSignalSpy(field.valueChanged)
    owner.resize(240, 90)
    owner.show()
    try:
        QTest.mouseClick(field.dropButton, Qt.MouseButton.LeftButton)
        wait_until(
            qt_application, lambda: field.dropMenu is not None and field.dropMenu.isVisible()
        )
        menu = field.dropMenu
        item = menu.view.item(0)
        menu.view.scrollToItem(item)
        QTest.mouseClick(
            menu.view.viewport(), Qt.MouseButton.LeftButton,
            pos=menu.view.visualItemRect(item).center(),
        )
        assert field.text() == "10"
        assert field.value() == 10
        assert field.currentIndex() == 0
        assert changed.count() == 1
    finally:
        if field.dropMenu is not None:
            field.dropMenu.close()
        owner.close()


@pytest.mark.parametrize("value,expected_index", [(600, 4), (10, 0), (77, -1)])
def test_set_value_keeps_text_and_native_selection_consistent(
    qt_application, value, expected_index,
):
    field = StrictIntComboBox(1, 10000, 30, presets=(10, 30, 60, 120, 600, 4320))
    changed = QSignalSpy(field.valueChanged)
    try:
        field.setValue(value)
        assert field.text() == str(value)
        assert field.value() == value
        assert field.currentIndex() == expected_index
        assert changed.count() == 1
        field.setValue(value)
        assert changed.count() == 1
    finally:
        field.close()


def test_keyboard_edit_then_first_preset_preserves_strict_commit(qt_application):
    field = StrictIntComboBox(1, 10000, 600, presets=(10, 30, 60, 120, 600, 4320))
    field.show()
    try:
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "77")
        assert field.currentIndex() == -1
        QTest.keyClick(field, Qt.Key.Key_Return)
        assert field.value() == 77
        assert field.text() == "77"
        field.setCurrentIndex(0)
        assert field.commit_value()
        assert field.text() == "10" and field.value() == 10
        field.selectAll()
        QTest.keyClicks(field, "bad")
        assert not field.commit_value()
        assert field.value() == 10 and field.text() == "bad"
        assert field.currentIndex() == -1
    finally:
        field.close()
