"""会话状态从宿主投影到全局设备栏，并保持窄屏可读与操作可达。"""

from itertools import combinations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, FluentIcon, InfoBadge, InfoLevel, PushButton

from gui.pages.workspace_features import WorkspaceFeatureHost
from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceContextBar
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry


@pytest.fixture
def session_bar(qt_application):
    window = QWidget()
    window.resize(1120, 680)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    bar = DeviceContextBar(window)
    layout.addWidget(bar)
    layout.addStretch(1)
    sources = QWidget(window)
    sources.hide()
    combo = ComboBox(sources)
    combo.addItem("demo-a", userData="demo-a")
    close = PushButton("关闭应用管理", sources)
    badge = InfoBadge(sources)
    badge.setText("在线")
    badge.setLevel(InfoLevel.SUCCESS)
    badge.setAccessibleName("会话状态")
    badge.setToolTip("当前设备可执行操作")
    badge.setAccessibleDescription("当前设备可执行操作")
    badge.show()
    bar.set_context(["demo-a"], ["demo-a", "demo-b"], "ready")
    window.show()
    qt_application.processEvents()
    return window, bar, combo, close, badge


def test_session_status_updates_without_changing_device_or_close_controls(session_bar):
    _window, bar, combo, close, badge = session_bar
    switched = QSignalSpy(bar.session_requested)
    bar.set_session_context(combo, close, badge)
    assert bar.session_hint.text() == "在线"
    assert bar.session_hint.level == InfoLevel.SUCCESS
    assert bar.session_hint.accessibleName() == "会话状态"
    assert bar.session_hint.isVisible()
    assert badge.parentWidget() is not bar.session_row

    for text, level, description in (
        ("离线", InfoLevel.WARNING, "当前设备已经断开连接"),
        ("未选为操作目标", InfoLevel.WARNING, "已有内容仍可查看，原任务仍可停止"),
        ("等待选择设备", InfoLevel.INFOAMTION, "请明确选择当前功能使用的一台设备"),
        ("正在关闭", InfoLevel.WARNING, "后台资源释放后自动恢复操作"),
        ("正在关闭", InfoLevel.INFOAMTION, "仍在等待资源释放"),
    ):
        badge.setText(text)
        badge.setLevel(level)
        badge.setToolTip(description)
        badge.setAccessibleDescription(description)
        bar.set_session_context(combo, close, badge)
        assert bar.session_hint.text() == text
        assert bar.session_hint.level == level
        assert bar.session_hint.toolTip() == description
        assert bar.session_hint.accessibleDescription() == description
        assert bar.session_combo.currentData() == "demo-a"
        assert bar.close_button.text() == "关闭应用管理"
    assert switched.count() == 0


def test_session_status_visibility_and_route_clear_do_not_leave_stale_text(session_bar):
    _window, bar, combo, close, badge = session_bar
    bar.set_session_context(None, None, badge)
    assert bar.session_row.isVisible()
    assert bar.session_hint.isVisible()
    assert bar.session_combo.isHidden()
    assert bar.close_button.isHidden()

    badge.hide()
    bar.set_session_context(None, None, badge)
    assert bar.session_hint.isHidden()
    assert bar.session_hint.text() == ""
    assert bar.session_row.isHidden()

    badge.show()
    bar.set_session_context(combo, close, badge)
    assert bar.session_hint.isVisible()
    bar.set_session_context(None, None)
    assert bar.session_row.isHidden()
    assert bar.session_hint.text() == ""
    assert bar.session_hint.toolTip() == ""
    assert bar.session_hint.accessibleDescription() == ""


@pytest.mark.parametrize("width,font_size", [(452, 12), (452, 22), (1120, 22)])
@pytest.mark.parametrize("status", ["等待选择设备", "未选为操作目标"])
def test_session_status_and_actions_fit_after_width_and_font_changes(
    session_bar, qt_application, monkeypatch, width, font_size, status
):
    window, bar, combo, close, badge = session_bar
    bar.set_session_context(combo, close, badge)
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size)),
    )
    badge.setText(status)
    bar._apply_fonts()
    bar.set_session_context(combo, close, badge)
    window.resize(width, 680)
    controls = (bar.session_label, bar.session_combo, bar.session_hint, bar.close_button)
    wait_for_stable_geometry(qt_application, (window, bar, bar.session_row, *controls))
    assert window.width() == width
    for control in controls:
        assert control.isVisible()
        assert bar.rect().contains(mapped_rect(control, bar))
        assert control.height() >= control.fontMetrics().height()
    for first, second in combinations(controls, 2):
        assert not mapped_rect(first, bar).intersects(mapped_rect(second, bar))
    assert bar.session_hint.width() >= bar.session_hint.sizeHint().width()
    assert bar.close_button.width() >= bar.close_button.sizeHint().width()
    assert bar.session_hint.text() == status


def test_external_controls_keep_host_badge_owned_and_project_online_changes(qt_application):
    host = WorkspaceFeatureHost("system", "系统工具", QWidget())
    host.register_feature("probe", "测试会话", FluentIcon.SCROLL, lambda _key: QWidget())
    host.set_external_device_controls(True)
    host.set_device_context(["demo-a"], ["demo-a"])
    host.open_feature("probe", preferred_device="demo-a")
    bar = DeviceContextBar()
    bar.resize(960, 200)
    bar.show()
    bar.set_session_context(host.device_combo, host.close_session_button, host.session_badge)
    qt_application.processEvents()
    assert host.session_badge.parentWidget() is host.session_toolbar
    assert host.session_toolbar.isHidden()
    assert bar.session_hint.isVisible()
    assert bar.session_hint.text() == "在线"
    assert bar.session_hint.level == InfoLevel.SUCCESS
    assert not bar.session_hint.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    host.set_device_context([], [])
    bar.set_session_context(host.device_combo, host.close_session_button, host.session_badge)
    assert bar.session_hint.text() == "离线"
    assert bar.session_hint.level == InfoLevel.WARNING
    assert host.session_badge.parentWidget() is host.session_toolbar
