"""验证 Apps、System 和 Remote 面板在断点切换时仅重排现有控件。"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QDoubleValidator, QFont, QIntValidator, QRegularExpressionValidator
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOptionGroupBox,
    QStyleOptionViewItem,
    QWidget,
)

from adblab.application.supervision import StopDisposition, TaskSupervisor
from gui.panels.app_panel import AppPanel
from gui.panels.remote_panel import RemotePanel
from gui.panels.side_panel import SidePanel
from gui.styles import BaseStyles
from gui.styles.typography import FontConfig, typography_manager
from gui.widgets.responsive_controller import (
    ReflowReason,
    ResponsiveCoordinator,
    ResponsiveGridBinding,
)
from gui.widgets.responsive_layout import (
    LayoutContext,
    WidthPolicy,
    adaptive_layout_spacing,
    row_major_mode,
)
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_non_overlapping,
    assert_positive_geometry,
    assert_scroll_target_reachable,
    wait_for_stable_geometry,
    wait_until,
)


@pytest.fixture(autouse=True)
def _fast_responsive_debounce(monkeypatch):
    """逐像素几何扫描无需真实防抖等待，缩短到 1ms 以压缩套件耗时。"""

    monkeypatch.setattr(ResponsiveCoordinator, "RESIZE_DEBOUNCE_MS", 1)


def _side_panel() -> SimpleNamespace:
    """构造面板布局测试需要的最小 SidePanel 接口。"""

    return SimpleNamespace(
        _font_sm=QFont("Arial", 10),
        _font_base=QFont("Arial", 10),
        _font_mono=QFont("Courier New", 10),
        _font_tab=QFont("Arial", 10),
        _package_history=[],
        _apply_completer_style=lambda _completer: None,
        selected_devices=[],
        signals=SimpleNamespace(),
    )


def _set_scroll_viewport_width(
    qt_application,
    panel: SidePanel,
    scroll: QScrollArea,
    width: int,
) -> int:
    """仅调整真实顶层宽度，直到滚动 viewport 达到请求的逻辑宽度。"""

    requested = int(width)
    for _attempt in range(12):
        actual = scroll.viewport().contentsRect().width()
        if actual == requested:
            return actual
        panel.resize(max(panel.minimumWidth(), panel.width() + requested - actual), panel.height())
        qt_application.processEvents()
    actual = scroll.viewport().contentsRect().width()
    assert actual == requested, (requested, actual, panel.size(), scroll.size())
    return actual


def _show_feature_panel(
    panel_name: str,
    width: int,
    font_size: int,
    qt_application,
    monkeypatch,
    *,
    patch_font_factory: bool = True,
):
    """创建真实 SidePanel、懒加载页和滚动内容，返回实际 viewport 几何。"""

    def font_for_role(_cls, _role, size=None):
        return QFont("Arial", size if size is not None else font_size)

    if patch_font_factory:
        monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(font_for_role))
    tab_index = {"apps": 0, "system": 1, "remote": 2}[panel_name]
    settings = Mock()
    settings.get.side_effect = lambda _key, default=None: default
    settings.save_directory = "."
    adb = SimpleNamespace(path="adb")
    with (
        patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]),
        patch("core.settings_manager.AppSettings.instance", return_value=settings),
        patch("gui.panels.remote_panel.AppSettings.instance", return_value=settings),
        patch("gui.panels.remote_panel.ADBBridge", return_value=adb),
        patch("gui.panels.remote_panel.ScrcpyService", return_value=Mock()),
        patch("gui.panels.remote_panel.RemoteControlService", return_value=Mock()),
        patch("gui.panels.remote_panel.RemoteInputEngine", return_value=Mock()),
    ):
        panel = SidePanel()
        # 292px 验收属于受限工作区；生产路径会由 MainFrame 同步该状态。
        panel.set_restricted_width_mode(True)
        panel.resize(max(320, width + 32), 900)
        panel.show()
        panel.tabs.setCurrentIndex(tab_index)
        feature_panel = panel._ensure_tab_loaded(tab_index)
    scroll = panel._tab_scroll_areas[tab_index]
    content_widget = scroll.widget()
    wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
    _resize_feature_viewport(qt_application, panel, feature_panel, scroll, width)
    return panel, feature_panel, scroll, content_widget


def _resize_feature_viewport(
    qt_application,
    panel: SidePanel,
    feature_panel,
    scroll: QScrollArea,
    width: int,
) -> int:
    """只经宿主尺寸变化调整真实 viewport，并等待页面计划覆盖最终 Qt 几何。"""

    requested = int(width)
    for _attempt in range(4):
        _set_scroll_viewport_width(qt_application, panel, scroll, requested)
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        wait_for_stable_geometry(
            qt_application,
            (panel, scroll, scroll.viewport(), scroll.widget()),
        )
        actual = scroll.viewport().contentsRect().width()
        if actual == requested and feature_panel.responsive_geometry_is_applied():
            return actual
    actual = scroll.viewport().contentsRect().width()
    assert actual == requested, (requested, actual, panel.size(), scroll.size())
    assert feature_panel.responsive_geometry_is_applied()
    return actual


def _validator_signature(widget) -> tuple | None:
    """把字段 validator 的类型、身份和业务范围冻结为与布局无关的状态。"""

    target = widget.lineEdit() if isinstance(widget, QComboBox) and widget.isEditable() else widget
    validator = target.validator() if isinstance(target, QLineEdit) else None
    if validator is None:
        return None
    signature = [type(validator).__name__, id(validator)]
    if isinstance(validator, QIntValidator):
        signature.extend((validator.bottom(), validator.top()))
    elif isinstance(validator, QDoubleValidator):
        signature.extend(
            (
                validator.bottom(),
                validator.top(),
                validator.decimals(),
                validator.notation(),
            )
        )
    elif isinstance(validator, QRegularExpressionValidator):
        expression = validator.regularExpression()
        signature.extend((expression.pattern(), expression.patternOptions()))
    return tuple(signature)


def _binding_widget_state(feature_panel) -> tuple:
    """冻结所有 binding 直接控件的身份、业务状态和非几何属性。"""

    state = []
    for binding in feature_panel._responsive_rows:
        for widget in binding.widgets():
            value = None
            if isinstance(widget, QComboBox):
                editor = widget.lineEdit() if widget.isEditable() else None
                value = (
                    widget.currentIndex(),
                    widget.currentText(),
                    widget.currentData(),
                    widget.isEditable(),
                    tuple(
                        (widget.itemText(index), widget.itemData(index))
                        for index in range(widget.count())
                    ),
                    (
                        (
                            id(editor),
                            editor.isEnabled(),
                            editor.text(),
                            editor.placeholderText(),
                            editor.cursorPosition(),
                            editor.selectionStart(),
                            editor.selectedText(),
                            editor.isReadOnly(),
                            editor.maxLength(),
                            editor.inputMask(),
                        )
                        if editor is not None
                        else None
                    ),
                    _validator_signature(widget),
                )
            elif isinstance(widget, QLineEdit):
                value = (
                    widget.text(),
                    widget.placeholderText(),
                    widget.cursorPosition(),
                    widget.selectionStart(),
                    widget.selectedText(),
                    widget.isReadOnly(),
                    widget.maxLength(),
                    widget.inputMask(),
                    _validator_signature(widget),
                )
            elif isinstance(widget, QCheckBox):
                value = (widget.text(), widget.isChecked(), widget.checkState())
            elif isinstance(widget, QPushButton):
                value = (widget.text(), widget.isCheckable(), widget.isChecked())
            elif isinstance(widget, QLabel):
                value = (
                    widget.text(),
                    widget.styleSheet(),
                    widget.accessibleDescription(),
                )
            state.append(
                (
                    id(widget),
                    id(widget.parentWidget()),
                    type(widget).__name__,
                    widget.isEnabled(),
                    widget.toolTip(),
                    widget.accessibleName(),
                    value,
                )
            )
    return tuple(state)


def _assert_feature_binding_geometry(feature_panel, scroll, content) -> tuple:
    """核对当前 viewport 下所有响应行的几何，并返回真实溢出 binding。"""

    bindings = tuple(feature_panel._responsive_rows)
    overflowing = tuple(
        binding
        for binding in bindings
        if binding.applied_plan is not None and binding.applied_plan.overflow_required
    )
    for binding in bindings:
        plan = binding.applied_plan
        assert plan is not None
        widgets = binding.widgets()
        assert widgets
        for widget in widgets:
            assert_positive_geometry(widget, content)
            assert_contained(widget, content)
        assert_non_overlapping(widgets, content)

    horizontal = scroll.horizontalScrollBar()
    horizontal.setValue(horizontal.minimum())
    QApplication.processEvents()
    viewport_rect = scroll.viewport().rect()
    for binding in bindings:
        plan = binding.applied_plan
        if plan is None or plan.overflow_required:
            continue
        for widget in binding.widgets():
            rect = QRect(widget.mapTo(scroll.viewport(), QPoint(0, 0)), widget.size())
            assert viewport_rect.left() <= rect.left()
            assert rect.right() <= viewport_rect.right()

    for binding in overflowing:
        widgets = binding.widgets()
        assert_scroll_target_reachable(scroll, widgets[0])
        assert_scroll_target_reachable(scroll, widgets[-1])
    return overflowing


def _close_feature_panel(panel: SidePanel) -> None:
    """停止 Remote 资源并回收本测试创建的真实 SidePanel。"""

    remote = panel._scrcpy_tab
    if remote is not None:
        remote.shutdown()
    panel.device_widget.close()
    panel.device_widget.deleteLater()
    panel.close()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _resize_binding_until_mode(
    qt_application,
    panel: SidePanel,
    scroll: QScrollArea,
    feature_panel,
    binding: ResponsiveGridBinding,
    mode_name: str,
) -> int:
    """测试侧逐像素扫描真实 viewport，不调用生产布局决策 helper。"""

    for width in range(180, 901):
        _set_scroll_viewport_width(qt_application, panel, scroll, width)
        feature_panel.apply_responsive_width(scroll.viewport().contentsRect().width())
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        plan = binding.applied_plan
        if plan is not None and plan.mode.name == mode_name:
            return width
    raise AssertionError(f"responsive mode was not reachable: {mode_name}")


def _grid_position(layout, widget) -> tuple[int, int]:
    """读取控件在网格中的行列位置。"""

    index = layout.indexOf(widget)
    assert index >= 0
    row, column, _row_span, _column_span = layout.getItemPosition(index)
    return row, column


def _grid_item_position(layout, widget) -> tuple[int, int, int, int]:
    """读取控件在网格中的行、列及跨行列数。"""

    index = layout.indexOf(widget)
    assert index >= 0
    return layout.getItemPosition(index)


def _visible_device_layout_members(manager):
    """返回 Devices 视觉根内需要互不覆盖的显式布局成员。"""

    return tuple(
        widget
        for widget in (
            manager.ip_entry,
            manager.btn_connect_devices,
            manager.listbox_devices,
            manager._device_action_frame,
        )
        if widget.isVisibleTo(manager.device_widget)
    )


def _close_device_test_ui(panel):
    """按 popup、detached 根、无父级控制器和 SidePanel 的顺序清理测试对象。"""

    manager = panel._devices_tab
    controllers = tuple(
        controller
        for controller in (
            manager,
            panel._apps_tab,
            panel._advanced_tab,
            panel._scrcpy_tab,
        )
        if controller is not None
    )
    manager.ip_entry.hidePopup()
    view = manager.ip_entry.view()
    if view is not None:
        view.hide()
    completer = manager.ip_entry.completer()
    popup = completer.popup() if completer is not None else None
    if popup is not None:
        popup.hide()
    app_completer = getattr(panel._apps_tab, "completer", None)
    app_popup = app_completer.popup() if app_completer is not None else None
    if app_popup is not None:
        app_popup.hide()
    if app_completer is not None:
        app_completer.deleteLater()
    panel.device_widget.close()
    panel.device_widget.deleteLater()
    for controller in controllers:
        controller.close()
        controller.deleteLater()
    panel.close()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application = QApplication.instance()
    if application is not None:
        application.processEvents()


def _styled_device_row_height(listbox) -> int:
    """使用 Qt 样式系统计算带复选框设备项的一行完整高度。"""

    option = QStyleOptionViewItem()
    listbox.initViewItemOption(option)
    option.features |= (
        QStyleOptionViewItem.ViewItemFeature.HasDisplay
        | QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    )
    option.text = "device"
    option.checkState = Qt.CheckState.Unchecked
    indicator_height = listbox.style().pixelMetric(
        QStyle.PixelMetric.PM_IndicatorHeight,
        option,
        listbox,
    )
    content_height = max(listbox.fontMetrics().height(), indicator_height)
    return (
        listbox.style()
        .sizeFromContents(
            QStyle.ContentsType.CT_ItemViewItem,
            option,
            QSize(1, content_height),
            listbox,
        )
        .height()
    )


@pytest.mark.parametrize(
    ("available", "minimum", "font_height", "gaps", "expected"),
    (
        (100, 100, 10, 2, 2),
        (107, 100, 10, 2, 2),
        (108, 100, 10, 2, 4),
        (116, 100, 10, 2, 6),
        (113, 100, 28, 2, 2),
        (114, 100, 28, 2, 4),
        (128, 100, 28, 2, 6),
        (900, 100, 28, 0, 2),
    ),
)
def test_adaptive_layout_spacing_uses_font_aware_discrete_slack_bands(
    available,
    minimum,
    font_height,
    gaps,
    expected,
):
    """真实最小需求之外的逐缝余量只能映射到稳定的 2/4/6px 档位。"""

    assert adaptive_layout_spacing(available, minimum, font_height, gaps) == expected


def test_adaptive_layout_spacing_converges_at_boundaries_in_both_directions():
    """跨临界值正反拖动必须得到同一离散序列，不得因方向产生往返振荡。"""

    widths = tuple(range(100, 131))
    forward = tuple(adaptive_layout_spacing(width, 100, 28, 2) for width in widths)
    reverse = tuple(adaptive_layout_spacing(width, 100, 28, 2) for width in reversed(widths))
    assert forward == tuple(reversed(reverse))
    assert forward[13:15] == (2, 4)
    assert forward[27:29] == (4, 6)
    assert set(forward) == {2, 4, 6}


def test_grid_plan_fingerprint_includes_spacing(qt_application, monkeypatch):
    """同一响应行只有 spacing 改变时，计划指纹也必须随之改变。"""

    panel, app_panel, _scroll, _content = _show_feature_panel(
        "apps", 420, 12, qt_application, monkeypatch
    )
    try:
        plan = app_panel.package_action_binding.applied_plan
        assert plan is not None
        assert replace(plan, spacing=6 if plan.spacing != 6 else 4).fingerprint != plan.fingerprint
    finally:
        _close_feature_panel(panel)


def test_responsive_binding_does_not_rewrite_an_identical_grid_plan(qt_application):
    """Applying an identical plan twice must not detach and re-add every widget."""

    class CountingGridLayout(QGridLayout):
        def __init__(self, parent):
            self.take_count = 0
            self.add_count = 0
            super().__init__(parent)

        def takeAt(self, index):
            self.take_count += 1
            return super().takeAt(index)

        def addWidget(self, *args, **kwargs):
            self.add_count += 1
            return super().addWidget(*args, **kwargs)

    container = QWidget()
    container.resize(420, 100)
    layout = CountingGridLayout(container)
    buttons = (QPushButton("One"), QPushButton("Two"))
    for index, button in enumerate(buttons):
        layout.addWidget(button, 0, index)
    coordinator = ResponsiveCoordinator()
    context = LayoutContext(420, 100, False, ("Arial", 12.0), 0)
    binding = ResponsiveGridBinding(
        container,
        layout,
        buttons,
        (WidthPolicy.NATURAL, WidthPolicy.NATURAL),
        (
            row_major_mode("two", 2, 0, column_stretches=(1, 1)),
            row_major_mode("one", 1, 1, column_stretches=(1,)),
        ),
        coordinator,
        context_provider=lambda _container: context,
        adaptive_spacing=True,
    )
    try:
        plan = binding.responsive_plan(context)
        binding.apply_responsive_plan(plan)
        writes_after_first_apply = (layout.take_count, layout.add_count)

        binding.apply_responsive_plan(plan)

        assert (layout.take_count, layout.add_count) == writes_after_first_apply

        adjacent_context = LayoutContext(421, 100, False, ("Arial", 12.0), 0)
        adjacent_plan = binding.responsive_plan(adjacent_context)
        assert adjacent_plan.mode == plan.mode
        assert adjacent_plan.placements == plan.placements
        assert adjacent_plan.spacing == plan.spacing

        binding.apply_responsive_plan(adjacent_plan)

        assert (layout.take_count, layout.add_count) == writes_after_first_apply
    finally:
        container.close()


@pytest.mark.parametrize("panel_name", ("apps", "system", "remote"))
def test_responsive_spacing_tracks_viewport_without_replacing_widgets(
    qt_application,
    monkeypatch,
    panel_name,
):
    """BasePanel 行在窄/宽/窄往返中改变间距，但控件身份和业务状态保持。"""

    panel, feature_panel, scroll, _content = _show_feature_panel(
        panel_name, 292, 22, qt_application, monkeypatch
    )
    try:
        identities = tuple(
            tuple(map(id, binding.widgets())) for binding in feature_panel._responsive_rows
        )
        state = _binding_widget_state(feature_panel)
        narrow = tuple(binding.applied_plan.spacing for binding in feature_panel._responsive_rows)
        assert 2 in narrow

        _resize_feature_viewport(qt_application, panel, feature_panel, scroll, 900)
        wide = tuple(binding.applied_plan.spacing for binding in feature_panel._responsive_rows)
        assert 6 in wide
        assert wide != narrow

        _resize_feature_viewport(qt_application, panel, feature_panel, scroll, 292)
        restored = tuple(binding.applied_plan.spacing for binding in feature_panel._responsive_rows)
        assert restored == narrow
        assert (
            tuple(tuple(map(id, binding.widgets())) for binding in feature_panel._responsive_rows)
            == identities
        )
        assert _binding_widget_state(feature_panel) == state
        for binding in feature_panel._responsive_rows:
            layout = binding._layout_ref()
            assert layout.horizontalSpacing() == binding.applied_plan.spacing
            assert layout.verticalSpacing() == binding.applied_plan.spacing
    finally:
        _close_feature_panel(panel)


@pytest.mark.parametrize("font_size", (8, 12, 18, 22))
def test_empty_device_list_minimum_reserves_a_styled_row_and_possible_scrollbar(
    qt_application,
    monkeypatch,
    font_size,
):
    """空列表在最小高度也必须预留完整设备行和未来可能出现的横向滚动条。"""

    def font_for_role(_cls, _role, size=None):
        return QFont("Arial", size if size is not None else font_size)

    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(font_for_role))
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    device_widget = panel.device_widget
    try:
        device_widget.resize(300, 520)
        device_widget.show()
        manager.apply_responsive_width(300)
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)

        device_list = manager.listbox_devices
        expected_row_height = _styled_device_row_height(device_list)
        viewport_margins = device_list.viewportMargins()
        expected_minimum = (
            expected_row_height
            + device_list.frameWidth() * 2
            + viewport_margins.top()
            + viewport_margins.bottom()
            + device_list.horizontalScrollBar().sizeHint().height()
        )
        assert device_list.count() == 0
        assert expected_row_height > 0
        assert device_list.minimumHeight() >= expected_minimum

        device_widget.resize(300, device_widget.minimumSizeHint().height())
        wait_for_stable_geometry(
            qt_application,
            (device_widget, device_list, device_list.viewport()),
        )
        assert device_list.viewport().height() >= expected_row_height
    finally:
        _close_device_test_ui(panel)


@pytest.mark.parametrize("font_size", (8, 12, 18, 22))
def test_devices_real_geometry_never_overlaps_at_restricted_height(
    qt_application,
    monkeypatch,
    font_size,
):
    """四档字号的真实最小高度必须容纳列表和全部动作按钮。"""

    def font_for_role(_cls, _role, size=None):
        return QFont("Arial", size if size is not None else font_size)

    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(font_for_role))
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    device_widget = panel.device_widget
    device = "emulator-" + "5" * 96
    info = {
        "Brand": "Google" * 12,
        "Model": "Pixel" * 12,
        "Aversion": "15",
        "ip": device,
    }
    try:
        compact_limit, _wide_limit, action_widths = _device_boundary_oracle(
            device_widget,
            manager,
            qt_application,
        )
        horizontal_insets = compact_limit - action_widths["two"]
        safe_width = max(
            300,
            action_widths["one"] + horizontal_insets,
        )
        device_widget.resize(safe_width, 520)
        device_widget.show()
        manager.apply_responsive_width(device_widget.contentsRect().width())
        wait_until(
            qt_application,
            lambda: panel._responsive_coordinator.diagnostics.stable,
        )
        target_height = device_widget.minimumSizeHint().height()
        diagnostics = _show_device_geometry(
            device_widget,
            manager,
            safe_width,
            target_height,
            qt_application,
        )
        members = _visible_device_layout_members(manager)
        wait_for_stable_geometry(
            qt_application,
            (
                device_widget,
                *members,
                manager._device_action_frame,
                *manager._device_action_buttons,
            ),
        )

        assert device_widget.contentsRect().size() == QSize(safe_width, target_height)
        assert device_widget.findChildren(QScrollArea) == []
        assert diagnostics.fallback_reason is None
        assert manager._device_body_mode == "stacked"
        assert manager._device_action_frame.minimumWidth() == 0
        assert manager._device_layout_mode == "compact"
        assert _grid_item_position(manager._connect_layout, manager.ip_entry) == (
            0,
            0,
            1,
            2,
        )
        assert _grid_item_position(
            manager._connect_layout,
            manager.btn_connect_devices,
        ) == (1, 0, 1, 2)
        assert abs(manager.ip_entry.width() - manager.btn_connect_devices.width()) <= 1
        assert abs(manager.ip_entry.width() - manager._connect_layout.geometry().width()) <= 1
        assert len(members) == 4
        assert_contained(manager._device_group, device_widget)
        assert_non_overlapping(members, device_widget)
        for member in members:
            assert_positive_geometry(member, device_widget)
            assert_contained(member, device_widget)

        button_height = max(
            max(
                button.minimumHeight(),
                button.sizeHint().height(),
                button.minimumSizeHint().height(),
            )
            for button in manager._device_action_buttons
        )
        assert manager._device_action_frame.minimumHeight() >= button_height
        assert manager.listbox_devices.viewport().height() >= _styled_device_row_height(
            manager.listbox_devices
        )
        assert_non_overlapping(manager._device_action_buttons, manager._device_action_frame)
        for button in manager._device_action_buttons:
            assert_contained(button, manager._device_action_frame)
            assert_contained(button, device_widget)
            assert button.size().width() >= button.minimumSizeHint().width()
            assert button.size().height() >= button.minimumSizeHint().height()

        before = panel._responsive_coordinator.diagnostics.generation
        with patch(
            "gui.panels.device_manager.DeviceStore.get_full_devices_info",
            return_value=[info],
        ):
            panel.update_device_list([device])
        wait_until(
            qt_application,
            lambda: (
                panel._responsive_coordinator.diagnostics.stable
                and panel._responsive_coordinator.diagnostics.generation > before
            ),
        )
        wait_for_stable_geometry(
            qt_application,
            (
                device_widget,
                manager.listbox_devices,
                manager.listbox_devices.viewport(),
            ),
        )
        assert device_widget.contentsRect().size() == QSize(safe_width, target_height)
        _assert_device_list_endpoints(qt_application, manager)
    finally:
        _close_device_test_ui(panel)


@pytest.mark.parametrize("font_size", (8, 12, 18, 22))
def test_device_body_height_boundary_switches_both_directions_without_fallback(
    qt_application,
    monkeypatch,
    font_size,
):
    """高度往返不得改变由宽度决定的 Devices 宿主或动作列。"""

    def font_for_role(_cls, _role, size=None):
        return QFont("Arial", size if size is not None else font_size)

    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(font_for_role))
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    device_widget = panel.device_widget
    try:
        device_widget.resize(300, 700)
        device_widget.show()
        manager.apply_responsive_width(300)
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        wait_for_stable_geometry(
            qt_application,
            (device_widget, manager.listbox_devices, manager._device_action_frame),
        )
        assert manager._device_layout_mode == "compact"
        assert manager._device_body_mode == "stacked"
        minimum = device_widget.minimumSizeHint().height()
        transitions = (minimum, minimum + 1, minimum + 120, minimum + 1, minimum)
        identities = tuple(manager._device_action_buttons)
        action_columns = manager._device_actions_layout.property("deviceActionColumnCount")
        observed_modes = []
        for height in transitions:
            diagnostics = _show_device_height(
                device_widget,
                manager,
                height,
                qt_application,
            )
            observed_modes.append(manager._device_body_mode)
            assert diagnostics.fallback_reason is None
            assert 1 <= diagnostics.rounds < 3
            assert manager._device_layout_mode == "compact"
            assert manager._device_body_mode == "stacked"
            assert tuple(manager._device_action_buttons) == identities
            assert (
                manager._device_actions_layout.property("deviceActionColumnCount") == action_columns
            )
            assert _grid_item_position(manager._connect_layout, manager.ip_entry) == (
                0,
                0,
                1,
                2,
            )
            assert _grid_item_position(
                manager._connect_layout,
                manager.btn_connect_devices,
            ) == (1, 0, 1, 2)
            assert _grid_item_position(
                manager._device_body_layout,
                manager.listbox_devices,
            ) == (0, 0, 1, 2)
            assert _grid_item_position(
                manager._device_body_layout,
                manager._device_action_frame,
            ) == (1, 0, 1, 2)

        assert observed_modes == ["stacked"] * len(transitions)
    finally:
        _close_device_test_ui(panel)


@pytest.mark.parametrize("font_size", (8, 12, 18, 22))
def test_medium_connect_width_is_independent_of_body_height_and_fallback(
    qt_application,
    monkeypatch,
    font_size,
):
    """medium 的 Connect 宽度和宿主只能由宽度计划决定。"""

    def font_for_role(_cls, _role, size=None):
        return QFont("Arial", size if size is not None else font_size)

    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(font_for_role))
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    device_widget = panel.device_widget
    try:
        compact_limit, wide_limit, _metrics = _device_boundary_oracle(
            device_widget,
            manager,
            qt_application,
        )
        medium_width = compact_limit + max(1, (wide_limit - compact_limit) // 2)
        assert compact_limit <= medium_width < wide_limit

        minimum_height = device_widget.minimumSizeHint().height()
        _show_device_geometry(
            device_widget,
            manager,
            medium_width,
            minimum_height + 200,
            qt_application,
        )
        assert manager._device_layout_mode == "medium"
        assert manager._device_body_mode == "stacked"
        high_connect_width = manager.btn_connect_devices.width()
        high_context = manager.action_binding.responsive_context()
        high_plan = manager._build_device_plan(
            manager.action_binding,
            high_context,
            conservative=False,
        )
        assert high_plan.connect_width == high_connect_width

        _show_device_geometry(
            device_widget,
            manager,
            medium_width,
            device_widget.minimumSizeHint().height(),
            qt_application,
        )
        assert manager._device_layout_mode == "medium"
        assert manager._device_body_mode == "stacked"
        low_context = manager.action_binding.responsive_context()
        low_plan = manager._build_device_plan(
            manager.action_binding,
            low_context,
            conservative=False,
        )
        assert low_plan.connect_width == high_connect_width
        assert manager.btn_connect_devices.width() == high_connect_width
        assert _grid_item_position(manager._connect_layout, manager.ip_entry) == (0, 0, 1, 2)
        assert _grid_item_position(
            manager._connect_layout,
            manager.btn_connect_devices,
        ) == (1, 1, 1, 1)
    finally:
        _close_device_test_ui(panel)


@pytest.mark.parametrize("width", (120, 143, 160, 200, 240))
def test_compact_device_address_remains_full_width_and_editable_below_240px(
    qt_application,
    monkeypatch,
    width,
):
    """极窄视觉根仍保持地址整行，不能被 Connect 的自然宽度挤压为零。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Arial", size or 22)),
    )
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    device_widget = panel.device_widget
    try:
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        device_widget.resize(width, 180)
        device_widget.show()
        before = panel._responsive_coordinator.diagnostics.generation
        manager.apply_responsive_width(width)
        wait_until(
            qt_application,
            lambda: (
                panel._responsive_coordinator.diagnostics.stable
                and panel._responsive_coordinator.diagnostics.generation > before
            ),
        )
        wait_for_stable_geometry(
            qt_application,
            (device_widget, *_visible_device_layout_members(manager)),
        )
        line_edit = manager.ip_entry.lineEdit()
        line_edit.setText("192.0.2.10:5555")
        line_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        qt_application.processEvents()

        assert device_widget.width() == width
        assert manager._device_layout_mode == "compact"
        assert _grid_item_position(manager._connect_layout, manager.ip_entry) == (
            0,
            0,
            1,
            2,
        )
        assert _grid_item_position(
            manager._connect_layout,
            manager.btn_connect_devices,
        ) == (1, 0, 1, 2)
        assert manager.ip_entry.width() > 0
        assert abs(manager.ip_entry.width() - manager.btn_connect_devices.width()) <= 1
        assert line_edit.text() == "192.0.2.10:5555"
        assert line_edit.focusPolicy() != Qt.FocusPolicy.NoFocus
    finally:
        _close_device_test_ui(panel)


