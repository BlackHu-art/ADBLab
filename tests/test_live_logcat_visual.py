"""Logcat 嵌入模式、中文控件、日志可读性与阅读位置回归。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import CommandBar, PlainTextEdit, ProgressRing, RoundMenu

from gui.features.logcat import LiveLogcatPage
from gui.styles import BaseStyles, FontRole
from tests.test_main_window_layout import _FakeScreen, _FakeScreenAdapter, build_main_frame
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until


def _contrast(first, second):
    def luminance(color):
        parts = [channel / 255 for channel in (color.red(), color.green(), color.blue())]
        values = [part / 12.92 if part <= .04045 else ((part + .055) / 1.055) ** 2.4
                  for part in parts]
        return sum(value * weight for value, weight in zip(values, (.2126, .7152, .0722)))
    values = sorted((luminance(first), luminance(second)))
    return (values[1] + .05) / (values[0] + .05)


def _open_command_menu(page, qt_application):
    """从用户可见的更多入口打开真实菜单，等待其几何动画结束。"""
    assert page._command_bar.moreButton.isVisible()
    assert page._command_bar.moreButton.toolTip()
    assert page._command_bar.moreButton.accessibleName()
    QTest.mouseClick(page._command_bar.moreButton, Qt.MouseButton.LeftButton)
    menus = [menu for menu in page._command_bar.findChildren(RoundMenu) if menu.isVisible()]
    assert len(menus) == 1
    menu = menus[0]
    wait_until(
        qt_application, lambda: menu.aniManager.ani.state() == QAbstractAnimation.State.Stopped,
    )
    return menu


def _menu_item_for_action(menu, action):
    return next(menu.view.item(index) for index in range(menu.view.count())
                if menu.view.item(index).data(Qt.ItemDataRole.UserRole) is action)


def _click_menu_action(menu, action):
    item = _menu_item_for_action(menu, action)
    QTest.mouseClick(
        menu.view.viewport(), Qt.MouseButton.LeftButton,
        pos=menu.view.visualItemRect(item).center(),
    )


def _assert_commands_reachable(page, qt_application):
    """六个操作必须由行内按钮和真实溢出菜单完整覆盖。"""
    bar = page._command_bar
    assert isinstance(bar, CommandBar)
    expected = {getattr(page, f"{name}_action")
                for name in ("start", "stop", "follow", "wrap", "export", "clear")}
    assert set(bar.actions()) == expected
    visible = {button.action() for button in bar.commandButtons if button.isVisible()}
    if visible == expected:
        assert not bar.moreButton.isVisible()
        return
    menu = _open_command_menu(page, qt_application)
    try:
        assert set(menu.actions()) | visible == expected
        assert set(menu.actions()).isdisjoint(visible)
        for action in menu.actions():
            item = _menu_item_for_action(menu, action)
            assert bool(item.flags() & Qt.ItemFlag.ItemIsEnabled) == action.isEnabled()
    finally:
        menu.close()
        qt_application.processEvents()


def _assert_single_line_status(page):
    """状态与缓存环共用一行，窄屏和大字体下仍不侵占命令或正文。"""
    status = page.status_bar
    ring = page.cache_ring
    assert isinstance(ring, ProgressRing)
    assert ring.size() == QSize(28, 28)
    assert not ring.isTextVisible()
    assert not status.wordWrap()
    assert status.width() <= page.actions.width() // 4 + 2
    status_rect = QRect(status.mapTo(page.actions, QPoint()), status.size())
    ring_rect = QRect(ring.mapTo(page.actions, QPoint()), ring.size())
    assert page.actions.rect().contains(status_rect)
    assert page.actions.rect().contains(ring_rect)
    assert abs(status_rect.center().y() - ring_rect.center().y()) <= 1
    assert status_rect.right() < ring_rect.left()
    assert not status_rect.intersects(ring_rect)
    group_rect = QRect(page._status_group.mapTo(page, QPoint()), page._status_group.size())
    assert page.actions.geometry().contains(group_rect)
    assert group_rect.bottom() < page.output.geometry().top()


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
    assert page.start_btn.accessibleName() == "开始采集"
    assert page.stop_btn.accessibleName() == "停止采集"
    assert page.follow_btn.accessibleName() == "跟随最新"
    assert page.wrap_btn.accessibleName() == "自动换行"
    for name, text in (
        ("start", "开始"), ("stop", "停止"), ("follow", "跟随"),
        ("wrap", "换行"), ("export", "导出"), ("clear", "清空"),
    ):
        assert getattr(page, f"{name}_btn").text() == text
    assert page.follow_btn.toolTip()
    buttons = tuple(page._command_bar.commandButtons)
    for button in buttons:
        assert button.font().pointSize() == font_size
        assert button.height() >= button.fontMetrics().height() + 12
        assert button.isEnabled() == button.action().isEnabled()
        assert button.isChecked() == button.action().isChecked()
    controls = (page.level_combo, page.pkg_input, page.btn_get_pkg, page.status_bar)
    visible_buttons = tuple(button for button in (*buttons, page._command_bar.moreButton)
                            if button.isVisible())
    for control in (*controls, *visible_buttons):
        assert control.isVisibleTo(owner)
        assert control.font().pointSize() == font_size
        assert control.height() >= control.fontMetrics().height()
        assert page.rect().contains(QRect(control.mapTo(page, QPoint()), control.size()))
    assert page.pkg_input.height() >= page.pkg_input.fontMetrics().height() + 14
    assert page.output.height() >= page.output.fontMetrics().lineSpacing() * 6
    for row in ((page.level_combo, page.pkg_input, page.btn_get_pkg), visible_buttons):
        rects = [QRect(control.mapTo(page, QPoint()), control.size()) for control in row]
        assert max(rect.top() for rect in rects) < min(rect.bottom() for rect in rects)
        assert all(not left.intersects(right) for index, left in enumerate(rects)
                   for right in rects[index + 1:])
    assert page.level_combo.geometry().bottom() < page.actions.geometry().top()
    assert page.actions.geometry().bottom() < page.output.geometry().top()
    assert page.actions.rect().contains(QRect(
        page._status_group.mapTo(page.actions, QPoint()), page._status_group.size(),
    ))
    assert page._status_group.geometry().left() > page._command_bar.geometry().right()
    assert page.cache_ring.isVisibleTo(owner)
    _assert_single_line_status(page)
    _assert_commands_reachable(page, qt_application)
    page.wrap_btn.click()
    assert page.wrap_action.isChecked()
    assert page.wrap_btn.isChecked()
    page.close()
    owner.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("focused", [False, True])
def test_logcat_output_background_and_all_levels_keep_readable_contrast(
    qt_application, theme, focused
):
    page = LiveLogcatPage(device_ip="demo-a")
    reference = PlainTextEdit(page.output.parentWidget())
    reference.setReadOnly(True)
    reference.resize(180, 100)
    page.resize(700, 500)
    page.show()
    BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
    BaseStyles.switch_theme(theme)
    qt_application.processEvents()

    def surface_color(editor):
        image = page.grab().toImage()
        point = editor.viewport().mapTo(page, editor.viewport().rect().center())
        scale = image.devicePixelRatio()
        return image.pixelColor(round(point.x() * scale), round(point.y() * scale))

    # 同一几何区域轮流绘制，避免参考框覆盖标题卡片或透出原输出框而重复叠色。
    page.layout().setEnabled(False)
    reference.setGeometry(page.output.geometry())
    page.output.hide()
    reference.setVisible(True)
    if focused:
        reference.setFocus()
    else:
        page.pkg_input.setFocus()
    qt_application.processEvents()
    for control in (reference, reference.viewport()):
        qt_application.sendEvent(control, QEvent(QEvent.Type.Leave))
        assert not control.underMouse()
    expected = surface_color(reference)
    reference.hide()
    page.output.show()
    if focused:
        page.output.setFocus()
    else:
        page.pkg_input.setFocus()
    qt_application.processEvents()
    for control in (page.output, page.output.viewport()):
        qt_application.sendEvent(control, QEvent(QEvent.Type.Leave))
        assert not control.underMouse()
    assert surface_color(page.output) == expected
    page.layout().setEnabled(True)
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
        assert page.cache_ring.value() == 125
        assert "125 / 8000" in page.cache_ring.toolTip()
        assert "5 行新日志" in page.cache_ring.toolTip()
        assert len(page.entries) == 125
        page.follow_btn.click()
        assert page.follow_btn.isChecked()
        assert bar.value() == bar.maximum()
        assert "已暂停跟随" not in page.cache_ring.toolTip()
        page._on_line("pending before clear", "I")
        page.clear_btn.click()
        page._flush_pending_lines()
        assert page.output.toPlainText() == ""
        assert not page.entries
        assert page.cache_ring.value() == 0
        assert "0 / 8000" in page.cache_ring.toolTip()
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
        assert page.cache_ring.value() == page.cache_ring.maximum() == page.MAX_BUFFER
        assert "8000 / 8000" in page.cache_ring.toolTip()
        assert page.output.horizontalScrollBar().maximum() > 0
        frame.resize(860, 700)
        qt_application.processEvents()
        QTest.qWait(350)
        outer = host.content_scroll
        outer.ensureWidgetVisible(page.output, 0, 0)
        qt_application.processEvents()
        output_rect = QRect(page.output.mapTo(outer.viewport(), QPoint()), page.output.size())
        assert outer.viewport().rect().contains(output_rect)
        follow_entry = (page.follow_btn if page.follow_btn.isVisible()
                        else page._command_bar.moreButton)
        outer.ensureWidgetVisible(follow_entry, 0, 0)
        qt_application.processEvents()
        button_rect = QRect(
            follow_entry.mapTo(outer.viewport(), QPoint()), follow_entry.size()
        )
        assert outer.viewport().rect().contains(button_rect)
        _assert_commands_reachable(page, qt_application)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_logcat_return_from_performance_keeps_output_inside_view_and_reading_state(
    qt_application, monkeypatch,
):
    monkeypatch.setattr("models.device_store.DeviceStore.get_basic_devices_info", lambda: [])
    monkeypatch.setattr(
        "models.device_store.DeviceStore.get_full_devices_info", lambda _devices: [],
    )
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("logcat", QSize(1600, 1100)))
    )
    try:
        frame.show()
        frame.resize(1048, 650)
        frame._on_devices_updated(["demo-a"])
        frame.left_panel._devices_tab.set_selected_devices(["demo-a"])
        host = frame._workspace_feature_hosts["system"]

        def settle():
            wait_until(qt_application, lambda: (
                frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped
                and frame.navigationInterface.panel.expandAni.state()
                == QAbstractAnimation.State.Stopped
            ))
            wait_for_stable_geometry(qt_application, (
                frame, host.content_scroll, host.stack, host.stack.currentWidget(),
            ))

        assert frame._open_workspace_feature("system", "logcat", device_id="demo-a")
        settle()
        page = host.stack.currentWidget()
        for index in range(300):
            page._on_line(f"synthetic record {index} " + "message " * 30, "I")
        page._flush_pending_lines()
        settle()
        output_size = page.output.size()
        bar = page.output.verticalScrollBar()
        bar.setValue(bar.maximum() // 3)
        anchor = page.output.firstVisibleBlock().text()
        assert not page.follow_btn.isChecked()

        assert frame._open_workspace_feature("system", "performance", device_id="demo-a")
        settle()
        assert frame._open_workspace_feature("system", "logcat", device_id="demo-a")
        settle()

        assert host.stack.currentWidget() is page
        assert host.content_scroll.verticalScrollBar().maximum() == 0
        assert page.height() == host.content_scroll.viewport().height()
        assert page.output.size() == output_size
        assert not page.follow_btn.isChecked()
        page._on_line("record added after return", "W")
        page._flush_pending_lines()
        assert page.output.firstVisibleBlock().text() == anchor
        page.wrap_btn.click()
        assert page.wrap_btn.isChecked() and not page.follow_btn.isChecked()
        page.follow_btn.click()
        settle()
        assert page.follow_btn.isChecked()
        assert bar.value() == bar.maximum()
        cursor = QTextCursor(page.output.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        tail = page.output.viewport().mapTo(
            host.content_scroll.viewport(), page.output.cursorRect(cursor).center(),
        )
        assert host.content_scroll.viewport().rect().contains(tail)
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
        assert "1 行新日志" in page.cache_ring.toolTip()
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
        output_rect = QRect(page.output.mapTo(outer.viewport(), QPoint()), page.output.size())
        assert outer.viewport().rect().contains(output_rect)
        for control in (page.actions, page.cache_ring):
            outer.ensureWidgetVisible(control, 0, 0)
            qt_application.processEvents()
            rect = QRect(control.mapTo(outer.viewport(), QPoint()), control.size())
            assert outer.viewport().rect().contains(rect)
        _assert_commands_reachable(page, qt_application)
        assert not page.follow_action.isChecked()
        assert "1 行新日志" in page.cache_ring.toolTip()
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


@pytest.mark.ui
def test_logcat_overflow_clear_tracks_content_and_dispatches_once(qt_application):
    """空日志禁用清空，菜单打开后新增日志也能同步启用，并只清理一次。"""
    page = LiveLogcatPage(device_ip="demo-a")
    page.resize(420, 700)
    page.show()
    qt_application.processEvents()
    try:
        assert not page.clear_btn.isVisible()
        menu = _open_command_menu(page, qt_application)
        action = page.clear_action
        spy = QSignalSpy(action.triggered)
        item = _menu_item_for_action(menu, action)
        assert not action.isEnabled()
        assert not item.flags() & Qt.ItemFlag.ItemIsEnabled
        _click_menu_action(menu, action)
        assert spy.count() == 0
        assert menu.isVisible()
        page._on_line("incoming record", "I")
        page._flush_pending_lines()
        qt_application.processEvents()
        assert action.isEnabled()
        assert item.flags() & Qt.ItemFlag.ItemIsEnabled
        assert page.clear_btn.isEnabled()
        _click_menu_action(menu, action)
        assert spy.count() == 1
        assert not page.entries
        assert page.output.toPlainText() == ""
        assert not action.isEnabled()
        assert not page.clear_btn.isEnabled()
    finally:
        page.close()


@pytest.mark.ui
@pytest.mark.parametrize("name", ["follow", "wrap"])
def test_logcat_overflow_reading_action_toggles_once_and_returns_inline(
    qt_application, monkeypatch, name,
):
    """大字体窄屏菜单与恢复宽屏后的按钮共享阅读状态，单击只切换一次。"""
    monkeypatch.setattr(
        BaseStyles, "font_for_role", classmethod(lambda _cls, role, size=None: QFont(
            "Consolas" if role in (FontRole.LOG, FontRole.MONO) else "Microsoft YaHei",
            size or 22,
        )),
    )
    page = LiveLogcatPage(device_ip="demo-a")
    page.resize(420, 700)
    page.show()
    qt_application.processEvents()
    try:
        button = getattr(page, f"{name}_btn")
        action = getattr(page, f"{name}_action")
        assert not button.isVisible()
        before = action.isChecked()
        spy = QSignalSpy(action.triggered)
        menu = _open_command_menu(page, qt_application)
        _click_menu_action(menu, action)
        qt_application.processEvents()
        assert spy.count() == 1
        assert action.isChecked() is not before
        assert button.isChecked() == action.isChecked()
        if name == "follow":
            assert "已暂停跟随" in page.cache_ring.toolTip()
        else:
            assert page.output.lineWrapMode() == page.output.LineWrapMode.WidgetWidth
        page.resize(1800, 700)
        qt_application.processEvents()
        assert button.isVisible()
        assert button.isChecked() == action.isChecked()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert spy.count() == 2
        assert action.isChecked() == before
        if name == "follow":
            assert "已暂停跟随" not in page.cache_ring.toolTip()
        else:
            assert page.output.lineWrapMode() == page.output.LineWrapMode.NoWrap
    finally:
        page.close()


@pytest.mark.ui
def test_logcat_top_status_preserves_full_text_without_shrinking_output(qt_application):
    """顶部绘制短状态，完整原因与暂停计数仍可从提示及辅助描述获取。"""
    page = LiveLogcatPage(device_ip="demo-a")
    page.resize(420, 700)
    page.show()
    qt_application.processEvents()
    try:
        output_size = page.output.size()
        toolbar_height = page.actions.height()
        assert page.status_bar.compactText() == "待采集"
        message = "采集已停止：" + "连接状态发生变化，请检查设备连接。" * 12
        page.status_bar.setText("已停止")
        compact_image = page.status_bar.grab().toImage()
        page.status_bar.setText(message, "已停止")
        assert page.status_bar.grab().toImage() == compact_image
        page.follow_btn.click()
        for index in range(12):
            page._on_line(f"incoming record {index}", "I")
        page._flush_pending_lines()
        qt_application.processEvents()
        assert page.output.size() == output_size
        assert page.actions.height() == toolbar_height
        assert page.status_bar.text() == message
        assert page.status_bar.compactText() == "已停止"
        assert message in page.status_bar.toolTip()
        assert page.status_bar.accessibleDescription() == message
        assert page.cache_ring.value() == 12
        for description in (page.cache_ring.toolTip(), page.cache_ring.accessibleDescription()):
            assert "缓存 12 / 8000 行" in description
            assert "已暂停跟随" in description
            assert "12 行新日志" in description
            assert "仅保留最近 8000 行原始日志" in description
            assert "导出保存当前筛选结果" in description
        assert page.status_bar.height() >= page.status_bar.fontMetrics().height()
        _assert_single_line_status(page)
    finally:
        page.close()
