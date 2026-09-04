"""验证主要面板、内嵌功能页与瞬态对话框按钮的 tooltip 契约。"""

import re

from PySide6.QtWidgets import QPushButton, QTabBar, QToolButton
from qfluentwidgets import ComboBox
from qfluentwidgets.components.navigation.segmented_widget import SegmentedItem
from qfluentwidgets.components.widgets.line_edit import LineEditButton
from qfluentwidgets.components.widgets.scroll_bar import ArrowButton
from qfluentwidgets.components.widgets.tab_view import TabItem, TabToolButton

from gui.dialogs.file_explorer_image import FileExplorerImagePreview
from gui.features import AboutPanel
from gui.features.app_manager import AppDetailsPage, AppManagerPage
from gui.features.file_explorer import FileExplorerPage
from gui.features.logcat import LiveLogcatPage
from gui.features.media import ScreenshotPage
from gui.features.performance import PerformancePage
from gui.panels.side_panel import SidePanel
from tests.test_main_window_layout import build_main_frame


def _normalized(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.casefold(), flags=re.UNICODE).strip()


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
        roots = [
            panel.device_widget,
            *(panel._tab_scroll_areas[index].widget() for index in range(3)),
        ]
        for root in roots:
            _assert_buttons_use_function_descriptions(root)
    finally:
        panel.shutdown()
        panel.close()


def test_home_action_cards_expose_function_descriptions(qt_application):
    frame = build_main_frame()
    try:
        assert not hasattr(frame, "_toolbar")
        cards = frame._home_page.tool_cards.values()
        assert cards
        assert all(card.accessibleName().strip() for card in cards)
        assert all(card.accessibleDescription().strip() for card in cards)
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


def test_primary_feature_buttons_use_function_descriptions(monkeypatch, qt_application):
    monkeypatch.setattr(AppManagerPage, "_load_apps", lambda _self: None)
    monkeypatch.setattr(AppDetailsPage, "_load_data", lambda _self: None)
    monkeypatch.setattr(FileExplorerPage, "_refresh", lambda _self: None)
    widgets = (
        AboutPanel(),
        AppDetailsPage(None, device_ip="", package_name="com.example.app"),
        AppManagerPage(device_ip=""),
        FileExplorerPage(device_ip=""),
        FileExplorerImagePreview(),
        LiveLogcatPage(device_ip=""),
        PerformancePage(device_ip=""),
        ScreenshotPage([]),
    )
    try:
        for widget in widgets:
            buttons = widget.findChildren(QPushButton)
            if buttons:
                _assert_buttons_use_function_descriptions(widget)
    finally:
        for widget in widgets:
            shutdown = getattr(widget, "shutdown", None)
            if callable(shutdown):
                shutdown()
            widget.close()