@pytest.mark.parametrize("font_size", (8, 12, 18, 22))
@pytest.mark.parametrize("populate_after_shrink", (False, True))
def test_device_list_minimum_keeps_a_long_row_visible_after_content_changes(
    qt_application,
    monkeypatch,
    font_size,
    populate_after_shrink,
):
    """设备项无论先于还是晚于收缩出现，最小高度都必须容纳行和横向滚动条。"""

    def font_for_role(_cls, _role, size=None):
        return QFont("Arial", size if size is not None else font_size)

    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(font_for_role))
    device = "emulator-" + "5" * 96
    info = {
        "Brand": "Google" * 12,
        "Model": "Pixel" * 12,
        "Aversion": "15",
        "ip": device,
    }
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    device_widget = panel.device_widget
    try:
        device_widget.resize(300, 520)
        device_widget.show()
        manager.apply_responsive_width(300)
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)

        if populate_after_shrink:
            empty_minimum = device_widget.minimumSizeHint().height()
            device_widget.resize(300, empty_minimum)
            wait_for_stable_geometry(
                qt_application,
                (device_widget, manager.listbox_devices, manager.listbox_devices.viewport()),
            )
            before = panel._responsive_coordinator.diagnostics.generation
        else:
            empty_minimum = device_widget.minimumSizeHint().height()
            before = panel._responsive_coordinator.diagnostics.generation

        with patch(
            "gui.panels.device_manager.DeviceStore.get_full_devices_info",
            return_value=[info],
        ):
            panel.update_device_list([device])

        wait_until(
            qt_application,
            lambda: (
                panel._responsive_coordinator.diagnostics.stable
                and panel._responsive_coordinator.diagnostics.generation > before
            ),
        )
        wait_for_stable_geometry(
            qt_application,
            (
                device_widget,
                manager.listbox_devices,
                manager.listbox_devices.viewport(),
            ),
        )

        item = manager.listbox_devices.item(0)
        row_height = manager.listbox_devices.sizeHintForRow(0)
        assert item is not None and row_height > 0
        horizontal = manager.listbox_devices.horizontalScrollBar()
        assert horizontal.maximum() > horizontal.minimum()

        # 独立使用 Qt 已实现的 viewport 几何作为 oracle；不读取生产高度计算函数。
        non_viewport_height = (
            manager.listbox_devices.height() - manager.listbox_devices.viewport().height()
        )
        required_height = row_height + non_viewport_height
        assert manager.listbox_devices.minimumHeight() >= required_height
        assert abs(device_widget.minimumSizeHint().height() - empty_minimum) <= 1
        assert ReflowReason.EXPLICIT in panel._responsive_coordinator.diagnostics.reasons

        target_height = device_widget.minimumSizeHint().height()
        device_widget.resize(300, target_height)
        wait_for_stable_geometry(
            qt_application,
            (
                device_widget,
                manager.listbox_devices,
                manager.listbox_devices.viewport(),
            ),
        )
        item_rect = manager.listbox_devices.visualItemRect(item)
        viewport_rect = manager.listbox_devices.viewport().rect()
        assert item_rect.top() >= viewport_rect.top()
        assert item_rect.bottom() <= viewport_rect.bottom()
    finally:
        _close_device_test_ui(panel)


