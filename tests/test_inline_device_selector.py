"""页内设备选择的布局、焦点与原操作归属回归。"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QFont, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, PushButton

from gui.i18n import install_translators, tr
from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceContextBar
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def selector(qt_application):
    window = QWidget()
    window.resize(730, 680)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    bar = DeviceContextBar(window)
    body = QWidget(window)
    layout.addWidget(bar)
    layout.addWidget(body, 1)
    bar.set_context(["demo-a"], ["demo-a", "demo-b"], "ready")
    window.show()
    qt_application.processEvents()
    yield window, bar, body
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_inline_selector_pushes_body_and_reuses_one_embedded_widget(selector, qt_application):
    window, bar, body = selector
    initial_y = body.y()
    top_levels = set(QApplication.topLevelWidgets())
    bar.open_picker()
    wait_for_stable_geometry(qt_application, (bar, body))
    picker = bar._picker
    assert not picker.isWindow()
    assert picker.window() is window
    assert set(QApplication.topLevelWidgets()) == top_levels
    assert bar.is_selector_expanded and body.y() > initial_y
    bar.open_picker()
    assert bar._picker is picker
    bar.collapse_selector()
    wait_for_stable_geometry(qt_application, (bar, body))
    assert not bar.is_selector_expanded and body.y() == initial_y
    bar.open_picker()
    assert bar._picker is picker


def test_mounted_selector_content_does_not_fill_over_shared_material(selector):
    _window, bar, _body = selector
    bar.open_picker()
    picker = bar._picker
    assert not picker.content.autoFillBackground()
    assert not picker.scroll_area.viewport().autoFillBackground()
    assert not picker.device_list.viewport().autoFillBackground()


def test_expander_button_tracks_open_close_and_keyboard_escape(selector, qt_application):
    _window, bar, _body = selector
    button = bar.targets_button
    collapsed_text = button.text()
    assert button.isCheckable() and not button.isChecked()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert bar.is_selector_expanded and button.isChecked()
    assert button.text() == "收起设备"
    assert "收起设备" in button.accessibleName()
    bar._picker.device_list.setFocus()
    QTest.keyClick(bar._picker.device_list, Qt.Key.Key_Escape)
    qt_application.processEvents()
    assert not bar.is_selector_expanded and not button.isChecked()
    assert button.text() == collapsed_text


def test_selector_reserves_five_rows_regardless_of_device_count(selector, qt_application):
    window, bar, _body = selector
    window.resize(730, 1000)
    bar.open_picker()
    heights = []
    for count in (0, 1, 5, 8):
        bar.set_context([], [f"demo-{i}" for i in range(count)], "ready")
        picker = bar._picker
        wait_for_stable_geometry(qt_application, (window, bar, picker))
        heights.append(picker.height())
        row_height = picker.device_list.sizeHintForRow(0)
        assert picker.scroll_area.height() >= row_height * 5 + picker.toolbar.height()
        if count <= 5:
            assert picker.scroll_area.verticalScrollBar().maximum() == 0
        else:
            assert picker.scroll_area.verticalScrollBar().maximum() > 0
        assert picker.device_list.y() <= picker.toolbar.height() + 4
    assert len(set(heights)) == 1


def test_device_rows_show_separated_metadata_without_numbered_names(selector, qt_application):
    window, bar, _body = selector
    bar.set_device_labels({"demo-a": "Example Phone", "demo-b": "Example Phone"})
    bar.set_device_details({
        device: {"android_version": "15", "connection": "USB"}
        for device in ("demo-a", "demo-b")
    })
    bar.open_picker()
    picker = bar._picker
    wait_for_stable_geometry(qt_application, (window, bar, picker))
    for row in picker._rows.values():
        assert row.name_label.text() == "Example Phone"
        assert row.version_label.text() == "Android 15"
        assert row.connection_label.text() == "USB"
        assert row.name_separator.isVisible() and row.connection_separator.isVisible()
        assert "设备 1" not in row.item.toolTip()
        assert "Android 15" in row.check_box.accessibleName()
        assert row.name_label.geometry().right() < row.version_label.geometry().left()
        assert row.version_label.geometry().right() < row.connection_label.geometry().left()
    selected = QSignalSpy(bar.selection_requested)
    QTest.mouseClick(picker._rows["demo-b"].check_box, Qt.MouseButton.LeftButton)
    assert selected.at(0)[0] == ["demo-a", "demo-b"]
    assert bar.device_label("demo-a") == "设备 1 · Example Phone"


def test_brand_and_model_stay_compact_while_actions_stay_right_aligned(selector, qt_application):
    window, bar, _body = selector
    bar.set_context(["demo-a"], ["demo-a"], "ready")
    source = ComboBox(window)
    source.addItem("demo-a", userData="demo-a")
    source.hide()
    close = PushButton("关闭文件管理", window)
    close.hide()
    bar.set_session_context(source, close)
    bar.set_device_labels({"demo-a": "Example Phone"})
    bar.set_device_details({"demo-a": {
        "brand": "Example", "model": "Phone", "android_version": "15", "connection": "USB",
    }})
    assert bar.targets_button.text() == "Phone"
    bar.open_picker()
    picker = bar._picker
    row = picker._rows["demo-a"]
    for width in (730, 1000, 730):
        window.resize(width, 680)
        wait_for_stable_geometry(qt_application, (window, picker, row, row.name_label))
        assert row.name_label.text() == "Phone"
        assert row.brand_label.text() == "Example"
        assert row.brand_label.width() <= (
            row.brand_label.fontMetrics().horizontalAdvance("Example") + 3
        )
        assert row.name_label.width() <= row.name_label.fontMetrics().horizontalAdvance("Phone") + 3
        assert 0 < row.version_label.x() - row.name_label.geometry().right() <= 24
        assert row.brand_label.geometry().right() < row.name_label.x()
        right_edge = picker.close_button.mapTo(row, picker.close_button.rect().topRight()).x()
        assert 0 <= row.width() - 1 - right_edge <= 5
    # 型号变化独立于旧任务标签；展示更新不能把已确定的操作身份改成型号。
    bar.set_device_details({"demo-a": {
        "brand": "Example", "model": "Phone Pro", "android_version": "15", "connection": "USB",
    }})
    bar.collapse_selector()
    assert bar.targets_button.text() == "Phone Pro"
    assert bar.device_label("demo-a") == "设备 1 · Example Phone"
    assert row.item.data(Qt.ItemDataRole.UserRole) == "demo-a"


@pytest.mark.parametrize("font_size", [12, 22])
def test_device_information_columns_align_across_rows_and_resize(
    selector, qt_application, monkeypatch, font_size,
):
    window, bar, _body = selector
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    bar.set_context(["demo-a"], ["demo-a", "demo-b", "demo-c"], "ready")
    details = {
        "demo-a": {"brand": "vivo", "model": "V2458A", "android_version": "16",
                   "connection": "USB"},
        "demo-b": {"brand": "Redmi", "model": "23113RKC6C", "android_version": "15",
                   "connection": "模拟器"},
        "demo-c": {"model": "Pixel 8", "android_version": "14", "connection": "无线"},
    }
    bar.set_device_details(details)
    source = ComboBox(window)
    source.addItem("demo-a", userData="demo-a")
    source.hide()
    close = PushButton("关闭文件管理", window)
    close.hide()
    bar.set_session_context(source, close)
    bar._apply_fonts()
    bar.open_picker()
    picker = bar._picker
    rows = list(picker._rows.values())
    fields = ("brand_label", "name_label", "version_label", "connection_label")

    def assert_columns():
        for field in (*fields, "brand_separator", "name_separator", "connection_separator"):
            cells = [getattr(row, field) for row in rows]
            assert all(cell.isVisible() for cell in cells)
            assert len({(cell.x(), cell.width()) for cell in cells}) == 1
        for row in rows:
            cells = [row.check_box, *(getattr(row, field) for field in fields)]
            assert max(cell.geometry().center().y() for cell in cells) - min(
                cell.geometry().center().y() for cell in cells
            ) <= 1
            assert all(row.rect().contains(cell.geometry()) for cell in cells)
            assert all(left.geometry().right() < right.x()
                       for left, right in zip(cells, cells[1:]))

    for width in (1000, 730, 430, 1000):
        window.resize(width, 680)
        wait_for_stable_geometry(qt_application, (window, picker, *rows, picker.close_button))
        assert window.width() == width
        assert_columns()
        first = rows[0]
        action_bounds = QRect(
            picker.close_button.mapTo(first, QPoint()), picker.close_button.size(),
        )
        assert first.rect().contains(action_bounds)
        assert first.connection_label.geometry().right() < action_bounds.left()
        assert 0 <= first.width() - 1 - action_bounds.right() <= 5
        if width == 1000:
            for field in fields:
                cells = [getattr(row, field) for row in rows]
                longest = max(
                    cell.fontMetrics().horizontalAdvance(cell.toolTip()) for cell in cells
                )
                assert longest <= cells[0].width() <= longest + 3
    assert rows[2].brand_label.text() == ""
    assert rows[2].name_label.text() == "Pixel 8"
    original_width = rows[0].name_label.width()
    bar.set_device_details({"demo-b": {**details["demo-b"], "model": "Redmi Note 14 Pro"}})
    wait_for_stable_geometry(qt_application, (picker, *rows))
    assert_columns()
    assert rows[0].name_label.width() > original_width
    assert picker._rows["demo-a"] is rows[0]
    assert picker._rows["demo-b"].item.data(Qt.ItemDataRole.UserRole) == "demo-b"
    bar.set_device_details({device: {**detail, "brand": ""} for device, detail in details.items()})
    wait_for_stable_geometry(qt_application, (picker, *rows))
    for row in rows:
        assert row.brand_label.isHidden() and row.brand_separator.isHidden()
        assert row.name_label.x() - row.check_box.geometry().right() <= 12
    assert len({row.version_label.x() for row in rows}) == 1


def test_unknown_brand_does_not_leave_an_empty_information_column(selector, qt_application):
    window, bar, _body = selector
    bar.set_device_labels({"demo-a": "Phone"})
    bar.open_picker()
    picker = bar._picker
    wait_for_stable_geometry(qt_application, (window, picker))
    row = picker._rows["demo-a"]
    assert row.brand_label.isHidden() and row.brand_separator.isHidden()
    assert row.name_label.x() - row.check_box.geometry().right() <= 12


def test_mouse_selection_does_not_paint_accent_frame(selector, qt_application):
    window, bar, _body = selector
    bar.open_picker()
    picker = bar._picker
    wait_for_stable_geometry(qt_application, (window, bar, picker))
    row = picker._rows["demo-b"]
    QTest.mouseClick(row, Qt.MouseButton.LeftButton)
    picker.device_list.setFocus(Qt.FocusReason.MouseFocusReason)
    QTest.mouseMove(window, QPoint(window.width() - 2, window.height() - 2))
    qt_application.processEvents()
    snapshot = picker.device_list.viewport().grab().toImage()
    bounds = picker.device_list.visualItemRect(row.item)
    # 只观察行顶边中部，排除仍使用强调色的原生复选框。
    dpr = snapshot.devicePixelRatio()
    for x in range(bounds.center().x() - 15, bounds.center().x() + 15):
        color = snapshot.pixelColor(int(x * dpr), int((bounds.top() + 1) * dpr))
        assert color.blue() - color.red() < 35


@pytest.mark.parametrize("font_size,width", [(12, 730), (22, 430)])
def test_device_row_keeps_name_status_and_action_on_one_line(
    selector, qt_application, monkeypatch, font_size, width,
):
    window, bar, _body = selector
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    source = ComboBox(window)
    source.addItem("demo-a", userData="demo-a")
    close = PushButton("关闭文件管理", window)
    source.hide()
    close.hide()
    bar.set_session_context(source, close)
    bar.set_device_labels({"demo-a": "这是一台用于检查长名称省略的示例设备"})
    bar.set_device_details({"demo-a": {
        "brand": "Example", "android_version": "15", "connection": "无线",
    }})
    bar._apply_fonts()
    window.resize(width, 680)
    bar.open_picker()
    wait_for_stable_geometry(qt_application, (window, bar, bar._picker))
    picker = bar._picker
    row = picker.device_list.itemWidget(picker.device_list.item(0))
    assert row is not None
    assert row.geometry() == picker.device_list.visualItemRect(picker.device_list.item(0))
    controls = (
        row.check_box, row.brand_label, row.name_label, row.version_label, row.connection_label,
        picker.close_button,
    )
    for control in controls:
        bounds = QRect(control.mapTo(row, QPoint()), control.size())
        assert row.rect().contains(bounds)
        assert abs(bounds.center().y() - row.rect().center().y()) <= 1
    for previous, following in zip(controls, controls[1:]):
        assert previous.mapTo(row, previous.rect().topRight()).x() < following.mapTo(
            row, QPoint(),
        ).x()
    assert window.width() == width
    assert picker.close_button.toolTip()
    selected = QSignalSpy(bar.selection_requested)
    closed = QSignalSpy(bar.close_session_requested)
    QTest.mouseClick(picker.close_button, Qt.MouseButton.LeftButton)
    assert closed.count() == 1 and selected.count() == 0


def test_device_toolbar_actions_never_wrap(selector, qt_application, monkeypatch):
    window, bar, _body = selector
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or 22),
    ))
    close = PushButton("清除截图结果", window)
    close.hide()
    bar.set_session_context(None, close, single=False, close_scope="page")
    window.resize(430, 680)
    bar._apply_fonts()
    bar.open_picker()
    wait_for_stable_geometry(qt_application, (window, bar, bar._picker))
    picker = bar._picker
    centers = []
    for control in (picker.select_all_button, picker.clear_button, picker.close_button):
        bounds = QRect(control.mapTo(picker.toolbar, QPoint()), control.size())
        assert picker.toolbar.rect().contains(bounds)
        centers.append(bounds.center().y())
    assert max(centers) - min(centers) <= 1
    assert window.width() == 430


@pytest.mark.parametrize("font_size", [12, 22])
def test_expanded_rows_and_actions_follow_window_width_round_trip(
    selector, qt_application, monkeypatch, font_size,
):
    window, bar, _body = selector
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    source = ComboBox(window)
    source.addItem("demo-a", userData="demo-a")
    source.hide()
    close = PushButton("关闭文件管理", window)
    close.hide()
    bar.set_session_context(source, close)
    bar.set_device_labels({"demo-a": "Example Phone"})
    bar.set_device_details({"demo-a": {
        "brand": "Example", "model": "Phone", "android_version": "15", "connection": "USB",
    }})
    bar._apply_fonts()
    bar.open_picker()
    picker = bar._picker
    row = picker._rows["demo-a"]
    for width in (730, 430, 730):
        window.resize(width, 680)
        wait_for_stable_geometry(qt_application, (
            window, picker, picker.device_list, row, picker.close_button,
        ))
        assert row.geometry() == picker.device_list.visualItemRect(row.item)
        bounds = QRect(picker.close_button.mapTo(picker.device_list.viewport(), QPoint()),
                       picker.close_button.size())
        assert picker.device_list.viewport().rect().contains(bounds)
        assert row.connection_label.geometry().right() < picker.close_button.mapTo(
            row, QPoint(),
        ).x()


def test_current_offline_session_keeps_only_nonselectable_close_row(selector, qt_application):
    window, bar, _body = selector
    source = ComboBox(window)
    source.addItem("demo-a", userData="demo-a")
    close = PushButton("关闭日志会话", window)
    source.hide()
    close.hide()
    bar.set_session_context(source, close)
    bar.set_context([], ["demo-b"], "ready")
    bar.open_picker()
    qt_application.processEvents()
    picker = bar._picker
    assert picker.device_list.count() == 2
    row = picker.device_list.itemWidget(picker.device_list.item(1))
    assert row.status_label.text() == "离线"
    assert not row.check_box.isEnabled()
    assert picker.close_button.parentWidget().parentWidget() is row
    assert picker.close_button.isEnabled()
    changed = QSignalSpy(bar.selection_requested)
    QTest.mouseClick(row, Qt.MouseButton.LeftButton)
    assert changed.count() == 0


def test_selection_lock_keeps_close_and_clear_available(selector, qt_application):
    window, bar, _body = selector
    source = ComboBox(window)
    source.addItem("demo-a", userData="demo-a")
    close = PushButton("关闭文件管理", window)
    source.hide()
    close.hide()
    bar.set_session_context(source, close, selection_locked=True)
    bar.open_picker()
    qt_application.processEvents()
    picker = bar._picker
    row = picker.device_list.itemWidget(picker.device_list.item(0))
    assert not row.check_box.isEnabled()
    assert picker.clear_button.isEnabled()
    assert picker.close_button.isEnabled()
    changed = QSignalSpy(bar.selection_requested)
    QTest.mouseClick(row, Qt.MouseButton.LeftButton)
    assert changed.count() == 0
    QTest.mouseClick(picker.clear_button, Qt.MouseButton.LeftButton)
    assert changed.count() == 1 and changed.at(0)[0] == []


def test_outer_scroll_reaches_last_device_and_escape_returns_focus(selector, qt_application):
    window, bar, _body = selector
    devices = [f"demo-{number}" for number in range(20)]
    bar.set_context([], devices, "ready")
    bar.open_picker()
    wait_for_stable_geometry(qt_application, (window, bar, bar._picker))
    picker = bar._picker
    assert picker.device_list.verticalScrollBar().maximum() == 0
    assert picker.scroll_area.verticalScrollBar().maximum() > 0
    picker.device_list.setCurrentRow(0)
    picker.device_list.setFocus()
    for _ in range(19):
        QTest.keyClick(picker.device_list, Qt.Key.Key_Down)
    assert picker.device_list.currentRow() == 19
    qt_application.processEvents()
    item_rect = picker.device_list.visualItemRect(picker.device_list.item(19))
    center = picker.device_list.viewport().mapTo(picker.scroll_area.viewport(), item_rect.center())
    assert picker.scroll_area.viewport().rect().contains(center)
    QTest.keyClick(picker.device_list, Qt.Key.Key_Space)
    assert picker.device_list.item(19).checkState() == Qt.CheckState.Checked
    QTest.keyClick(picker.device_list, Qt.Key.Key_Escape)
    qt_application.processEvents()
    assert not bar.is_selector_expanded
    assert bar.targets_button.hasFocus()


def test_wheel_over_device_rows_scrolls_only_outer_area(selector, qt_application):
    window, bar, _body = selector
    bar.set_context([], [f"demo-{number}" for number in range(20)], "ready")
    bar.open_picker()
    wait_for_stable_geometry(qt_application, (window, bar, bar._picker))
    picker = bar._picker
    viewport = picker.device_list.viewport()
    point = QPoint(20, 20)
    wheel = QWheelEvent(
        QPointF(point), QPointF(viewport.mapToGlobal(point)), QPoint(), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(viewport, wheel)
    wait_until(qt_application, lambda: picker.scroll_area.verticalScrollBar().value() > 0)
    assert picker.device_list.verticalScrollBar().value() == 0


def test_keyboard_current_row_has_visible_focus_feedback(selector, qt_application):
    window, bar, _body = selector
    bar.open_picker()
    wait_for_stable_geometry(qt_application, (window, bar, bar._picker))
    listing = bar._picker.device_list
    QTest.mouseMove(window, QPoint(window.width() - 2, window.height() - 2))
    listing.setCurrentRow(0)
    listing.setFocus(Qt.FocusReason.TabFocusReason)
    qt_application.processEvents()
    first = listing.grab().toImage()
    QTest.keyClick(listing, Qt.Key.Key_Down)
    qt_application.processEvents()
    assert listing.hasFocus() and listing.currentRow() == 1
    assert listing.grab().toImage() != first


def test_short_window_and_font_round_trip_restores_selector_height(
    selector, qt_application, monkeypatch,
):
    window, bar, _body = selector
    font_size = 12
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    bar._apply_fonts()
    bar.set_context([], [f"demo-{index}" for index in range(20)], "ready")
    bar.open_picker()
    wait_for_stable_geometry(qt_application, (window, bar, bar._picker))
    initial = bar._picker.height()
    font_size = 22
    bar._apply_fonts()
    window.resize(430, 320)
    wait_for_stable_geometry(qt_application, (window, bar, bar._picker))
    assert window.size().width() == 430 and window.size().height() == 320
    assert bar._picker.height() <= int((window.height() - bar._surface.height() - 18) * .45)
    font_size = 12
    bar._apply_fonts()
    window.resize(730, 680)
    wait_for_stable_geometry(qt_application, (window, bar, bar._picker))
    assert bar._picker.height() == initial


@pytest.mark.parametrize("language", ["zh_CN", "en_US", "zh_HK"])
@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("scope", ["session", "page"])
def test_translated_single_rows_and_actions_fit_narrow_window(
    qt_application, monkeypatch, language, font_size, scope,
):
    """真实翻译在大字号窄窗中仍保持单行、完整命名和按钮可点击区域。"""
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    translators = install_translators(qt_application, language)
    window = None
    try:
        window = QWidget()
        window.resize(430, 680)
        layout = QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = DeviceContextBar(window)
        layout.addWidget(bar)
        layout.addStretch(1)
        source = ComboBox(window)
        source.addItem("demo-a", userData="demo-a")
        source.hide()
        close_text = tr("关闭文件管理" if scope == "session" else "清除截图结果")
        close = PushButton(close_text, window)
        close.hide()
        bar.set_context(["demo-a"], ["demo-a", "demo-b"], "ready")
        long_name = "Example device with a deliberately long display name · 示例设备"
        bar.set_device_labels({"demo-a": long_name})
        bar.set_device_details({"demo-a": {
            "brand": "Example", "android_version": "15", "connection": tr("模拟器"),
        }})
        bar.set_session_context(
            source if scope == "session" else None, close,
            single=scope == "session", close_scope=scope,
        )
        window.show()
        bar.open_picker()
        picker = bar._picker
        wait_for_stable_geometry(
            qt_application, (window, bar, picker, picker.toolbar, picker.close_button),
        )
        assert window.width() == 430
        assert picker.close_button.accessibleName() == close_text
        assert close_text in picker.close_button.toolTip()
        if language != "zh_CN":
            assert close_text != ("关闭文件管理" if scope == "session" else "清除截图结果")

        toolbar_buttons = [picker.clear_button]
        if scope == "page":
            toolbar_buttons.extend((picker.select_all_button, picker.close_button))
        toolbar_centers = []
        for button in toolbar_buttons:
            assert button.isVisible()
            rect = QRect(button.mapTo(picker.toolbar, QPoint()), button.size())
            assert picker.toolbar.rect().contains(rect)
            assert button.height() >= button.fontMetrics().height()
            assert button.accessibleName() and button.toolTip()
            toolbar_centers.append(rect.center().y())
        assert max(toolbar_centers) - min(toolbar_centers) <= 1

        for index in range(picker.device_list.count()):
            item = picker.device_list.item(index)
            row = picker.device_list.itemWidget(item)
            assert row.geometry() == picker.device_list.visualItemRect(item)
            controls = [row.check_box]
            if row.brand_label.isVisible():
                controls.append(row.brand_label)
            controls.extend((row.name_label, row.version_label, row.connection_label))
            if row.status_label.isVisible():
                controls.append(row.status_label)
            if scope == "session" and index == 0:
                controls.append(picker.close_button)
            for control in controls:
                rect = QRect(control.mapTo(row, QPoint()), control.size())
                assert row.rect().contains(rect)
                assert abs(rect.center().y() - row.rect().center().y()) <= 1
            for previous, following in zip(controls, controls[1:]):
                assert previous.mapTo(row, previous.rect().topRight()).x() < following.mapTo(
                    row, QPoint(),
                ).x()
            if index == 0:
                assert long_name in row.name_label.toolTip()
                assert long_name in row.name_label.accessibleName()
                assert row.name_label.text()
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
