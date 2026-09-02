"""验证主要面板与二级对话框按钮的功能描述 tooltip 契约。"""

import re

from PySide6.QtWidgets import QPushButton, QTabBar, QToolButton
from qfluentwidgets import ComboBox
from qfluentwidgets.components.navigation.segmented_widget import SegmentedItem
from qfluentwidgets.components.widgets.line_edit import LineEditButton
from qfluentwidgets.components.widgets.scroll_bar import ArrowButton
from qfluentwidgets.components.widgets.tab_view import TabItem, TabToolButton

from gui.dialogs.about_dialog import AboutDialog
from gui.dialogs.app_manager import AppDetailsDialog, AppManagerDialog
from gui.dialogs.file_explorer import FileExplorerDialog, _ImageViewerDialog
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.dialogs.performance_launcher import PerformanceLauncherDialog
from gui.dialogs.screenshot_viewer import ScreenshotViewer
from gui.dialogs.settings_dialog import SettingsDialog
from gui.panels.side_panel import SidePanel
from tests.test_main_window_layout import build_main_frame


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _button_label(button: QPushButton | QToolButton) -> str:
    action = button.defaultAction() if isinstance(button, QToolButton) else None
    return action.text() if action is not None else button.text()


def _is_value_selector(button: QPushButton | QToolButton) -> bool:
    """值选择/内部子控件（下拉框、分段项、输入框清空按钮、滚动条箭头、页签项
    与页签工具按钮）不是动作按钮，无需功能描述 tooltip。"""

    return isinstance(
        button, (ComboBox, SegmentedItem, LineEditButton, ArrowButton, TabItem, TabToolButton)
    )


def _assert_buttons_use_function_descriptions(root) -> None:
    buttons = [
        button
        for button in [*root.findChildren(QPushButton), *root.findChildren(QToolButton)]
        if not _is_value_selector(button)
    ]
    assert buttons
    failures = []
    for button in buttons:
        if isinstance(button.parent(), QTabBar):
            continue
        label = _button_label(button).strip()
        tooltip = button.toolTip().strip()
        if not tooltip:
            failures.append(f"{label or button.objectName() or type(button).__name__}: missing")
        elif label and _normalized(tooltip) == _normalized(label):
            failures.append(f"{label}: repeats label")
    assert not failures, failures


def test_all_main_panel_buttons_use_short_function_descriptions(qt_application):
    panel = SidePanel()
    try:
        for index in range(3):
            panel._ensure_tab_loaded(index)
        _assert_buttons_use_function_descriptions(panel)
    finally:
        panel.shutdown()
        panel.close()


def test_toolbar_buttons_use_function_descriptions(qt_application):
    frame = build_main_frame()
    try:
        _assert_buttons_use_function_descriptions(frame._toolbar)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_primary_dialog_buttons_use_function_descriptions(monkeypatch, qt_application):
    monkeypatch.setattr(AppManagerDialog, "_load_apps", lambda _self: None)
    monkeypatch.setattr(AppDetailsDialog, "_load_data", lambda _self: None)
    monkeypatch.setattr(FileExplorerDialog, "_refresh", lambda _self: None)
    monkeypatch.setattr(
        SettingsDialog,
        "_available_ui_font_families",
        classmethod(lambda _cls, _configured="": ["System Default"]),
    )
    dialogs = (
        AboutDialog(),
        AppDetailsDialog(None, device_ip="", package_name="com.example.app"),
        AppManagerDialog(device_ip=""),
        FileExplorerDialog(device_ip=""),
        _ImageViewerDialog(),
        LiveLogcatDialog(device_ip=""),
        PerformanceLauncherDialog(device_ip=""),
        ScreenshotViewer([]),
        SettingsDialog(),
    )
    try:
        for dialog in dialogs:
            _assert_buttons_use_function_descriptions(dialog)
    finally:
        for dialog in dialogs:
            shutdown = getattr(dialog, "shutdown", None)
            if callable(shutdown):
                shutdown()
            dialog.close()
