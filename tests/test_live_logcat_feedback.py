"""Logcat 交互反馈与正文边界回归，不启动设备命令。"""

from collections import deque

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QFont, QIcon, QTextCursor
from PySide6.QtTest import QSignalSpy, QTest
from qfluentwidgets import themeColor

from adblab.application.supervision import StopDisposition, TaskStopResult
from gui.dialogs.live_logcat import LiveLogcatPage, LogcatBatch, LogcatWorker
from gui.dialogs.live_logcat_worker import LogcatTermination, LogcatTerminationKind
from gui.styles import BaseStyles, FontRole
from tests.test_phase2_live_logcat_gate import FakeQtTaskSupervisor
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


class PaintCounter(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.count = 0
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.count += 1
        return False


def test_start_feedback_precedes_worker_dispatch(qt_application, monkeypatch):
    page = LiveLogcatPage(device_ip="demo", task_supervisor=FakeQtTaskSupervisor())
    statuses = []
    monkeypatch.setattr(LogcatWorker, "start", lambda _worker: statuses.append(
        page.status_bar.compactText()
    ))
    try:
        page._start()
        assert statuses == ["启动中"]
        assert not page.start_action.isEnabled()
        assert page.stop_action.isEnabled()
    finally:
        if page.worker is not None:
            page.worker._finished_event.set()
            page._on_worker_finished(page.worker)
        page.close()


@pytest.mark.parametrize("notification", ["status", "batch", "dropped"])
def test_stopping_feedback_survives_queued_capture_messages(
    qt_application, monkeypatch, notification,
):
    page = LiveLogcatPage(device_ip="demo", task_supervisor=FakeQtTaskSupervisor())
    monkeypatch.setattr(LogcatWorker, "start", lambda _worker: None)
    try:
        page._start()
        worker = page.worker
        page._stop()
        if notification == "status":
            page._on_worker_status(worker, "正在采集")
        elif notification == "batch":
            acknowledgements = []
            monkeypatch.setattr(worker, "acknowledge_batch", lambda: acknowledgements.append(True))
            page._on_lines(worker, LogcatBatch((("last line", "I", 0),), dropped_before=1))
            page._flush_pending_lines()
            assert page.output.toPlainText() == "last line"
            assert acknowledgements == [True]
        else:
            page._on_dropped(worker, 1)
        assert page.status_bar.compactText() == "停止中"
        assert not page.stop_action.isEnabled()
    finally:
        if page.worker is not None:
            page.worker._finished_event.set()
            page._on_worker_finished(page.worker)
        page.close()


@pytest.mark.parametrize("disposition", [StopDisposition.TIMED_OUT, StopDisposition.FAILED])
def test_late_termination_keeps_explicit_stop_result(qt_application, monkeypatch, disposition):
    adapter = FakeQtTaskSupervisor()
    page = LiveLogcatPage(device_ip="demo", task_supervisor=adapter)
    monkeypatch.setattr(LogcatWorker, "start", lambda _worker: None)
    try:
        page._start()
        worker = page.worker
        page._stop()
        page._on_task_stopped(TaskStopResult(
            page._supervisor_task_id, page._supervisor_owner_id, disposition,
        ))
        status = page.status_bar.text()
        page._on_worker_terminated(worker, LogcatTermination(LogcatTerminationKind.CANCELLED))
        assert page.status_bar.text() == status
        worker._finished_event.set()
        page._on_worker_finished(worker)
        assert page.worker is None
        assert page.start_action.isEnabled()
    finally:
        if page.worker is not None:
            page.worker._finished_event.set()
            page._on_worker_finished(page.worker)
        page.close()


def test_small_cache_increment_schedules_ring_repaint(qt_application):
    page = LiveLogcatPage(device_ip="demo")
    page.resize(980, 600)
    page.show()
    try:
        page.entries = deque((("line", "I", 0),) * 1000, maxlen=page.MAX_BUFFER)
        page._stream_controller._refresh_reading_status()
        QTest.qWait(100)
        counter = PaintCounter(page.cache_ring)
        page.entries.append(("small increment", "I", 0))
        page._stream_controller._refresh_reading_status()
        QTest.qWait(30)
        assert page.cache_ring.value() == 1001
        assert counter.count > 0
    finally:
        page.close()


@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_embedded_log_alignment_and_edge_scrollbars(qt_application, monkeypatch, font_size, theme):
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, role, size=None: QFont(
            "Consolas" if role in (FontRole.LOG, FontRole.MONO) else "Microsoft YaHei",
            size or font_size,
        )
    ))
    BaseStyles.switch_theme(theme)
    page = LiveLogcatPage(device_ip="demo")
    page.set_workspace_embedded(True)
    page.resize(980, 650)
    page.show()
    try:
        for embedded in (False, True):
            page.set_workspace_embedded(embedded)
            assert page.output.viewportMargins().left() == 14
            assert page.output.viewportMargins().right() == 14
        page.output.setPlainText("\n".join(
            f"line {index} " + "content " * 120 for index in range(100)
        ))
        qt_application.processEvents()
        cursor = QTextCursor(page.output.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        text_left = page.output.viewport().mapTo(page, page.output.cursorRect(cursor).topLeft()).x()
        controls_left = page._level_label.mapTo(page, QPoint()).x()
        viewport_right = page.output.viewport().mapTo(
            page, page.output.viewport().rect().topRight(),
        ).x()
        assert page.output.geometry().left() == 0
        assert page.output.geometry().right() == page.width() - 1
        assert text_left == page.width() - 1 - viewport_right == 14
        assert controls_left == 32
        vertical = page.output.scrollDelegate.vScrollBar
        horizontal = page.output.scrollDelegate.hScrollBar
        assert vertical.isVisible()
        assert horizontal.isVisible()
        assert page.width() - vertical.mapTo(page, vertical.rect().topRight()).x() <= 2
        assert page.height() - horizontal.mapTo(page, horizontal.rect().bottomLeft()).y() <= 2
        for button in (page.follow_btn, page.wrap_btn):
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            assert not button.property("adblabKeyboardFocus")
            assert button.property("adblabKeyboardFocusOnly")
    finally:
        page.close()


@pytest.mark.parametrize("name", ["follow", "wrap"])
def test_reading_switch_retains_keyboard_feedback_and_single_dispatch(qt_application, name):
    page = LiveLogcatPage(device_ip="demo")
    page.resize(980, 650)
    page.show()
    try:
        qt_application.processEvents()
        button = getattr(page, f"{name}_btn")
        action = getattr(page, f"{name}_action")
        spy = QSignalSpy(action.triggered)
        before = action.isChecked()
        button.setFocus(Qt.FocusReason.TabFocusReason)
        qt_application.processEvents()
        assert button.hasFocus()
        assert button.property("adblabKeyboardFocus")
        QTest.keyClick(button, Qt.Key.Key_Space)
        assert spy.count() == 1
        assert button.isChecked() == action.isChecked() == (not before)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert spy.count() == 2
        assert button.isChecked() == action.isChecked() == before
        assert not button.property("adblabKeyboardFocus")
    finally:
        page.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_horizontal_scrollbar_fades_out_after_pointer_leaves(qt_application, theme):
    BaseStyles.switch_theme(theme)
    page = LiveLogcatPage(device_ip="demo")
    page.set_workspace_embedded(True)
    page.resize(860, 500)
    page.show()
    try:
        page.output.setPlainText("long log " * 300)
        qt_application.processEvents()
        bar = page.output.scrollDelegate.hScrollBar
        native = page.output.horizontalScrollBar()
        assert native.maximum() > 0
        QTest.mouseMove(page.pkg_input, page.pkg_input.rect().center())
        wait_until(qt_application, lambda: bar.handle.opacity == 0)
        QTest.mouseMove(bar, bar.handle.geometry().center())
        wait_until(qt_application, lambda: bar.handle.opacity == 1)
        origin = bar.handle.geometry().center()
        QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=origin)
        QTest.mouseMove(bar, origin + QPoint(60, 0))
        QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=origin + QPoint(60, 0))
        assert native.value() > 0
        position = native.value()
        QTest.mouseMove(page.pkg_input, page.pkg_input.rect().center())
        wait_until(qt_application, lambda: bar.handle.opacity == 0)
        assert native.value() == position
        page.wrap_btn.click()
        qt_application.processEvents()
        assert not bar.isVisible()
        page.wrap_btn.click()
        qt_application.processEvents()
        assert bar.isVisible()
        assert bar.handle.opacity == 0
        page._clear()
        qt_application.processEvents()
        assert not bar.isVisible()
    finally:
        page.close()


