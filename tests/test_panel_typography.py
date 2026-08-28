"""验证主面板使用独立的界面和日志字体角色。"""

from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QGroupBox, QScrollArea, QStyle, QStyleOptionGroupBox, QWidget

from gui.panels.device_manager import DeviceManager
from gui.panels.log_panel import LogPanel
from gui.panels.side_panel import SidePanel
from gui.styles import BaseStyles, FontRole
from gui.widgets.responsive_controller import ReflowReason
from tests.ui_geometry_helpers import wait_until


def _effective_size(font: QFont) -> int:
    return font.pointSize() if font.pointSize() > 0 else font.pixelSize()


def _group_title_gap(group: QGroupBox) -> tuple[int, int]:
    option = QStyleOptionGroupBox()
    group.initStyleOption(option)
    title_rect = group.style().subControlRect(
        QStyle.ComplexControl.CC_GroupBox,
        option,
        QStyle.SubControl.SC_GroupBoxLabel,
        group,
    )
    direct_children = [
        child
        for child in group.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
        if not child.isHidden()
    ]
    assert direct_children
    first_content_top = min(child.geometry().top() for child in direct_children)
    return first_content_top - title_rect.bottom() - 1, first_content_top


def test_side_panel_refreshes_loaded_and_detached_device_widgets(monkeypatch, qt_application):
    sizes = {
        FontRole.UI: 18,
        FontRole.UI_SMALL: 16,
        FontRole.MONO: 14,
        FontRole.LOG: 12,
        FontRole.TITLE: 22,
    }

    def font_for_role(_cls, role, size=None):
        role = FontRole(role)
        return QFont("Arial", size if size is not None else sizes[role])

    panel = SidePanel()
    system_panel = panel._ensure_tab_loaded(1)
    remote_panel = panel._ensure_tab_loaded(2)
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(font_for_role))
    try:
        panel._on_fonts_changed(None)

        assert _effective_size(panel.tabs.font()) == 18
        assert _effective_size(panel._font_sm) == 18
        assert _effective_size(panel._apps_tab.btn_screenshot.font()) == 18
        assert _effective_size(panel._apps_tab.email_text_sender.font()) == 18
        assert _effective_size(panel._apps_tab.record_duration.font()) == 18
        assert _effective_size(panel._apps_tab.monkey_chk_crashes.font()) == 18
        assert _effective_size(system_panel.btn_shell_run.font()) == 18
        assert _effective_size(remote_panel.btn_start.font()) == 18
        assert _effective_size(panel._devices_tab.btn_refresh.font()) == 18
        assert _effective_size(panel._devices_tab.ip_entry.font()) == 14
        assert _effective_size(panel._devices_tab.ip_entry.lineEdit().font()) == 14
        assert _effective_size(panel._devices_tab.listbox_devices.font()) == 14
        assert _effective_size(panel._devices_tab.ip_entry.view().font()) == 14
        assert _effective_size(panel._devices_tab.ip_entry.view().horizontalHeader().font()) == 14

        roots = (panel, panel._device_widget)
        ui_widgets = []
        small_widgets = []
        for root in roots:
            for widget in root.findChildren(QWidget):
                role = widget.property("fontRole")
                if role == FontRole.UI.value:
                    ui_widgets.append(widget)
                elif role == FontRole.UI_SMALL.value:
                    small_widgets.append(widget)
        assert ui_widgets
        assert all(_effective_size(widget.font()) == 18 for widget in ui_widgets)
        assert small_widgets == []
    finally:
        panel.close()