@pytest.mark.parametrize("panel_name", ("apps", "system", "remote"))
@pytest.mark.parametrize("font_size", (8, 12, 18, 22))
def test_feature_panel_real_geometry_and_scroll_contract(
    qt_application,
    monkeypatch,
    panel_name,
    font_size,
):
    """四档字号/292px 下每行使用真实 binding，内容正尺寸且横向溢出可达。"""

    panel, feature_panel, scroll, content_widget = _show_feature_panel(
        panel_name,
        292,
        font_size,
        qt_application,
        monkeypatch,
    )
    try:
        assert scroll.viewport().contentsRect().width() == 292
        bindings = tuple(feature_panel._responsive_rows)
        assert bindings
        assert all(isinstance(binding, ResponsiveGridBinding) for binding in bindings)
        wait_for_stable_geometry(
            qt_application,
            tuple(widget for binding in bindings for widget in binding.widgets()),
        )
        for binding_index, binding in enumerate(bindings):
            plan = binding.applied_plan
            assert plan is not None, (
                panel_name,
                font_size,
                binding_index,
                tuple(widget.objectName() for widget in binding.widgets()),
                panel._responsive_coordinator.diagnostics,
            )
            widgets = binding.widgets()
            assert widgets
            for widget in widgets:
                try:
                    assert_positive_geometry(widget, content_widget)
                except AssertionError as error:
                    raise AssertionError(
                        (
                            panel_name,
                            font_size,
                            binding_index,
                            plan.mode.name,
                            plan.required_width,
                            plan.available_width,
                            tuple(item.geometry().getRect() for item in widgets),
                            tuple(
                                (metric.minimum_width, metric.preferred_width)
                                for metric in plan.metrics
                            ),
                        )
                    ) from error
            try:
                assert_non_overlapping(widgets, content_widget)
            except AssertionError as error:
                raise AssertionError(
                    (
                        panel_name,
                        font_size,
                        binding_index,
                        plan.mode.name,
                        plan.required_width,
                        plan.available_width,
                        widgets[0].parentWidget().contentsRect().width(),
                        content_widget.width(),
                        scroll.horizontalScrollBar().maximum(),
                        plan.column_widths,
                        tuple(
                            widgets[0].parentWidget().layout().columnMinimumWidth(column)
                            for column in range(plan.mode.columns)
                        ),
                        tuple(widget.geometry().getRect() for widget in widgets),
                    )
                ) from error

        overflowing = [
            (binding_index, binding)
            for binding_index, binding in enumerate(bindings)
            if binding.applied_plan is not None and binding.applied_plan.overflow_required
        ]
        scroll.horizontalScrollBar().setValue(scroll.horizontalScrollBar().minimum())
        qt_application.processEvents()
        viewport_rect = scroll.viewport().rect()
        for binding_index, binding in enumerate(bindings):
            plan = binding.applied_plan
            if plan is None or plan.overflow_required:
                continue
            for widget in binding.widgets():
                rect = QRect(widget.mapTo(scroll.viewport(), QPoint(0, 0)), widget.size())
                assert (
                    viewport_rect.left() <= rect.left() and rect.right() <= viewport_rect.right()
                ), (
                    panel_name,
                    font_size,
                    binding_index,
                    plan.mode.name,
                    plan.required_width,
                    plan.available_width,
                    rect,
                    viewport_rect,
                    content_widget.size(),
                )
        if overflowing:
            for binding_index, binding in overflowing:
                widgets = binding.widgets()
                try:
                    assert_scroll_target_reachable(scroll, widgets[0])
                    assert_scroll_target_reachable(scroll, widgets[-1])
                except AssertionError as error:
                    plan = binding.applied_plan
                    raise AssertionError(
                        (
                            panel_name,
                            font_size,
                            binding_index,
                            plan.mode.name,
                            plan.required_width,
                            plan.available_width,
                            widgets[0].parentWidget().contentsRect().width(),
                            content_widget.size(),
                            scroll.viewport().size(),
                            scroll.horizontalScrollBar().maximum(),
                            scroll.verticalScrollBar().maximum(),
                            tuple(
                                (
                                    getattr(widget, "text", lambda: "")(),
                                    metric.minimum_width,
                                    metric.preferred_width,
                                    widget.minimumSizeHint().width(),
                                )
                                for widget, metric in zip(widgets, plan.metrics)
                            ),
                        )
                    ) from error
        else:
            assert scroll.horizontalScrollBar().maximum() == 0, (
                panel_name,
                font_size,
                content_widget.size(),
                content_widget.minimumSizeHint(),
                tuple(
                    (
                        group.title(),
                        group.width(),
                        group.minimumSizeHint().width(),
                        group.sizeHint().width(),
                    )
                    for group in content_widget.findChildren(
                        QGroupBox, options=Qt.FindDirectChildrenOnly
                    )
                ),
            )
    finally:
        _close_feature_panel(panel)


@pytest.mark.parametrize("panel_name", ("apps", "system", "remote"))
@pytest.mark.parametrize("font_size", (12, 22))
@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_feature_panel_geometry_is_stable_in_light_and_dark_themes(
    qt_application,
    monkeypatch,
    panel_name,
    font_size,
    theme,
):
    """两种主题和常规/最大字号下都由同一语义计划保持有效几何。"""

    BaseStyles.switch_theme(theme)
    panel, feature_panel, scroll, content_widget = _show_feature_panel(
        panel_name,
        292,
        font_size,
        qt_application,
        monkeypatch,
    )
    try:
        bindings = tuple(feature_panel._responsive_rows)
        wait_for_stable_geometry(
            qt_application,
            tuple(widget for binding in bindings for widget in binding.widgets()),
        )
        for binding in bindings:
            assert binding.applied_plan is not None
            widgets = binding.widgets()
            for widget in widgets:
                assert_positive_geometry(widget, content_widget)
            assert_non_overlapping(widgets, content_widget)
        has_overflow = any(binding.applied_plan.overflow_required for binding in bindings)
        assert (scroll.horizontalScrollBar().maximum() > 0) is has_overflow
    finally:
        _close_feature_panel(panel)


def test_package_manager_two_column_tail_spans_full_row(
    qt_application,
    monkeypatch,
):
    """Package Manager 的三动作行在 two 模式让尾动作横跨整行。"""

    panel, app_panel, scroll, _content = _show_feature_panel(
        "apps",
        420,
        12,
        qt_application,
        monkeypatch,
    )
    try:
        assert len(app_panel.package_action_bindings) == 3
        assert app_panel.package_action_binding is app_panel.package_action_bindings[0]
        for binding in app_panel.package_action_bindings:
            _resize_binding_until_mode(
                qt_application,
                panel,
                scroll,
                app_panel,
                binding,
                "two",
            )
            plan = binding.applied_plan
            assert plan is not None
            assert plan.mode.column_count == 2
            assert plan.placements[-1].column == 0
            assert plan.placements[-1].column_span == 2
    finally:
        _close_feature_panel(panel)


@pytest.mark.parametrize("panel_name", ("apps", "system", "remote"))
def test_lazy_feature_rows_share_one_coordinator_and_register_once(
    qt_application,
    monkeypatch,
    panel_name,
):
    """懒加载页的每行只注册一次，并统一消费 SidePanel coordinator。"""

    panel, feature_panel, scroll, _content = _show_feature_panel(
        panel_name,
        420,
        12,
        qt_application,
        monkeypatch,
    )
    try:
        bindings = tuple(feature_panel._responsive_rows)
        assert bindings
        assert all(isinstance(binding, ResponsiveGridBinding) for binding in bindings)
        assert all(
            binding._coordinator_ref() is panel._responsive_coordinator for binding in bindings
        )
        count_before = panel._responsive_coordinator.target_count
        index = {"apps": 0, "system": 1, "remote": 2}[panel_name]
        assert panel._ensure_tab_loaded(index) is feature_panel
        feature_panel.apply_responsive_width(scroll.viewport().contentsRect().width())
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        assert panel._responsive_coordinator.target_count == count_before
        assert len({id(binding) for binding in bindings}) == len(bindings)
    finally:
        _close_feature_panel(panel)


