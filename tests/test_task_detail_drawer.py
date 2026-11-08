"""共享任务抽屉的真实位置动画、交互隔离和宿主生命周期。"""

from dataclasses import replace

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import delete, isValid

from core.settings_manager import AppSettings
from gui.styles import BaseStyles
from gui.widgets.task_detail_drawer import TaskDetailDrawer
from gui.widgets.task_table import TaskRowData
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def _row(key="action:first", **changes):
    return replace(TaskRowData(key, "查询设备", "设备", "设备 1", "运行中", "accent",
                               "刚刚", "本次", cancellable=True), **changes)


@pytest.fixture
def drawer(qt_application):
    host = QWidget()
    host.resize(840, 620)
    origin = QPushButton("查看任务", host)
    origin.setGeometry(20, 20, 100, 36)
    panel = TaskDetailDrawer(host)
    content = QWidget()
    layout = QVBoxLayout(content)
    editor = QLineEdit("保留正文", content)
    action = QPushButton("内容操作", content)
    layout.addWidget(editor)
    layout.addWidget(action)
    panel.set_content(content)
    panel.present(_row())
    host.show()
    host.activateWindow()
    qt_application.processEvents()
    yield host, panel, origin, content, editor, action
    if isValid(host):
        panel.shutdown()
        host.close()


def test_position_animation_has_opaque_intermediate_frames_without_resizing_content(drawer):
    host, panel, _origin, content, _editor, _action = drawer
    panel.open_drawer()
    assert panel.opened
    assert panel.animation.state() == QAbstractAnimation.State.Running
    panel.animation.setCurrentTime(110)
    assert 450 < panel.x() < 840
    assert panel.size().width() == 390
    assert panel.height() == 620
    original_size = content.size()
    panel.animation.setCurrentTime(190)
    assert content.size() == original_size
    assert panel.graphicsEffect() is None
    image = panel.grab().toImage()
    color = image.pixelColor(image.width() - 3, image.height() - 3)
    assert color.alpha() == 255
    assert color == QColor(BaseStyles.color("CONTENT_BG"))
    panel.animation.setCurrentTime(panel.animation.duration())
    assert panel.x() == host.width() - 390


def test_close_intent_precedes_hidden_signal_and_fast_reversal_keeps_reader(drawer):
    _host, panel, _origin, content, editor, _action = drawer
    changed = QSignalSpy(panel.opened_changed)
    closed = QSignalSpy(panel.closed)
    panel.open_drawer(animated=False)
    editor.selectAll()
    panel.close_drawer()
    assert not panel.opened
    assert changed.count() == 2
    assert changed.at(changed.count() - 1) == [False]
    assert not panel.isHidden()
    assert closed.count() == 0
    panel.animation.setCurrentTime(100)
    current = panel.x()
    panel.open_drawer()
    assert panel.x() == current
    panel.animation.setCurrentTime(panel.animation.duration())
    assert closed.count() == 0
    assert content.parentWidget() is not None
    assert editor.selectedText() == "保留正文"
    panel.close_drawer()
    panel.animation.setCurrentTime(panel.animation.duration())
    assert panel.isHidden()
    assert closed.count() == 1
    panel.close_drawer(animated=False)
    assert closed.count() == 1


def test_host_resize_tracks_available_width_and_retargets_running_animation(drawer, qt_application):
    host, panel, _origin, _content, _editor, _action = drawer
    panel.open_drawer()
    panel.animation.setCurrentTime(100)
    host.resize(300, 460)
    qt_application.processEvents()
    assert panel.width() == 300
    assert panel.height() == 460
    assert 0 <= panel.x() <= 300
    panel.animation.setCurrentTime(panel.animation.duration())
    assert panel.geometry().getRect() == (0, 0, 300, 460)
    host.resize(1000, 700)
    qt_application.processEvents()
    assert panel.geometry().getRect() == (610, 0, 390, 700)


def test_auto_open_preserves_focus_and_explicit_escape_returns_valid_origin(drawer, qt_application):
    _host, panel, origin, _content, editor, _action = drawer
    origin.setFocus()
    wait_until(qt_application, origin.hasFocus)
    panel.open_drawer(animated=False)
    assert origin.hasFocus()
    panel.close_drawer(animated=False)
    panel.open_drawer(origin, animated=False)
    assert panel.close_button.hasFocus()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert not panel.opened
    assert origin.hasFocus()


