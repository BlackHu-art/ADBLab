"""验证直接 qfluentwidgets 集成与项目级配置函数。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QBoxLayout
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    HeaderCardWidget,
    ListWidget,
    ProgressBar,
    PushButton,
    RoundMenu,
    SegmentedWidget,
    SmoothScrollArea,
    TableWidget,
    themeColor,
)

from gui.panels.base_panel import BasePanel
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import (
    add_menu_action,
    apply_focus_indicator,
    apply_label_role,
    configure_button,
    configure_fluent_control,
    refresh_fluent_widget_style,
)


def _font_size(font) -> int:
    return font.pointSize() if font.pointSize() > 0 else font.pixelSize()


def test_direct_button_configuration_contract(qt_application):
    button = PushButton()
    configure_button(button, text="执行", tooltip="执行当前操作")

    assert type(button) is PushButton
    assert button.toolTip() == "执行当前操作"
    assert button.property("functionalToolTip") == "执行当前操作"
    assert button.accessibleDescription() == "执行当前操作"

    with pytest.raises(ValueError):
        configure_button(PushButton(), text="无提示", tooltip="")


def test_disabled_danger_button_keeps_readable_text_in_both_themes(qt_application):
    button = PushButton()
    configure_button(button, text="断开", tooltip="断开已选择设备", danger=True)

    assert BaseStyles.color_for("Light", "TEXT_DISABLED") in button.property(
        "lightCustomQss"
    )
    assert BaseStyles.color_for("Dark", "TEXT_DISABLED") in button.property(
        "darkCustomQss"
    )


def test_custom_focus_style_refreshes_after_accent_change(qt_application):
    original = BaseStyles.accent_color()
    target = "#C239B3" if original != "#C239B3" else "#0F6CBD"
    button = PushButton()
    configure_button(button, text="执行", tooltip="执行操作")
    try:
        BaseStyles.set_accent_color(target)
        refresh_fluent_widget_style(button)

        assert target.lower() in str(button.property("lightCustomQss")).lower()
        assert target.lower() in str(button.property("darkCustomQss")).lower()
    finally:
        BaseStyles.set_accent_color(original)
        refresh_fluent_widget_style(button)


def test_direct_controls_receive_semantic_font_roles(qt_application):
    label = apply_label_role(BodyLabel("标题"), FontRole.TITLE, color_key="TITLE_COLOR", bold=True)
    combo = configure_fluent_control(ComboBox(), FontRole.UI)

    expected_title = BaseStyles.font_for_role(FontRole.TITLE)
    assert type(label) is BodyLabel
    assert label.property("fontRole") == FontRole.TITLE.value
    assert _font_size(label.font()) == expected_title.pointSize()
    assert type(combo) is ComboBox
    assert combo.property("fontRole") == FontRole.UI.value


def test_direct_segmented_widget_routes_selection(qt_application):
    segmented = SegmentedWidget()
    segmented.addItem("log", "日志")
    segmented.addItem("chart", "图表")
    segmented.setCurrentItem("log")

    changed = []
    segmented.currentItemChanged.connect(changed.append)
    segmented.items["chart"].click()

    assert segmented.currentRouteKey() == "chart"
    assert changed == ["chart"]


def test_base_panel_card_factory_returns_reference_component(qt_application):
    panel = BasePanel.__new__(BasePanel)
    card = panel._card("测试卡片")

    assert type(card) is HeaderCardWidget
    assert card.title == "测试卡片"
    assert card.accessibleName() == "测试卡片"
    assert card.viewLayout.direction() == QBoxLayout.Direction.TopToBottom


def test_round_menu_uses_qaction_without_menu_wrapper(qt_application):
    menu = RoundMenu("菜单")
    action = add_menu_action(menu, "重命名", data="rename", checkable=True, checked=True)

    assert action.data() == "rename"
    assert action.isChecked()
    assert action in menu.actions()


def test_focus_indicator_is_applied_to_direct_control(qt_application):
    button = PushButton("Focus")
    apply_focus_indicator(button, selector="PushButton")

    assert "PushButton:focus" in button.styleSheet()


def test_reference_components_construct_without_project_wrappers(qt_application):
    progress = ProgressBar()
    progress.setRange(0, 100)
    progress.setValue(25)

    table = TableWidget()
    table.setColumnCount(2)
    listing = ListWidget()
    scroll = SmoothScrollArea()

    assert progress.value() == 25
    assert table.columnCount() == 2
    assert listing.count() == 0
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_accent_color_updates_qfluentwidgets_and_emits_project_signal(qt_application):
    original = BaseStyles.accent_color()
    target = "#C239B3" if original != "#C239B3" else "#0F6CBD"
    spy = QSignalSpy(BaseStyles.accent_color_changed)
    try:
        applied = BaseStyles.set_accent_color(target)

        assert applied == target
        assert themeColor().name().upper() == target
        assert spy.count() == 1
        assert spy.at(0) == [target]
    finally:
        BaseStyles.set_accent_color(original)