def test_shrinkable_package_field_ignores_dynamic_text_width(
    qt_application,
    monkeypatch,
):
    """动态包名不得进入 SHRINKABLE 字段的自然宽度或布局指纹。"""

    panel, app_panel, scroll, _content = _show_feature_panel(
        "apps",
        520,
        12,
        qt_application,
        monkeypatch,
    )
    try:
        binding = next(
            item for item in app_panel._responsive_rows if app_panel.program_edit in item.widgets()
        )
        before = binding.applied_plan
        assert before is not None
        app_panel.program_edit.setCurrentText("com." + "verylongpackage" * 40)
        app_panel.apply_responsive_width(scroll.viewport().contentsRect().width())
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        after = binding.applied_plan
        assert after is not None
        assert after.required_width == before.required_width
        assert after.mode.name == before.mode.name
        assert after.metrics == before.metrics
    finally:
        _close_feature_panel(panel)


def test_system_label_field_pair_never_splits_in_narrow_mode(
    qt_application,
    monkeypatch,
):
    """System 的 Battery 标签与参数字段在窄模式仍位于同一语义行。"""

    panel, system_panel, scroll, _content = _show_feature_panel(
        "system",
        292,
        22,
        qt_application,
        monkeypatch,
    )
    try:
        binding = system_panel.battery_parameter_binding
        plan = binding.applied_plan
        assert plan is not None
        widgets = binding.widgets()
        assert system_panel._battery_value_pair in widgets
        assert system_panel.battery_label.parentWidget() is system_panel._battery_value_pair
        assert system_panel.battery_val.parentWidget() is system_panel._battery_value_pair
        assert (
            system_panel.battery_label.geometry().right()
            < system_panel.battery_val.geometry().left()
        )
        assert system_panel.battery_label.buddy() is system_panel.battery_val
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    finally:
        _close_feature_panel(panel)


def test_monkey_parameter_and_percentage_pairs_survive_reflow(
    qt_application,
    monkeypatch,
):
    """Monkey 参数、九组比例和独立单位/Total 在各模式中保持语义归属。"""

    panel, app_panel, scroll, _content = _show_feature_panel(
        "apps",
        292,
        22,
        qt_application,
        monkeypatch,
    )
    try:
        parameter_binding = app_panel.monkey_parameter_binding
        percentage_binding = app_panel.monkey_percentage_binding
        percentage_widgets = percentage_binding.widgets()
        for width in (292, 760, 292):
            _set_scroll_viewport_width(qt_application, panel, scroll, width)
            app_panel.apply_responsive_width(scroll.viewport().contentsRect().width())
            wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
            plan = percentage_binding.applied_plan
            assert plan is not None
            positions = {placement.item_index: placement for placement in plan.placements}
            for label, field in zip(
                app_panel._monkey_pct_labels.values(),
                app_panel._monkey_pct_combos.values(),
            ):
                label_index = percentage_widgets.index(label)
                field_index = percentage_widgets.index(field)
                assert positions[label_index].row == positions[field_index].row
                assert positions[field_index].column == positions[label_index].column + 1

        before = parameter_binding.applied_plan
        assert before is not None
        for combo in app_panel._monkey_pct_combos.values():
            combo.setCurrentText("0")
        app_panel._monkey_pct_combos["touch"].setCurrentText("100")
        app_panel._update_pct_total()
        app_panel.apply_responsive_width(scroll.viewport().contentsRect().width())
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        after = parameter_binding.applied_plan
        assert after is not None
        assert after.mode.name == before.mode.name
        assert app_panel._pct_total_lbl.text() == "Total: 100%"
        assert BaseStyles.color("LOG_SUCCESS") in app_panel._pct_total_lbl.styleSheet()
    finally:
        _close_feature_panel(panel)


@pytest.mark.parametrize("panel_name", ("apps", "system", "remote"))
def test_feature_binding_breakpoint_is_stable_at_b_minus_one_b_and_b_plus_one(
    qt_application,
    monkeypatch,
    panel_name,
):
    """测试侧有限扫描所得动态边界在 B−1/B/B+1 使用 Qt 最终 viewport 收敛。"""

    panel, feature_panel, scroll, _content = _show_feature_panel(
        panel_name,
        300,
        12,
        qt_application,
        monkeypatch,
    )
    try:
        if panel_name == "apps":
            binding = feature_panel.package_action_binding
        elif panel_name == "system":
            binding = feature_panel.battery_parameter_binding
        else:
            binding = feature_panel.parameter_binding
        sampled = []
        previous = None
        bracket = None
        for width in range(180, 901, 8):
            _set_scroll_viewport_width(qt_application, panel, scroll, width)
            feature_panel.apply_responsive_width(scroll.viewport().contentsRect().width())
            wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
            mode = binding.applied_plan.mode.name
            sampled.append((width, mode))
            if previous is not None and previous[1] != mode:
                bracket = (previous[0], width, previous[1], mode)
                break
            previous = (width, mode)
        assert bracket is not None, sampled
        lower, upper, narrow_mode, wide_mode = bracket
        boundary = None
        for width in range(lower + 1, upper + 1):
            _set_scroll_viewport_width(qt_application, panel, scroll, width)
            feature_panel.apply_responsive_width(scroll.viewport().contentsRect().width())
            wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
            if binding.applied_plan.mode.name == wide_mode:
                boundary = width
                break
        assert boundary is not None
        for width, expected in (
            (boundary - 1, narrow_mode),
            (boundary, wide_mode),
            (boundary + 1, wide_mode),
        ):
            actual = _set_scroll_viewport_width(qt_application, panel, scroll, width)
            feature_panel.apply_responsive_width(actual)
            wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
            assert actual == width
            assert binding.applied_plan.mode.name == expected
    finally:
        _close_feature_panel(panel)


@pytest.mark.parametrize("panel_name", ("apps", "system", "remote"))
def test_feature_theme_and_font_events_each_create_one_generation(
    qt_application,
    monkeypatch,
    panel_name,
):
    """已加载功能页的主题与字体刷新各合并为单一 coordinator generation。"""

    panel, _feature_panel, _scroll, _content = _show_feature_panel(
        panel_name,
        420,
        12,
        qt_application,
        monkeypatch,
    )
    try:
        before_theme = panel._responsive_coordinator.diagnostics.generation
        panel._on_theme_changed(BaseStyles.current_theme())
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        assert panel._responsive_coordinator.diagnostics.generation == before_theme + 1

        before_font = panel._responsive_coordinator.diagnostics.generation
        panel._on_fonts_changed(BaseStyles.current_font_config())
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        assert panel._responsive_coordinator.diagnostics.generation == before_font + 1
    finally:
        _close_feature_panel(panel)


@pytest.mark.parametrize("panel_name", ("apps", "system", "remote"))
def test_real_feature_viewport_resize_uses_one_generation_and_ignores_feedback(
    qt_application,
    monkeypatch,
    panel_name,
):
    """真实顶层缩放只开启一代，内部 viewport 反馈不得排队形成额外代次。"""

    panel, feature_panel, scroll, content = _show_feature_panel(
        panel_name,
        180,
        22,
        qt_application,
        monkeypatch,
    )
    try:
        samples = []
        narrow_width = None
        for width in range(180, 901, 24):
            _resize_feature_viewport(qt_application, panel, feature_panel, scroll, width)
            overflow_count = sum(
                1
                for binding in feature_panel._responsive_rows
                if binding.applied_plan is not None and binding.applied_plan.overflow_required
            )
            horizontal_maximum = scroll.horizontalScrollBar().maximum()
            samples.append((width, overflow_count, horizontal_maximum))
            if narrow_width is None and overflow_count > 0 and horizontal_maximum > 0:
                narrow_width = width
        assert narrow_width is not None, samples
        assert samples[-1][0] == 900
        assert samples[-1][1:] == (0, 0), samples

        _resize_feature_viewport(
            qt_application,
            panel,
            feature_panel,
            scroll,
            narrow_width,
        )
        narrow_overflow = _assert_feature_binding_geometry(feature_panel, scroll, content)
        assert narrow_overflow
        assert scroll.horizontalScrollBar().maximum() > 0

        before_resize = panel._responsive_coordinator.diagnostics.generation
        panel.resize(panel.width() + 900 - narrow_width, panel.height())
        wait_until(
            qt_application,
            lambda: (
                panel._responsive_coordinator.diagnostics.stable
                and panel._responsive_coordinator.diagnostics.generation > before_resize
            ),
        )
        wait_for_stable_geometry(qt_application, (panel, scroll, content))
        # 页面变宽后纵向滚动条可能消失，viewport 会额外获得滚动条占用的宽度；
        # 这属于同一次顶层缩放的稳定几何，不应被误判为额外响应式代次。
        final_viewport_width = scroll.viewport().contentsRect().width()
        scrollbar_width = scroll.verticalScrollBar().sizeHint().width()
        assert 900 <= final_viewport_width <= 900 + scrollbar_width
        wide_overflow = _assert_feature_binding_geometry(feature_panel, scroll, content)
        assert panel._responsive_coordinator.diagnostics.generation == before_resize + 1
        assert panel._responsive_coordinator.diagnostics.fallback_reason is None
        assert wide_overflow == ()
        assert scroll.horizontalScrollBar().maximum() == 0

        # 清空当前代次应用过程中排队的 Resize/LayoutRequest；稳定几何必须覆盖这些反馈。
        for _attempt in range(4):
            QCoreApplication.sendPostedEvents()
            qt_application.processEvents()
        assert panel._responsive_coordinator.diagnostics.stable
        assert panel._responsive_coordinator.diagnostics.generation == before_resize + 1
        assert feature_panel.responsive_geometry_is_applied()
        assert all(
            binding.applied_plan is not None
            and binding.applied_plan.available_width == binding.responsive_context().width
            and binding.applied_plan.context_fingerprint == binding.responsive_context().fingerprint
            for binding in feature_panel._responsive_rows
        )

        before_burst = panel._responsive_coordinator.diagnostics.generation
        panel.resize(panel.width() - 180, panel.height())
        panel.resize(panel.width() + 40, panel.height())
        panel.resize(panel.width() + 60, panel.height())
        wait_until(
            qt_application,
            lambda: (
                panel._responsive_coordinator.diagnostics.stable
                and panel._responsive_coordinator.diagnostics.generation > before_burst
            ),
        )
        wait_for_stable_geometry(qt_application, (panel, scroll, content))
        burst_overflow = _assert_feature_binding_geometry(feature_panel, scroll, content)
        for _attempt in range(4):
            QCoreApplication.sendPostedEvents()
            qt_application.processEvents()
        assert panel._responsive_coordinator.diagnostics.generation == before_burst + 1
        assert panel._responsive_coordinator.diagnostics.fallback_reason is None
        assert feature_panel.responsive_geometry_is_applied()
        assert (scroll.horizontalScrollBar().maximum() > 0) is bool(burst_overflow)
    finally:
        _close_feature_panel(panel)


def test_runtime_font_change_refreshes_responsive_auto_minimums(
    qt_application,
    monkeypatch,
):
    """运行时切换字号后，响应项下限必须与当前字体重新度量。"""

    panel, app_panel, _scroll, _content = _show_feature_panel(
        "apps",
        292,
        8,
        qt_application,
        monkeypatch,
    )
    try:

        def large_font_for_role(_cls, _role, size=None):
            return QFont("Arial", size if size is not None else 22)

        monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(large_font_for_role))
        panel._on_fonts_changed(BaseStyles.current_font_config())
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)

        label = app_panel._pct_total_lbl
        field = app_panel.monkey_events
        assert label.minimumWidth() == label.fontMetrics().horizontalAdvance("MMMMMM")
        assert field.minimumWidth() == field.fontMetrics().horizontalAdvance("MM")
    finally:
        _close_feature_panel(panel)


def test_runtime_12_to_22_font_metrics_match_fresh_remote_panel(
    qt_application,
    monkeypatch,
):
    """真实字体配置从 12 切到 22 后，同一实例应与 22 号新实例采用相同计划。"""

    current = BaseStyles.current_font_config()

    def apply_font_size(size: int) -> FontConfig:
        config = FontConfig(
            ui_family="Arial",
            ui_size=size,
            log_size=current.log_size,
            mono_family=current.mono_family,
        )
        BaseStyles._sync_legacy_values(config)
        typography_manager.apply(config)
        return config

    apply_font_size(12)
    panel, remote, scroll, content = _show_feature_panel(
        "remote",
        292,
        12,
        qt_application,
        monkeypatch,
        patch_font_factory=False,
    )
    try:
        before_generation = panel._responsive_coordinator.diagnostics.generation
        apply_font_size(22)
        wait_until(
            qt_application,
            lambda: (
                panel._responsive_coordinator.diagnostics.stable
                and panel._responsive_coordinator.diagnostics.generation > before_generation
            ),
        )
        wait_for_stable_geometry(qt_application, (panel, scroll, content))
        runtime_snapshot = tuple(
            (binding.applied_plan.mode.name, binding.applied_plan.metrics)
            for binding in (remote.status_binding, remote.parameter_binding)
        )
    finally:
        _close_feature_panel(panel)

    fresh_panel, fresh_remote, _fresh_scroll, _fresh_content = _show_feature_panel(
        "remote",
        292,
        22,
        qt_application,
        monkeypatch,
        patch_font_factory=False,
    )
    try:
        fresh_snapshot = tuple(
            (binding.applied_plan.mode.name, binding.applied_plan.metrics)
            for binding in (fresh_remote.status_binding, fresh_remote.parameter_binding)
        )
        assert runtime_snapshot == fresh_snapshot
    finally:
        _close_feature_panel(fresh_panel)


