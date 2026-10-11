"""镜像操作投影不改变共享设备选择及其他页面的会话策略。"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import TransparentPushButton

from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceContextBar, DeviceRowOperation
from tests.ui_geometry_helpers import wait_for_stable_geometry

pytestmark = pytest.mark.ui


@pytest.fixture
def operation_selector(qt_application):
    window = QWidget()
    window.resize(900, 850)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    bar = DeviceContextBar(window)
    layout.addWidget(bar)
    layout.addStretch(1)
    bar.set_device_details({
        "demo-a": {
            "brand": "Example", "model": "Phone A", "android_version": "16", "connection": "USB",
        },
        "demo-b": {
            "brand": "Test", "model": "Phone B", "android_version": "15", "connection": "无线",
        },
    })
    bar.set_context(["demo-a"], ["demo-a", "demo-b"], "ready")
    window.show()
    bar.open_picker()
    qt_application.processEvents()
    yield window, bar, bar._picker
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_row_operation_does_not_select_and_rejects_repeated_clicks(operation_selector):
    _window, bar, picker = operation_selector
    operations = {
        "demo-a": DeviceRowOperation("镜像中", "stop", "停止", True, True),
        "demo-b": DeviceRowOperation("启动失败", "retry", "重试", True, False, "编码器不可用"),
    }
    bar.set_device_operations(operations)
    selected = QSignalSpy(bar.selection_requested)
    sessions = QSignalSpy(bar.session_requested)
    requested = QSignalSpy(bar.device_operation_requested)
    row = picker._rows["demo-b"]
    assert row.status_label.text() == "启动失败"
    assert "编码器不可用" in row.operation_button.toolTip()
    QTest.mouseClick(row.operation_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(row.operation_button, Qt.MouseButton.LeftButton)
    row.operation_button.clicked.emit()
    assert requested.count() == 1
    assert requested.at(0) == ["demo-b", "retry"]
    assert not row.operation_button.isEnabled()
    assert selected.count() == sessions.count() == 0
    assert picker._rows["demo-a"].check_box.isChecked()
    assert not row.check_box.isChecked()
    bar.set_context(["demo-a"], ["demo-a", "demo-b"], "scanning")
    assert not row.operation_button.isEnabled()
    bar.set_device_operations(operations)
    assert row.operation_button.isEnabled()


def test_preparation_lock_blocks_all_selection_routes_and_restores_on_exit(operation_selector):
    _window, bar, picker = operation_selector
    requested = QSignalSpy(bar.selection_requested)
    bar.set_device_operations({}, selection_locked=True)
    assert not picker.clear_button.isEnabled()
    assert not picker.select_all_button.isEnabled()
    assert all(not row.check_box.isEnabled() for row in picker._rows.values())
    picker._set_all(False)
    picker._set_all(True)
    picker._rows["demo-b"].item.setCheckState(Qt.CheckState.Checked)
    picker.selection_requested.emit(["demo-b"])
    assert requested.count() == 0
    assert not picker._rows["demo-b"].check_box.isChecked()
    bar.set_device_operations(None)
    assert picker.clear_button.isEnabled()
    assert picker.select_all_button.isEnabled()
    QTest.mouseClick(picker._rows["demo-b"].check_box, Qt.MouseButton.LeftButton)
    assert requested.count() == 1
    assert requested.at(0) == [["demo-a", "demo-b"]]
    bar.set_session_context(None, None, selection_locked=True)
    assert picker.clear_button.isEnabled()
    picker.clear_button.click()
    assert requested.at(1) == [[]]


def test_retained_offline_mirror_can_stop_without_becoming_an_online_target(operation_selector):
    _window, bar, picker = operation_selector
    bar.set_device_operations({
        "demo-a": DeviceRowOperation("镜像中", "stop", "停止", True, True),
        "demo-b": DeviceRowOperation("启动失败", "retry", "重试", False),
    })
    bar.set_context([], [], "ready")
    assert list(picker._rows) == ["demo-a"]
    row = picker._rows["demo-a"]
    assert row.status_label.text() == "镜像中"
    assert not row.check_box.isEnabled()
    assert not row.item.data(Qt.ItemDataRole.UserRole)
    assert not picker.select_all_button.isEnabled()
    requested = QSignalSpy(bar.device_operation_requested)
    row.operation_button.click()
    assert requested.at(0) == ["demo-a", "stop"]
    bar.set_device_operations(None)
    assert not picker._rows
    assert picker.device_list.count() == 1


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_operation_button_focus_is_keyboard_only_and_disabled_action_cannot_dispatch(
    operation_selector, qt_application, theme,
):
    window, bar, picker = operation_selector
    BaseStyles.switch_theme(theme)
    bar.set_device_operations({
        "demo-a": DeviceRowOperation("镜像中", "stop", "停止", True, True),
        "demo-b": DeviceRowOperation("启动失败", "retry", "重试", False),
    })
    window.activateWindow()
    button = picker._rows["demo-a"].operation_button
    wait_for_stable_geometry(qt_application, (window, picker, button))
    requested = QSignalSpy(bar.device_operation_requested)
    picker._rows["demo-b"].operation_button.clicked.emit()
    assert requested.count() == 0
    button.setFocus(Qt.FocusReason.TabFocusReason)
    qt_application.processEvents()
    image = button.grab().toImage()
    accent = QColor(BaseStyles.color("BORDER_FOCUS"))
    assert image.pixelColor(image.width() // 2, round(image.devicePixelRatio())) == accent
    old_size = button.size()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    qt_application.processEvents()
    image = button.grab().toImage()
    assert image.pixelColor(image.width() // 2, round(image.devicePixelRatio())) != accent
    assert button.size() == old_size
    assert requested.at(0) == ["demo-a", "stop"]
    bar.set_device_operations(None)
    button.clicked.emit()
    assert requested.count() == 1


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("font_size", [12, 22])
def test_operation_columns_align_and_compact_without_changing_five_row_height(
    operation_selector, qt_application, isolated_app_settings, theme, font_size,
):
    window, bar, picker = operation_selector
    isolated_app_settings.set("ui_font_size", font_size)
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    wait_for_stable_geometry(qt_application, (window, bar, picker))
    original_height = picker.height()
    bar.set_device_operations({
        "demo-a": DeviceRowOperation("镜像中", "stop", "停止", True, True),
        "demo-b": DeviceRowOperation("启动失败", "retry", "重试", True),
    })
    for width in (900, 430, 900):
        window.resize(width, 850)
        rows = list(picker._rows.values())
        wait_for_stable_geometry(qt_application, (window, picker, *rows))
        assert picker.height() == original_height
        for field in (
            "brand_label", "name_label", "version_label", "connection_label", "status_label",
        ):
            cells = [getattr(row, field) for row in rows]
            assert len({(cell.x(), cell.width()) for cell in cells}) == 1
        for row in rows:
            button = row.operation_button
            assert isinstance(button, TransparentPushButton)
            assert button.font().pixelSize() == row.name_label.font().pixelSize()
            assert button.accessibleName() in ("停止", "重试")
            assert row.connection_label.geometry().right() < row.status_label.x()
            assert row.rect().contains(row.operation_section.geometry())
            assert row.width() - row.operation_section.geometry().right() <= 5
            assert button.text() == ("" if width == 430 else button.accessibleName())
    bar.set_device_operations(None)
    assert all(row.operation_section.isHidden() and row.status_label.isHidden()
               for row in picker._rows.values())
    assert not picker.content.autoFillBackground()
