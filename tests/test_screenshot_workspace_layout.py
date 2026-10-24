"""验证截图画布与底部命令行的可用空间及鼠标、键盘焦点。"""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from gui.styles import BaseStyles
from gui.styles.fluent import refresh_fluent_widget_style
from gui.widgets.content_section import ContentSection
from tests.screenshot_helpers import close_screenshot_page, make_screenshot_page
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until

pytestmark = pytest.mark.ui


def _images(tmp_path, count):
    paths = []
    for index in range(count):
        image = QPixmap(180, 320)
        image.fill(Qt.GlobalColor.red)
        path = tmp_path / f"portrait-{index}.png"
        assert image.save(str(path))
        paths.append(str(path))
    return paths


@pytest.mark.parametrize("with_image", [False, True], ids=["empty", "loaded"])
@pytest.mark.parametrize("width,font_size", [(380, 12), (1000, 22)])
def test_screenshot_commands_stay_below_expanding_canvas_with_balanced_insets(
    qt_application, tmp_path, monkeypatch, with_image, width, font_size,
):
    """窄屏、大字体和借用工具行不挤出底部命令；增加高度全部交还画布。"""
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda cls, role, size=None: QFont("Microsoft YaHei", size or font_size)
    ))
    parking = QWidget()
    tools = QWidget(parking)
    tools.setFixedHeight(60)
    page = make_screenshot_page(_images(tmp_path, 1) if with_image else [])
    page.prepare_for_workspace()
    page.set_device_tools(tools, parking)
    page.resize(width, 680)
    page.show()
    try:
        canvas, bar = page._canvas_frame, page._command_bar
        wait_for_stable_geometry(qt_application, (page, tools, canvas, bar))
        assert tools.y() == 8
        assert canvas.y() == tools.geometry().bottom() + 9
        assert bar.y() == canvas.geometry().bottom() + 9
        assert page.rect().bottom() - bar.geometry().bottom() == 8
        assert bar.geometry().left() == canvas.geometry().left() == 32
        assert page.rect().right() - bar.geometry().right() == 32
        assert page.rect().contains(bar.geometry())
        previous_height = canvas.height()

        page.resize(width, 800)
        page._apply_theme()
        wait_for_stable_geometry(qt_application, (page, tools, canvas, bar))
        assert canvas.height() == previous_height + 120
        assert bar.y() == canvas.geometry().bottom() + 9
        assert page.rect().bottom() - bar.geometry().bottom() == 8
        assert page._add_action.isEnabled()
    finally:
        close_screenshot_page(page)
        parking.close()


@pytest.mark.parametrize("header_hidden", [False, True])
def test_screenshot_borrowed_card_aligns_first_control_and_restores_its_spacing(
    qt_application, header_hidden,
):
    """嵌入时只保留页外留白；原卡片回到暂存宿主后恢复标题、分隔及内边距。"""
    parking = QWidget()
    tools = ContentSection("screen", parking)
    tools.headerView.setVisible(not header_hidden)
    tools.separator.show()
    original_margins = tools.viewLayout.contentsMargins()
    control = QWidget()
    control.setFixedHeight(36)
    tools.viewLayout.addWidget(control)
    page = make_screenshot_page([])
    page.prepare_for_workspace()
    page.set_device_tools(tools, parking)
    page.set_device_tools(tools, parking)
    page.resize(800, 680)
    page.show()
    try:
        wait_for_stable_geometry(qt_application, (page, tools, control, page._canvas_frame))
        assert control.mapTo(page, QPoint()) == QPoint(32, 8)
        assert page._canvas_frame.y() == control.mapTo(page, control.rect().bottomLeft()).y() + 9
        close_screenshot_page(page)
        assert tools.parentWidget() is parking
        assert tools.viewLayout.contentsMargins() == original_margins
        assert tools.headerView.isHidden() is header_hidden
        assert not tools.separator.isHidden()
    finally:
        close_screenshot_page(page)
        parking.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("control", ["view", "pager"])
def test_screenshot_mouse_focus_has_no_outline_and_keyboard_navigation_keeps_it(
    qt_application, tmp_path, theme, control,
):
    """真实鼠标点击去掉外围强调框，键盘切图仍有焦点提示且不改变画布尺寸。"""
    original_accent = BaseStyles.accent_color()
    BaseStyles.switch_theme(theme)
    BaseStyles.set_accent_color("#C239B3")
    page = make_screenshot_page(_images(tmp_path, 2))
    page.prepare_for_workspace()
    page.resize(800, 680)
    page.show()
    page.activateWindow()
    widget = page._view if control == "view" else page._pager

    def border_color():
        image = widget.grab().toImage()
        return image.pixelColor(image.width() // 2, 0).name().lower()

    try:
        wait_for_stable_geometry(qt_application, (page, page._view, page._pager))
        widget.clearFocus()
        widget.setFocus(Qt.FocusReason.TabFocusReason)
        qt_application.processEvents()
        assert widget.hasFocus()
        assert border_color() == "#c239b3"
        geometry = widget.viewport().geometry()
        QTest.mouseClick(widget.viewport(), Qt.MouseButton.LeftButton)
        qt_application.processEvents()
        assert widget.hasFocus()
        assert border_color() != "#c239b3"
        assert widget.viewport().geometry() == geometry

        BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
        for child in page.findChildren(QWidget):
            refresh_fluent_widget_style(child)
        assert border_color() != "#c239b3"
        QTest.keyClick(widget, Qt.Key.Key_End)
        wait_until(qt_application, lambda: page._current_idx == 1)
        assert border_color() == "#c239b3"
        assert widget.viewport().geometry() == geometry
    finally:
        BaseStyles.set_accent_color(original_accent)
        close_screenshot_page(page)
