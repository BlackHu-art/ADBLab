"""验证主面板使用独立的界面和日志字体角色。"""

from unittest.mock import Mock

from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QScrollArea, QWidget
from qfluentwidgets import HeaderCardWidget, ListWidget

from gui.panels.device_manager import DeviceManager
from gui.panels.log_panel import LogPanel
from gui.panels.side_panel import SidePanel
from gui.styles import BaseStyles, FontRole
from gui.widgets.responsive_controller import ReflowReason
from tests.ui_geometry_helpers import wait_until


def _effective_size(font: QFont) -> int:
    return font.pointSize() if font.pointSize() > 0 else font.pixelSize()


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

        assert _effective_size(panel._font_sm) == 18
        assert _effective_size(panel._apps_tab.btn_screenshot.font()) == 18
        assert _effective_size(panel._apps_tab.email_text_sender.font()) == 18
        assert _effective_size(panel._apps_tab.record_duration.font()) == 18
        assert _effective_size(panel._apps_tab.monkey_chk_crashes.font()) == 18
        assert _effective_size(system_panel.btn_shell_run.font()) == 18
        assert _effective_size(remote_panel.btn_start.font()) == 18
        assert _effective_size(panel._devices_tab.btn_refresh.font()) == 18
        assert _effective_size(panel._devices_tab.ip_entry.font()) == 14
        assert _effective_size(panel._devices_tab.listbox_devices.font()) == 14

        roots = (
            panel._device_widget,
            *(panel._tab_scroll_areas[index].widget() for index in range(3)),
        )
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
        assert isinstance(panel._devices_tab.listbox_devices, ListWidget)
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


def test_device_manager_font_refreshes_direct_reference_controls(monkeypatch):
    mono_font = QFont("Consolas", 13)
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role: mono_font),
    )
    manager = Mock()
    manager.listbox_devices.count.return_value = 0

    DeviceManager.apply_fonts(manager)

    manager.listbox_devices.setFont.assert_called_once_with(mono_font)
    manager.ip_entry.setFont.assert_called_once_with(mono_font)


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

            groups = list(device_widget.findChildren(HeaderCardWidget))
            for index in range(3):
                tab_widget = panel._tab_scroll_areas[index].widget()
                groups.extend(tab_widget.findChildren(HeaderCardWidget))

            assert groups
            measured_titles = set()
            for group in groups:
                assert group.viewLayout.contentsMargins().top() >= 4
                assert group.headerLabel.height() >= group.headerLabel.fontMetrics().height()
                measured_titles.add(group.title)

            assert "设备与连接" in measured_titles
            # “文本与屏幕”已收敛为 Card，改为验证其标题标签高度随字号缩放。
            ts_card = next(
                card
                for card in panel._apps_tab._apps_section_groups
                if card.title == "文本与屏幕"
            )
            first_offsets[font_size] = _effective_size(ts_card.headerLabel.font())
            device_control_heights[font_size] = panel._devices_tab.btn_refresh.minimumHeight()

        assert first_offsets[22] > first_offsets[12]
        assert first_offsets[8] <= first_offsets[12]
        assert device_control_heights[22] > device_control_heights[12]
        assert device_control_heights[8] <= device_control_heights[12]
    finally:
        device_widget.close()
        panel.close()
