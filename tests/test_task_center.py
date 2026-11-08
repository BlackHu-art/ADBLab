"""TaskCenterPage 的轮询、取消路由与隐藏停表契约测试。"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtTest import QSignalSpy, QTest

from gui.pages.tasks_page import TaskCenterPage
from gui.styles import BaseStyles
from services.task_history import TaskHistoryStore
from services.tasks.operations import OperationManager


def _assert_table_control_reachable(page, key, column, control):
    from PySide6.QtCore import QCoreApplication, QRect

    view = page.table.view
    assert key in page.table.record_keys
    assert page.table.rows[key].cells[column].isAncestorOf(control)
    view.ensureWidgetVisible(control, 0, 4)
    QCoreApplication.processEvents()
    assert (
        view.viewport()
        .rect()
        .contains(QRect(control.mapTo(view.viewport(), QPoint()), control.size()))
    )


@pytest.mark.parametrize("font_size,width", [(12, 1120), (22, 860)])
def test_task_route_shows_one_title_without_device_controls(
    qt_application, monkeypatch, font_size, width,
):
    from core.settings_manager import AppSettings
    from gui.i18n import tr
    from tests.test_main_window_layout import (
        _FakeScreen,
        _FakeScreenAdapter,
        _MainFrameSettings,
        build_main_frame,
    )
    from tests.ui_geometry_helpers import wait_for_stable_geometry
    from tests.ui_lifecycle_helpers import cleanup_ui_windows

    settings = _MainFrameSettings()
    settings.values.update(ui_font_size=font_size, font_family="Arial", window_width=width)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr("models.device_store.DeviceStore.get_basic_devices_info", lambda: [])
    monkeypatch.setattr("models.device_store.DeviceStore.get_full_devices_info", lambda *_: [])
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    BaseStyles.reload_from_settings()
    frame = build_main_frame(
        settings=settings,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("task-title", QSize(1600, 1000))),
    )
    try:
        frame.show()
        frame._on_nav_requested("tasks")
        page = frame._task_page
        wait_for_stable_geometry(qt_application, (page, page.title_label, page.filters))
        assert frame.stackedWidget.currentWidget() is frame._tasks_page
        assert page.title_label.text() == tr("任务中心")
        assert page.title_label.isVisibleTo(frame)
        assert frame._global_device_bar.isHidden()
        assert page.title_label.font() == frame._global_device_bar.page_title.font()
    finally:
        assert not cleanup_ui_windows((frame,), cleanup_records={})


def test_existing_task_rows_follow_font_round_trip_without_rebuilding(
    qt_application, monkeypatch,
):
    """修改字号原位刷新任务文字，保留活动行、文本选择和取消目标。"""
    from types import SimpleNamespace

    from core.settings_manager import DEFAULTS, AppSettings
    from gui.styles import FontRole
    from tests.ui_geometry_helpers import assert_text_fits

    values = dict(DEFAULTS, ui_font_size=12, font_family="Arial")
    monkeypatch.setattr(
        AppSettings, "instance", classmethod(lambda _cls: SimpleNamespace(get=values.get)),
    )
    BaseStyles.reload_from_settings()
    manager = OperationManager()
    operation = manager.begin("batch_install")
    manager.mark_running(operation.operation_id)
    manager.update_progress(operation.operation_id, 10, message="正在安装应用")
    stop_hook = Mock()
    page = TaskCenterPage(operation_manager=manager, stop_hook=stop_hook)
    try:
        page.resize(650, 600)
        page.show()
        qt_application.processEvents()
        key = f"operation:{operation.operation_id}"
        row = page.table.rows[key]
        cancel = row.cancel
        row.title.click()
        cursor = page.operation_output.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
        page.operation_output.setTextCursor(cursor)
        selected_text = cursor.selectedText()
        for size in (22, 12):
            values["ui_font_size"] = size
            BaseStyles.reload_from_settings()
            page.refresh()
            qt_application.processEvents()
            assert page.table.rows[key] is row
            assert row.cancel is cancel
            assert page.operation_output.textCursor().selectedText() == selected_text
            for widget, role in (
                (row.title, FontRole.UI),
                (row.status, FontRole.UI_SMALL),
                (page.count_label, FontRole.UI_SMALL),
                (page.table.header_cells[0], FontRole.UI_SMALL),
            ):
                assert widget.font().pointSizeF() == BaseStyles.font_for_role(role).pointSizeF()
            _assert_table_control_reachable(page, key, 3, cancel)
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
    from PySide6.QtCore import QAbstractAnimation

    from core.settings_manager import AppSettings
    from gui.i18n import install_translators, tr
    from services.tasks.action_results import ActionResults, ActionSpec, capture_action_job
    from tests.test_main_window_layout import (
        _FakeScreen,
        _FakeScreenAdapter,
        _MainFrameSettings,
        build_main_frame,
    )
    from tests.ui_geometry_helpers import (
        assert_contained,
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
            button = page.table.rows[f"operation:{operation.operation_id}"].cancel
            assert button.accessibleName() == tr("取消任务")
            _assert_table_control_reachable(page, f"operation:{operation.operation_id}", 3, button)
            assert_text_fits(button)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            assert manager.get(operation.operation_id).cancel_requested
            stop_hook.assert_any_call(operation.operation_id)
        assert stop_hook.call_count == 2
        running_row = page.table.rows[f"action:{job.request_id}"]
        assert running_row.title.toolTip() == tr("查询")
        assert running_row.title.accessibleName() == tr("查询")
        _assert_table_control_reachable(page, f"action:{job.request_id}", 0, running_row.title)
        assert_text_fits(running_row.title)
        reader = page.action_results
        clicked = QSignalSpy(running_row.title.clicked)
        QTest.mouseClick(running_row.title, Qt.MouseButton.LeftButton)
        assert clicked.count() == 1
        key = f"action:{job.request_id}"
        drawer = frame._task_feedback.drawer
        assert page.selected_key == key
        assert drawer.opened and drawer.selected_key == key
        wait_until(qt_application, lambda: (
            drawer.isVisibleTo(frame)
            and drawer.animation.state() == QAbstractAnimation.State.Stopped
        ))
        assert drawer.parentWidget() is frame._content_surface
        assert_contained(drawer, frame._content_surface)
        assert drawer.isAncestorOf(page.detail)
        assert page.action_results is reader
        assert drawer.isAncestorOf(reader)
        assert reader._selected == job.request_id
        assert reader.isVisibleTo(frame)
        assert_scroll_target_reachable(drawer.scroll_area, reader.summary)
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


def test_poll_diff_preserves_existing_rows_when_snapshot_unchanged(qt_application):
    manager = OperationManager()
    operation = manager.begin("install")
    page = TaskCenterPage(operation_manager=manager, history_store=TaskHistoryStore())
    key = f"operation:{operation.operation_id}"
    row = page.table.rows[key]
    title, cancel = row.title, row.cancel

    page.refresh()
    page.refresh()
    assert page.table.rows[key] is row
    assert row.title is title
    assert row.cancel is cancel

    added = manager.begin("install")
    page.refresh()
    assert f"operation:{added.operation_id}" in page.table.rows
    assert page.table.rows[key] is row
    assert row.title is title
    assert row.cancel is cancel

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

    cancel_button = page.table.rows[f"operation:{operation.operation_id}"].cancel
    assert len(page.table.rows) == 1
    cancel_button.click()
    assert not cancel_button.isEnabled()

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
