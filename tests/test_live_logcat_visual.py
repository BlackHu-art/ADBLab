"""Logcat 嵌入模式、中文控件、日志可读性与阅读位置回归。"""

import pytest
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.features.logcat import LiveLogcatPage
from gui.styles import BaseStyles, FontRole
from tests.test_main_window_layout import _FakeScreen, _FakeScreenAdapter, build_main_frame


def _contrast(first, second):
    def luminance(color):
        parts = [channel / 255 for channel in (color.red(), color.green(), color.blue())]
        values = [part / 12.92 if part <= .04045 else ((part + .055) / 1.055) ** 2.4
                  for part in parts]
        return sum(value * weight for value, weight in zip(values, (.2126, .7152, .0722)))
    values = sorted((luminance(first), luminance(second)))
    return (values[1] + .05) / (values[0] + .05)


def test_logcat_main_window_embedded_mode_has_one_heading(qt_application):
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("logcat", QSize(1600, 1100)))
    )
    try:
        frame.show()
        host = frame._workspace_feature_hosts["system"]
        host.set_device_context(["demo-a"], ["demo-a"])
        assert frame._open_workspace_feature("system", "logcat", device_id="demo-a")
        qt_application.processEvents()
        page = host.stack.currentWidget()
        assert page.property("workspace_embedded") is True
        assert not page.header_card.isVisibleTo(frame)
        assert page.level_combo.isVisibleTo(frame)
        assert page.output.isVisibleTo(frame)
        page.set_workspace_embedded(False)
        assert page.header_card.isVisibleTo(frame)
        assert page.dialog_title.text() == "实时 Logcat"
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("width", [420, 980])
def test_logcat_controls_follow_font_and_fit_narrow_content(
    qt_application, monkeypatch, font_size, width
):
    monkeypatch.setattr(
        BaseStyles, "font_for_role",
        classmethod(lambda _cls, role, size=None: QFont(
            "Consolas" if role in (FontRole.LOG, FontRole.MONO) else "Microsoft YaHei",
            size or font_size,
        )),
    )
    owner = QWidget()
    owner.resize(width, 900)
    layout = QVBoxLayout(owner)
    layout.setContentsMargins(0, 0, 0, 0)
    page = LiveLogcatPage(device_ip="demo-a")
    layout.addWidget(page)
    owner.show()
    qt_application.processEvents()
    assert owner.width() == width, [
        (type(child).__name__, child.objectName(), child.minimumSizeHint())
        for child in page.findChildren(QWidget) if child.parentWidget() is page
    ]
    assert page.start_btn.text() == "开始采集"
    assert page.stop_btn.text() == "停止采集"
    assert page.wrap_btn.text() == "自动换行"
    controls = (page.level_combo, page.pkg_input, page.btn_get_pkg, page.start_btn,
                page.stop_btn, page.clear_btn, page.export_btn, page.wrap_btn, page.status_bar)
    for control in controls:
        assert control.isVisibleTo(owner)
        assert control.font().pointSize() == font_size
        assert control.height() >= control.fontMetrics().height()
        assert page.rect().contains(QRect(control.mapTo(page, QPoint()), control.size()))
    assert page.pkg_input.height() >= page.pkg_input.fontMetrics().height() + 14
    assert page.output.height() >= page.output.fontMetrics().lineSpacing() * 6
    page.close()
    owner.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_logcat_output_background_and_all_levels_keep_readable_contrast(
    qt_application, theme
):
    page = LiveLogcatPage(device_ip="demo-a")
    page.resize(700, 500)
    page.show()
    BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
    BaseStyles.switch_theme(theme)
    qt_application.processEvents()
    expected = QColor(BaseStyles.color("LOG_BACKGROUND"))
    image = page.output.viewport().grab().toImage()
    assert image.pixelColor(2, 2) == expected
    for level in "VDIWEFSU":
        text = f"09-05 18:10:12.345 1001 1001 {level} Demo: synthetic log text"
        page.output.setPlainText(text)
        page.highlighter.rehighlight()
        block = page.output.document().firstBlock()
        formats = block.layout().formats()
        foreground = formats[0].format.foreground().color()
        assert _contrast(foreground, expected) >= 4.5, (theme, level, foreground.name())
    page.close()


def test_logcat_new_batch_keeps_history_position_and_resumes_following_at_tail(qt_application):
    page = LiveLogcatPage(device_ip="demo-a")
    page.resize(650, 430)
    page.show()
    page.output.setPlainText("\n".join(f"historical line {index}" for index in range(150)))
    qt_application.processEvents()
    scrollbar = page.output.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum() // 3)
    previous = scrollbar.value()
    page._on_line("new line", "I")
    page._flush_pending_lines()
    assert scrollbar.value() == previous
    scrollbar.setValue(scrollbar.maximum())
    page._on_line("latest line", "I")
    page._flush_pending_lines()
    assert scrollbar.value() == scrollbar.maximum()
    page.close()
