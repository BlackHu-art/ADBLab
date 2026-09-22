"""System 面板分类导航与卡片归属契约。"""

from types import SimpleNamespace

import pytest
from PySide6.QtTest import QSignalSpy

from gui.panels.side_panel_signals import SidePanelSignals
from gui.panels.system_panel import SystemPanel
from gui.styles import BaseStyles, FontRole

pytestmark = pytest.mark.ui


def _build_system_panel():
    owner = SimpleNamespace(
        selected_devices=[],
        signals=SidePanelSignals(),
        _font_sm=BaseStyles.font_for_role(FontRole.UI),
        _font_mono=BaseStyles.font_for_role(FontRole.MONO),
        _font_base=BaseStyles.font_for_role(FontRole.UI),
    )
    panel = SystemPanel(owner)
    widget = panel.build_ui()
    return panel, widget


def test_reverse_clear_describes_full_scope_and_emits_selected_target_snapshot(qt_application):
    panel, widget = _build_system_panel()
    panel.connect_signals()
    selected = ["demo-a", "demo-a", "demo-b"]
    panel.panel.selected_devices = selected
    panel._update_action_states()
    requested = QSignalSpy(panel.signals.remove_reverse_requested)
    try:
        assert panel.btn_remove_rev.text() == "清空反向规则"
        assert panel.btn_remove_rev.toolTip() == "移除所选设备的全部反向转发规则"
        assert panel.btn_remove_rev.accessibleDescription() == panel.btn_remove_rev.toolTip()
        # 端口输入不参与清空操作，目标在点击时复制并去重。
        panel.fwd_local.setText("8080")
        panel.fwd_remote.setText("80")
        panel.btn_remove_rev.click()
        selected[:] = ["demo-c"]
        assert requested.count() == 1
        assert requested.at(0)[0] == ["demo-a", "demo-b"]
        panel.panel.selected_devices = []
        panel._update_action_states()
        assert not panel.btn_remove_rev.isEnabled()
        panel.btn_remove_rev.clicked.emit()
        assert requested.count() == 1
    finally:
        widget.close()
        widget.deleteLater()


def _cards_by_title(panel: SystemPanel):
    return {card.headerLabel.text(): card for card in panel._system_section_groups}


def test_system_categories_expose_stable_keys(qt_application):
    panel, widget = _build_system_panel()

    assert panel.category_stack.category_keys == (
        "commands",
    )
    assert panel.category_stack.current_key == "commands"

    widget.deleteLater()


def test_system_cards_belong_to_expected_category_pages(qt_application):
    panel, widget = _build_system_panel()
    cards = _cards_by_title(panel)
    expected = {
        "commands": (
            "Shell 命令", "广播与 Intent", "Android 设置", "重启与模式", "端口转发",
            "系统服务开关 (svc)", "电池与快捷设置", "输入法与模拟器控制", "系统工具",
        ),
    }

    assert set(cards) == {title for titles in expected.values() for title in titles}
    for key, titles in expected.items():
        page = panel.category_stack.page(key)
        assert page is not None
        page_cards = tuple(
            page.layout().itemAt(index).widget() for index in range(page.layout().count())
        )
        assert page_cards == tuple(cards[title] for title in titles)

    widget.deleteLater()


def test_legacy_system_categories_share_one_complete_page(qt_application):
    panel, widget = _build_system_panel()
    widget.resize(900, 700)
    widget.show()
    qt_application.processEvents()

    assert panel.category_stack.set_current("device") is True
    qt_application.processEvents()

    selected = panel.category_stack.page("device")
    assert panel.category_stack.stack.currentWidget() is selected
    assert selected is not None and selected.isVisibleTo(widget)
    assert all(
        panel.category_stack.page(key) is selected
        for key in ("commands", "settings")
    )

    widget.close()
    widget.deleteLater()