def test_closing_immediately_removes_mouse_and_tab_interaction_without_gray_palette(drawer):
    _host, panel, origin, _content, editor, action = drawer
    panel.open_drawer(origin, animated=False)
    clicked = QSignalSpy(action.clicked)
    panel.close_drawer()
    assert editor.isEnabled()
    assert action.isEnabled()
    assert editor.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert action.focusPolicy() == Qt.FocusPolicy.NoFocus
    QTest.mouseClick(action, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    assert clicked.count() == 0
    panel.open_drawer(animated=False)
    assert editor.focusPolicy() == Qt.FocusPolicy.StrongFocus
    QTest.mouseClick(action, Qt.MouseButton.LeftButton)
    assert clicked.count() == 1


@pytest.mark.parametrize("action", ["hide", "minimize"])
def test_hidden_or_minimized_host_settles_animation_without_resurrection(
    drawer, qt_application, action,
):
    host, panel, _origin, _content, _editor, _action = drawer
    panel.open_drawer()
    panel.animation.setCurrentTime(90)
    if action == "hide":
        host.hide()
    else:
        host.showMinimized()
    qt_application.processEvents()
    assert panel.animation.state() == QAbstractAnimation.State.Stopped
    host.showNormal()
    qt_application.processEvents()
    assert panel.opened
    assert panel.x() == 450
    assert panel.animation.state() == QAbstractAnimation.State.Stopped


def test_shutdown_closes_once_and_rejects_late_present_and_open(drawer):
    _host, panel, origin, _content, _editor, _action = drawer
    closed = QSignalSpy(panel.closed)
    panel.open_drawer(origin)
    panel.shutdown()
    assert not panel.opened
    assert panel.isHidden()
    assert panel.animation.state() == QAbstractAnimation.State.Stopped
    assert closed.count() == 1
    panel.present(_row("action:late"))
    panel.open_drawer(origin)
    panel.shutdown()
    assert panel.selected_key == "action:first"
    assert panel.isHidden()
    assert closed.count() == 1


def test_metadata_buttons_emit_identity_and_completed_tasks_cannot_cancel(drawer):
    _host, panel, _origin, _content, _editor, _action = drawer
    cancel = QSignalSpy(panel.cancel_requested)
    panel.present(_row(), source_label="设备概览", source_available=True,
                  recent=(_row(), _row("action:other", title="其他查询")))
    panel.open_drawer(animated=False)
    assert panel.source_label.text() == "设备概览"
    assert panel.target_label.text() == "设备 1"
    panel.cancel_button.click()
    assert cancel.count() == 1
    assert cancel.at(0) == ["action:first"]
    panel.present(_row(cancellable=False), source_available=True, from_task_center=True)
    panel.cancel_button.click()
    assert cancel.count() == 1
    assert panel.cancel_button.isHidden()


def test_content_is_installed_once_and_destroying_host_stops_animation(drawer, qt_application):
    host, panel, _origin, content, _editor, _action = drawer
    parent = content.parentWidget()
    panel.set_content(content)
    assert content.parentWidget() is parent
    other = QWidget()
    with pytest.raises(ValueError):
        panel.set_content(other)
    other.deleteLater()
    panel.open_drawer()
    animation = panel.animation
    delete(host)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_application.processEvents()
    assert not isValid(panel)
    assert not isValid(animation)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_theme_and_large_font_keep_actions_reachable_and_reader_selection(
    drawer, qt_application, monkeypatch, theme,
):
    host, panel, _origin, _content, editor, _action = drawer
    panel.open_drawer(animated=False)
    editor.selectAll()
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: {
        "ui_font_size": 22, "font_family": "Arial", "log_font_size": 11,
    }))
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    host.resize(300, 620)
    qt_application.processEvents()
    assert editor.selectedText() == "保留正文"
    assert panel.width() == 300
    for button in (panel.close_button, panel.cancel_button):
        assert panel.rect().contains(button.mapTo(panel, button.rect().topLeft()))
        assert panel.rect().contains(button.mapTo(panel, button.rect().bottomRight()))
        assert button.height() >= button.fontMetrics().height() + 8
    assert panel.scroll_area.horizontalScrollBar().maximum() == 0
    image = panel.grab().toImage()
    assert image.pixelColor(image.width() - 3, image.height() - 3) == QColor(
        BaseStyles.color("CONTENT_BG")
    )


def test_deleted_focus_origin_can_close_without_accessing_destroyed_widget(drawer):
    _host, panel, origin, _content, editor, _action = drawer
    panel.open_drawer(origin, animated=False)
    editor.setFocus()
    delete(origin)
    panel.close_drawer(animated=False)
    assert panel.isHidden()
    assert not panel.opened


def test_new_reader_control_cannot_enter_tab_chain_during_close(drawer, qt_application):
    _host, panel, _origin, content, _editor, _action = drawer
    panel.open_drawer(animated=False)
    panel.close_drawer()
    late_editor = QLineEdit("晚到内容", content)
    content.layout().addWidget(late_editor)
    late_editor.show()
    qt_application.processEvents()
    assert late_editor.focusPolicy() == Qt.FocusPolicy.NoFocus
    panel.open_drawer(animated=False)
    assert late_editor.focusPolicy() == Qt.FocusPolicy.StrongFocus


@pytest.mark.parametrize("reader_class", [QTextEdit, QListWidget])
def test_focus_proxy_readers_keep_tab_focus_on_first_open_and_reopen(
    qt_application, reader_class,
):
    host = QWidget()
    host.resize(840, 620)
    panel = TaskDetailDrawer(host)
    reader = reader_class()
    original_reader_policy = reader.focusPolicy()
    original_viewport_policy = reader.viewport().focusPolicy()
    assert original_reader_policy == Qt.FocusPolicy.StrongFocus
    assert reader.viewport().focusProxy() is reader
    panel.set_content(reader)
    panel.present(_row())
    host.show()
    host.activateWindow()
    qt_application.processEvents()
    try:
        for _ in range(2):
            panel.open_drawer(animated=False)
            assert reader.focusPolicy() == original_reader_policy
            assert reader.viewport().focusPolicy() == original_viewport_policy
            panel.close_button.setFocus()
            for _step in range(len(panel.findChildren(QWidget)) + 1):
                focus = QApplication.focusWidget()
                assert focus is not None
                QTest.keyClick(focus, Qt.Key.Key_Tab)
                if reader.hasFocus():
                    break
            assert reader.hasFocus()
            panel.close_drawer()
            assert reader.focusPolicy() == Qt.FocusPolicy.NoFocus
            assert reader.viewport().focusPolicy() == Qt.FocusPolicy.NoFocus
            panel.animation.setCurrentTime(panel.animation.duration())
    finally:
        panel.shutdown()
        host.close()
