"""验证 Fluent 基础组件库的契约与主题/字体钩子。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit

from gui.styles import BaseStyles, FontRole
from gui.widgets.fluent import (
    Card,
    EmptyState,
    FluentButton,
    FluentComboBox,
    FluentMenu,
    FluentProgressBar,
    FluentSplitter,
    FluentTable,
    FluentTooltip,
    FocusRing,
    IconButton,
    LoadingState,
    SegmentedControl,
    TableRow,
)


def _font_size(font) -> int:
    return font.pointSize() if font.pointSize() > 0 else font.pixelSize()


# ── FluentButton：tooltip 契约、字体角色、主题钩子 ──────────────────────


def test_fluent_button_uses_push_button_style(qt_application):
    normal = FluentButton("确定", tooltip="确认操作")
    # FluentButton 已改用 PushButton 的 FluentStyleSheet（含 PushButton 选择器）。
    assert "PushButton" in normal.styleSheet()


def test_fluent_button_tooltip_contract(qt_application):
    with pytest.raises(ValueError):
        FluentButton("无提示")
    with pytest.raises(ValueError):
        FluentButton("空白提示", tooltip="   ")

    button = FluentButton("执行", tooltip="执行当前操作")
    assert button.toolTip() == "执行当前操作"
    assert button.property("functionalToolTip") == "执行当前操作"
    assert button.accessibleDescription() == "执行当前操作"

    button.set_tooltip("新的功能说明")
    assert button.toolTip() == "新的功能说明"
    with pytest.raises(ValueError):
        button.set_tooltip("   ")


def test_fluent_button_apply_font_role(qt_application):
    button = FluentButton("x", tooltip="x")
    button.apply_font_role(FontRole.UI_SMALL)
    assert button.property("fontRole") == FontRole.UI_SMALL.value
    expected = BaseStyles.font_for_role(FontRole.UI_SMALL)
    assert button.font().family() == expected.family()
    assert _font_size(button.font()) == expected.pointSize()


def test_fluent_button_sync_theme_state_refreshes_icon(qt_application):
    button = FluentButton("保存", tooltip="保存", icon="floppy-disk.svg")
    button._sync_theme_state()
    assert not button.icon().isNull()
    assert button.property("iconName") == "floppy-disk.svg"


# ── IconButton ──────────────────────────────────────────────────────────


def test_icon_button_contract(qt_application):
    button = IconButton("gear.svg", "打开设置")
    assert button.property("functionalToolTip") == "打开设置"
    assert button.property("iconName") == "gear.svg"
    assert button.accessibleName() == "打开设置"
    with pytest.raises(ValueError):
        IconButton("gear.svg", " ")


# ── SegmentedControl：选择信号与 currentData ───────────────────────────


def test_segmented_control_selection_signal(qt_application):
    seg = SegmentedControl()
    seg.set_items(["甲", "乙", "丙"], data=["a", "b", "c"])
    assert seg.count() == 3
    assert seg.current_index() == 0
    assert seg.current_text() == "甲"
    assert seg.current_data() == "a"

    indices = []
    datas = []
    seg.selectionChanged.connect(indices.append)
    seg.currentChanged.connect(datas.append)

    seg.set_current_index(1)
    assert (seg.current_index(), seg.current_text(), seg.current_data()) == (1, "乙", "b")
    assert indices == [1]
    assert datas == ["b"]

    seg.buttons()[2].click()
    assert seg.current_index() == 2
    assert seg.current_data() == "c"
    assert indices == [1, 2]
    assert datas == ["b", "c"]


# ── EmptyState：动作按钮回调 ────────────────────────────────────────────


def test_empty_state_action_button_callback(qt_application):
    calls = []
    empty = EmptyState(icon="warning.svg", title="无设备", description="未找到连接的设备")
    button = empty.set_action("刷新", callback=lambda: calls.append("refresh"))
    assert empty.action_button() is button
    assert button.property("functionalToolTip") == "刷新"

    emitted = []
    empty.actionClicked.connect(lambda: emitted.append("clicked"))
    button.click()
    assert calls == ["refresh"]
    assert emitted == ["clicked"]


# ── FluentTable：行插入与选中 ───────────────────────────────────────────


def test_fluent_table_row_insertion_and_selection(qt_application):
    table = FluentTable(columns=["名称", "状态"])
    first = table.add_row(["设备A", "在线"], data="device-a")
    second = table.insert_row(0, ["设备B", "离线"], data="device-b")
    assert (first, second) == (0, 0)
    assert table.rowCount() == 2
    assert table.row_at(0) == TableRow(("设备B", "离线"), "device-b")
    assert table.row_at(1) == TableRow(("设备A", "在线"), "device-a")

    selected = []
    table.rowSelected.connect(selected.append)
    table.setCurrentCell(0, 0)
    assert table.selected_index() == 0
    assert table.selected_data() == "device-b"
    assert table.selected_row() == TableRow(("设备B", "离线"), "device-b")
    assert selected == [0]


# ── FluentComboBox：editable 变体与 Optional 收窄 ───────────────────────


def test_fluent_combo_box_editable_variant(qt_application):
    combo = FluentComboBox(editable=True)
    assert combo.is_editable()
    editor = combo.line_edit()
    assert editor is not None
    assert editor.property("fontRole") == FontRole.UI.value

    combo.set_items(["一", "二"], data=[1, 2], current_index=1)
    assert combo.currentIndex() == 1
    assert combo.current_data() == 2

    readonly = FluentComboBox()
    assert not readonly.is_editable()
    readonly.set_editable(True)
    assert readonly.is_editable()
    assert readonly.line_edit() is not None


# ── FocusRing：主题钩子与恢复 ──────────────────────────────────────────


def test_focus_ring_sync_theme_state_and_clear(qt_application):
    target = QLineEdit()
    ring = FocusRing(target)
    assert BaseStyles.color("BORDER_FOCUS") in target.styleSheet()
    try:
        BaseStyles.switch_theme("Dark")
        ring._sync_theme_state()
        assert BaseStyles.color("BORDER_FOCUS") in target.styleSheet()
    finally:
        BaseStyles.switch_theme("Light")
    ring.clear()
    assert "border: 2px solid" not in target.styleSheet()


# ── 其余组件：构造、主题钩子与最小公共 API ─────────────────────────────


def test_remaining_components_construct_and_sync(qt_application):
    card = Card("标题", subtitle="副标题")
    card.add_widget(QLabel("内容"))
    card._sync_theme_state()
    assert card.title() == "标题"
    assert card.subtitle() == "副标题"

    loading = LoadingState("加载中")
    assert loading.message() == "加载中"
    assert loading.is_spinning()
    loading.set_spinning(False)
    assert not loading.is_spinning()
    loading._sync_theme_state()

    progress = FluentProgressBar(minimum=0, maximum=50, value=10)
    assert progress.value() == 10
    progress.set_value(25)
    assert progress.value() == 25
    progress.set_range(0, 100)
    assert progress.maximum() == 100
    progress._sync_theme_state()

    menu = FluentMenu("菜单")
    action = menu.add_action("重命名", data="rename")
    assert action.data() == "rename"
    menu._sync_theme_state()

    splitter = FluentSplitter(Qt.Orientation.Vertical)
    assert splitter.orientation() == Qt.Orientation.Vertical
    splitter._sync_theme_state()

    tooltip = FluentTooltip("提示")
    assert tooltip.text() == "提示"
    tooltip.set_text("新提示")
    assert tooltip.text() == "新提示"
    tooltip._sync_theme_state()
