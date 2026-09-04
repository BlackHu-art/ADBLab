"""System 面板分类导航与卡片归属契约。"""

from types import SimpleNamespace

import pytest

from gui.panels.system_panel import SystemPanel
from gui.styles import BaseStyles, FontRole

pytestmark = pytest.mark.ui


def _build_system_panel():
    owner = SimpleNamespace(
        selected_devices=[],
        _font_sm=BaseStyles.font_for_role(FontRole.UI),
        _font_mono=BaseStyles.font_for_role(FontRole.MONO),
        _font_base=BaseStyles.font_for_role(FontRole.UI),
    )
    panel = SystemPanel(owner)
    widget = panel.build_ui()
    return panel, widget


def _cards_by_title(panel: SystemPanel):
    return {card.headerLabel.text(): card for card in panel._system_section_groups}


def test_system_categories_expose_stable_keys(qt_application):
    panel, widget = _build_system_panel()

    assert panel.category_stack.category_keys == (
        "commands",
        "connectivity",
        "settings",
        "device",
    )
    assert panel.category_stack.current_key == "commands"

    widget.deleteLater()


def test_system_cards_belong_to_expected_category_pages(qt_application):
    panel, widget = _build_system_panel()
    cards = _cards_by_title(panel)
    expected = {
        "commands": ("Shell 命令", "重启与模式", "广播与 Intent"),
        "connectivity": ("端口转发", "系统服务开关 (svc)"),
        "settings": ("Android 设置", "系统工具"),
        "device": ("电池与快捷设置", "输入法与模拟器控制"),
    }

    assert tuple(cards) == tuple(title for titles in expected.values() for title in titles)
    for key, titles in expected.items():
        page = panel.category_stack.page(key)
        assert page is not None
        page_cards = tuple(
            page.layout().itemAt(index).widget() for index in range(page.layout().count())
        )
        assert page_cards == tuple(cards[title] for title in titles)

    widget.deleteLater()


def test_system_category_switch_shows_only_selected_page(qt_application):
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
        panel.category_stack.page(key).isHidden()
        for key in ("commands", "connectivity", "settings")
    )

    widget.close()
    widget.deleteLater()
