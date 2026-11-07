"""任务中心沿用页面标题、分层空态和既有筛选语义。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest

from core.settings_manager import AppSettings
from gui.i18n import install_translators, tr
from gui.pages.tasks_page import TaskCenterPage
from gui.styles import BaseStyles
from gui.widgets.device_context_bar import DeviceContextBar
from services.tasks.action_results import ActionResult, ActionSpec
from services.tasks.operations import OperationManager
from tests.ui_geometry_helpers import (
    assert_scroll_target_reachable,
    assert_text_fits,
    wait_for_stable_geometry,
)

pytestmark = pytest.mark.ui


def _assert_wrapped_text_fits(label):
    bounds = label.contentsRect()
    needed = label.fontMetrics().boundingRect(
        QRect(0, 0, bounds.width(), 10000), Qt.TextFlag.TextWordWrap, label.text(),
    )
    assert needed.height() <= bounds.height() + 2


@pytest.mark.parametrize("width,font_size", [(360, 12), (360, 22), (1000, 12), (1000, 22)])
@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_title_and_empty_state_follow_workspace_geometry(
    qt_application, monkeypatch, width, font_size, theme,
):
    settings = {"ui_font_size": font_size, "font_family": "Arial", "log_font_size": 11}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    reference = DeviceContextBar()
    reference.set_page_title(tr("任务中心"))
    reference.resize(1000, 100)
    reference.show()
    page = TaskCenterPage()
    page.resize(width, 650)
    page.show()
    try:
        wait_for_stable_geometry(qt_application, (page, page.filters, page.empty_state))
        assert page.title_label.isVisibleTo(page)
        assert page.title_label.text() == tr("任务中心")
        assert page.title_label.font() == reference.page_title.font()
        assert page.title_label.mapTo(page, QPoint()) == QPoint(32, 12)
        assert page.filters.mapTo(page._scroll.viewport(), QPoint()) == QPoint(32, 8)
        assert_text_fits(page.title_label)
        assert page.empty_state.isVisibleTo(page)
        assert page.empty_title.text() == tr("暂无任务")
        assert not page.table.isVisibleTo(page)
        assert not page.clear_filters_button.isVisibleTo(page)
        center = page.empty_state.rect().center().x()
        icon_center = page.empty_icon.mapTo(page.empty_state, page.empty_icon.rect().center()).x()
        assert abs(center - icon_center) <= 1
        assert page._scroll.horizontalScrollBar().maximum() == 0
        _assert_wrapped_text_fits(page.empty_title)
        _assert_wrapped_text_fits(page.empty_label)
        assert_scroll_target_reachable(page._scroll, page.empty_label)
        initial_title = page.title_label.mapTo(page, QPoint())
        page._scroll.verticalScrollBar().setValue(page._scroll.verticalScrollBar().maximum())
        assert page.title_label.mapTo(page, QPoint()) == initial_title
    finally:
        page.shutdown()
        page.close()
        reference.close()


def test_no_matches_can_clear_all_filters_without_changing_tasks(qt_application):
    manager = OperationManager()
    operation = manager.begin("install")
    manager.mark_running(operation.operation_id)
    stop = Mock()
    page = TaskCenterPage(manager, stop_hook=stop)
    page.present_action_result(ActionResult(
        "failed-request", ActionSpec("shell_command", "system.shell", "执行 Shell", "text"),
        (), 100, state="failed",
    ))
    page.resize(900, 650)
    page.show()
    try:
        keys = set(page.table.rows)
        assert len(keys) == 2
        assert page.empty_state.isHidden()
        page.search_edit.setText("no-such-task")
        page.kind_combo.setCurrentIndex(page.kind_combo.findData("file"))
        page.state_combo.setCurrentIndex(page.state_combo.findData("succeeded"))
        qt_application.processEvents()
        assert page.empty_title.text() == tr("没有匹配的任务")
        assert page.empty_state.isVisibleTo(page)
        assert page.table.isHidden()
        assert page.clear_filters_button.isVisibleTo(page)
        QTest.mouseClick(page.clear_filters_button, Qt.MouseButton.LeftButton)
        assert page.search_edit.text() == ""
        assert page.kind_combo.currentData() == page.state_combo.currentData() == ""
        assert set(page.table.rows) == keys
        assert page.table.isVisibleTo(page)
        assert page.empty_state.isHidden()
        assert not manager.get(operation.operation_id).cancel_requested
        stop.assert_not_called()
    finally:
        page.shutdown()
        page.close()


@pytest.mark.parametrize("language,title,description,clear", [
    ("zh_CN", "暂无任务", "执行操作或完成测试后，任务进度与结果会显示在这里。", "清除筛选"),
    ("zh_HK", "暫無任務", "執行操作或完成測試後，任務進度與結果會顯示在這裡。", "清除篩選"),
    (
        "en_US", "No tasks yet",
        "Run an action or finish a test to see its progress and results here.", "Clear filters",
    ),
])
def test_empty_state_uses_bundled_translations(
    qt_application, monkeypatch, language, title, description, clear,
):
    settings = {"ui_font_size": 22, "font_family": "Arial", "log_font_size": 11}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()
    translators = install_translators(qt_application, language)
    page = TaskCenterPage()
    page.resize(360, 400)
    page.show()
    try:
        wait_for_stable_geometry(qt_application, (page, page.empty_state, page.empty_label))
        assert page.empty_title.text() == title
        assert page.empty_label.text() == description
        assert page.clear_filters_button.text() == clear
        _assert_wrapped_text_fits(page.empty_title)
        _assert_wrapped_text_fits(page.empty_label)
        assert_scroll_target_reachable(page._scroll, page.empty_label)
        page.present_action_result(ActionResult(
            "translated-task", ActionSpec("shell_command", "system.shell", "执行 Shell", "text"),
            (), 100, state="failed",
        ))
        page.search_edit.setText("no-match")
        for font_size in (22, 12, 22):
            settings["ui_font_size"] = font_size
            BaseStyles.reload_from_settings()
            wait_for_stable_geometry(qt_application, (page.empty_content, page.empty_title))
            assert page.empty_title.text() == tr("没有匹配的任务")
            _assert_wrapped_text_fits(page.empty_title)
            _assert_wrapped_text_fits(page.empty_label)
            assert_text_fits(page.clear_filters_button)
            assert_scroll_target_reachable(page._scroll, page.clear_filters_button)
    finally:
        page.shutdown()
        page.close()
        for translator in translators:
            qt_application.removeTranslator(translator)