@pytest.mark.parametrize("text", ["x" * 3000, "中文日志" * 1000], ids=["latin", "cjk"])
def test_wrapping_hides_tiny_overflow_even_during_scrollbar_hover(qt_application, text):
    page = LiveLogcatPage(device_ip="demo")
    page.set_workspace_embedded(True)
    page.resize(860, 500)
    page.show()
    try:
        page.output.setPlainText(text)
        qt_application.processEvents()
        bar = page.output.scrollDelegate.hScrollBar
        QTest.mouseMove(bar, bar.handle.geometry().center())
        wait_until(qt_application, lambda: bar.handle.opacity == 1)
        for _ in range(3):
            page.wrap_btn.click()
            qt_application.processEvents()
            assert not bar.isVisible()
            page.wrap_btn.click()
            qt_application.processEvents()
            assert bar.isVisible()
        QTest.mouseMove(page.pkg_input, page.pkg_input.rect().center())
        wait_until(qt_application, lambda: bar.handle.opacity == 0)
    finally:
        page.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("font_size", [12, 22])
def test_empty_hint_is_centered_without_changing_log_insets(
    qt_application, monkeypatch, theme, font_size,
):
    original_font = BaseStyles.font_for_role
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, role, size=None: QFont("Microsoft YaHei", font_size)
        if role == FontRole.UI else original_font(role, size)
    ))
    BaseStyles.switch_theme(theme)
    page = LiveLogcatPage(device_ip="demo")
    page.set_workspace_embedded(True)
    page.resize(700, 500)
    page.show()
    try:
        qt_application.processEvents()
        output = page.output
        text = output.placeholderText()
        with_hint = output.viewport().grab().toImage()
        output.setPlaceholderText("")
        blank = output.viewport().grab().toImage()
        width, height = with_hint.width(), with_hint.height()
        assert with_hint.copy(0, 0, width, height // 4) == blank.copy(0, 0, width, height // 4)
        assert (with_hint.copy(0, height // 3, width, height // 3)
                != blank.copy(0, height // 3, width, height // 3))
        output.setPlaceholderText(text)
        output.setPlainText("visible log")
        with_content = output.viewport().grab().toImage()
        output.setPlaceholderText("")
        assert output.viewport().grab().toImage() == with_content
        assert output.viewportMargins().left() == output.viewportMargins().right() == 14
    finally:
        page.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_reading_button_feedback_matches_toolbar(qt_application, theme):
    BaseStyles.switch_theme(theme)
    page = LiveLogcatPage(device_ip="demo")
    page.resize(980, 650)
    page.show()
    try:
        qt_application.processEvents()
        reference = page.start_btn
        for state in ("hover", "pressed", "keyboard"):
            backgrounds = []
            for button in (reference, page.follow_btn, page.wrap_btn):
                if state == "keyboard":
                    QTest.mouseMove(page.pkg_input, page.pkg_input.rect().center())
                    button.setFocus(Qt.FocusReason.TabFocusReason)
                    assert button.hasFocus()
                else:
                    QTest.mouseMove(button, button.rect().center())
                if state == "pressed":
                    QTest.mousePress(button, Qt.MouseButton.LeftButton)
                image = button.grab().toImage()
                scale = image.devicePixelRatio()
                backgrounds.append(image.copy(0, 0, round(10 * scale), round(10 * scale)))
                if state == "pressed":
                    # 松开在按钮外，避免样式检查触发真实采集。
                    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=QPoint(-2, -2))
            assert backgrounds[1:] == [backgrounds[0], backgrounds[0]]
    finally:
        page.close()


@pytest.mark.parametrize("follow", [True, False])
@pytest.mark.parametrize("selected", [False, True])
def test_wrap_switch_stays_at_line_start_with_tail_cursor(qt_application, follow, selected):
    page = LiveLogcatPage(device_ip="demo")
    page.set_workspace_embedded(True)
    page.resize(860, 500)
    page.show()
    try:
        for index in range(80):
            page._on_line(f"row {index:03d} " + "long words " * 100, "I")
        page._flush_pending_lines()
        qt_application.processEvents()
        output = page.output
        cursor = output.textCursor()
        assert cursor.atEnd()
        if selected:
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, 15)
            output.setTextCursor(cursor)
        selection = cursor.selectionStart(), cursor.selectionEnd()
        vertical = output.verticalScrollBar()
        if not follow:
            vertical.setValue(vertical.maximum() // 3)
        anchor = output.firstVisibleBlock().text()
        output.horizontalScrollBar().setValue(0)
        for _ in range(8):
            QTest.mouseClick(page.wrap_btn, Qt.MouseButton.LeftButton)
            qt_application.processEvents()
            assert output.horizontalScrollBar().value() == 0
            assert page.follow_btn.isChecked() == follow
            current_cursor = output.textCursor()
            assert (current_cursor.selectionStart(), current_cursor.selectionEnd()) == selection
            if follow:
                assert vertical.value() == vertical.maximum()
            else:
                assert output.firstVisibleBlock().text() == anchor
    finally:
        page.close()


def _accent_pixels(image):
    color = themeColor()
    # 16 像素细线含半透明抗锯齿，反预乘会产生少量 RGB 舍入误差。
    return sum(
        pixel.alpha() >= 100
        and max(abs(pixel.red() - color.red()), abs(pixel.green() - color.green()),
                abs(pixel.blue() - color.blue())) <= 2
        for y in range(image.height()) for x in range(image.width())
        for pixel in (image.pixelColor(x, y),)
    )


def _assert_action_icon_state(action):
    image = action.icon().pixmap(24, 24, QIcon.Mode.Normal, QIcon.State.Off).toImage()
    assert bool(_accent_pixels(image)) == action.isChecked()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("font_size", [12, 22])
def test_reading_icons_change_color_without_changing_text_or_underlining(
    qt_application, monkeypatch, theme, font_size,
):
    original_accent = BaseStyles.accent_color()
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, role, size=None: QFont("Microsoft YaHei", size or font_size)
    ))
    BaseStyles.switch_theme(theme)
    page = LiveLogcatPage(device_ip="demo")
    page.resize(1500, 650)
    page.show()
    try:
        qt_application.processEvents()
        QTest.mouseMove(page.pkg_input, page.pkg_input.rect().center())
        for color in ("#9C27B0", "#087F5B"):
            BaseStyles.set_accent_color(color)
            qt_application.processEvents()
            for button, label in ((page.follow_btn, "跟随"), (page.wrap_btn, "换行")):
                if button.isChecked():
                    button.click()
                off_image = button.grab().toImage()
                assert _accent_pixels(off_image) == 0
                button.click()
                on_image = button.grab().toImage()
                assert button.text() == button.action().text() == label
                assert _accent_pixels(on_image) > 0
                _assert_action_icon_state(button.action())
                # 图标之后的文字与底部区域均保持不变，不能残留旧指示线。
                ratio = on_image.devicePixelRatio()
                text_left = round(29 * ratio)
                assert on_image.copy(text_left, 0, on_image.width() - text_left,
                                     on_image.height()) == off_image.copy(
                    text_left, 0, off_image.width() - text_left, off_image.height(),
                )
                bottom = round((button.height() - 5) * ratio)
                assert on_image.copy(0, bottom, on_image.width(), on_image.height() - bottom) == (
                    off_image.copy(0, bottom, off_image.width(), off_image.height() - bottom)
                )
                button.click()
                assert button.grab().toImage() == off_image
    finally:
        page.close()
        BaseStyles.set_accent_color(original_accent)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_reading_icons_follow_scroll_wrap_and_live_theme(qt_application, theme):
    original_accent = BaseStyles.accent_color()
    BaseStyles.switch_theme(theme)
    BaseStyles.set_accent_color("#9C27B0")
    page = LiveLogcatPage(device_ip="demo")
    page.resize(980, 650)
    page.show()
    try:
        for index in range(100):
            page._on_line(f"row {index:03d} " + "long words " * 50, "I")
        page._flush_pending_lines()
        qt_application.processEvents()
        for action in (page.follow_action, page.wrap_action):
            _assert_action_icon_state(action)
        vertical = page.output.verticalScrollBar()
        assert vertical.maximum() > 0
        vertical.setValue(vertical.maximum() // 3)
        assert not page.follow_action.isChecked()
        _assert_action_icon_state(page.follow_action)
        for _ in range(4):
            page.wrap_btn.click()
            assert not page.follow_action.isChecked()
            _assert_action_icon_state(page.wrap_action)
            _assert_action_icon_state(page.follow_action)
        vertical.setValue(vertical.maximum())
        assert page.follow_action.isChecked()
        _assert_action_icon_state(page.follow_action)
        page.wrap_btn.click()
        BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
        for action in (page.follow_action, page.wrap_action):
            assert action.isChecked()
            _assert_action_icon_state(action)
        vertical.setValue(vertical.maximum() // 3)
        before = (page.output.firstVisibleBlock().text(), vertical.value(), page.output.font())
        for color in ("#087F5B", "#D05070"):
            BaseStyles.set_accent_color(color)
            qt_application.processEvents()
            for action in (page.follow_action, page.wrap_action):
                _assert_action_icon_state(action)
            assert not page.follow_action.isChecked()
            assert before == (
                page.output.firstVisibleBlock().text(), vertical.value(), page.output.font(),
            )
        # 用户再次开启跟随会恢复到末尾，颜色不能只响应鼠标而漏掉滚动导致的变化。
        page.wrap_btn.click()
        qt_application.processEvents()
        _assert_action_icon_state(page.wrap_action)
        page.follow_btn.click()
        wait_until(qt_application, lambda: vertical.value() == vertical.maximum())
        assert page.follow_action.isChecked()
        _assert_action_icon_state(page.follow_action)
        keys = [action.icon().cacheKey() for action in (page.follow_action, page.wrap_action)]
        page.close()
        BaseStyles.set_accent_color("#9C27B0")
        qt_application.processEvents()
        assert keys == [action.icon().cacheKey()
                        for action in (page.follow_action, page.wrap_action)]
    finally:
        page.close()
        BaseStyles.set_accent_color(original_accent)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_reading_icon_colors_stay_in_sync_in_overflow_menu(
    qt_application, monkeypatch, theme,
):
    from tests.test_live_logcat_visual import (
        _click_menu_action,
        _menu_item_for_action,
        _open_command_menu,
    )

    original_accent = BaseStyles.accent_color()
    BaseStyles.switch_theme(theme)
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, role, size=None: QFont("Microsoft YaHei", size or 22)
    ))
    page = LiveLogcatPage(device_ip="demo")
    page.resize(420, 700)
    page.show()
    try:
        qt_application.processEvents()
        for action, button in ((page.follow_action, page.follow_btn),
                               (page.wrap_action, page.wrap_btn)):
            assert not button.isVisible()
            before = action.isChecked()
            spy = QSignalSpy(action.triggered)
            menu = _open_command_menu(page, qt_application)
            _click_menu_action(menu, action)
            assert spy.count() == 1
            assert action.isChecked() is not before
            _assert_action_icon_state(action)
            menu = _open_command_menu(page, qt_application)
            try:
                BaseStyles.set_accent_color("#9C27B0" if before else "#087F5B")
                qt_application.processEvents()
                item = _menu_item_for_action(menu, action)
                image = item.icon().pixmap(24, 24).toImage()
                assert bool(_accent_pixels(image)) == action.isChecked()
            finally:
                menu.close()
        page.resize(1500, 700)
        qt_application.processEvents()
        for action, button in ((page.follow_action, page.follow_btn),
                               (page.wrap_action, page.wrap_btn)):
            assert button.isVisible()
            assert action.isChecked() == button.isChecked()
            _assert_action_icon_state(action)
    finally:
        page.close()
        BaseStyles.set_accent_color(original_accent)
