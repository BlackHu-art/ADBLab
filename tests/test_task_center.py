"""TaskCenterPage 的轮询、取消路由与隐藏停表契约测试。"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QPushButton

from adblab.application.operations import OperationManager
from gui.pages.tasks_page import TaskCenterPage
from gui.styles import BaseStyles
from services.task_history import TaskHistoryStore


def test_existing_task_rows_follow_font_round_trip_without_rebuilding(
    qt_application, monkeypatch,
):
    """修改字号原位刷新任务文字，保留活动行、文本选择和取消目标。"""
    from types import SimpleNamespace

    from core.settings_manager import DEFAULTS, AppSettings
    from gui.styles import FontRole
    from tests.ui_geometry_helpers import assert_scroll_target_reachable, assert_text_fits

    values = dict(DEFAULTS, ui_font_size=12, font_family="Arial")
    monkeypatch.setattr(
        AppSettings, "instance", classmethod(lambda _cls: SimpleNamespace(get=values.get)),
    )
    BaseStyles.reload_from_settings()
    manager = OperationManager()
    operation = manager.begin("batch_install")
    manager.mark_running(operation.operation_id)
    stop_hook = Mock()
    page = TaskCenterPage(operation_manager=manager, stop_hook=stop_hook)
    try:
        page.resize(650, 600)
        page.show()
        qt_application.processEvents()
        row = page._active_rows[operation.operation_id]
        cancel = next(button for button in row.findChildren(QPushButton))
        row._summary.setSelection(0, 2)
        selected_text = row._summary.selectedText()
        for size in (22, 12):
            values["ui_font_size"] = size
            BaseStyles.reload_from_settings()
            page.refresh()
            qt_application.processEvents()
            assert page._active_rows[operation.operation_id] is row
            assert row._summary.selectedText() == selected_text
            for widget, role in (
                (row._summary, FontRole.UI),
                (row._badge, FontRole.UI_SMALL),
                (cancel, FontRole.UI),
                (page._active_card.headerLabel, FontRole.TITLE),
                (page._history_card.headerLabel, FontRole.TITLE),
                (page.action_empty_label, FontRole.UI_SMALL),
                (page.running_actions_button, FontRole.UI),
            ):
                assert widget.font().pointSizeF() == BaseStyles.font_for_role(role).pointSizeF()
            assert_scroll_target_reachable(page._scroll, cancel)
            assert_text_fits(cancel)
        QTest.mouseClick(cancel, Qt.MouseButton.LeftButton)
        assert manager.get(operation.operation_id).cancel_requested
        stop_hook.assert_called_once_with(operation.operation_id)
    finally:
        page.shutdown()
        page.close()


@pytest.mark.parametrize("width,language", [(720, "zh_CN"), (860, "zh_CN"), (452, "en_US")])
def test_large_font_active_task_cancel_remains_reachable_in_main_frame(
    qt_application, monkeypatch, width, language,
):
    from adblab.application.action_results import ActionResults, ActionSpec, capture_action_job
    from core.settings_manager import AppSettings
    from gui.i18n import install_translators, tr
    from tests.test_main_window_layout import (
        _FakeScreen,
        _FakeScreenAdapter,
        _MainFrameSettings,
        build_main_frame,
    )
    from tests.ui_geometry_helpers import (
        assert_scroll_target_reachable,
        assert_text_fits,
        wait_for_stable_geometry,
        wait_until,
    )

    settings = _MainFrameSettings()
    settings.values.update({"ui_font_size": 22, "font_family": "Microsoft YaHei"})
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr("models.device_store.DeviceStore.get_full_devices_info", lambda *_args: [])
    monkeypatch.setattr("models.device_store.DeviceStore.get_basic_devices_info", lambda *_args: [])
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    BaseStyles.reload_from_settings()
    translators = install_translators(qt_application, language)
    adapter = _FakeScreenAdapter(_FakeScreen("test-screen", QSize(width, 650)))
    frame = build_main_frame(screen_adapter=adapter, settings=settings)
    manager = OperationManager()
    operations = [manager.begin(kind) for kind in ("batch_install", "screenshot")]
    for operation in operations:
        manager.mark_running(operation.operation_id)
    page = frame._task_page
    page._operation_manager = manager
    stop_hook = Mock()
    page._stop_hook = stop_hook
    results = ActionResults(page.present_action_result)
    job = results.run(
        ActionSpec("pending-query", "system.shell", "查询"), (),
        lambda: capture_action_job("query_async"),
    )
    try:
        frame.show()
        frame._bind_window_screen()
        frame._on_nav_requested("tasks")
        page.refresh()
        wait_until(qt_application, lambda: page.isVisibleTo(frame))
        wait_for_stable_geometry(qt_application, (frame, page, page._scroll.widget()))
        assert frame.width() == width
        assert page._scroll.widget().width() <= page._scroll.viewport().width() + 2
        for operation in operations:
            button = next(
                button for button in page.findChildren(QPushButton)
                if button.text() == tr("取消") and operation.operation_id in button.toolTip()
            )
            assert_scroll_target_reachable(page._scroll, button)
            assert_text_fits(button)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            assert manager.get(operation.operation_id).cancel_requested
            stop_hook.assert_any_call(operation.operation_id)
        assert stop_hook.call_count == 2
        running_button = page.running_actions_button
        full_text = tr("查看执行中的操作（{count}）").format(count=1)
        assert running_button.toolTip() == full_text
        assert running_button.accessibleName() == full_text
        assert_scroll_target_reachable(page._scroll, running_button)
        assert_text_fits(running_button)
        clicked = QSignalSpy(running_button.clicked)
        QTest.mouseClick(running_button, Qt.MouseButton.LeftButton)
        assert clicked.count() == 1
        assert page.action_results._selected == job.request_id
        assert page.action_results.isVisibleTo(page)
    finally:
        results.close()
        page.shutdown()
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        for translator in translators:
            qt_application.removeTranslator(translator)


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
