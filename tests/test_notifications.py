"""验证各页共用 Toast 的阅读范围、交互时序和窗口归属。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget
from shiboken6 import isValid

from core.settings_manager import DEFAULTS, AppSettings
from gui.notifications import ToastNotification, show_toast
from gui.styles import BaseStyles


@pytest.fixture
def window(qt_application):
    owner = QWidget()
    owner.resize(860, 700)
    owner.show()
    yield owner
    owner.close()


@pytest.mark.parametrize("width,font_size", [(360, 12), (360, 22), (860, 12), (860, 22)])
@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_long_toast_preserves_text_and_fits_window_after_resize(
    window, qt_application, monkeypatch, width, font_size, theme,
):
    BaseStyles.switch_theme(theme)
    monkeypatch.setattr(
        BaseStyles, "font_for_role", lambda *_args: QFont("Microsoft YaHei UI", font_size)
    )
    panel = QWidget(window)
    panel.resize(120, 34)
    panel.show()
    content = "截图结果\n" + "W" * 1200 + "\n最终内容.png"
    notice = show_toast(panel, "完整的提示", content, duration=-1)
    assert notice is not None
    window.resize(width, 700)
    qt_application.processEvents()
    assert notice.parentWidget() is window
    assert notice.isVisible()
    assert isinstance(notice.content_edit, QLineEdit)
    assert notice.content_edit.text() == content.replace("\n", " ")
    assert notice.content_edit.toolTip() == content
    assert notice.geometry().right() == window.width() - 25
    assert notice.y() == 24
    assert window.rect().contains(notice.geometry())
    assert not notice.titleLabel.wordWrap()
    assert notice.content_edit.cursorPosition() == 0
    QTest.mouseClick(notice.content_edit, Qt.MouseButton.LeftButton)
    QTest.keyClick(notice.content_edit, Qt.Key.Key_End)
    qt_application.processEvents()
    assert notice.content_edit.cursorPosition() == len(notice.content_edit.text())
    assert notice.content_edit.rect().contains(notice.content_edit.cursorRect().center())
    for control in (notice.titleLabel, notice.content_edit, notice.closeButton):
        assert notice.rect().contains(control.geometry())
        assert abs(control.geometry().center().y() - notice.height() // 2) <= 1
    assert notice.content_edit.font().pointSizeF() == font_size
    assert notice.titleLabel.font().pointSizeF() == font_size


def test_long_title_is_readable_inside_bounded_toast(window, qt_application):
    title = "文件属性：" + "完整文件名" * 100
    notice = show_toast(window, title, "文件大小：123 KB", duration=-1)
    assert notice is not None
    qt_application.processEvents()
    assert window.rect().contains(notice.geometry())
    assert notice.titleLabel.toolTip() == title
    assert not notice.titleLabel.wordWrap()
    assert notice.titleLabel.fontMetrics().horizontalAdvance(notice.titleLabel.text()) <= (
        notice.titleLabel.width()
    )
    assert notice.content_edit.text() == "文件大小：123 KB"
    assert notice.content_edit.width() > notice.titleLabel.width()
    assert notice.closeButton.isVisibleTo(notice)


@pytest.mark.parametrize("width,font_size", [(360, 12), (360, 22), (860, 12), (860, 22)])
def test_single_row_action_stays_reachable_after_font_and_window_changes(
    window, qt_application, monkeypatch, width, font_size,
):
    calls = []
    notice = show_toast(
        window, "截图完成", "截图已保存\n" + "result.png " * 80, duration=-1,
        action_text="查看结果", on_action=lambda: calls.append("opened"),
    )
    assert notice is not None and notice.action_button is not None
    notice.content_edit.setSelection(0, 5)
    selected = notice.content_edit.selectedText()
    monkeypatch.setattr(
        BaseStyles, "font_for_role", lambda *_args: QFont("Microsoft YaHei UI", font_size),
    )
    window.resize(width, 500)
    BaseStyles.fonts_changed.emit(BaseStyles.current_font_config())
    qt_application.processEvents()
    assert notice.content_edit.selectedText() == selected
    controls = (notice.iconWidget, notice.titleLabel, notice.content_edit,
                notice.action_button, notice.closeButton)
    for index, control in enumerate(controls):
        assert control.isVisibleTo(notice)
        assert notice.rect().contains(control.geometry())
        assert abs(control.geometry().center().y() - notice.height() // 2) <= 1
        if index:
            assert controls[index - 1].geometry().right() < control.geometry().left()
    assert notice.action_button.toolTip() == "查看结果"
    assert notice.action_button.font().pointSizeF() == font_size
    assert notice.action_button.height() >= notice.action_button.fontMetrics().height()
    assert notice.content_edit.font().pointSizeF() == font_size
    assert window.rect().contains(notice.geometry())
    QTest.mouseClick(notice.action_button, Qt.MouseButton.LeftButton)
    assert calls == ["opened"]


def test_single_line_body_keeps_full_diagnostic_beyond_default_line_edit_limit(
    window, qt_application,
):
    content = "First field\r\nSecond field\rThird field\u2028" + "diagnostic " * 4000 + " END"
    displayed = "First field Second field Third field " + "diagnostic " * 4000 + " END"
    notice = show_toast(window, "Details", content, duration=-1)
    assert notice is not None
    reader = notice.content_edit
    assert reader.text() == displayed
    assert reader.toolTip() == content
    reader.setFocus()
    reader.selectAll()
    assert reader.selectedText() == displayed
    QTest.keyClicks(reader, "must not replace read-only text")
    assert reader.text() == displayed
    assert notice.content == content


@pytest.mark.parametrize("font_size", [12, 22])
def test_standard_screenshot_notice_fits_complete_single_line(
    window, qt_application, monkeypatch, font_size,
):
    monkeypatch.setattr(
        BaseStyles, "font_for_role", lambda *_args: QFont("Microsoft YaHei UI", font_size),
    )
    content = "结果已加入“截图与屏幕”页面。"
    notice = show_toast(
        window, "截图已完成", content, duration=-1,
        action_text="查看结果", on_action=lambda: None,
    )
    assert notice is not None and notice.action_button is not None
    qt_application.processEvents()
    assert notice.titleLabel.text() == "截图已完成"
    assert notice.action_button.text() == "查看结果"
    assert notice.content_edit.text() == content
    assert notice.content_edit.width() > notice.content_edit.fontMetrics().horizontalAdvance(
        content,
    )
    assert window.rect().contains(notice.geometry())


def test_single_line_copy_uses_complete_text_on_isolated_offscreen_clipboard(
    window, qt_application,
):
    if qt_application.platformName() != "offscreen":
        pytest.skip("真实系统剪贴板不用于自动化复制测试")
    content = "Result\n" + "long-text " * 4000 + " END"
    notice = show_toast(window, "Details", content, duration=-1)
    assert notice is not None
    notice.content_edit.setFocus()
    QTest.keyClick(notice.content_edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(notice.content_edit, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qt_application.clipboard().text() == content.replace("\n", " ")
    assert notice.content_edit.text() == content.replace("\n", " ")
    assert notice.content == content


def test_duplicate_toasts_merge_and_stack_never_overflows(window, qt_application):
    first = show_toast(window, "完成", "内容相同", duration=-1)
    assert first is not None
    assert show_toast(window, "完成", "内容相同", duration=-1) is first
    notices = [first]
    for index in range(6):
        notices.append(show_toast(window, "提示", f"第{index}项", duration=-1))
    qt_application.processEvents()
    visible = [n for n in notices if isValid(n) and n.isVisible()]
    assert len(visible) == 3
    assert visible[-1].content == "第5项"
    for index, notice in enumerate(visible):
        assert window.rect().contains(notice.geometry())
        if index:
            assert not notice.geometry().intersects(visible[index - 1].geometry())
    window.resize(500, 260)
    qt_application.processEvents()
    for notice in notices:
        if isValid(notice) and notice.isVisible():
            assert window.rect().contains(notice.geometry())


def test_hover_pauses_auto_close_and_leaving_resumes_it(window, qt_application):
    notice = show_toast(window, "提示", "可停留阅读", duration=120)
    assert notice is not None
    destroyed = QSignalSpy(notice.destroyed)
    event = QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))
    QApplication.sendEvent(notice, event)
    QTest.qWait(180)
    assert notice.isVisible() and destroyed.count() == 0
    QApplication.sendEvent(notice, QEvent(QEvent.Type.Leave))
    QTest.qWait(180)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed.count() == 1
    assert not isValid(notice)


def test_action_runs_once_and_does_not_block_window(window, qt_application):
    calls = []
    notice = show_toast(
        window, "截图完成", "结果已保存", duration=-1,
        action_text="查看结果", on_action=lambda: calls.append("opened"),
    )
    assert notice is not None and notice.action_button is not None
    assert QApplication.activeModalWidget() is None
    QTest.mouseClick(notice.action_button, Qt.MouseButton.LeftButton)
    notice._activate_action()
    assert calls == ["opened"]
    assert window.isEnabled()


def test_window_close_releases_toasts_and_timers_and_rejects_late_notifications(
    window, qt_application,
):
    notice = show_toast(window, "错误", "可重试", level="error", duration=30000)
    assert notice is not None
    timer = notice._timer
    destroyed = QSignalSpy(notice.destroyed)
    window._closing = True
    window.close()
    assert not timer.isActive()
    assert show_toast(window, "晚到结果", "不再显示") is None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed.count() == 1
    assert not isValid(timer)


def test_performance_missing_package_shows_toast_and_leaves_form_editable(
    qt_application, monkeypatch, tmp_path,
):
    from tests.test_performance_responsive import _build_performance_page

    values = dict(DEFAULTS, save_directory=str(tmp_path))
    settings = SimpleNamespace(
        get=values.get, set=values.__setitem__, save_directory=str(tmp_path),
    )
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    page, runner = _build_performance_page(package="")
    try:
        page.resize(860, 800)
        page.show()
        page.start_btn.click()
        page.start_btn.click()
        notices = [n for n in page.findChildren(ToastNotification) if n.isVisible()]
        assert len(notices) == 1
        assert notices[0].level == "warning"
        assert QApplication.activeModalWidget() is None
        assert runner.start_count == 0
        assert page.package_edit.isEnabled() and page.start_btn.isEnabled()
        page.package_edit.setFocus()
        QTest.keyClicks(page.package_edit, "com.example.app")
        assert page.package_edit.text() == "com.example.app"
    finally:
        page.close()


def test_toast_sits_below_window_chrome_without_covering_close_button(window):
    window.titleBar = QWidget(window)
    window.titleBar.resize(window.width(), 48)
    window.titleBar.show()
    notice = show_toast(window, "提示", "短正文", duration=-1)
    assert notice is not None
    assert notice.y() == 60
    assert notice.width() < 520
    assert not notice.geometry().intersects(window.titleBar.geometry())
