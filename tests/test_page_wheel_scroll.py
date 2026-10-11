"""普通滚动页、像素列表与文本视图共用高刷滚轮时的输入及生命周期契约。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QScrollArea,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ListWidget, PlainTextEdit, ScrollArea, SmoothScrollArea, TableWidget

from gui.styles import fluent
from gui.widgets.settings_scroll import SettingsWheelScroll
from tests.test_settings_scroll import _wheel

pytestmark = pytest.mark.ui


@pytest.fixture
def make_area(qt_application):
    areas = []

    def build(kind):
        if kind == "table":
            area = TableWidget()
            area.setColumnCount(2)
            area.setRowCount(120)
            for row in range(120):
                area.setItem(row, 0, QTableWidgetItem(f"item {row}"))
        elif kind == "list":
            area = ListWidget()
            area.addItems([f"item {row}" for row in range(120)])
        elif kind == "plain":
            area = PlainTextEdit()
            area.setPlainText("\n".join(f"line {row}" for row in range(200)))
        else:
            area = {"qt": QScrollArea, "fluent": ScrollArea, "smooth": SmoothScrollArea}[kind]()
            content = QWidget()
            content.setMinimumSize(340, 2200)
            area.setWidget(content)
            area.setWidgetResizable(True)
        areas.append(area)
        area.resize(520, 380)
        area.show()
        qt_application.processEvents()
        fluent.use_smooth_scroll(area)
        return area

    yield build
    for area in areas:
        area.close()
        area.deleteLater()


@pytest.mark.parametrize("kind", ["qt", "fluent", "smooth", "table", "list"])
def test_page_wheel_keeps_first_frame_then_moves_in_small_steps(make_area, qt_application, kind):
    area = make_area(kind)
    bar = area.verticalScrollBar()
    bar.setValue(100)
    if kind == "table":
        area.selectRow(8)
        selected = area.currentRow()
    before = bar.value()
    _wheel(qt_application, area.viewport())
    assert bar.value() == before
    scroll = area.findChild(SettingsWheelScroll)
    assert scroll is not None
    animation = scroll._animation
    assert animation.state() == QAbstractAnimation.State.Running
    animation.pause()
    values = [before]
    for time in (24, 48, 96, animation.duration()):
        animation.setCurrentTime(time)
        values.append(bar.value())
    assert values == sorted(set(values)), values
    step = min(bar.pageStep(), bar.singleStep() * QApplication.wheelScrollLines())
    assert values[-1] == before + step
    if kind == "table":
        assert area.currentRow() == selected


def test_installing_twice_keeps_one_clock_and_one_wheel_target(make_area, qt_application):
    area = make_area("fluent")
    fluent.use_smooth_scroll(area)
    assert len(area.findChildren(SettingsWheelScroll)) == 1
    bar = area.verticalScrollBar()
    _wheel(qt_application, area.viewport())
    animation = area.findChild(SettingsWheelScroll)._animation
    animation.pause()
    animation.setCurrentTime(animation.duration())
    assert bar.value() == min(bar.pageStep(), bar.singleStep() * QApplication.wheelScrollLines())


def test_plain_log_uses_native_line_units_without_delayed_animation(make_area, qt_application):
    area = make_area("plain")
    bar = area.verticalScrollBar()
    bar.setValue(50)
    _wheel(qt_application, area.viewport())
    assert bar.value() > 50
    assert area.findChild(SettingsWheelScroll) is None
    engine = area.scrollDelegate.verticalSmoothScroll.fixedStepScrollEngine
    assert not engine.smoothMoveTimer.isActive()


@pytest.mark.parametrize("reason", ["disable", "hide", "external", "range", "drag"])
def test_shared_scroll_stops_when_view_owner_changes(make_area, qt_application, reason):
    area = make_area("smooth")
    _wheel(qt_application, area.viewport())
    controller = area.findChild(SettingsWheelScroll)
    controller._animation.pause()
    controller._animation.setCurrentTime(50)
    if reason == "disable":
        area.setEnabled(False)
    elif reason == "hide":
        area.hide()
    elif reason == "external":
        area.verticalScrollBar().setValue(350)
    elif reason == "range":
        area.verticalScrollBar().setMaximum(800)
    else:
        area.delegate.vScrollBar.sliderPressed.emit()
    value = area.verticalScrollBar().value()
    assert controller._animation.state() == QAbstractAnimation.State.Stopped
    controller._animation.setCurrentTime(controller._animation.duration())
    assert area.verticalScrollBar().value() == value


def test_shared_scroll_does_not_capture_read_only_selection_or_shift_wheel(
    make_area, qt_application,
):
    area = make_area("table")
    area.selectRow(8)
    selected = area.currentRow()
    _wheel(qt_application, area.viewport(), modifiers=Qt.KeyboardModifier.ShiftModifier)
    animation = area.findChild(SettingsWheelScroll)._animation
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert area.currentRow() == selected
    assert isinstance(area, QAbstractScrollArea)


def test_live_logcat_uses_native_line_step_and_keeps_history_anchor(qt_application):
    from gui.features.logcat import LiveLogcatPage

    page = LiveLogcatPage(device_ip="demo-a")
    try:
        page.resize(800, 600)
        page.show()
        page.output.setPlainText("\n".join(f"history {index}" for index in range(200)))
        qt_application.processEvents()
        bar = page.output.verticalScrollBar()
        bar.setValue(60)
        _wheel(qt_application, page.output.viewport())
        assert bar.value() > 60
        assert page.output.findChild(SettingsWheelScroll) is None
        engine = page.output.scrollDelegate.verticalSmoothScroll.fixedStepScrollEngine
        assert not engine.smoothMoveTimer.isActive()
        before = bar.value()
        page._on_line("new line", "I")
        page._flush_pending_lines()
        assert bar.value() == before
    finally:
        page.close()


@pytest.mark.parametrize("kind", ["table", "plain"])
def test_nested_wheel_moves_only_inner_until_it_reaches_edge(make_area, qt_application, kind):
    outer = make_area("smooth")
    inner = make_area(kind)
    layout = QVBoxLayout(outer.widget())
    layout.addWidget(inner)
    layout.addStretch(1)
    inner.setFixedHeight(260)
    inner.show()
    qt_application.processEvents()
    outer_bar, inner_bar = outer.verticalScrollBar(), inner.verticalScrollBar()
    outer_bar.setValue(0)
    inner_bar.setValue(20)
    _wheel(qt_application, inner.viewport())
    controller = inner.findChild(SettingsWheelScroll)
    if controller:
        controller._animation.pause()
        controller._animation.setCurrentTime(controller._animation.duration())
    assert inner_bar.value() > 20
    assert outer_bar.value() == 0
    assert outer._wheel_scroll._animation.state() == QAbstractAnimation.State.Stopped
    inner_bar.setValue(inner_bar.maximum())
    # 使用窗口输入入口验证 Qt 对未接受滚轮的祖先传播；sendEvent 只直投单一接收者。
    point = inner.viewport().mapTo(outer, inner.viewport().rect().center())
    QTest.wheelEvent(outer.windowHandle(), point, QPoint(0, -120))
    qt_application.processEvents()
    animation = outer._wheel_scroll._animation
    assert animation.state() == QAbstractAnimation.State.Running
    animation.pause()
    animation.setCurrentTime(animation.duration())
    assert outer_bar.value() > 0
