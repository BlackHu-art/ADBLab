"""真实应用页诊断结果不能扩大页面，完整正文仍可搜索、复制和导出。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QSize
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from adblab.application.action_results import ActionItem, ActionResult, ActionSpec
from core.settings_manager import AppSettings
from gui.styles import BaseStyles
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)
from tests.ui_geometry_helpers import wait_for_stable_geometry

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("font_size", [12, 22])
def test_diagnostic_result_keeps_apps_page_width_and_complete_output(
    qt_application, monkeypatch, font_size,
):
    settings = _MainFrameSettings()
    settings.values.update({"font_family": "Sans Serif", "ui_font_size": font_size})
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr("models.device_store.DeviceStore.get_full_devices_info", lambda *_: [])
    monkeypatch.setattr("models.device_store.DeviceStore.get_basic_devices_info", lambda *_: [])
    monkeypatch.setattr("gui.main_frame.MainFrame._start_scan_thread", lambda _self: None)
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    monkeypatch.setattr("core.exec.CommandRunner.run", Mock(side_effect=AssertionError("real ADB")))
    monkeypatch.setattr("gui.action_feedback.QFileDialog.getSaveFileName", lambda *_: ("", ""))
    BaseStyles.reload_from_settings()
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("synthetic-screen", QSize(720, 800))),
        settings=settings,
    )
    frame.show()
    frame._bind_window_screen()
    frame._on_nav_requested("apps")
    apps = frame.left_panel._apps_tab
    scroll = frame._workspace_feature_hosts["apps"].overview.body
    content = scroll.widget()
    view = apps.diagnostic_results
    full_output = "Total PSS: 12345 kB\n" + "long-unbroken-output" * 4000 + "\nsearch-tail-marker"
    result = ActionResult(
        "diagnostic", ActionSpec("diagnostic", "apps.diagnostics", "内存", "text"),
        ("mock-device",), 1, "succeeded",
        target_names=("Synthetic model with a long display name " * 15,),
        items=(ActionItem("job", "mock-device", "设备 1", "succeeded", full_output),),
        finished_at=2,
    )
    exported = QSignalSpy(view.export_requested)
    try:
        wait_for_stable_geometry(qt_application, (frame, scroll, content))
        assert scroll.horizontalScrollBar().maximum() == 0
        view.present(result)
        wait_for_stable_geometry(qt_application, (frame, scroll, content, view))
        qt_application.processEvents()
        assert scroll.horizontalScrollBar().maximum() == 0
        assert content.width() <= scroll.viewport().width()
        assert scroll.horizontalScrollBar().value() == 0
        assert view.mapTo(scroll.viewport(), QPoint()).x() >= 0
        assert "…" in view.targets.text()
        assert view.targets.toolTip() == view.targets.currentText()
        assert view.targets.currentData() == "job"
        assert view.output.toPlainText() == full_output[:64000]
        view.search.setText("search-tail-marker")
        view._find()
        assert view.output.textCursor().selectedText() == "search-tail-marker"
        view.copy_button.click()
        assert QApplication.clipboard().text() == full_output
        view.export_button.click()
        assert exported.at(0) == ["diagnostic", full_output]
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
