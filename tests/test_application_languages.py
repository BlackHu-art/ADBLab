"""沿全部主导航验收实际业务页语言，使用合成设备隔离 I/O。"""

from __future__ import annotations

import re
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from core.settings_manager import DEFAULTS, AppSettings
from gui.dialogs.app_manager import AppManagerPage
from gui.dialogs.file_explorer import FileExplorerPage
from gui.i18n import install_translators
from gui.main_frame import MainFrame
from models.device_store import DeviceStore
from tests.test_main_window_layout import _MainFrameSettings, build_main_frame
from tests.ui_geometry_helpers import wait_for_stable_geometry
from tests.ui_text_helpers import visible_ui_texts

ROUTES = (
    "homePage", "devicesPage", "filesPage", "remotePage", "appManagerPage", "appsPage",
    "screenshotsPage", "systemPage", "logcatPage", "performancePage", "tasksPage", "settingsPage",
)


@pytest.mark.parametrize("with_device", [False, True])
def test_all_navigation_pages_use_english_for_visible_application_text(
    qt_application, monkeypatch, with_device,
):
    settings = _MainFrameSettings()
    settings.values.update(DEFAULTS, language="en_US", continuous_device_scan=False)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr(MainFrame, "_start_scan_thread", lambda _self: None)
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda _devices: [])
    monkeypatch.setattr(AppManagerPage, "_load_apps", Mock(return_value=False))
    monkeypatch.setattr(FileExplorerPage, "_refresh", Mock())
    translators = install_translators(qt_application, "en_US")
    window = None
    failures = []
    try:
        window = build_main_frame(settings=settings)
        window.show()
        if with_device:
            window._on_devices_updated(["demo-device"])
            window._global_device_bar.selection_requested.emit(["demo-device"])
        for route in ROUTES:
            window.navigationInterface.widget(route).click()
            wait_for_stable_geometry(qt_application, (window, window.stackedWidget.currentWidget()))
            for name, field, text in visible_ui_texts(window):
                # 语言选择器必须保留每种语言的自称，便于误选后恢复。
                if text in {"简体中文", "繁體中文"}:
                    continue
                if re.search(r"[\u3400-\u9fff]", text):
                    failures.append((route, name, field, text))
        assert not failures, "\n".join(map(str, failures[:40])) + f"\nTotal: {len(failures)}"
    finally:
        if window is not None:
            for host in window._workspace_feature_hosts.values():
                host.shutdown()
            window._unbind_window_screen()
            window._close_ready = True
            window.close()
            window.deleteLater()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
