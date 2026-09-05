"""验证功能导航的宽度适配、选择提交和键盘焦点连续性。"""

from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy

from gui.widgets.adaptive_navigation import AdaptiveNavigation


def test_navigation_commits_only_accepted_choices_and_emits_once(qt_application):
    navigation = AdaptiveNavigation("test")
    navigation.add_item("first", "设备连接")
    navigation.add_item("second", "文件管理")
    requests = QSignalSpy(navigation.current_requested)
    navigation.pivot.widget("test:second").click()
    assert requests.count() == 1
    assert navigation.pivot.currentRouteKey() == "test:first"
    assert navigation.combo.currentData() == "first"

    navigation.current_requested.connect(navigation.set_current)
    navigation.combo.setCurrentIndex(1)
    assert requests.count() == 2
    assert navigation.pivot.currentRouteKey() == "test:second"
    assert navigation.combo.currentData() == "second"
    navigation.pivot.widget("test:second").click()
    assert requests.count() == 2
    navigation.close()


def test_navigation_uses_actual_text_width_and_keeps_window_shrinkable(qt_application):
    navigation = AdaptiveNavigation("test", minimum_pivot_width=300)
    for index in range(6):
        navigation.add_item(str(index), f"设备功能与性能诊断 {index}")
    navigation.resize(560, 80)
    navigation.show()
    qt_application.processEvents()
    assert navigation.width() == 560
    assert navigation.combo.isVisibleTo(navigation)
    assert navigation.pivot.isHidden()

    navigation.resize(1800, 80)
    qt_application.processEvents()
    assert navigation.pivot.isVisibleTo(navigation)
    for item in navigation.pivot.items.values():
        font = QFont(item.font())
        font.setPointSize(24)
        item.setFont(font)
    navigation.refresh_mode()
    navigation.resize(400, 80)
    qt_application.processEvents()
    assert navigation.width() == 400
    assert navigation.combo.isVisibleTo(navigation)
    assert navigation.pivot.isHidden()
    navigation.close()


def test_navigation_preserves_focus_and_selection_across_modes(qt_application):
    navigation = AdaptiveNavigation("test", minimum_pivot_width=500)
    navigation.add_item("first", "设备")
    navigation.add_item("second", "文件")
    navigation.set_current("second")
    navigation.resize(800, 80)
    navigation.show()
    navigation.activateWindow()
    navigation.pivot.widget("test:second").setFocus()
    qt_application.processEvents()
    assert navigation.pivot.widget("test:second").hasFocus()
    requests = QSignalSpy(navigation.current_requested)

    navigation.resize(350, 80)
    qt_application.processEvents()
    assert navigation.combo.hasFocus()
    assert navigation.combo.currentData() == "second"
    navigation.resize(800, 80)
    qt_application.processEvents()
    assert navigation.pivot.widget("test:second").hasFocus()
    assert requests.count() == 0
    navigation.close()