def test_detached_devices_theme_and_font_bursts_each_settle_once(
    monkeypatch,
    qt_application,
):
    """脱离 SidePanel 树的 Devices 也刷新样式，且每批刷新仅稳定一代。"""

    panel = SidePanel()
    device_widget = panel.device_widget
    device_widget.resize(420, 360)
    device_widget.show()
    wait_until(
        qt_application,
        lambda: (
            panel._responsive_coordinator.diagnostics.stable
            and panel._last_settled_generation
            == panel._responsive_coordinator.diagnostics.generation
        ),
    )
    try:
        marker = "QListWidget#deviceList { background: rgb(1, 2, 3); }"
        monkeypatch.setattr(
            BaseStyles,
            "DEVICE_LIST_STYLE",
            classmethod(lambda _cls: marker),
        )
        before = panel._responsive_coordinator.diagnostics.generation
        theme_settled = QSignalSpy(panel.responsive_layout_settled)
        for _ in range(3):
            panel._on_theme_changed(None)
        wait_until(
            qt_application,
            lambda: (
                panel._responsive_coordinator.diagnostics.stable
                and panel._last_settled_generation
                == panel._responsive_coordinator.diagnostics.generation
                and panel._last_settled_generation > before
            ),
        )
        assert marker in panel._devices_tab.listbox_devices.styleSheet()
        # 响应式布局有意为动作区引入 _ShrinkableActionScroll（QScrollArea 子类），
        # 用于承接横向溢出的滚动；主题/字体 burst 不应产生其他滚动容器。
        # 因此这里只断言不存在除该预期动作滚动容器之外的 QScrollArea。
        expected_scroll = panel._devices_tab._device_action_scroll
        assert [
            scroll
            for scroll in device_widget.findChildren(QScrollArea)
            if scroll is not expected_scroll
        ] == []
        assert panel._responsive_coordinator.diagnostics.generation == before + 1
        assert theme_settled.count() == 1
        assert ReflowReason.THEME in panel._responsive_coordinator.diagnostics.reasons

        monkeypatch.setattr(
            BaseStyles,
            "font_for_role",
            classmethod(lambda _cls, _role, size=None: QFont("Arial", size or 18)),
        )
        before = panel._responsive_coordinator.diagnostics.generation
        font_settled = QSignalSpy(panel.responsive_layout_settled)
        for _ in range(3):
            panel._on_fonts_changed(None)
        wait_until(
            qt_application,
            lambda: (
                panel._responsive_coordinator.diagnostics.stable
                and panel._last_settled_generation
                == panel._responsive_coordinator.diagnostics.generation
                and panel._last_settled_generation > before
            ),
        )
        assert panel._responsive_coordinator.diagnostics.generation == before + 1
        assert font_settled.count() == 1
        assert ReflowReason.FONT in panel._responsive_coordinator.diagnostics.reasons
    finally:
        device_widget.close()
        panel.close()


def test_device_manager_font_refreshes_current_completer(monkeypatch):
    mono_font = QFont("Consolas", 13)
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role: mono_font),
    )
    header = Mock()
    view = Mock()
    view.horizontalHeader.return_value = header
    completer = object()
    manager = Mock()
    manager.listbox_devices.count.return_value = 0
    manager.ip_entry.view.return_value = view
    manager.ip_entry.completer.return_value = completer

    DeviceManager.apply_fonts(manager)

    manager.listbox_devices.setFont.assert_called_once_with(mono_font)
    view.setFont.assert_called_once_with(mono_font)
    header.setFont.assert_called_once_with(mono_font)
    manager.panel._apply_completer_style.assert_called_once_with(completer)


def test_log_panel_font_change_rerenders_for_hanging_indent(
    monkeypatch,
    qt_application,
):
    """字号变化会重绘：悬挂缩进按新字体度量计算（ADR-0005 日志优化）。"""

    monkeypatch.setattr(LogPanel, "_connect_services", lambda _self: None)
    panel = LogPanel()
    rerender = Mock()
    panel._rerender_all = rerender

    def font_for_role(_cls, role, size=None):
        del size
        assert FontRole(role) is FontRole.LOG
        return QFont("Consolas", 13)

    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(font_for_role))
    try:
        panel._on_log_font_changed(None)

        assert _effective_size(panel.text_output.font()) == 13
        rerender.assert_called_once()
    finally:
        panel.close()


def test_all_main_panel_group_titles_keep_clearance_across_font_sizes(
    monkeypatch,
    qt_application,
):
    current_size = {"value": 12}

    def font_for_role(_cls, role, size=None):
        del role
        return QFont("Arial", size if size is not None else current_size["value"])

    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(font_for_role))
    panel = SidePanel()
    panel._ensure_tab_loaded(1)
    panel._ensure_tab_loaded(2)
    device_widget = panel.device_widget
    panel.resize(640, 900)
    device_widget.resize(640, 520)
    panel.show()
    device_widget.show()
    qt_application.processEvents()
    first_offsets = {}
    device_control_heights = {}
    try:
        for font_size in (12, 22, 8):
            current_size["value"] = font_size
            panel._on_fonts_changed(None)
            qt_application.processEvents()

            groups = list(device_widget.findChildren(QGroupBox))
            for index in range(panel.tabs.count()):
                panel.tabs.setCurrentIndex(index)
                qt_application.processEvents()
                tab_widget = panel._tab_scroll_areas[index].widget()
                groups.extend(tab_widget.findChildren(QGroupBox))

            assert groups
            measured_titles = set()
            for group in groups:
                gap, first_content_top = _group_title_gap(group)
                assert gap >= 4, f"{group.title()} 标题与首行内容仅保留 {gap}px"
                title = group.title()
                measured_titles.add("Devices" if title.startswith("Devices · ") else title)
                if group.title() == "Text & Screen Capture":
                    first_offsets[font_size] = first_content_top

            assert {"Devices", "Text & Screen Capture"} <= measured_titles
            device_control_heights[font_size] = panel._devices_tab.btn_refresh.minimumHeight()

        assert first_offsets[22] > first_offsets[12]
        assert first_offsets[8] <= first_offsets[12]
        assert device_control_heights[22] > device_control_heights[12]
        assert device_control_heights[8] <= device_control_heights[12]
    finally:
        device_widget.close()
        panel.close()
