"""功能设备栏保持单行，会话状态通过操作控件说明保留。"""

import pytest
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QAbstractButton, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, FluentIcon, InfoBadge, InfoLevel, PushButton

from gui.pages.workspace_features import WorkspaceFeatureHost
from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceContextBar
from tests.test_workspace_feature_host import _LifecyclePage
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
    badge_owner = badge.parentWidget()
    bar.set_session_context(combo, close, badge)
    bar.open_picker()
    picker = bar._picker
    assert bar.session_hint.text() == "在线"
    assert bar.session_hint.level == InfoLevel.SUCCESS
    assert bar.session_hint.accessibleName() == "会话状态"
    assert bar.session_hint.isHidden()
    assert "在线" in bar.session_combo.accessibleDescription()
    assert "当前设备可执行操作" in bar.session_combo.toolTip()
    assert badge.parentWidget() is badge_owner

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
        assert bar.session_hint.isHidden()
        for control in (bar.session_combo, picker.close_button):
            assert text in control.accessibleDescription()
            assert description in control.accessibleDescription()
            assert text in control.toolTip()
            assert description in control.toolTip()
        assert bar.session_combo.currentData() == "demo-a"
        assert picker.close_button.accessibleName() == "关闭应用管理"
    assert switched.count() == 0


def test_session_status_visibility_and_route_clear_do_not_leave_stale_text(session_bar):
    _window, bar, combo, close, badge = session_bar
    bar.set_session_context(None, None, badge)
    bar.open_picker()
    assert bar.session_hint.isHidden()
    assert bar.session_combo.isHidden()
    assert not bar._picker.close_button.isVisible()

    badge.hide()
    bar.set_session_context(None, None, badge)
    assert bar.session_hint.isHidden()
    assert bar.session_hint.text() == ""
    assert not bar._picker.close_button.isVisible()

    badge.show()
    bar.set_session_context(combo, close, badge)
    assert bar.session_hint.isHidden()
    assert bar._picker.close_button.isVisible()
    bar.set_session_context(None, None)
    assert bar._picker is None
    assert bar.session_hint.text() == ""
    assert bar.session_hint.toolTip() == ""
    assert bar.session_hint.accessibleDescription() == ""
    assert bar.session_combo.accessibleDescription() == ""
    assert bar.session_combo.toolTip() == ""
    bar.open_picker()
    assert not bar._picker.close_button.isVisible()
    assert bar._picker.close_button.accessibleDescription() == ""


@pytest.mark.parametrize("width,font_size", [(968, 12), (1000, 12), (1400, 12), (650, 22)])
@pytest.mark.parametrize("close_text", ["关闭应用管理", "关闭文件管理", "关闭日志会话", None])
def test_device_selection_preserves_bar_rows(
    session_bar, qt_application, monkeypatch, width, font_size, close_text
):
    window, bar, combo, close, badge = session_bar
    monkeypatch.setattr(
        BaseStyles, "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size)),
    )
    combo.clear()
    combo.addItem("demo-device-01", userData="demo-device-01")
    if close_text is not None:
        close.setText(close_text)
    bar._apply_fonts()
    window.resize(width, 680)
    initial = None
    switched = QSignalSpy(bar.session_requested)
    for selected, status in ((True, "在线"), (False, "未选为操作目标"), (True, "在线")):
        bar.set_context(["demo-device-01"] if selected else [], ["demo-device-01"], "ready")
        badge.setText(status)
        bar.set_session_context(combo, close if close_text is not None else None, badge)
        wait_for_stable_geometry(qt_application, (window, bar, bar.targets_button))
        rows = (bar.height(), mapped_rect(bar.targets_button, bar).top())
        if initial is None:
            initial = rows
        assert rows == initial
        assert bar.session_combo.currentData() == "demo-device-01"
        assert bar.session_hint.isHidden()
        assert bar.session_target.isHidden()
        assert bar.session_combo.isHidden()
        assert status in bar.session_combo.accessibleDescription()
        assert status in bar.accessibleDescription()
        assert ("未勾选" in bar.targets_button.accessibleName()) == (not selected)
        assert [control for control in bar.findChildren(QAbstractButton)
                if control.isVisible()] == [bar.targets_button]
        assert bar.rect().contains(mapped_rect(bar.targets_button, bar))
        bar.open_picker()
        picker = bar._picker
        wait_for_stable_geometry(qt_application, (picker, picker.close_button))
        if close_text is not None:
            assert picker.close_button.isVisible()
            assert picker.close_button.width() >= picker.close_button.sizeHint().width()
            assert status in picker.close_button.accessibleDescription()
            assert picker.rect().contains(mapped_rect(picker.close_button, picker))
            assert (mapped_rect(picker.close_button, picker).top()
                    > mapped_rect(picker.clear_button, picker).bottom())
        else:
            assert not picker.close_button.isVisible()
        bar.dismiss_popups()
    assert switched.count() == 0