@pytest.mark.parametrize("panel_name", ("apps", "remote"))
def test_large_font_static_semantic_labels_are_not_clipped_after_runtime_change(
    qt_application,
    monkeypatch,
    panel_name,
):
    """静态参数标签必须按当前字体保留完整文本宽度。"""

    panel, feature_panel, scroll, content = _show_feature_panel(
        panel_name,
        292,
        8,
        qt_application,
        monkeypatch,
    )
    try:

        def large_font_for_role(_cls, _role, size=None):
            return QFont("Arial", size if size is not None else 22)

        monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(large_font_for_role))
        panel._on_fonts_changed(BaseStyles.current_font_config())
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        wait_for_stable_geometry(qt_application, (panel, scroll, content))

        if panel_name == "apps":
            labels = (
                feature_panel.monkey_events_label,
                feature_panel.monkey_throttle_label,
                feature_panel.monkey_ms_label,
                *feature_panel._monkey_pct_labels.values(),
            )
        else:
            labels = tuple(feature_panel._parameter_labels)
        for label in labels:
            assert label.contentsRect().width() >= label.fontMetrics().horizontalAdvance(
                label.text()
            ), (panel_name, label.text(), label.contentsRect(), label.minimumSizeHint())
    finally:
        _close_feature_panel(panel)


def test_remote_overflow_row_constraints_clear_when_viewport_grows(
    qt_application,
    monkeypatch,
):
    """溢出行恢复为可容纳状态时，行宽约束和共享滚动范围必须同步清除。"""

    panel, remote, scroll, _content = _show_feature_panel(
        "remote",
        292,
        12,
        qt_application,
        monkeypatch,
    )
    try:
        binding = remote._remote_action_binding
        narrow_plan = binding.applied_plan
        assert narrow_plan is not None and narrow_plan.overflow_required
        container = binding._container_ref()
        assert container is not None
        assert container.minimumWidth() == narrow_plan.required_width
        assert container.maximumWidth() == narrow_plan.required_width

        actual = _set_scroll_viewport_width(qt_application, panel, scroll, 900)
        remote.apply_responsive_width(actual)
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        wait_for_stable_geometry(qt_application, (panel, scroll, container))

        wide_plan = binding.applied_plan
        assert wide_plan is not None and not wide_plan.overflow_required
        assert container.minimumWidth() == 0
        assert container.maximumWidth() == wide_plan.available_width
        assert scroll.horizontalScrollBar().maximum() == 0
    finally:
        _close_feature_panel(panel)


def test_queued_remote_reflow_unregisters_bindings_and_keeps_shutdown_once(
    qt_application,
    monkeypatch,
):
    """排队重排中关闭 Remote 时，binding 注销且 worker/executor 只清理一次。"""

    panel, remote, scroll, content = _show_feature_panel(
        "remote",
        420,
        12,
        qt_application,
        monkeypatch,
    )
    bindings = tuple(remote._responsive_rows)
    worker = Mock()
    worker.isRunning.return_value = True
    worker.wait.return_value = True
    executor = Mock()
    remote._launch_worker = worker
    remote._remote_executor = executor
    try:
        count_before = panel._responsive_coordinator.target_count
        panel.request_responsive_reflow(ReflowReason.RESIZE)
        remote.shutdown()
        detached = scroll.takeWidget()
        assert detached is content
        content.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_application.processEvents()
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)

        worker.requestInterruption.assert_called_once_with()
        worker.wait.assert_called_once_with(0)
        worker.deleteLater.assert_called_once_with()
        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        assert panel._responsive_coordinator.target_count == count_before - len(bindings)
        assert all(binding.widgets() == () for binding in bindings)
    finally:
        _close_feature_panel(panel)


def test_side_panel_supervised_remote_close_cleans_active_resources_once(
    qt_application,
    monkeypatch,
):
    """排队重排中经 SidePanel 与 supervisor 关闭 Remote，每类资源只清理一次。"""

    class FakeSignal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback, *_args):
            self.callbacks.append(callback)

        def disconnect(self, callback=None):
            if callback is None:
                self.callbacks.clear()
            else:
                self.callbacks = [item for item in self.callbacks if item != callback]

        def emit(self):
            for callback in tuple(self.callbacks):
                callback()

    class DelayedWorker:
        def __init__(self):
            self.running = True
            self.interruptions = 0
            self.wait_calls = []
            self.delete_calls = 0
            self.log_message = FakeSignal()
            self.launch_ready = FakeSignal()
            self.finished = FakeSignal()

        def isRunning(self):
            return self.running

        def requestInterruption(self):
            self.interruptions += 1

        def wait(self, timeout_ms):
            self.wait_calls.append(timeout_ms)
            if timeout_ms <= 0:
                return False
            self.running = False
            self.finished.emit()
            return True

        def setParent(self, _parent):
            return None

        def deleteLater(self):
            self.delete_calls += 1

    class DelayedScrcpyService:
        def __init__(self):
            self.stop_requests = []
            self.force_calls = []
            self.stop_requested = False
            self.remaining_active_checks = 1

        def request_stop(self, process_key):
            self.stop_requests.append(process_key)
            self.stop_requested = True

        def is_active(self, _process_key):
            if not self.stop_requested:
                return True
            if self.remaining_active_checks > 0:
                self.remaining_active_checks -= 1
                return True
            return False

        def force_stop(self, process_key, timeout):
            self.force_calls.append((process_key, timeout))
            self.remaining_active_checks = 0
            return True

    panel, remote, scroll, content = _show_feature_panel(
        "remote",
        420,
        12,
        qt_application,
        monkeypatch,
    )
    bindings = tuple(remote._responsive_rows)
    count_before = panel._responsive_coordinator.target_count
    worker = DelayedWorker()
    scrcpy_service = DelayedScrcpyService()
    watchdog = Mock()
    executor = Mock()
    original_executor = remote._remote_executor
    original_executor.shutdown(wait=False, cancel_futures=True)
    adb = Mock(path="adb")
    adb_close_calls = []
    adb.close_input_sessions.side_effect = lambda: adb_close_calls.append(True)
    remote._process = object()
    remote._watchdog = watchdog
    remote._launch_worker = worker
    remote._scrcpy_service = scrcpy_service
    remote._remote_executor = executor
    remote._adb = adb
    remote._active_device = "active-device"
    destroyed = QSignalSpy(content.destroyed)
    content_deleted = {"value": False}
    content.destroyed.connect(lambda: content_deleted.__setitem__("value", True))
    post_delete_context_calls = []
    for binding in bindings:
        original_context = binding.responsive_context

        def guarded_context(_original=original_context):
            if content_deleted["value"]:
                post_delete_context_calls.append(True)
            return _original()

        monkeypatch.setattr(binding, "responsive_context", guarded_context)

    supervisor = TaskSupervisor()
    try:
        registered = panel.register_shutdown_tasks(supervisor, owner_id="test-owner")
        assert registered == ("test-owner-panel-2",)
        snapshot = supervisor.active_snapshot()
        assert len(snapshot) == 1
        assert snapshot[0].kind == "remote_session"

        panel.request_responsive_reflow(ReflowReason.RESIZE)
        panel.shutdown()
        detached = scroll.takeWidget()
        assert detached is content
        content.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_application.processEvents()
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)

        results = supervisor.stop_all(deadline=1.0)
        panel.shutdown()

        assert len(results) == 1
        assert results[0].disposition is StopDisposition.GRACEFUL
        assert supervisor.active_count == 0
        assert watchdog.stop.call_count == 1
        assert scrcpy_service.stop_requests == [remote._process_key]
        assert scrcpy_service.force_calls == []
        assert worker.interruptions == 1
        wait_until(
            qt_application,
            lambda: (
                worker.delete_calls == 1 and worker not in RemotePanel._orphaned_launch_workers
            ),
        )
        assert worker.delete_calls == 1
        assert worker not in RemotePanel._orphaned_launch_workers
        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        assert len(adb_close_calls) == 1
        assert remote._process is None
        assert remote._launch_worker is None
        assert remote._remote_executor is None
        assert remote._active_device is None
        assert panel._responsive_coordinator.target_count == count_before - len(bindings)
        assert all(binding.widgets() == () for binding in bindings)
        assert panel._responsive_coordinator.diagnostics.fallback_reason is None
        assert destroyed.count() == 1
        assert post_delete_context_calls == []
    finally:
        _close_feature_panel(panel)


