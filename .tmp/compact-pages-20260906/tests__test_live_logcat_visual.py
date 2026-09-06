"""Logcat 嵌入模式、中文控件、日志可读性与阅读位置回归。"""

import pytest
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QFont
from PySide6.QtTest import QTest
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
                page.stop_btn, page.clear_btn, page.export_btn, page.wrap_btn, page.status_bar,
                page.follow_btn, page.reading_status)
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


def test_logcat_reading_controls_pause_resume_and_clear_without_stopping_capture(qt_application):
    page = LiveLogcatPage(device_ip="demo-a")
    page.resize(800, 650)
    page.activate()
    try:
        assert not page.wrap_btn.isChecked()
        assert page.output.lineWrapMode() == page.output.LineWrapMode.NoWrap
        for index in range(120):
            page._on_line(f"historical record {index}", "I")
        page._flush_pending_lines()
        qt_application.processEvents()
        bar = page.output.verticalScrollBar()
        bar.setValue(bar.maximum() // 3)
        anchor = page.output.firstVisibleBlock().text()
        assert not page.follow_btn.isChecked()
        for index in range(5):
            page._on_line(f"incoming record {index}", "W")
        page._flush_pending_lines()
        assert page.output.firstVisibleBlock().text() == anchor
        assert "125 / 8000" in page.reading_status.text()
        assert "5 行新日志" in page.reading_status.text()
        assert len(page.entries) == 125
        page.follow_btn.click()
        assert page.follow_btn.isChecked()
        assert bar.value() == bar.maximum()
        assert "已暂停跟随" not in page.reading_status.text()
        page._on_line("pending before clear", "I")
        page.clear_btn.click()
        page._flush_pending_lines()
        assert page.output.toPlainText() == ""
        assert not page.entries
        assert "0 / 8000" in page.reading_status.text()
        assert not page.export_btn.isEnabled()
        assert not page.clear_btn.isEnabled()
        assert page.follow_btn.isChecked()
        page._on_line("capture continues after clear", "E")
        page._flush_pending_lines()
        assert page.output.toPlainText() == "capture continues after clear"
    finally:
        page.close()


def test_logcat_large_output_keeps_workspace_geometry_and_bounded_document(qt_application):
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("logcat", QSize(1600, 1100)))
    )
    try:
        frame.show()
        frame.resize(1360, 900)
        host = frame._workspace_feature_hosts["system"]
        host.set_device_context(["demo-a"], ["demo-a"])
        assert frame._open_workspace_feature("system", "logcat", device_id="demo-a")
        qt_application.processEvents()
        QTest.qWait(350)
        page = host.stack.currentWidget()
        before_size = page.size()
        before_output = page.output.size()
        for index in range(9000):
            page._on_line(f"record {index:05d} " + "long-message-" * 30, "I")
            if index % 100 == 99:
                page._flush_pending_lines()
        qt_application.processEvents()
        assert page.size() == before_size
        assert page.output.size() == before_output
        assert len(page.entries) == page.MAX_BUFFER
        assert page.output.document().blockCount() == page.MAX_BUFFER
        assert page.output.document().firstBlock().text().startswith("record 01000 ")
        assert page.output.document().lastBlock().text().startswith("record 08999 ")
        assert "8000 / 8000" in page.reading_status.text()
        assert page.output.horizontalScrollBar().maximum() > 0
        frame.resize(860, 700)
        qt_application.processEvents()
        QTest.qWait(350)
        outer = host.content_scroll
        outer.ensureWidgetVisible(page.output, 0, 0)
        qt_application.processEvents()
        output_rect = QRect(page.output.mapTo(outer.viewport(), QPoint()), page.output.size())
        assert outer.viewport().rect().contains(output_rect)
        outer.ensureWidgetVisible(page.follow_btn, 0, 0)
        qt_application.processEvents()
        button_rect = QRect(
            page.follow_btn.mapTo(outer.viewport(), QPoint()), page.follow_btn.size()
        )
        assert outer.viewport().rect().contains(button_rect)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_logcat_resize_that_removes_scroll_range_keeps_reading_paused(qt_application):
    page = LiveLogcatPage(device_ip="demo-a")
    page.resize(700, 600)
    page.activate()
    try:
        for index in range(32):
            page._on_line(f"record {index}", "I")
        page._flush_pending_lines()
        qt_application.processEvents()
        bar = page.output.verticalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(bar.maximum() // 3)
        assert not page.follow_btn.isChecked()
        page.resize(700, 1600)
        qt_application.processEvents()
        assert bar.maximum() == 0
        assert not page.follow_btn.isChecked()
        page.resize(700, 600)
        qt_application.processEvents()
        assert not page.follow_btn.isChecked()
        page._on_line("new record while paused", "I")
        page._flush_pending_lines()
        assert not page.follow_btn.isChecked()
        assert "1 行新日志" in page.reading_status.text()
    finally:
        page.close()


def test_logcat_large_font_small_workspace_can_reach_full_output_and_reading_tools(
    qt_application, monkeypatch
):
    monkeypatch.setattr(
        BaseStyles, "font_for_role", classmethod(lambda _cls, role, size=None: QFont(
            "Consolas" if role in (FontRole.LOG, FontRole.MONO) else "Microsoft YaHei",
            size or (16 if role == FontRole.LOG else 22),
        )),
    )
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("logcat", QSize(1600, 1100)))
    )
    try:
        frame.show()
        frame.resize(860, 700)
        host = frame._workspace_feature_hosts["system"]
        host.set_device_context(["demo-a"], ["demo-a"])
        assert frame._open_workspace_feature("system", "logcat", device_id="demo-a")
        QTest.qWait(350)
        page = host.stack.currentWidget()
        for index in range(100):
            page._on_line(f"record {index}", "W")
        page._flush_pending_lines()
        page.follow_btn.click()
        page._on_line("new record while reading", "W")
        page._flush_pending_lines()
        qt_application.processEvents()
        outer = host.content_scroll
        outer.verticalScrollBar().setValue(outer.verticalScrollBar().maximum())
        qt_application.processEvents()
        for control in (page.output, page.follow_btn, page.wrap_btn,
                        page.export_btn, page.clear_btn, page.reading_status):
            rect = QRect(control.mapTo(outer.viewport(), QPoint()), control.size())
            assert outer.viewport().rect().contains(rect)
        assert outer.horizontalScrollBar().maximum() == 0
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.mark.parametrize(
    "label,code,visible_levels",
    [
        ("详细及以上", "V", "VDIWEFS"),
        ("调试及以上", "D", "DIWEFS"),
        ("信息及以上", "I", "IWEFS"),
        ("警告及以上", "W", "WEFS"),
        ("错误及以上", "E", "EFS"),
        ("严重错误", "F", "FS"),
    ],
)
def test_logcat_level_combo_filters_history_pending_and_future_records(
    qt_application, label, code, visible_levels,
):
    """真实等级下拉框同时过滤历史和后续日志，切换时不泄漏尚未落屏的低等级。"""

    page = LiveLogcatPage(device_ip="demo-a")
    records = []

    def ingest(prefix):
        for level in "VDIWEFSU":
            text = f"09-06 18:10:12.345 1001 1001 {level} Demo: {prefix}-{level}"
            records.append((text, level))
            page._on_line(text, level, 1001)

    def displayed_records():
        return [line for line in page.output.toPlainText().splitlines() if line]

    try:
        page.resize(720, 520)
        page.activate()
        qt_application.processEvents()
        ingest("history")
        page._flush_pending_lines()
        assert displayed_records() == [text for text, _level in records]

        ingest("pending")
        assert page._pending_visible_lines
        assert page._line_flush_timer.isActive()
        index = page.level_combo.findText(label)
        assert index > 0
        page.level_combo.setCurrentIndex(index)
        expected = [text for text, level in records if level in visible_levels]
        assert displayed_records() == expected
        assert page.level_combo.currentData() == code
        assert not page._pending_visible_lines
        assert not page._line_flush_timer.isActive()
        page._flush_pending_lines()
        assert displayed_records() == expected

        ingest("future")
        page._flush_pending_lines()
        assert displayed_records() == [text for text, level in records if level in visible_levels]
        assert len(page.entries) == len(records)

        ingest("pending-before-all")
        assert page._pending_visible_lines
        assert page._line_flush_timer.isActive()
        page.level_combo.setCurrentIndex(0)
        assert page.level_combo.currentData() is None
        assert displayed_records() == [text for text, _level in records]
        assert not page._pending_visible_lines
        assert not page._line_flush_timer.isActive()
        page._flush_pending_lines()
        assert displayed_records() == [text for text, _level in records]

        ingest("after-all")
        page._flush_pending_lines()
        assert displayed_records() == [text for text, _level in records]
        assert len(page.entries) == len(records)
    finally:
        page.close()