def test_long_session_name_does_not_force_a_second_row(session_bar, qt_application):
    window, bar, combo, close, badge = session_bar
    window.resize(1048, 680)
    name = "demo-device-with-a-long-display-name-" * 4 + "01"
    combo.clear()
    combo.addItem(name, userData="demo-a")
    bar.set_device_labels({"demo-a": name})
    badge.setText("未选为操作目标")
    bar.set_context([], ["demo-a"], "ready")
    bar.set_session_context(combo, close, badge)
    wait_for_stable_geometry(qt_application, (window, bar, bar.targets_button))
    assert bar.session_combo.currentText() == name
    assert bar.session_combo.currentData() == "demo-a"
    assert bar.session_combo.itemText(0) == name
    assert name in bar.session_combo.accessibleDescription()
    assert "未选为操作目标" in bar.session_combo.accessibleDescription()
    assert bar.session_combo.isHidden()
    assert bar.session_target.isHidden()
    assert "…" in bar.targets_button.text()
    for width in (500, 1048):
        window.resize(width, 680)
        wait_for_stable_geometry(
            qt_application, (window, bar, bar.targets_button),
        )
        assert name in bar.session_combo.accessibleDescription()
        assert "未选为操作目标" in bar.session_combo.accessibleDescription()
        assert name in bar.targets_button.accessibleName()
        assert name in bar.targets_button.toolTip()
        assert bar.rect().contains(mapped_rect(bar.targets_button, bar))
        bar.open_picker()
        picker = bar._picker
        wait_for_stable_geometry(qt_application, (picker, picker.close_button))
        assert picker.close_button.isVisible()
        assert picker.rect().contains(mapped_rect(picker.close_button, picker))
        bar.dismiss_popups()


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
    wait_for_stable_geometry(qt_application, (window, bar, bar.targets_button))
    assert window.width() == width
    assert bar.targets_button.isVisible()
    assert bar.rect().contains(mapped_rect(bar.targets_button, bar))
    assert bar.targets_button.height() >= bar.targets_button.fontMetrics().height()
    assert bar.session_hint.isHidden()
    assert bar.session_target.isHidden()
    assert bar.session_combo.isHidden()
    bar.open_picker()
    picker = bar._picker
    wait_for_stable_geometry(qt_application, (picker, picker.close_button))
    assert picker.close_button.isVisible()
    assert picker.rect().contains(mapped_rect(picker.close_button, picker))
    assert picker.close_button.height() >= picker.close_button.fontMetrics().height()
    assert picker.close_button.width() >= picker.close_button.sizeHint().width()
    assert status in bar.session_combo.accessibleDescription()
    assert status in bar.accessibleDescription()
    assert status in picker.close_button.accessibleDescription()
    assert "关闭应用管理" in picker.close_button.accessibleName()


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
    assert bar.session_hint.isHidden()
    assert bar.session_hint.text() == "在线"
    assert bar.session_hint.level == InfoLevel.SUCCESS
    assert "在线" in bar.session_combo.accessibleDescription()

    host.set_device_context([], [])
    bar.set_session_context(host.device_combo, host.close_session_button, host.session_badge)
    assert bar.session_hint.text() == "离线"
    assert bar.session_hint.level == InfoLevel.WARNING
    assert "离线" in bar.session_combo.accessibleDescription()
    assert host.session_badge.parentWidget() is host.session_toolbar


