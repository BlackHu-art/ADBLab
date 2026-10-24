"""报告文件入口在窄面板、省略文本和完整附件路径之间保持一致。"""

import pytest
from PySide6.QtTest import QSignalSpy

from core.settings_manager import AppSettings
from gui.styles import BaseStyles
from gui.widgets.report_artifacts import ReportArtifactsView
from services.tasks.action_results import ActionItem, ActionResult, ActionSpec
from tests.test_responsive_panels import (
    _close_feature_panel,
    _resize_feature_viewport,
    _show_feature_panel,
)
from tests.ui_geometry_helpers import wait_for_stable_geometry

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("width", [360, 540])
def test_long_report_names_fit_panel_after_resize_and_font_change(
    qt_application, monkeypatch, width,
):
    settings = {"font_family": "Sans Serif", "ui_font_size": 12, "log_font_size": 11}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()
    device = "mock-sensitive-device"
    paths = (
        f"/synthetic-home/log_{device}_{'old_report_name_' * 12}.txt",
        f"/synthetic-home/log_{device}_{'another_long_report_' * 12}.txt",
    )
    view = ReportArtifactsView()
    view.resize(width, 250)
    view.present(ActionResult(
        "report", ActionSpec("report", "apps.reports", "提取日志", "text"),
        (device,), 1, "succeeded",
        items=(ActionItem("job", device, "设备 1", "succeeded", "完成", artifacts=paths),),
        finished_at=2,
    ))
    view.show()
    opened = QSignalSpy(view.artifact_requested)
    try:
        for size in (12, 22, 12):
            settings["ui_font_size"] = size
            BaseStyles.reload_from_settings()
            for index, panel_width in ((0, width), (1, width + 120), (0, width)):
                view.resize(panel_width, 250)
                view.files.setCurrentIndex(index)
                wait_for_stable_geometry(qt_application, (view, view.files))
                display = view.files.text()
                full_label = view.files.currentText()
                assert view.width() == panel_width
                assert view.rect().contains(view.files.geometry())
                assert view.files.fontMetrics().horizontalAdvance(display) < view.files.width()
                assert "…" in display and display != full_label
                assert view.files.toolTip() == full_label
                assert view.files.accessibleDescription() == full_label
                assert device not in full_label and "/synthetic-home" not in full_label
                assert view.files.currentData() == paths[1 - index]
                view.open_button.click()
                view.folder_button.click()
                assert opened.at(opened.count() - 2) == [paths[1 - index], False]
                assert opened.at(opened.count() - 1) == [paths[1 - index], True]
    finally:
        view.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_long_report_selector_fits_actual_apps_page(qt_application, monkeypatch, theme):
    settings = {"font_family": "Sans Serif", "ui_font_size": 22, "log_font_size": 11}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    owner, apps, scroll, content = _show_feature_panel(
        "apps", 452, 22, qt_application, monkeypatch, patch_font_factory=False,
    )
    view = apps.report_artifacts
    path = "/synthetic-home/" + "historical-long-filename-" * 12 + ".txt"
    view.present(ActionResult(
        "report", ActionSpec("report", "apps.reports", "提取日志", "text"), (),
        1, "succeeded",
        items=(ActionItem("job", "", "设备 1", "succeeded", "完成", artifacts=(path,)),),
        finished_at=2,
    ))
    try:
        for width in (452, 720, 452):
            _resize_feature_viewport(qt_application, owner, apps, scroll, width)
            scroll.ensureWidgetVisible(view.files)
            qt_application.processEvents()
            assert view.files.isVisibleTo(content)
            assert scroll.horizontalScrollBar().maximum() == 0
            assert content.width() <= scroll.viewport().width()
            assert view.rect().contains(view.files.geometry())
            assert "…" in view.files.text()
            assert view.files.font().pointSize() == 22
            text_width = view.files.fontMetrics().horizontalAdvance(view.files.text())
            assert text_width < view.files.width()
            assert view.files.toolTip() == view.files.currentText()
            assert view.files.currentData() == path
    finally:
        _close_feature_panel(owner)
