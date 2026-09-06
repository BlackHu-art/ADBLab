"""以合成元数据检查设备概览在真实主窗口中的紧凑布局。"""
import argparse
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.settings_manager import AppSettings, DEFAULTS
from gui.i18n import install_translators
from gui.styles import BaseStyles
from models.device_store import DeviceStore
from tests.test_device_hub_page import _rich_metadata
from tests.test_main_window_layout import (
    _FakeScreen, _FakeScreenAdapter, _MainFrameSettings, build_main_frame,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--font", type=int, default=12)
    parser.add_argument("--theme", default="Light")
    parser.add_argument("--language", default="zh_CN")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    translators = install_translators(app, args.language)
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        if (fonts / name).exists():
            QFontDatabase.addApplicationFont(str(fonts / name))
    settings = _MainFrameSettings()
    settings.values = dict(DEFAULTS)
    settings.values.update(theme=args.theme, mica_enabled=False, font_family="Microsoft YaHei UI",
                           ui_font_size=args.font, window_width=args.width, window_height=900,
                           save_directory="E:/ADBLab-results", continuous_scan=False)
    records = _rich_metadata()
    with (patch.object(AppSettings, "instance", classmethod(lambda cls: settings)),
          patch.object(DeviceStore, "get_full_devices_info", return_value=records)):
        BaseStyles.reload_from_settings()
        BaseStyles.switch_theme(args.theme)
        frame = build_main_frame(
            settings=settings,
            screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(2560, 1440))),
        )
        frame.show()
        frame.resize(args.width, 900)
        frame._on_devices_updated([record["ip"] for record in records])
        frame.left_panel._devices_tab.set_selected_devices([records[0]["ip"]])
        frame._open_workspace_feature("devices", "overview")
        QTest.qWait(350)
        hub = frame._device_hub
        first = hub.device_cards[0]
        suffix = f"{args.theme.lower()}-{args.width}-font{args.font}"
        if args.language != "zh_CN":
            suffix += f"-{args.language}"
        target = Path(__file__).parent
        frame.grab().save(str(target / f"device-hub-collapsed-{suffix}.png"))
        collapsed = first.height()
        first.details_button.click()
        QTest.qWait(250)
        frame.grab().save(str(target / f"device-hub-expanded-{suffix}.png"))
        first.grab().save(str(target / f"device-card-expanded-{suffix}.png"))
        copy_bounds = QRect(first.copy_details_button.mapTo(first, QPoint()),
                            first.copy_details_button.size())
        assert first.rect().contains(copy_bounds)
        print({"frame": [frame.width(), frame.height()], "hub": [hub.width(), hub.height()],
               "collapsed_height": collapsed, "expanded_height": first.height(),
               "copy_contained": first.rect().contains(copy_bounds)})
        inner = frame._workspace_feature_hosts["devices"].overview.body
        inner.ensureWidgetVisible(first.copy_details_button, 0, 8)
        QTest.qWait(120)
        bounds = QRect(first.copy_details_button.mapTo(inner.viewport(), QPoint()),
                       first.copy_details_button.size())
        assert inner.viewport().rect().contains(bounds), (bounds, inner.viewport().rect())
        frame.grab().save(str(target / f"device-hub-copy-visible-{suffix}.png"))
        frame.left_panel.shutdown()
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        QTest.qWait(100)
    for translator in translators:
        app.removeTranslator(translator)


if __name__ == "__main__":
    main()