def test_closing_session_projects_resource_wait_instead_of_operation_permission(
    qt_application, monkeypatch
):
    host = WorkspaceFeatureHost("system", "系统工具", QWidget())
    host.register_feature("probe", "测试会话", FluentIcon.SCROLL, _LifecyclePage)
    host.set_external_device_controls(True)
    host.set_device_context(["demo-a"], ["demo-a"])
    host.open_feature("probe", preferred_device="demo-a")
    page = host.stack.currentWidget()
    before_dispose = []

    def postpone_disposal(_reason):
        before_dispose.append((
            host.session_badge.toolTip(), host.session_badge.accessibleDescription(),
        ))
        return False

    monkeypatch.setattr(page, "request_dispose", postpone_disposal)
    bar = DeviceContextBar()
    bar.resize(960, 200)
    bar.show()
    expected = "后台资源仍在退出。完成后可重新打开此功能，不会复用正在关闭的页面。"
    host.close_current_session()
    assert before_dispose == [(expected, expected)]
    for reopen in (False, True):
        if reopen:
            host.show_overview()
            host.open_feature("probe", preferred_device="demo-a")
        assert host.stack.currentWidget() is host.closing_page
        bar.set_session_context(host.device_combo, host.close_session_button, host.session_badge)
        if bar._picker is None:
            bar.open_picker()
        assert not bar._picker.close_button.isEnabled()
        assert bar._picker.close_button.accessibleName() == "正在关闭"
        assert bar.session_hint.isHidden()
        for control in (bar.session_combo, bar._picker.close_button):
            assert "正在关闭" in control.toolTip()
            assert expected in control.toolTip()
            assert expected in control.accessibleDescription()
            assert "当前设备可执行操作" not in control.accessibleDescription()
    page.dispose_ready.emit(page.key)


def test_closing_projection_survives_target_and_connection_changes(qt_application):
    """关闭屏障优先于设备状态；变更操作目标不恢复关闭按钮或复用退出中的页面。"""
    host = WorkspaceFeatureHost("system", "系统工具", QWidget())
    host.register_feature("probe", "测试会话", FluentIcon.SCROLL, _LifecyclePage)
    host.set_external_device_controls(True)
    bar = DeviceContextBar()
    bar.resize(960, 200)
    bar.show()
    connected = ["demo-a", "demo-b"]

    def project_controls():
        bar.set_session_context(host.device_combo, host.close_session_button, host.session_badge)

    def select_targets(selected):
        bar.set_context(selected, connected, "ready" if connected else "empty")
        host.set_device_context(selected, connected)

    host.controls_changed.connect(project_controls)
    bar.selection_requested.connect(select_targets)
    select_targets(["demo-a"])
    host.open_feature("probe", preferred_device="demo-a")
    page = host.stack.currentWidget()
    page.dispose_immediately = False
    key = page.key
    host.close_current_session()
    expected = "后台资源仍在退出。完成后可重新打开此功能，不会复用正在关闭的页面。"

    def assert_closing():
        assert host.stack.currentWidget() is host.closing_page
        assert host.registry.is_disposing(key)
        assert not host.close_session_button.isEnabled()
        if bar._picker is None:
            bar.open_picker()
        assert not bar._picker.close_button.isEnabled()
        assert bar._picker.close_button.accessibleName() == "正在关闭"
        assert host.session_badge.text() == "正在关闭"
        for control in (bar.session_combo, bar._picker.close_button):
            assert "正在关闭" in control.toolTip()
            assert expected in control.accessibleDescription()
            assert "当前设备可执行操作" not in control.accessibleDescription()

    assert_closing()
    for checked in (False, True):
        bar.session_target.click()
        assert bar.session_target.isChecked() is checked
        assert bar.session_target.isEnabled()
        assert tuple(host._selected_devices) == (("demo-a",) if checked else ())
        assert_closing()
    connected = []
    select_targets([])
    assert not bar.session_target.isEnabled()
    assert_closing()
    connected = ["demo-a", "demo-b"]
    select_targets(["demo-a"])
    assert bar.session_target.isEnabled()
    assert_closing()
    host.show_overview()
    host.open_feature("probe", preferred_device="demo-a")
    assert_closing()
    assert page.activations == [None]

    page.dispose_ready.emit(key)
    assert host.registry.get(key) is None
    host.open_feature("probe", preferred_device="demo-a")
    replacement = host.stack.currentWidget()
    assert replacement is not page and replacement is not host.closing_page
    assert replacement.key.generation == key.generation + 1
    bar.open_picker()
    assert bar._picker.close_button.isEnabled()
    assert host.session_badge.text() == "在线"
    assert "正在关闭" not in bar.session_combo.accessibleDescription()
