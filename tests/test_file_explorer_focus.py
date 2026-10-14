"""验证文件表格焦点即时使用强调色，并保持鼠标与键盘的边框策略。"""

import pytest
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QWidget

from gui.features.file_explorer import FileExplorerPage
from gui.styles import BaseStyles
from gui.styles.fluent import refresh_fluent_widget_style

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_file_table_keyboard_focus_tracks_accent_without_mouse_outline(qt_application, theme):
    """用真实焦点与渲染边缘验证颜色变化，不以属性注册代替可见结果。"""
    original_accent = BaseStyles.accent_color()
    BaseStyles.switch_theme(theme)
    page = FileExplorerPage()
    page.resize(1000, 700)
    page.show()
    page.activateWindow()
    qt_application.processEvents()
    observer = page.table.findChild(QObject, "adblabKeyboardFocusObserver")
    assert observer is not None
    observer_destroyed = QSignalSpy(observer.destroyed)
    table_destroyed = QSignalSpy(page.table.destroyed)

    def border_color():
        image = page.table.grab().toImage()
        return image.pixelColor(image.width() // 2, 0).name().lower()

    try:
        other_theme = "Dark" if theme == "Light" else "Light"
        cases = ((theme, "#8B5CF6", Qt.FocusReason.TabFocusReason),
                 (other_theme, "#C239B3", Qt.FocusReason.BacktabFocusReason),
                 (theme, "#0F6CBD", Qt.FocusReason.TabFocusReason))
        for current_theme, accent, reason in cases:
            BaseStyles.switch_theme(current_theme)
            BaseStyles.set_accent_color(accent)
            # 主窗口的统一刷新遍历同一页面后代；不调用页面主题槽掩盖遗漏。
            for widget in page.findChildren(QWidget):
                refresh_fluent_widget_style(widget)
            font = page.table.font()
            geometry = page.table.viewport().geometry()
            page.table.clearFocus()
            page.table.setFocus(reason)
            qt_application.processEvents()
            assert page.table.hasFocus()
            assert border_color() == accent.lower()
            QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton)
            qt_application.processEvents()
            assert page.table.hasFocus()
            assert border_color() != accent.lower()
            QTest.keyClick(page.table, Qt.Key.Key_Down)
            qt_application.processEvents()
            assert border_color() == accent.lower()
            assert page.table.font() == font
            assert page.table.viewport().geometry() == geometry
    finally:
        BaseStyles.set_accent_color(original_accent)
        assert page.request_dispose("test")
        page.close()
        page.deleteLater()
        qt_application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert observer_destroyed.count() == 1
        assert table_destroyed.count() == 1
