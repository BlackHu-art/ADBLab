"""TaskCenterPage 的轮询、取消路由与隐藏停表契约测试。"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QPushButton

from adblab.application.operations import OperationManager
from gui.pages.tasks_page import TaskCenterPage
from gui.styles import BaseStyles
from services.task_history import TaskHistoryStore


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_task_lists_share_page_background_without_an_outer_frame(qt_application, theme):
    BaseStyles.switch_theme(theme)
    page = TaskCenterPage(operation_manager=OperationManager())
    page.resize(680, 600)
    page.show()
    qt_application.processEvents()
    rendered = page.grab().toImage()
    edge = page._scroll.mapTo(page, QPoint(0, 80))
    scale = rendered.devicePixelRatio()
    assert rendered.pixelColor(round(edge.x() * scale), round(edge.y() * scale)) == QColor(
        BaseStyles.color("WINDOW_BG")
    )
    page.shutdown()


def test_poll_diff_skips_rebuild_when_snapshot_unchanged():
    manager = OperationManager()
    page = TaskCenterPage(operation_manager=manager, history_store=TaskHistoryStore())
    spy = Mock(wraps=page._render_active_rows)
    page._render_active_rows = spy

    page.refresh()
    page.refresh()
    assert spy.call_count == 1  # 快照未变，不重建控件

    manager.begin("install")
    page.refresh()
    assert spy.call_count == 2  # 快照变化，才重建

    page.shutdown()


def test_cancel_dual_path_requests_cancel_and_calls_stop_hook():
    manager = OperationManager()
    operation = manager.begin("install")
    manager.mark_running(operation.operation_id)
    stop_hook = Mock()
    page = TaskCenterPage(operation_manager=manager, stop_hook=stop_hook)

    page._cancel(operation.operation_id)

    snapshot = manager.get(operation.operation_id)
    assert snapshot is not None
    assert snapshot.cancel_requested is True
    stop_hook.assert_called_once_with(operation.operation_id)
    page.shutdown()


def test_cancel_button_triggers_dual_path():
    manager = OperationManager()
    operation = manager.begin("install")
    manager.mark_running(operation.operation_id)
    stop_hook = Mock()
    page = TaskCenterPage(operation_manager=manager, stop_hook=stop_hook)
    page.refresh()

    cancel_buttons = [
        button for button in page.findChildren(QPushButton) if button.text() == "取消"
    ]
    assert len(cancel_buttons) == 1
    cancel_buttons[0].click()

    snapshot = manager.get(operation.operation_id)
    assert snapshot is not None
    assert snapshot.cancel_requested is True
    stop_hook.assert_called_once_with(operation.operation_id)
    page.shutdown()


def test_hide_stops_poll_timer_and_show_starts_it():
    page = TaskCenterPage(operation_manager=OperationManager())

    page.show()
    assert page._poll_timer.isActive()

    page.hide()
    assert not page._poll_timer.isActive()

    page.shutdown()
