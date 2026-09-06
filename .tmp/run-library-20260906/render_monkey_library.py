"""用合成设备与内存方案库检查 Monkey 卡片，不访问 ADB 或用户配置文件。"""
import os
import sys
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pytest import MonkeyPatch
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gui.run_library import RunLibraryController
from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from services.run_library import RunLibrary
from tests.test_monkey_preparation import _success
from tests.test_responsive_panels import (
    _close_feature_panel, _resize_feature_viewport, _show_feature_panel,
)
from tests.ui_geometry_helpers import wait_until

app = QApplication.instance() or QApplication([])
font_root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
    QFontDatabase.addApplicationFont(str(font_root / filename))

for theme, size, width in (("light", 12, 960), ("dark", 22, 740), ("dark", 22, 292)):
    BaseStyles.switch_theme(theme.title())
    config = replace(BaseStyles.current_font_config(), ui_family="Microsoft YaHei UI", ui_size=size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    patch = MonkeyPatch()
    owner, panel, scroll, _ = _show_feature_panel(
        "apps", width, size, app, patch, patch_font_factory=False,
    )
    library = RunLibraryController(RunLibrary())
    try:
        owner._devices_tab.update_device_list(["demo-a", "demo-b"])
        owner._devices_tab.set_selected_devices(["demo-a", "demo-b"])
        panel.program_edit.setText("com.example.demo")
        panel.monkey_seed_mode.setCurrentIndex(1)
        panel.monkey_seed.setText("2147483647")
        panel.set_run_library(library)
        library.save_preset("日常稳定性测试", "monkey", panel.capture_run_parameters())
        wait_until(app, lambda: len(library.presets) == 1)
        panel.monkey_preset_bar.combo.setCurrentIndex(1)
        panel._begin_monkey_preparation()
        pending = panel._monkey_preparation
        panel.on_monkey_preparation_finished(pending.request_id, _success(pending))
        _resize_feature_viewport(app, owner, panel, scroll, width)
        QTest.qWait(100)
        BaseStyles.switch_theme(theme.title())
        QTest.qWait(80)
        output = Path(__file__).parent / f"monkey-library-{theme}-{width}-font{size}.png"
        panel.monkey_section.grab().save(str(output))
        print(str(output), panel.monkey_section.size(), panel.monkey_preset_bar.size())
        item = panel.monkey_preset_bar.save_button
        while item is not panel.monkey_parameters_card:
            print(type(item).__name__, item.geometry(), item.isVisible(), item.minimumHeight(), item.maximumHeight())
            item = item.parentWidget()
    finally:
        assert library.shutdown()
        library.deleteLater()
        _close_feature_panel(owner)
        patch.undo()