def _expected_grid_placement(index: int, item_count: int, columns: int, span_tail: bool):
    """按 responsive_layout._generated_placements 的 row-major/span-tail 规则推导位置。"""

    if not span_tail or item_count == 0 or item_count % columns == 0:
        return (index // columns, index % columns, 1, 1)
    tail_count = item_count % columns
    full_count = item_count - tail_count
    if index < full_count:
        return (index // columns, index % columns, 1, 1)
    tail_row = full_count // columns
    base_span, extra = divmod(columns, tail_count)
    tail_index = index - full_count
    column = 0
    for prior in range(tail_index):
        column += base_span + (1 if prior < extra else 0)
    span = base_span + (1 if tail_index < extra else 0)
    return (tail_row, column, 1, span)


def test_remote_control_real_viewport_scan_observes_only_four_and_two_columns(
    qt_application,
    monkeypatch,
):
    """Remote 三组控制只由真实 applied plan 与 Qt 网格证明可达的四列/两列。"""

    panel, remote, scroll, content = _show_feature_panel(
        "remote",
        292,
        12,
        qt_application,
        monkeypatch,
    )
    observed = {id(binding): set() for binding in remote.remote_control_bindings}
    try:
        for width in range(180, 901, 8):
            _resize_feature_viewport(qt_application, panel, remote, scroll, width)
            for binding in remote.remote_control_bindings:
                plan = binding.applied_plan
                assert plan is not None
                columns = plan.mode.columns
                assert columns in {2, 4}
                observed[id(binding)].add(columns)

                widgets = binding.widgets()
                assert widgets
                layout = widgets[0].parentWidget().layout()
                assert isinstance(layout, QGridLayout)
                assert layout.columnCount() <= 4
                span_tail = bool(getattr(plan.mode, "span_tail", False))
                for index, widget in enumerate(widgets):
                    item_index = layout.indexOf(widget)
                    assert item_index >= 0
                    row, column, row_span, column_span = layout.getItemPosition(item_index)
                    assert (row, column, row_span, column_span) == _expected_grid_placement(
                        index, len(widgets), columns, span_tail
                    )
                    assert_positive_geometry(widget, content)
                assert_non_overlapping(widgets, content)

        assert all(columns == {2, 4} for columns in observed.values())
    finally:
        _close_feature_panel(panel)


def test_remote_reflow_preserves_session_values_identity_and_single_action(
    qt_application,
    monkeypatch,
):
    """Remote 292→900→292 只移动既有控件，不改变完整配置与会话状态。"""

    panel, remote, scroll, _content = _show_feature_panel(
        "remote",
        292,
        18,
        qt_application,
        monkeypatch,
    )
    try:
        current_device = "current-device"
        active_device = "session-device"
        monkeypatch.setattr(
            type(panel._devices_tab),
            "selected_devices",
            property(lambda _manager: [current_device]),
        )
        session_config = object()
        process = object()
        remote._active_device = active_device
        remote._session_config = session_config
        remote._process = process
        remote._record_path = "C:/captures/session-device.mp4"
        remote._allocated_record_paths = {"c:/captures/session-device.mp4"}
        was_loading = remote._loading
        remote._loading = True
        try:
            remote.preset.setCurrentIndex(2)
            for combo, text in (
                (remote.maxsize, "1920"),
                (remote.fps, "120"),
                (remote.codec, "av1"),
                (remote.buffer, "150"),
                (remote.bitrate, "24"),
                (remote.orientation, "270"),
            ):
                combo.setCurrentText(text)
            for checkbox, checked in (
                (remote.chk_record, True),
                (remote.chk_fullscreen, True),
                (remote.chk_aot, False),
                (remote.chk_showtouches, True),
                (remote.chk_stayawake, False),
                (remote.chk_turnscreenoff, True),
                (remote.chk_hw_encoder, True),
                (remote.chk_noplayback, False),
                (remote.chk_noaudio, True),
            ):
                checkbox.setChecked(checked)
        finally:
            remote._loading = was_loading
        remote.record_path.setText("C:/captures/session-device.mp4")
        remote.record_path.setToolTip("C:/captures/session-device.mp4")

        configuration_controls = remote._startup_configuration_controls()
        binding_widgets = tuple(
            widget for binding in remote._responsive_rows for widget in binding.widgets()
        )

        def snapshot():
            return {
                "configuration_identity": tuple(id(control) for control in configuration_controls),
                "binding_identity": tuple(id(widget) for widget in binding_widgets),
                "binding_parents": tuple(id(widget.parentWidget()) for widget in binding_widgets),
                "binding_state": _binding_widget_state(remote),
                "combo_values": tuple(
                    (combo.currentIndex(), combo.currentText())
                    for combo in (
                        remote.preset,
                        remote.maxsize,
                        remote.fps,
                        remote.codec,
                        remote.buffer,
                        remote.bitrate,
                        remote.orientation,
                    )
                ),
                "checks": tuple(
                    (checkbox.isChecked(), checkbox.checkState())
                    for checkbox in (
                        remote.chk_record,
                        remote.chk_fullscreen,
                        remote.chk_aot,
                        remote.chk_showtouches,
                        remote.chk_stayawake,
                        remote.chk_turnscreenoff,
                        remote.chk_hw_encoder,
                        remote.chk_noplayback,
                        remote.chk_noaudio,
                    )
                ),
                "record": (
                    remote._record_path,
                    remote.record_path.text(),
                    remote.record_path.toolTip(),
                    frozenset(remote._allocated_record_paths),
                ),
                "session": (
                    remote._active_device,
                    remote._session_config,
                    remote._session_state,
                    remote._running,
                    remote._process,
                    remote._process_key,
                ),
                "queue": (
                    remote._remote_submitted,
                    remote._remote_completed,
                    remote._remote_sent,
                    remote._remote_failed,
                ),
                "enabled": tuple(
                    control.isEnabled()
                    for control in (
                        remote.btn_start,
                        remote.btn_stop,
                        *configuration_controls,
                        *remote._remote_control_buttons,
                    )
                ),
                "tooltip": tuple(control.toolTip() for control in configuration_controls),
            }

        for state in (
            RemotePanel._SESSION_IDLE,
            RemotePanel._SESSION_STARTING,
            RemotePanel._SESSION_RUNNING,
            RemotePanel._SESSION_STOPPING,
        ):
            remote._set_session_state(state)
            before = snapshot()
            _resize_feature_viewport(qt_application, panel, remote, scroll, 900)
            _resize_feature_viewport(qt_application, panel, remote, scroll, 292)
            after = snapshot()
            assert after == before
            assert remote._session_config is session_config
            assert remote._process is process
        assert remote.parameter_binding.applied_plan.mode.name in {"one", "two", "three"}
        status_plan = remote.status_binding.applied_plan
        assert status_plan is not None and status_plan.mode.name == "one"
        assert len({placement.row for placement in status_plan.placements}) == 9
    finally:
        _close_feature_panel(panel)


def test_remote_preset_status_queue_align_with_mirroring_options(
    qt_application,
    monkeypatch,
):
    """Preset/Status/Queue 与下方参数选项共享列边界，不会出现组间错位。"""

    panel, remote, scroll, _content = _show_feature_panel(
        "remote",
        292,
        12,
        qt_application,
        monkeypatch,
    )
    try:
        widgets = remote.mirroring_binding.widgets()
        assert len(widgets) == 16
        preset_label, preset, size_label, size = widgets[0], widgets[1], widgets[2], widgets[3]
        status, queue, fps_label, codec_label = (
            widgets[14],
            widgets[15],
            widgets[4],
            widgets[6],
        )
        assert status.wordWrap() is False
        assert queue.wordWrap() is False
        for width in (292, 420, 700):
            _resize_feature_viewport(qt_application, panel, remote, scroll, width)
            assert preset_label.geometry().x() == size_label.geometry().x()
            assert preset_label.geometry().width() == size_label.geometry().width()
            assert preset.geometry().x() == size.geometry().x()
            assert preset.geometry().width() == size.geometry().width()
            assert status.geometry().x() == fps_label.geometry().x()
            assert queue.geometry().x() == codec_label.geometry().x()
            if width == 700:
                assert preset_label.geometry().center().y() == status.geometry().center().y()
                assert status.geometry().center().y() == queue.geometry().center().y()
                plan = remote.mirroring_binding.applied_plan
                assert plan is not None and plan.mode.name == "three"
                assert len({placement.row for placement in plan.placements}) == 3
    finally:
        _close_feature_panel(panel)

def test_remote_key_and_action_each_submit_once_after_real_reflow(
    qt_application,
    monkeypatch,
):
    """真实 Remote 按钮连接在往返重排后仍保持一次点击一次 executor 提交。"""

    class InlineExecutor:
        def __init__(self):
            self.tasks = []
            self.shutdown_calls = []

        def submit(self, task):
            self.tasks.append(task)
            task()
            return Mock()

        def shutdown(self, **kwargs):
            self.shutdown_calls.append(kwargs)

    panel, remote, scroll, _content = _show_feature_panel(
        "remote",
        292,
        12,
        qt_application,
        monkeypatch,
    )
    try:
        device = "selected-device"
        monkeypatch.setattr(
            type(panel._devices_tab),
            "selected_devices",
            property(lambda _manager: [device]),
        )
        _resize_feature_viewport(qt_application, panel, remote, scroll, 900)
        _resize_feature_viewport(qt_application, panel, remote, scroll, 292)
        remote._set_session_state(RemotePanel._SESSION_IDLE)

        original_executor = remote._remote_executor
        original_executor.shutdown(wait=False, cancel_futures=True)
        executor = InlineExecutor()
        remote._remote_executor = executor
        remote._remote_control = Mock()
        remote._remote_control.send_keyevent.return_value = True
        remote._remote_control.perform_action.return_value = True

        key_button = next(
            button
            for binding in remote.remote_control_bindings
            for button in binding.widgets()
            if button.property("remoteKey") == "HOME"
        )
        action_button = next(
            button
            for binding in remote.remote_control_bindings
            for button in binding.widgets()
            if button.property("remoteAction") == "swipe_up"
        )
        assert key_button.isEnabled() and action_button.isEnabled()

        key_button.click()
        action_button.click()
        qt_application.processEvents()

        assert len(executor.tasks) == 2
        remote._remote_control.send_keyevent.assert_called_once_with(device, "HOME")
        remote._remote_control.perform_action.assert_called_once_with(device, "swipe_up")
        assert (
            remote._remote_submitted,
            remote._remote_completed,
            remote._remote_sent,
            remote._remote_failed,
        ) == (2, 2, 2, 0)
    finally:
        _close_feature_panel(panel)


def test_apps_real_reflow_preserves_all_binding_state_batches_and_one_signal(
    qt_application,
    monkeypatch,
):
    """Apps 真实窄宽往返保持全部绑定控件、validator 与录屏/Monkey 批次。"""

    panel, apps, scroll, _content = _show_feature_panel(
        "apps",
        292,
        12,
        qt_application,
        monkeypatch,
    )
    try:
        devices = ["device-a", "device-b"]
        monkeypatch.setattr(
            type(panel._devices_tab),
            "selected_devices",
            property(lambda _manager: devices),
        )
        apps.email_text_sender.setText("verification 123456")
        apps.record_duration.setCurrentText("120s")
        apps.program_edit.setCurrentText("com.example.contract")
        apps.monkey_events.setCurrentText("500000")
        apps.monkey_throttle.setCurrentText("2000")
        percentages = (40, 20, 10, 10, 5, 5, 5, 0, 5)
        for combo, value in zip(apps._monkey_pct_combos.values(), percentages):
            combo.setCurrentText(str(value))
        for checkbox, checked in (
            (apps.monkey_chk_crashes, True),
            (apps.monkey_chk_timeouts, False),
            (apps.monkey_chk_security, True),
        ):
            checkbox.setChecked(checked)

        apps._screenshot_running = True
        apps._recording_running = True
        apps._recording_active_devices = tuple(devices)
        apps._recording_pending_count = 1
        apps._recording_pending_devices = {devices[1]}
        apps._recording_batch_id = "record-batch"
        apps._recording_stopping = True
        apps._monkey_running = True
        apps._monkey_active_devices = tuple(devices)
        apps._monkey_pending_count = 1
        apps._monkey_pending_devices = {devices[0]}
        apps._monkey_batch_id = "monkey-batch"
        apps._monkey_stopping = True
        apps._update_action_states()

        assert _validator_signature(apps.monkey_events)[2:] == (1, 1_000_000)
        assert _validator_signature(apps.monkey_throttle)[2:] == (0, 60_000)
        assert all(
            _validator_signature(combo)[2:] == (0, 100)
            for combo in apps._monkey_pct_combos.values()
        )

        def batch_state():
            return (
                apps._screenshot_running,
                apps._recording_running,
                apps._recording_active_devices,
                apps._recording_pending_count,
                frozenset(apps._recording_pending_devices),
                apps._recording_batch_id,
                apps._recording_stopping,
                apps._monkey_running,
                apps._monkey_active_devices,
                apps._monkey_pending_count,
                frozenset(apps._monkey_pending_devices),
                apps._monkey_batch_id,
                apps._monkey_stopping,
            )

        before_widgets = _binding_widget_state(apps)
        before_batches = batch_state()
        _resize_feature_viewport(qt_application, panel, apps, scroll, 900)
        _resize_feature_viewport(qt_application, panel, apps, scroll, 292)
        assert _binding_widget_state(apps) == before_widgets
        assert batch_state() == before_batches

        uninstall_spy = QSignalSpy(panel.signals.uninstall_app_requested)
        apps.uninstall_btn.click()
        assert uninstall_spy.count() == 1
        assert list(uninstall_spy.at(0)) == [devices, "com.example.contract"]
    finally:
        _close_feature_panel(panel)


def test_system_real_reflow_preserves_all_binding_state_validators_and_one_signal(
    qt_application,
    monkeypatch,
):
    """System 真实窄宽往返保持字段、动态 validator、原子组及一次业务信号。"""

    panel, system, scroll, _content = _show_feature_panel(
        "system",
        292,
        12,
        qt_application,
        monkeypatch,
    )
    try:
        devices = ["device-system"]
        monkeypatch.setattr(
            type(panel._devices_tab),
            "selected_devices",
            property(lambda _manager: devices),
        )
        for field, text in (
            (system.shell_cmd_input, "echo responsive-contract"),
            (system.tcpip_port_input, "45678"),
            (system.broadcast_action, "com.example.CONTRACT"),
            (system.activity_spec, "com.example/.MainActivity"),
            (system.deep_link_uri, "https://example.test/contract/path?value=long"),
            (system.fwd_local, "12345"),
            (system.fwd_remote, "23456"),
            (system.settings_key, "animator_duration_scale"),
            (system.settings_val, "0.5"),
            (system.content_uri, "content://settings/system"),
            (system.kill_pid_input, "2147483647"),
            (system.ime_id_input, "com.example/.InputMethod"),
            (system.emu_sms_sender, "+8613800000000"),
            (system.emu_sms_text, "contract message"),
            (system.emu_call_num, "+8613900000000"),
            (system.emu_geo_lon, "179.25"),
            (system.emu_geo_lat, "-89.75"),
        ):
            field.setText(text)
        system.reboot_mode_combo.setCurrentText("Recovery")
        system.settings_ns.setCurrentText("secure")
        system.dumpsys_combo.setCurrentText("notification")
        system.quick_setting_combo.setCurrentIndex(2)
        system.battery_param.setCurrentText("status")
        system.battery_val.setText("4")
        system._update_action_states()

        assert _validator_signature(system.tcpip_port_input)[2:] == (1, 65535)
        assert _validator_signature(system.fwd_local)[2:] == (1, 65535)
        assert _validator_signature(system.fwd_remote)[2:] == (1, 65535)
        assert _validator_signature(system.kill_pid_input)[2:] == (1, 2_147_483_647)
        assert _validator_signature(system.battery_val)[2:] == (1, 5)
        assert _validator_signature(system.emu_geo_lon)[2:5] == (-180.0, 180.0, 6)
        assert _validator_signature(system.emu_geo_lat)[2:5] == (-90.0, 90.0, 6)
        assert _validator_signature(system.deep_link_uri)[2] == r"https?://\S+"
        assert system.battery_label.buddy() is system.battery_val
        assert system.emu_label.buddy() is system.emu_sms_sender

        explicit_fields = (
            system.battery_val,
            system.emu_sms_sender,
            system.shell_cmd_input,
            system.tcpip_port_input,
            system.broadcast_action,
            system.activity_spec,
            system.deep_link_uri,
            system.fwd_local,
            system.fwd_remote,
            system.settings_key,
            system.settings_val,
            system.content_uri,
            system.kill_pid_input,
            system.dumpsys_combo,
            system.ime_id_input,
            system.emu_sms_text,
            system.emu_call_num,
            system.emu_geo_lon,
            system.emu_geo_lat,
        )

        def explicit_state():
            return tuple(
                (
                    id(field),
                    id(field.parentWidget()),
                    field.currentText() if isinstance(field, QComboBox) else field.text(),
                    field.isEnabled(),
                    _validator_signature(field),
                )
                for field in explicit_fields
            )

        before_widgets = _binding_widget_state(system)
        before_fields = explicit_state()
        _resize_feature_viewport(qt_application, panel, system, scroll, 900)
        _resize_feature_viewport(qt_application, panel, system, scroll, 292)
        assert _binding_widget_state(system) == before_widgets
        assert explicit_state() == before_fields
        assert system.battery_label.buddy() is system.battery_val
        assert system.emu_label.buddy() is system.emu_sms_sender

        battery_spy = QSignalSpy(panel.signals.battery_set_requested)
        system.btn_battery_set.click()
        assert battery_spy.count() == 1
        assert list(battery_spy.at(0)) == [devices, "status", "4"]
    finally:
        _close_feature_panel(panel)


def test_app_panel_actions_follow_device_and_package_context():
    settings = Mock()
    settings.get.return_value = {}
    side_panel = _side_panel()
    panel = AppPanel(side_panel)

    with patch("core.settings_manager.AppSettings.instance", return_value=settings):
        widget = panel.build_ui()

    try:
        assert not panel.btn_get_program.isEnabled()
        assert not panel.uninstall_btn.isEnabled()

        side_panel.selected_devices = ["device-1"]
        panel._update_action_states()
        assert panel.btn_get_program.isEnabled()
        assert not panel.uninstall_btn.isEnabled()

        panel.program_edit.setCurrentText("com.example.demo")
        assert panel.uninstall_btn.isEnabled()
        assert panel.start_monkey_btn.isEnabled()

        side_panel.selected_devices = []
        panel._update_action_states()
        assert not panel.uninstall_btn.isEnabled()
        assert not panel.btn_screenshot.isEnabled()
    finally:
        widget.close()
        panel.close()


def test_side_panel_routes_splitter_width_changes_only_through_coordinator(qt_application):
    panel = SidePanel()
    panel._devices_tab.apply_responsive_width = Mock()
    panel._apps_tab.apply_responsive_width = Mock()
    panel.request_responsive_reflow = Mock()
    try:
        panel.apply_responsive_widths(330, 700)

        panel._devices_tab.apply_responsive_width.assert_not_called()
        panel.request_responsive_reflow.assert_called_once_with(ReflowReason.RESIZE)
        panel._apps_tab.apply_responsive_width.assert_not_called()
    finally:
        panel.close()


def test_device_width_scan_only_reflows_for_fitting_columns_or_spacing(qt_application):
    """正反扫描只采用可容纳的列/间距，且高度变化不改变水平计划。"""

    with patch(
        "gui.panels.device_manager.DeviceStore.get_basic_devices_info",
        return_value=[("Google", "Pixel", "192.0.2.10:5555")],
    ):
        panel = SidePanel()
    manager = panel._devices_tab
    device_widget = panel.device_widget
    try:
        font = QFont("Arial", 10)
        manager.ip_entry.setFont(font)
        for button in manager._device_action_buttons:
            button.setFont(font)
        manager._sync_device_control_heights()
        widths = tuple(range(320, 1201, 40))

        def scan(width: int) -> tuple[object, ...]:
            actual_width = _show_device_layout(device_widget, manager, width, qt_application)
            assert actual_width == width
            plan = manager.action_binding.applied_plan
            assert plan is not None and not plan.overflow_required
            assert plan.required_width <= plan.available_width
            assert plan.mode.columns in (1, 2)
            assert plan.spacing in (2, 4, 6)
            assert device_widget.findChildren(QScrollArea) == []
            assert_non_overlapping(manager._device_action_buttons, manager._device_action_frame)
            for button in manager._device_action_buttons:
                assert_contained(button, manager._device_action_frame)
                assert button.width() >= button.minimumSizeHint().width()
                assert button.height() >= button.minimumSizeHint().height()

            positions = tuple(
                _grid_item_position(manager._device_actions_layout, button)
                for button in manager._device_action_buttons
            )
            horizontal_state = (
                manager._device_layout_mode,
                manager._device_body_mode,
                plan.mode.columns,
                plan.spacing,
                positions,
            )
            _show_device_geometry(
                device_widget,
                manager,
                width,
                device_widget.minimumSizeHint().height(),
                qt_application,
            )
            height_plan = manager.action_binding.applied_plan
            assert height_plan is not None
            assert (
                manager._device_layout_mode,
                manager._device_body_mode,
                height_plan.mode.columns,
                height_plan.spacing,
                tuple(
                    _grid_item_position(manager._device_actions_layout, button)
                    for button in manager._device_action_buttons
                ),
            ) == horizontal_state
            return horizontal_state

        forward = {width: scan(width) for width in widths}
        reverse = {width: scan(width) for width in reversed(widths)}
        assert reverse == forward
        assert {state[2] for state in forward.values()} == {1, 2}
        assert len({state[3] for state in forward.values()}) >= 2

        states = tuple(forward[width] for width in widths)
        for previous, current in zip(states, states[1:]):
            if previous[-1] != current[-1]:
                assert previous[:3] != current[:3]
    finally:
        _close_device_test_ui(panel)


def test_device_wide_action_rows_keep_declared_gap_and_leave_extra_height_below(
    qt_application,
    monkeypatch,
):
    """宽布局的多余高度不得被 QGridLayout 摊成逐渐变大的按钮间隙。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Arial", size or 10)),
    )
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    widget = panel._device_widget
    try:
        _compact_limit, wide_limit = manager._device_layout_limits()
        _show_device_geometry(widget, manager, wide_limit + 160, 700, qt_application)
        manager._device_actions_layout.activate()
        qt_application.processEvents()
        wait_for_stable_geometry(
            qt_application,
            manager._device_action_buttons,
        )

        plan = manager.action_binding.applied_plan
        assert plan is not None
        row_bounds: dict[int, tuple[int, int]] = {}
        for button in manager._device_action_buttons:
            row, _column, _row_span, _column_span = _grid_item_position(
                manager._device_actions_layout,
                button,
            )
            top, bottom = row_bounds.get(row, (button.geometry().top(), button.geometry().bottom()))
            row_bounds[row] = (
                min(top, button.geometry().top()),
                max(bottom, button.geometry().bottom()),
            )

        ordered_bounds = tuple(row_bounds[row] for row in sorted(row_bounds))
        gaps = tuple(
            following[0] - current[1] - 1
            for current, following in zip(ordered_bounds, ordered_bounds[1:])
        )
        assert gaps
        assert set(gaps) == {plan.spacing}, tuple(
            (button.text(), button.geometry().getRect())
            for button in manager._device_action_buttons
        )
        assert manager._device_action_frame.height() > ordered_bounds[-1][1] + 1
    finally:
        _close_device_test_ui(panel)


def test_stacked_connect_width_scan_uses_only_supported_geometry(qt_application):
    """扫描真实可用宽度，验证 stacked 连接区不依赖生产断点常量。"""

    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    widget = panel._device_widget
    try:
        widget.resize(640, 500)
        widget.show()
        qt_application.processEvents()
        observed_modes = set()
        for width in range(320, 1001, 20):
            actual_width = _show_device_layout(widget, manager, width, qt_application)
            if manager._device_body_mode != "stacked":
                continue

            plan = manager.action_binding.applied_plan
            assert plan is not None
            assert not plan.overflow_required
            assert plan.required_width <= plan.available_width
            assert widget.findChildren(QScrollArea) == []

            available = manager._connect_layout.geometry()
            connect = manager.btn_connect_devices.geometry()
            assert manager.ip_entry.geometry().left() == available.left()
            assert manager.ip_entry.geometry().right() == available.right()
            assert available.contains(connect)
            assert manager.btn_connect_devices.size().width() >= (
                manager.btn_connect_devices.minimumSizeHint().width()
            )
            assert manager.btn_connect_devices.size().height() >= (
                manager.btn_connect_devices.minimumSizeHint().height()
            )

            mode = manager._device_layout_mode
            observed_modes.add(mode)
            if mode == "compact":
                assert connect.left() == available.left()
                assert connect.right() == available.right()
            elif mode == "medium":
                assert connect.right() == available.right()
                assert manager.btn_connect_devices.width() == (
                    manager.btn_connect_devices.minimumWidth()
                )

            horizontal_state = (
                mode,
                manager._device_body_mode,
                _grid_item_position(manager._connect_layout, manager.ip_entry),
                _grid_item_position(
                    manager._connect_layout,
                    manager.btn_connect_devices,
                ),
            )
            _show_device_geometry(
                widget,
                manager,
                actual_width,
                widget.minimumSizeHint().height(),
                qt_application,
            )
            assert (
                manager._device_layout_mode,
                manager._device_body_mode,
                _grid_item_position(manager._connect_layout, manager.ip_entry),
                _grid_item_position(
                    manager._connect_layout,
                    manager.btn_connect_devices,
                ),
            ) == horizontal_state

        assert observed_modes == {"compact", "medium"}
    finally:
        _close_device_test_ui(panel)


def test_device_address_popups_follow_the_shrinkable_input_width(qt_application):
    """长 IPv6 地址不得撑宽父布局，两个地址弹窗必须随输入框同步收缩。"""

    with patch(
        "gui.panels.device_manager.DeviceStore.get_basic_devices_info",
        return_value=[("Google", "Pixel", "2001:db8:ffff:ffff:ffff:ffff:ffff:1:5555")],
    ):
        panel = SidePanel()
    manager = panel._devices_tab
    widget = panel._device_widget
    try:
        widget.resize(300, 500)
        widget.show()
        manager.apply_responsive_width(300)
        qt_application.processEvents()
        minimum_width_before = widget.minimumSizeHint().width()
        actual_width_before = widget.width()

        manager.ip_entry.setCurrentText("2001:db8:ffff:ffff:ffff:ffff:ffff:1:5555")
        qt_application.processEvents()
        assert (
            manager.ip_entry.sizePolicy().horizontalPolicy()
            == manager.ip_entry.sizePolicy().Policy.Ignored
        )
        assert widget.minimumSizeHint().width() == minimum_width_before
        assert widget.width() == actual_width_before

        manager.ip_entry.showPopup()
        qt_application.processEvents()
        assert manager.ip_entry.view().width() == manager.ip_entry.width()

        widget.resize(420, 500)
        qt_application.processEvents()
        manager.ip_entry.showPopup()
        qt_application.processEvents()
        assert manager.ip_entry.view().width() == manager.ip_entry.width()

        completer = manager.ip_entry.completer()
        assert completer is not None
        manager.ip_entry.lineEdit().setText("2001:db8")
        completer.complete()
        qt_application.processEvents()
        assert completer.popup().width() == manager.ip_entry.width()
    finally:
        _close_device_test_ui(panel)


def test_replaced_address_completer_syncs_its_popup_without_a_resize(qt_application):
    """历史地址刷新后，直接显示的新补全弹窗仍必须等宽于稳定的输入框。"""

    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    widget = panel._device_widget
    try:
        widget.resize(300, 500)
        widget.show()
        manager.apply_responsive_width(300)
        qt_application.processEvents()

        with patch(
            "gui.panels.device_manager.DeviceStore.get_basic_devices_info",
            return_value=[("Google", "Pixel", "2001:db8:ffff:ffff:ffff:ffff:ffff:1:5555")],
        ):
            manager._refresh_device_combobox()

        completer = manager.ip_entry.completer()
        assert completer is not None
        assert completer.popup().minimumWidth() == manager.ip_entry.width()
        manager.ip_entry.showPopup()
        qt_application.processEvents()
        assert manager.ip_entry.view().width() == manager.ip_entry.width()
        manager.ip_entry.lineEdit().setText("2001:db8")
        completer.complete()
        qt_application.processEvents()
        assert completer.popup().width() == manager.ip_entry.width()
        assert manager.ip_entry.view().minimumWidth() != 380
    finally:
        _close_device_test_ui(panel)


def _show_device_layout(widget, manager, requested_width: int, qt_application) -> int:
    """按 Qt 实际视觉根宽度请求一代重排，并等待协调器与子控件几何稳定。"""

    panel = manager.panel
    wait_until(
        qt_application,
        lambda: panel._responsive_coordinator.diagnostics.stable,
    )
    widget.resize(requested_width, 700)
    widget.show()
    wait_until(qt_application, lambda: widget.width() == requested_width)
    actual_width = widget.width()
    before = panel._responsive_coordinator.diagnostics.generation
    manager.apply_responsive_width(actual_width)
    wait_until(
        qt_application,
        lambda: (
            panel._responsive_coordinator.diagnostics.stable
            and panel._responsive_coordinator.diagnostics.generation > before
        ),
    )
    wait_for_stable_geometry(
        qt_application,
        (
            widget,
            manager.ip_entry,
            manager.btn_connect_devices,
            manager.listbox_devices,
            manager._device_action_frame,
            *manager._device_action_buttons,
        ),
    )
    return actual_width


def _device_boundary_oracle(widget, manager, qt_application):
    """仅从测试侧 Qt 度量推导 Devices 三态断点，不读取生产断点实现。"""

    seed_width = 300
    _show_device_layout(widget, manager, seed_width, qt_application)
    action_margins = manager._device_actions_layout.contentsMargins()
    action_spacing = max(0, manager._device_actions_layout.horizontalSpacing())
    minimum_widths = tuple(
        max(
            button.minimumWidth(),
            button.minimumSizeHint().width(),
        )
        for button in manager._device_action_buttons
    )
    action_cell_width = max(minimum_widths)
    one_column_width = action_cell_width + action_margins.left() + action_margins.right()
    two_column_width = (
        action_cell_width * 2 + action_spacing + action_margins.left() + action_margins.right()
    )

    group_option = QStyleOptionGroupBox()
    manager._device_group.initStyleOption(group_option)
    group_contents = manager._device_group.style().subControlRect(
        QStyle.ComplexControl.CC_GroupBox,
        group_option,
        QStyle.SubControl.SC_GroupBoxContents,
        manager._device_group,
    )
    group_outer = manager._device_group.rect()
    group_style_insets = (
        group_contents.left() - group_outer.left() + group_outer.right() - group_contents.right()
    )
    root_margins = widget.layout().contentsMargins()
    group_layout_margins = manager._device_group.layout().contentsMargins()
    body_margins = manager._device_body_layout.contentsMargins()
    outer_insets = sum(
        (
            root_margins.left(),
            root_margins.right(),
            group_style_insets,
            group_layout_margins.left(),
            group_layout_margins.right(),
            body_margins.left(),
            body_margins.right(),
        )
    )
    compact_limit = outer_insets + two_column_width

    # wide 使用 3:1 主体列；独立 QGrid 探针求出右侧动作单元首次可容纳的主体宽度。
    body_spacing = max(0, manager._device_body_layout.horizontalSpacing())
    probe_host = QWidget()
    probe_layout = QGridLayout(probe_host)
    probe_layout.setContentsMargins(0, 0, 0, 0)
    probe_layout.setHorizontalSpacing(body_spacing)
    probe_left = QWidget(probe_host)
    probe_right = QWidget(probe_host)
    probe_left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    probe_right.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    probe_layout.addWidget(probe_left, 0, 0)
    probe_layout.addWidget(probe_right, 0, 1)
    probe_layout.setColumnStretch(0, 3)
    probe_layout.setColumnStretch(1, 1)
    try:
        body_width = one_column_width
        while body_width <= one_column_width * 4 + body_spacing:
            probe_layout.setGeometry(QRect(0, 0, body_width, 40))
            if probe_right.width() >= one_column_width:
                break
            body_width += 1
        else:
            raise AssertionError("3:1 probe did not find a fitting action column")
    finally:
        probe_host.close()
    wide_limit = outer_insets + body_width
    return (
        compact_limit,
        wide_limit,
        {
            "one": one_column_width,
            "two": two_column_width,
            "wide_body": body_width,
        },
    )


def _assert_near(left: int, right: int) -> None:
    """允许 Qt 栅格在高 DPI 下出现一像素的舍入差。"""

    assert abs(left - right) <= 1


def _show_device_height(widget, manager, requested_height: int, qt_application):
    """直接请求设备根高度，等待新代次稳定并拒绝 Qt 静默夹紧。"""

    return _show_device_geometry(
        widget,
        manager,
        300,
        requested_height,
        qt_application,
    )


def _show_device_geometry(widget, manager, width: int, height: int, qt_application):
    """直接请求 Devices 根尺寸，等待新代次稳定并拒绝 Qt 静默夹紧。

    期望高度取请求值与重排后最小高度提示的较大者：apply_responsive_width 可能把按钮
    换行使最小高度上浮（如 760px 时 256→272），Qt 依契约夹紧到新最小值，不算静默夹紧。
    """

    panel = manager.panel
    wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
    before = panel._responsive_coordinator.diagnostics.generation
    widget.resize(width, height)
    manager.apply_responsive_width(width)
    wait_until(
        qt_application,
        lambda: (
            panel._responsive_coordinator.diagnostics.stable
            and panel._responsive_coordinator.diagnostics.generation > before
        ),
    )
    wait_for_stable_geometry(
        qt_application,
        (
            widget,
            manager.ip_entry,
            manager.btn_connect_devices,
            manager.listbox_devices,
            manager.listbox_devices.viewport(),
            manager._device_action_frame,
            *manager._device_action_buttons,
        ),
    )
    diagnostics = panel._responsive_coordinator.diagnostics
    expected_height = max(height, widget.minimumSizeHint().height())
    assert widget.contentsRect().size() == QSize(width, expected_height), (
        (width, height),
        widget.contentsRect().size(),
        widget.minimumSizeHint(),
        diagnostics,
    )
    return diagnostics


def _assert_device_list_endpoints(qt_application, manager) -> None:
    """验证长设备行纵向完整，且横向滚动首尾与 viewport 对齐。"""

    device_list = manager.listbox_devices
    item = device_list.item(0)
    assert item is not None
    row_height = device_list.sizeHintForRow(0)
    viewport = device_list.viewport()
    assert viewport.height() >= row_height
    item_rect = device_list.visualItemRect(item)
    assert item_rect.top() >= viewport.rect().top()
    assert item_rect.bottom() <= viewport.rect().bottom()

    horizontal = device_list.horizontalScrollBar()
    assert horizontal.maximum() > horizontal.minimum()
    horizontal.setValue(horizontal.minimum())
    qt_application.processEvents()
    assert abs(device_list.visualItemRect(item).left()) <= 1
    horizontal.setValue(horizontal.maximum())
    qt_application.processEvents()
    assert abs(device_list.visualItemRect(item).right() - viewport.rect().right()) <= 1


@pytest.mark.parametrize(
    ("mode", "medium_offset"),
    (("compact", 0), ("medium", 1), ("medium", 17), ("medium", 40), ("wide", 0)),
)
def test_device_manager_keeps_connection_and_device_columns_aligned_after_show(
    qt_application, mode, medium_offset
):
    """连接区必须在三态中复用设备主体的实际列宽，而不是只复用排列方向。"""

    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    widget = panel._device_widget
    try:
        compact_limit, wide_limit = manager._device_layout_limits()
        requested_width = {
            "compact": compact_limit - 1,
            "medium": compact_limit + max(8, medium_offset),
            "wide": wide_limit + 120,
        }[mode]
        actual_width = _show_device_layout(widget, manager, requested_width, qt_application)

        # QWidget 可能为 minimumSizeHint() 夹紧请求宽度，断言一律以 Qt 实际几何为准。
        assert manager._device_layout_mode == mode, (actual_width, manager._device_layout_limits())
        if mode == "compact":
            _assert_near(manager.ip_entry.width(), manager.btn_connect_devices.width())
            _assert_near(
                manager.btn_connect_devices.width(),
                manager._device_action_frame.width(),
            )
        elif mode == "medium":
            _assert_near(manager.ip_entry.width(), manager._connect_layout.geometry().width())
            _assert_near(manager.btn_connect_devices.width(), manager.btn_refresh.width())
            assert (
                manager.btn_connect_devices.geometry().right()
                == manager.ip_entry.geometry().right()
            )
        else:
            _assert_near(manager.ip_entry.width(), manager.listbox_devices.width())
            _assert_near(
                manager.btn_connect_devices.width(),
                manager._device_action_frame.width(),
            )
            _assert_near(manager.btn_connect_devices.width(), manager.btn_refresh.width())
        assert widget.findChildren(QScrollArea) == []
        for button in manager._device_action_buttons:
            assert_contained(button, manager._device_action_frame)
    finally:
        _close_device_test_ui(panel)


def test_device_wide_layout_keeps_connect_visually_separate_from_refresh(
    qt_application,
    monkeypatch,
):
    """连接区与动作区不得在宽布局中以零像素间距黏在一起。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Arial", size or 10)),
    )
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    widget = panel._device_widget
    try:
        _compact_limit, wide_limit = manager._device_layout_limits()
        _show_device_layout(widget, manager, wide_limit + 120, qt_application)
        manager._device_actions_layout.activate()
        qt_application.processEvents()

        connect_bottom = (
            manager.btn_connect_devices.mapTo(widget, QPoint(0, 0)).y()
            + manager.btn_connect_devices.height()
        )
        refresh_top = manager.btn_refresh.mapTo(widget, QPoint(0, 0)).y()

        assert manager._device_layout_mode == "wide"
        assert refresh_top - connect_bottom >= 4
    finally:
        _close_device_test_ui(panel)


@pytest.mark.parametrize("mode", ("compact", "wide"))
def test_device_list_and_last_action_keep_bottom_inset_in_every_body_mode(
    qt_application,
    monkeypatch,
    mode,
):
    """设备列表和最后一个动作不得随主体模式切换而贴住分组底边。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Arial", size or 10)),
    )
    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    widget = panel._device_widget
    try:
        compact_limit, wide_limit = manager._device_layout_limits()
        width = compact_limit - 20 if mode == "compact" else wide_limit + 120
        _show_device_layout(widget, manager, width, qt_application)
        manager._device_actions_layout.activate()
        qt_application.processEvents()

        group = manager._device_group
        for target in (manager.listbox_devices, manager.btn_none):
            target_bottom = target.mapTo(group, QPoint(0, 0)).y() + target.height()
            assert group.height() - target_bottom >= 4
    finally:
        _close_device_test_ui(panel)


def test_device_actions_stay_directly_visible_and_long_ip_is_layout_neutral(
    qt_application,
):
    """长 IPv6 不参与断点，动作按钮仍在直接宿主内完整显示。"""

    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    widget = panel.device_widget
    try:
        large_font = QFont("Arial", 22)
        for control in (
            manager.ip_entry,
            manager.btn_connect_devices,
            *manager._device_action_buttons,
        ):
            control.setFont(large_font)
        manager._sync_device_control_heights()
        compact_limit, _wide_limit, action_widths = _device_boundary_oracle(
            widget,
            manager,
            qt_application,
        )
        safe_width = max(300, compact_limit - action_widths["two"] + action_widths["one"])
        _show_device_layout(widget, manager, safe_width, qt_application)
        limits_before = manager._device_layout_limits()
        mode_before = manager._device_layout_mode

        manager.ip_entry.setCurrentText("[2001:db8:ffff:ffff:ffff:ffff:ffff:1]:5555")
        _show_device_layout(widget, manager, safe_width, qt_application)
        assert manager._device_layout_limits() == limits_before
        assert manager._device_layout_mode == mode_before == "compact"

        plan = manager.action_binding.applied_plan
        assert plan is not None and plan.mode.columns == 1
        assert not plan.overflow_required
        assert widget.findChildren(QScrollArea) == []
        assert_non_overlapping(manager._device_action_buttons, manager._device_action_frame)
        for button in manager._device_action_buttons:
            assert_contained(button, manager._device_action_frame)
            assert button.width() >= button.minimumSizeHint().width()
            assert button.height() >= button.minimumSizeHint().height()
    finally:
        _close_device_test_ui(panel)


def test_device_reflow_preserves_objects_state_and_single_signal_delivery(qt_application):
    """窄→宽→窄只移动既有控件，不改业务状态且点击仅发出一次信号。"""

    device = "192.0.2.10:5555"
    info = {
        "Brand": "Google",
        "Model": "Pixel",
        "Aversion": "15",
        "ip": device,
    }
    with (
        patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]),
        patch(
            "gui.panels.device_manager.DeviceStore.get_full_devices_info",
            return_value=[info],
        ),
    ):
        panel = SidePanel()
        panel.update_device_list([device])
    manager = panel._devices_tab
    widget = panel.device_widget
    try:
        manager.listbox_devices.item(0).setCheckState(Qt.Checked)
        manager.ip_entry.setCurrentText(device)
        identities = tuple(id(button) for button in manager._device_action_buttons)
        enabled_states = tuple(button.isEnabled() for button in manager._device_action_buttons)
        connect_spy = QSignalSpy(panel.signals.connect_requested)
        refresh_spy = QSignalSpy(panel.signals.refresh_devices_requested)
        _compact_limit, wide_limit = manager._device_layout_limits()

        for width in (300, wide_limit + 120, 300):
            _show_device_layout(widget, manager, width, qt_application)

        assert tuple(id(button) for button in manager._device_action_buttons) == identities
        assert panel.selected_devices == [device]
        assert manager.ip_entry.currentText() == device
        assert (
            tuple(button.isEnabled() for button in manager._device_action_buttons) == enabled_states
        )

        manager.btn_connect_devices.click()
        manager.btn_refresh.click()
        assert connect_spy.count() == 1
        assert refresh_spy.count() == 1
    finally:
        _close_device_test_ui(panel)


def test_side_panel_width_callback_preserves_device_column_mode_when_only_height_changes(
    qt_application,
):
    """SidePanel 宽度回调应生效，控件仅改变高度时不能改写已计算的列宽状态。"""

    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    widget = panel._device_widget
    try:
        _small_limit, wide_limit = manager._device_layout_limits()
        actual_width = _show_device_layout(widget, manager, wide_limit + 120, qt_application)
        panel.apply_responsive_widths(actual_width, 0)
        qt_application.processEvents()
        mode_before = manager._device_layout_mode
        input_width_before = manager.ip_entry.width()
        connect_width_before = manager.btn_connect_devices.width()

        widget.resize(actual_width, 480)
        qt_application.processEvents()
        panel.apply_responsive_widths(widget.width(), 0)
        qt_application.processEvents()

        assert manager._device_layout_mode == mode_before == "wide"
        _assert_near(manager.ip_entry.width(), input_width_before)
        _assert_near(manager.btn_connect_devices.width(), connect_width_before)
    finally:
        _close_device_test_ui(panel)


@pytest.mark.parametrize("point_size", (0, 22))
def test_device_manager_recalculates_equal_control_heights_for_current_font(
    qt_application, point_size
):
    """地址、Connect 和所有设备动作按钮必须使用同一实际高度。"""

    with patch("gui.panels.device_manager.DeviceStore.get_basic_devices_info", return_value=[]):
        panel = SidePanel()
    manager = panel._devices_tab
    widget = panel._device_widget
    try:
        if point_size:
            font = QFont("Arial", point_size)
            for control in (
                manager.ip_entry,
                manager.btn_connect_devices,
                *manager._device_action_buttons,
            ):
                control.setFont(font)
        _small_limit, wide_limit = manager._device_layout_limits()
        _show_device_layout(widget, manager, wide_limit + 120, qt_application)

        controls = (
            manager.ip_entry,
            manager.btn_connect_devices,
            *manager._device_action_buttons,
        )
        heights = {control.height() for control in controls}
        assert len(heights) == 1
        assert all(control.height() >= control.minimumSizeHint().height() for control in controls)
    finally:
        _close_device_test_ui(panel)
