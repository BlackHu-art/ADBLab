"""滚动内容的高度变化不应重复计算横向布局，真实宽度及内容变化仍须生效。"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from gui.dialogs.performance_launcher_form import (
    _PerformanceActionCard,
    _PerformanceField,
    _PerformanceGrid,
    _PerformanceRow,
)
from gui.widgets.performance_progress import PerformanceProgress
from tests.ui_geometry_helpers import wait_for_stable_geometry

pytestmark = pytest.mark.ui


def _show_component(qt_application, kind):
    """在真实父布局中构造组件，保留 Qt 自己产生的 Resize 与 LayoutRequest。"""
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    editor = QLineEdit("保留中的输入")
    if kind == "grid":
        component = _PerformanceGrid(tuple(
            _PerformanceField(QLabel(f"采样配置 {index}"), editor if index == 0 else QLineEdit())
            for index in range(3)
        ))
    elif kind == "row":
        component = _PerformanceRow((editor, QPushButton("应用并保存当前采样配置")))
    elif kind == "field":
        component = _PerformanceField(QLabel("本次性能采样参数"), editor)
    else:
        progress = PerformanceProgress()
        progress.set_animation_enabled(False)
        component = _PerformanceActionCard(progress, QPushButton("停止"), QPushButton("开始"))
    layout.addWidget(component)
    host.resize(1100, 260)
    host.show()
    wait_for_stable_geometry(qt_application, (host, component))
    return host, component, editor


def _observe_reflow(monkeypatch, component):
    """计数真实重排调用，不替换测量、布局或 Qt 事件行为。"""
    calls = []
    original = component._reflow

    def reflow():
        calls.append((component.width(), component.height()))
        return original()

    monkeypatch.setattr(component, "_reflow", reflow)
    return calls


@pytest.mark.parametrize("kind", ("grid", "row", "field"))
def test_performance_height_only_resize_keeps_horizontal_plan(
    qt_application, monkeypatch, kind,
):
    host, component, editor = _show_component(qt_application, kind)
    try:
        editor.setFocus()
        qt_application.processEvents()
        old_width, old_height = component.width(), component.height()
        calls = _observe_reflow(monkeypatch, component)
        for height in (320, 380, 300):
            host.resize(host.width(), height)
            wait_for_stable_geometry(qt_application, (host, component))
            assert component.width() == old_width
            assert component.height() != old_height
        assert calls == [], calls
        assert editor.text() == "保留中的输入"
        assert editor.hasFocus()
    finally:
        host.close()


@pytest.mark.parametrize("kind", ("grid", "row", "field"))
def test_performance_width_and_font_changes_still_refresh_plan(
    qt_application, monkeypatch, kind,
):
    host, component, editor = _show_component(qt_application, kind)
    try:
        calls = _observe_reflow(monkeypatch, component)
        width = component.inline_minimum_width() - 24 if kind == "field" else 240
        host.resize(width, host.height())
        wait_for_stable_geometry(qt_application, (host, component))
        assert calls, "真正的宽度变化必须更新横向断点"
        if kind == "grid":
            assert component._columns == 1
        else:
            assert component._box.direction() == QBoxLayout.Direction.TopToBottom
        calls.clear()
        font = QFont(component.font())
        font.setPointSize(22)
        component.setFont(font)
        wait_for_stable_geometry(qt_application, (host, component))
        assert calls, "字号变化必须更新自然尺寸，不能被同宽缓存吞掉"
        assert editor.text() == "保留中的输入"
    finally:
        host.close()


def test_performance_field_content_change_at_same_width_refreshes_plan(
    qt_application, monkeypatch,
):
    host, component, editor = _show_component(qt_application, "field")
    try:
        host.resize(650, host.height())
        wait_for_stable_geometry(qt_application, (host, component))
        assert component._box.direction() == QBoxLayout.Direction.LeftToRight
        width = component.width()
        calls = _observe_reflow(monkeypatch, component)
        text = "采样参数说明"
        while component.label.fontMetrics().horizontalAdvance(text) < width - 96:
            text += "说明"
        component.label.setText(text)
        wait_for_stable_geometry(qt_application, (host, component))
        assert component.width() == width
        assert calls, "同宽内容变化仍由 LayoutRequest 更新布局"
        assert component._box.direction() == QBoxLayout.Direction.TopToBottom
        assert editor.text() == "保留中的输入"
    finally:
        host.close()


def test_performance_action_height_update_does_not_reenter_horizontal_measurement(
    qt_application, monkeypatch,
):
    host, component, _editor = _show_component(qt_application, "actions")
    try:
        host.resize(420, host.height())
        wait_for_stable_geometry(qt_application, (host, component))
        width, height = component.width(), component.height()
        calls = _observe_reflow(monkeypatch, component)
        component._progress.detail_label.setText("正在等待采集结果，请保持设备连接。" * 8)
        component._progress.refresh_geometry()
        wait_for_stable_geometry(qt_application, (host, component))
        assert component.width() == width
        assert component.height() > height
        assert len(calls) == 1, calls
        assert component.height() == component.heightForWidth(component.width())
    finally:
        host.close()


def test_performance_action_width_and_font_changes_still_measure_natural_height(
    qt_application, monkeypatch,
):
    host, component, _editor = _show_component(qt_application, "actions")
    try:
        calls = _observe_reflow(monkeypatch, component)
        host.resize(420, host.height())
        wait_for_stable_geometry(qt_application, (host, component))
        assert calls
        assert component._mode != 0
        assert component.height() == component.heightForWidth(component.width())
        calls.clear()
        font = QFont(component.font())
        font.setPointSize(22)
        component.setFont(font)
        wait_for_stable_geometry(qt_application, (host, component))
        assert calls
        assert component.height() == component.heightForWidth(component.width())
    finally:
        host.close()
