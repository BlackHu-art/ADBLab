"""页内设备选择展开过渡的几何、焦点与中断行为回归。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceContextBar

pytestmark = pytest.mark.ui


@pytest.fixture
def animated_selector(qt_application):
    window = QWidget()
    window.resize(730, 680)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    bar = DeviceContextBar(window)
    body = QWidget(window)
    body_layout = QVBoxLayout(body)
    body_layout.addWidget(QPushButton("正文操作", body))
    body_layout.addStretch(1)
    layout.addWidget(bar)
    layout.addWidget(body, 1)
    bar.set_context(["demo-a"], ["demo-a", "demo-b"], "ready")
    window.show()
    window.activateWindow()
    qt_application.processEvents()
    yield window, bar, body
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _advance(bar, app, fraction):
    """用 Qt 动画时钟采样，避免用机器速度推断过渡是否存在。"""
    animation = getattr(bar, "_selector_animation", None)
    if animation is not None:
        if animation.state() == QAbstractAnimation.State.Running:
            animation.pause()
        animation.setCurrentTime(round(animation.duration() * fraction))
    _flush_layout(bar, app)


def _flush_layout(bar, app):
    app.processEvents()
    bar.window().layout().activate()
    app.processEvents()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_expansion_reveals_stable_rows_and_moves_body_through_intermediate_positions(
    animated_selector, qt_application, theme,
):
    window, bar, body = animated_selector
    BaseStyles.switch_theme(theme)
    qt_application.processEvents()
    collapsed_y = body.y()
    bar.open_picker()
    picker = bar._picker
    positions, row_heights = [], []
    for fraction in (.2, .6, 1):
        _advance(bar, qt_application, fraction)
        positions.append(body.y())
        row_heights.append(tuple(row.height() for row in picker._rows.values()))
    assert collapsed_y < positions[0] < positions[1] < positions[2]
    assert row_heights[0] == row_heights[1] == row_heights[2]
    assert all(height > 0 for height in row_heights[0])
    assert picker.window() is window and not picker.isWindow()
    assert bar.is_selector_expanded and bar.targets_button.isChecked()
    assert bar.rect().contains(QRect(picker.mapTo(bar, QPoint()), picker.size()))
    assert not picker.content.autoFillBackground()
    assert not picker.scroll_area.viewport().autoFillBackground()


def test_collapse_keeps_content_geometry_while_body_moves_back(
    animated_selector, qt_application,
):
    _window, bar, body = animated_selector
    collapsed_y = body.y()
    bar.open_picker()
    _advance(bar, qt_application, 1)
    expanded_y = body.y()
    row_sizes = tuple(row.size() for row in bar._picker._rows.values())
    bar.collapse_selector()
    assert not bar.is_selector_expanded and not bar.targets_button.isChecked()
    positions = []
    for fraction in (.2, .6, 1):
        _advance(bar, qt_application, fraction)
        positions.append(body.y())
        assert tuple(row.size() for row in bar._picker._rows.values()) == row_sizes
    assert expanded_y > positions[0] > positions[1] > positions[2] == collapsed_y
    assert not bar._picker.isVisible()


def test_repeated_open_and_rapid_reversal_keep_current_geometry_and_last_intent(
    animated_selector, qt_application,
):
    _window, bar, body = animated_selector
    collapsed_y = body.y()
    bar.open_picker()
    _advance(bar, qt_application, .35)
    picker = bar._picker
    opening_y = body.y()
    bar.open_picker()
    qt_application.processEvents()
    assert body.y() == opening_y
    bar.collapse_selector()
    qt_application.processEvents()
    assert body.y() == opening_y
    _advance(bar, qt_application, .35)
    reversing_y = body.y()
    assert collapsed_y < reversing_y < opening_y
    bar.open_picker()
    qt_application.processEvents()
    assert body.y() == reversing_y
    _advance(bar, qt_application, 1)
    assert bar._picker is picker and bar.is_selector_expanded
    assert body.y() > opening_y
    bar.collapse_selector()
    _advance(bar, qt_application, 1)
    assert body.y() == collapsed_y
    assert not bar.is_selector_expanded and not bar.targets_button.isChecked()


@pytest.mark.parametrize("keyboard", [False, True])
def test_only_keyboard_focus_completes_reveal_to_keep_navigation_visible(
    animated_selector, qt_application, keyboard,
):
    _window, bar, body = animated_selector
    transitions = []
    bar.selector_transition_changed.connect(transitions.append)
    bar.open_picker()
    _advance(bar, qt_application, .35)
    intermediate_y = body.y()
    row = bar._picker._rows["demo-a"]
    row.check_box.setFocus(
        Qt.FocusReason.TabFocusReason if keyboard else Qt.FocusReason.MouseFocusReason,
    )
    _flush_layout(bar, qt_application)
    assert row.check_box.hasFocus()
    if keyboard:
        assert body.y() > intermediate_y
        assert transitions == [True, False]
    else:
        assert body.y() == intermediate_y
        assert transitions == [True]


@pytest.mark.parametrize("keyboard", [False, True])
def test_collapse_returns_focus_and_removes_clipped_controls_from_tab_order(
    animated_selector, qt_application, keyboard,
):
    _window, bar, _body = animated_selector
    bar.open_picker()
    _advance(bar, qt_application, 1)
    picker = bar._picker
    picker.device_list.setFocus(Qt.FocusReason.TabFocusReason)
    qt_application.processEvents()
    if keyboard:
        QTest.keyClick(picker.device_list, Qt.Key.Key_Escape)
    else:
        QTest.mouseClick(bar.targets_button, Qt.MouseButton.LeftButton)
    _advance(bar, qt_application, .35)
    assert not bar.is_selector_expanded
    assert bar.targets_button.hasFocus()
    button_image = bar.targets_button.grab().toImage()
    accent = QColor(BaseStyles.color("BORDER_FOCUS"))
    border = button_image.pixelColor(
        button_image.width() // 2, round(button_image.devicePixelRatio()),
    )
    assert (border == accent) is keyboard
    for _ in range(8):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
        focus = QApplication.focusWidget()
        assert focus is not picker and not picker.isAncestorOf(focus)
    _advance(bar, qt_application, 1)
    assert not picker.isVisible()


@pytest.mark.parametrize("exit_route", ["dismiss", "hide"])
def test_leaving_page_ends_inflight_transition_without_late_reopen(
    animated_selector, qt_application, exit_route,
):
    _window, bar, body = animated_selector
    transitions = []
    bar.selector_transition_changed.connect(transitions.append)
    collapsed_y = body.y()
    bar.open_picker()
    _advance(bar, qt_application, .35)
    assert body.y() > collapsed_y
    if exit_route == "dismiss":
        bar.dismiss_popups()
    else:
        bar.hide()
        bar.show()
    _flush_layout(bar, qt_application)
    assert not bar.is_selector_expanded
    assert body.y() == collapsed_y
    assert not bar._picker.isVisible()
    _advance(bar, qt_application, 1)
    assert body.y() == collapsed_y and not bar._picker.isVisible()
    assert transitions == [True, False]


def test_font_and_short_window_change_during_transition_settle_with_height_budget(
    animated_selector, qt_application, monkeypatch,
):
    window, bar, body = animated_selector
    font_size = 12
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size),
    ))
    window.resize(730, 1000)
    bar._apply_fonts()
    bar.set_context([], [f"demo-{index}" for index in range(20)], "ready")
    qt_application.processEvents()
    collapsed_y = body.y()
    bar.open_picker()
    _advance(bar, qt_application, 1)
    picker = bar._picker
    full_height = picker.height()
    bar.collapse_selector()
    _advance(bar, qt_application, 1)
    bar.open_picker()
    _advance(bar, qt_application, .35)
    font_size = 22
    bar._apply_fonts()
    window.resize(430, 320)
    _advance(bar, qt_application, 1)
    assert window.width() == 430 and window.height() == 320
    assert picker.height() <= int((window.height() - bar._surface.height() - 18) * .45)
    assert picker.scroll_area.verticalScrollBar().maximum() > 0
    bar.collapse_selector()
    _advance(bar, qt_application, .35)
    font_size = 12
    bar._apply_fonts()
    window.resize(730, 1000)
    bar.open_picker()
    _advance(bar, qt_application, 1)
    assert picker.height() == full_height
    row_height = picker.device_list.sizeHintForRow(0)
    assert picker.scroll_area.height() >= row_height * 5 + picker.toolbar.height()
    assert body.y() > collapsed_y and bar.is_selector_expanded
    assert bar.rect().contains(QRect(picker.mapTo(bar, QPoint()), picker.size()))


@pytest.mark.parametrize("opening", [True, False])
def test_transition_eases_into_motion_without_a_large_first_step(
    animated_selector, qt_application, opening,
):
    _window, bar, body = animated_selector
    bar.open_picker()
    _advance(bar, qt_application, 1)
    distance = bar._selector_target_height
    if opening:
        bar.dismiss_popups()
        _flush_layout(bar, qt_application)
        bar.open_picker()
    else:
        bar.collapse_selector()
    start = body.y()
    _advance(bar, qt_application, .08)
    assert 0 < abs(body.y() - start) < distance * .05
    _advance(bar, qt_application, 1)


def test_header_button_keeps_its_geometry_across_both_selector_states(
    animated_selector, qt_application,
):
    _window, bar, _body = animated_selector
    before = bar.targets_button.geometry()
    bar.open_picker()
    _advance(bar, qt_application, .5)
    assert bar.targets_button.geometry() == before
    _advance(bar, qt_application, 1)
    bar.collapse_selector()
    _advance(bar, qt_application, .5)
    assert bar.targets_button.geometry() == before


def test_closing_preserves_enabled_appearance_but_rejects_input_and_restores_focus(
    animated_selector, qt_application,
):
    _window, bar, _body = animated_selector
    bar.open_picker()
    _advance(bar, qt_application, 1)
    picker = bar._picker
    enabled = {widget: widget.isEnabled() for widget in picker.findChildren(QWidget)}
    row = picker._rows["demo-b"]
    policy = row.check_box.focusPolicy()
    selections = []
    bar.selection_requested.connect(selections.append)
    bar.collapse_selector()
    _advance(bar, qt_application, .2)
    assert all(widget.isEnabled() == value for widget, value in enabled.items())
    assert row.check_box.focusPolicy() == Qt.FocusPolicy.NoFocus
    QTest.mouseClick(row.check_box, Qt.MouseButton.LeftButton)
    picker.clear_button.click()
    assert selections == []
    bar.set_context(["demo-a"], ["demo-a", "demo-b", "demo-c"], "ready")
    assert picker._rows["demo-c"].check_box.focusPolicy() == Qt.FocusPolicy.NoFocus
    bar.open_picker()
    _advance(bar, qt_application, 1)
    assert picker._rows["demo-b"].check_box.focusPolicy() == policy
    QTest.mouseClick(picker._rows["demo-b"].check_box, Qt.MouseButton.LeftButton)
    assert selections == [["demo-a", "demo-b"]]


@pytest.mark.parametrize("opening", [True, False])
def test_final_frame_is_presented_before_releasing_workspace_reflow(
    animated_selector, qt_application, opening,
):
    _window, bar, _body = animated_selector
    if not opening:
        bar.open_picker()
        _advance(bar, qt_application, 1)
    transitions = []
    bar.selector_transition_changed.connect(transitions.append)
    (bar.open_picker if opening else bar.collapse_selector)()
    _advance(bar, qt_application, .8)
    bar._selector_animation.setCurrentTime(bar._selector_animation.duration())
    assert transitions == [True], "最终高度尚未绘制时，不得启动正文的布局规划"
    assert bar.height() == bar.sizeHint().height()
    _flush_layout(bar, qt_application)
    assert transitions == [True, False]


@pytest.mark.parametrize("action", ["dismiss", "hide", "reverse"])
def test_pending_final_paint_cannot_release_a_new_transition_or_survive_hide(
    animated_selector, qt_application, action,
):
    window, bar, _body = animated_selector
    transitions = []
    bar.selector_transition_changed.connect(transitions.append)
    bar.open_picker()
    _advance(bar, qt_application, .8)
    bar._selector_animation.setCurrentTime(bar._selector_animation.duration())
    assert transitions == [True]
    if action == "reverse":
        bar.collapse_selector()
        _flush_layout(bar, qt_application)
        assert transitions == [True], "上一轮待绘制的终点不能提前解除新一轮的布局暂停"
        _advance(bar, qt_application, 1)
    elif action == "hide":
        window.hide()
    else:
        bar.dismiss_popups()
    _flush_layout(bar, qt_application)
    assert transitions == [True, False]
    assert not bar.is_selector_expanded
    assert bar._selector_animation.state() == QAbstractAnimation.State.Stopped
