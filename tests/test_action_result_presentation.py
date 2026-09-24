"""操作结果的字号调整保留阅读状态，窄窗口仍可使用全部操作。"""

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QSignalSpy, QTest

from adblab.application.action_results import (
    ActionItem,
    ActionResult,
    ActionResults,
    ActionSpec,
    capture_action_job,
)
from core.settings_manager import AppSettings
from gui.i18n import install_translators
from gui.pages.tasks_page import TaskCenterPage
from gui.styles import BaseStyles
from gui.widgets.report_artifacts import ReportArtifactsView
from tests.ui_geometry_helpers import (
    assert_scroll_target_reachable,
    wait_for_stable_geometry,
)


@pytest.mark.parametrize("language", ["zh_CN", "en_US"])
@pytest.mark.parametrize("width", [452, 540])
def test_result_font_changes_preserve_reading_and_keep_actions_reachable(
    qt_application, monkeypatch, language, width,
):
    settings = {"font_family": "Sans Serif", "ui_font_size": 12, "log_font_size": 11}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()
    translators = install_translators(qt_application, language)
    page = TaskCenterPage(poll_interval_ms=0)
    page.resize(width, 500)
    view = page.action_results
    results = ActionResults(page.present_action_result)
    job = results.run(
        ActionSpec("probe", "system.shell", "查询", "text"), (),
        lambda: capture_action_job("query_async"),
    )
    text = "first line\nreading-marker\nlast line"
    results.complete(job, {"success": True, "output": text})
    view.detail_toggle.setChecked(True)
    view.search.setText("reading-marker")
    view._find()
    page.show()
    controls = (
        view.history, view.targets, view.detail_toggle, view.search,
        view.copy_button, view.export_button, view.artifacts,
        view.open_button, view.folder_button,
    )
    exported = QSignalSpy(view.export_requested)
    try:
        for size in (12, 22, 12):
            settings["ui_font_size"] = size
            BaseStyles.reload_from_settings()
            wait_for_stable_geometry(qt_application, (page, view, view.export_button))
            assert view.summary.font().pointSize() == size
            assert view.message_label.font().pointSize() == size - 1
            for control in controls:
                assert control.font().pointSize() == size
                if control.isVisibleTo(page):
                    assert control.height() >= control.fontMetrics().height()
            assert page._scroll.horizontalScrollBar().maximum() == 0
            assert page._scroll.widget().width() <= page._scroll.viewport().width()
            assert view._selected == job.request_id
            assert view.output.toPlainText() == text
            assert view.output.textCursor().selectedText() == "reading-marker"
            assert view.output.font().pointSize() == 11
            for control in (view.copy_button, view.export_button):
                assert_scroll_target_reachable(page._scroll, control)
                assert control.width() >= control.sizeHint().width()
        QTest.mouseClick(view.export_button, Qt.MouseButton.LeftButton)
        assert exported.count() == 1
        assert exported.at(0) == [job.request_id, text]
    finally:
        results.close()
        page.shutdown()
        page.close()
        for translator in translators:
            qt_application.removeTranslator(translator)


@pytest.mark.parametrize("language", ["zh_CN", "en_US"])
@pytest.mark.parametrize("width", [360, 540])
def test_generated_report_font_changes_preserve_selected_artifact(
    qt_application, monkeypatch, language, width,
):
    settings = {"font_family": "Sans Serif", "ui_font_size": 12, "log_font_size": 11}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()
    translators = install_translators(qt_application, language)
    view = ReportArtifactsView()
    view.present(ActionResult(
        "report", ActionSpec("report", "apps.reports", "报告", "text"), (), 1, "succeeded",
        items=(ActionItem(
            "report-job", "", "设备 1", "succeeded", "完成",
            artifacts=("/tmp/first-report.txt", "/tmp/second-report.txt"),
        ),),
        finished_at=2,
    ))
    view.resize(width, 400)
    view.show()
    view.files.setCurrentIndex(1)
    selected = view.files.currentData()
    opened = QSignalSpy(view.artifact_requested)
    try:
        for size in (12, 22, 12):
            settings["ui_font_size"] = size
            BaseStyles.reload_from_settings()
            wait_for_stable_geometry(qt_application, (view, view.files, view.open_button))
            for control in (view.heading, view.files, view.open_button, view.folder_button):
                assert control.font().pointSize() == size
                assert control.height() >= control.fontMetrics().height()
            assert view.files.currentData() == selected
            assert view.width() <= width
            for button in (view.open_button, view.folder_button):
                assert view.rect().contains(button.geometry())
                assert button.width() >= button.sizeHint().width()
        view.open_button.click()
        assert opened.count() == 1
        assert opened.at(0) == [selected, False]
    finally:
        view.close()
    for translator in translators:
        qt_application.removeTranslator(translator)


def test_artifact_actions_fit_narrow_main_window_after_font_changes(
    qt_application, monkeypatch,
):
    """真实侧栏占宽后，产物操作须换行且始终指向原先选中的结果文件。"""
    from unittest.mock import Mock

    from tests.test_main_window_layout import (
        _FakeScreen,
        _FakeScreenAdapter,
        _MainFrameSettings,
        build_main_frame,
    )

    settings = _MainFrameSettings()
    settings.values.update({"font_family": "Sans Serif", "ui_font_size": 12})
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr("models.device_store.DeviceStore.get_full_devices_info", lambda *_: [])
    monkeypatch.setattr("models.device_store.DeviceStore.get_basic_devices_info", lambda *_: [])
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    monkeypatch.setattr("core.exec.CommandRunner.run", Mock(side_effect=AssertionError("real ADB")))
    BaseStyles.reload_from_settings()
    translators = install_translators(qt_application, "en_US")
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("test-screen", QSize(452, 650))),
        settings=settings,
    )
    page = frame._task_page
    page.present_action_result(ActionResult(
        "artifact", ActionSpec("artifact", "system.shell", "查询", "text"), (), 1, "succeeded",
        items=(ActionItem(
            "artifact-job", "", "设备 1", "succeeded", "完成",
            artifacts=("/tmp/narrow-result.txt",),
        ),),
        finished_at=2,
    ))
    page.history_views.set_current("operations")
    view = page.action_results
    view.detail_toggle.setChecked(True)
    opened = QSignalSpy(view.artifact_requested)
    try:
        frame.show()
        frame._bind_window_screen()
        frame._on_nav_requested("tasks")
        for size in (12, 22, 12):
            settings.values["ui_font_size"] = size
            BaseStyles.reload_from_settings()
            wait_for_stable_geometry(qt_application, (frame, page, view, view.folder_button))
            assert frame.width() == 452
            assert page._scroll.horizontalScrollBar().maximum() == 0
            assert page._scroll.widget().width() <= page._scroll.viewport().width()
            assert view.artifacts.currentData() == "/tmp/narrow-result.txt"
            for button in (view.open_button, view.folder_button):
                assert_scroll_target_reachable(page._scroll, button)
                assert button.width() >= button.sizeHint().width()
                assert button.height() >= button.fontMetrics().height()
        for button in (view.open_button, view.folder_button):
            assert_scroll_target_reachable(page._scroll, button)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert [opened.at(index) for index in range(opened.count())] == [
            ["/tmp/narrow-result.txt", False], ["/tmp/narrow-result.txt", True],
        ]
    finally:
        page.shutdown()
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        for translator in translators:
            qt_application.removeTranslator(translator)
