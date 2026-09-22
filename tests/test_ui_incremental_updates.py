"""界面增量更新与瞬态资源的直接回归。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QWidget
from qfluentwidgets import RoundMenu
from shiboken6 import isValid

from adblab.application.operations import OperationManager, OperationState
from gui.pages.tasks_page import TaskCenterPage


def test_progress_refresh_preserves_pressed_cancel_and_unaffected_rows(qt_application):
    manager = OperationManager()
    operations = [manager.begin("install") for _ in range(3)]
    for operation in operations:
        manager.mark_running(operation.operation_id)
    stop = Mock()
    page = TaskCenterPage(operation_manager=manager, stop_hook=stop)
    page.resize(900, 600)
    page.show()
    page.refresh()
    qt_application.processEvents()
    layout = page._active_card.viewLayout
    rows = [layout.itemAt(i).widget() for i in range(layout.count())]
    button = rows[0].findChild(QPushButton)
    assert button is not None
    QTest.mousePress(button, Qt.MouseButton.LeftButton)
    manager.update_progress(operations[0].operation_id, 35)
    page.refresh()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    try:
        assert all(isValid(row) for row in rows)
        assert [layout.itemAt(i).widget() for i in range(layout.count())] == rows
        assert rows[0]._progress.value() == 35
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        assert manager.get(operations[0].operation_id).cancel_requested
        stop.assert_called_once_with(operations[0].operation_id)
    finally:
        page.shutdown()
        page.close()


def test_task_rows_leave_and_return_without_replacing_survivors(qt_application):
    manager = OperationManager()
    first, second = manager.begin("install"), manager.begin("screenshot")
    page = TaskCenterPage(operation_manager=manager)
    try:
        page.refresh()
        first_row = page._active_rows[first.operation_id]
        survivor = page._active_rows[second.operation_id]
        manager.finish(first.operation_id, OperationState.CANCELLED)
        page.refresh()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(first_row)
        assert page._active_rows[second.operation_id] is survivor
        manager.finish(second.operation_id, OperationState.CANCELLED)
        page.refresh()
        assert page._active_card.viewLayout.count() == 1
        replacement = manager.begin("install")
        page.refresh()
        assert list(page._active_rows) == [replacement.operation_id]
        assert page._active_card.viewLayout.count() == 1
    finally:
        page.shutdown()
        page.close()


@pytest.mark.parametrize("factory", ["apps", "files"])
def test_context_menus_release_after_close_and_keep_shared_actions(qt_application, factory):
    from gui.dialogs.app_manager_form import AppManagerForm
    from gui.dialogs.file_explorer import FileExplorerPage
    from gui.widgets.transient_menu import add_shared_menu_action

    parent = QWidget()
    if factory == "apps":
        # 表单控制器只持页面，不需要初始化业务页和后台任务。
        def make_menu():
            return AppManagerForm._create_context_menu(SimpleNamespace(_frame=parent))
    else:
        def make_menu():
            return FileExplorerPage._create_context_menu(parent)
    action = QAction("shared", parent)
    triggered = Mock()
    action.triggered.connect(triggered)
    try:
        for index in range(5):
            menu = make_menu()
            add_shared_menu_action(menu, action)
            menu.exec(QPoint(30, 30), ani=False)
            assert isValid(menu) and menu.isVisible()
            if index == 0:
                menu._onItemClicked(menu.view.item(0))
            else:
                menu.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qt_application.processEvents()
            assert not isValid(menu)
            assert not parent.findChildren(RoundMenu)
            assert isValid(action)
            action.setText(f"shared {index}")
        triggered.assert_called_once()
    finally:
        parent.close()
        parent.deleteLater()


def test_device_icon_reuses_source_and_tinted_engine(qt_application, monkeypatch, tmp_path):
    from gui.styles import icon_loader

    path = tmp_path / "device.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
                    '<rect width="32" height="32" fill="currentColor"/></svg>', encoding="utf-8")
    icon = icon_loader.DeviceIcon()
    monkeypatch.setattr(icon, "path", lambda _theme: str(path))
    reads = Mock(wraps=Path.read_text)
    monkeypatch.setattr(Path, "read_text", lambda self, **kw: reads(self, **kw))
    engines = Mock(wraps=icon_loader.SvgIconEngine)
    monkeypatch.setattr(icon_loader, "SvgIconEngine", engines)
    for _ in range(30):
        assert not icon.icon(color="#123456").pixmap(32, 32).isNull()
    assert reads.call_count == 1
    assert engines.call_count == 1
    assert not icon.icon(color="#654321").pixmap(64, 64).isNull()
    assert reads.call_count == 1
    assert engines.call_count == 2


def test_hidden_performance_logs_buffer_until_activate(qt_application):
    from gui.dialogs.performance_launcher import PerformancePage

    page = PerformancePage(device_ip="device-test")
    page.activate()
    page._append_log("RAW", "visible")
    assert page._log_flush_timer.isActive()
    page.deactivate()
    page.hide()
    render = Mock(wraps=page._log_controller._render_log_rows)
    page._log_controller._render_log_rows = render
    try:
        for index in range(page.MAX_PENDING_LOG_ROWS + 25):
            page._append_log("RAW", f"hidden {index}")
        page._flush_pending_logs()
        assert not page._log_flush_timer.isActive()
        render.assert_not_called()
        assert len(page._pending_log_rows) == page.MAX_PENDING_LOG_ROWS
        page.activate()
        render.assert_called_once()
        assert page._pending_log_rows == []
        assert f"hidden {page.MAX_PENDING_LOG_ROWS + 24}" in page.log_view.toPlainText()
        assert page.log_view.document().blockCount() <= page._max_log_lines
        bar = page.log_view.verticalScrollBar()
        assert bar.value() == bar.maximum()
    finally:
        page.close()


def test_hidden_performance_logs_preserve_paused_scroll(qt_application):
    from gui.dialogs.performance_launcher import PerformancePage

    page = PerformancePage(device_ip="device-test")
    page.resize(900, 700)
    page.activate()
    try:
        page._append_log("RAW", "\n".join(f"visible {i}" for i in range(200)))
        qt_application.processEvents()
        bar = page.log_view.verticalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(10)
        page.deactivate()
        page.hide()
        page._append_log("RAW", "\n".join(f"hidden {i}" for i in range(50)))
        assert "hidden 49" not in page.log_view.toPlainText()
        page.activate()
        assert "hidden 49" in page.log_view.toPlainText()
        assert bar.value() == 10
        page.close()
        page._append_log("RAW", "late")
        assert not page._pending_log_rows
    finally:
        page.close()
