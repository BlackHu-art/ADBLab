"""覆盖手工创建控件的材质接入，防止只修到公共表单工厂。"""

import pytest
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon
from qfluentwidgets.components.material.acrylic_combo_box import AcrylicComboBoxMenu

from gui.pages.fluent_pages import ComboSettingCard
from gui.widgets.adaptive_navigation import AdaptiveNavigation
from gui.widgets.preset_spin_box import StrictIntComboBox
from gui.widgets.run_preset_bar import RunPresetBar

pytestmark = pytest.mark.ui


class MicaHost(QWidget):
    def isMicaEffectEnabled(self):
        return True


@pytest.mark.parametrize("kind", ["settings", "numeric", "navigation", "preset"])
def test_late_created_dropdown_uses_actual_host_material(qt_application, kind):
    host = MicaHost()
    if kind == "settings":
        owner = ComboSettingCard(FluentIcon.INFO, "选项", "说明", ["甲", "乙"], "甲", host)
        combo = owner.combo_box
    elif kind == "numeric":
        combo = StrictIntComboBox(1, 100, 30, presets=(10, 30), parent=host)
    elif kind == "navigation":
        owner = AdaptiveNavigation("audit", parent=host)
        combo = owner.combo
    else:
        owner = RunPresetBar("monkey", lambda: {}, lambda _parameters: None, parent=host)
        combo = owner.combo
    before = (combo.currentIndex(), combo.currentText(), combo.currentData(), combo.font())
    menu = combo._createComboMenu()
    try:
        assert isinstance(menu, AcrylicComboBoxMenu)
        assert (
            combo.currentIndex(), combo.currentText(), combo.currentData(), combo.font(),
        ) == before
    finally:
        menu.deleteLater()
        host.deleteLater()
