"""使用合成会话截图，避免布局验收触发真实设备操作或保存用户配置。"""
import argparse
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import HeaderCardWidget

from core.settings_manager import AppSettings, DEFAULTS
from gui.styles import BaseStyles
from gui.i18n import install_translators
from models.device_store import DeviceStore

if "before" in sys.argv:
    for name in ("gui.dialogs.performance_launcher_form", "gui.dialogs.performance_launcher_run",
                 "gui.dialogs.performance_launcher", "gui.panels.app_panel"):
        filename = Path(__file__).parent / (name.replace(".", "__") + ".py")
        spec = importlib.util.spec_from_file_location(name, filename)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

from tests.test_main_window_layout import (
    _FakeScreen, _FakeScreenAdapter, _MainFrameSettings, build_main_frame,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="after")
    parser.add_argument("--theme", default="Light")
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--font", type=int, default=12)
    parser.add_argument("--language", default="zh_CN")
    parser.add_argument("--expanded", action="store_true")
    parser.add_argument("--monkey-ready", action="store_true")
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
    settings.save_directory = "E:/ADBLab-results"
    with (patch.object(AppSettings, "instance", classmethod(lambda cls: settings)),
          patch.object(DeviceStore, "get_full_devices_info", return_value=[])):
        BaseStyles.reload_from_settings()
        BaseStyles.switch_theme(args.theme)
        frame = build_main_frame(
            settings=settings,
            screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(2560, 1440))),
        )
        frame.show()
        frame.resize(args.width, 900)
        frame._on_devices_updated(["demo-device"])
        frame.left_panel._devices_tab.set_selected_devices(["demo-device"])
        panel = frame.left_panel._ensure_tab_loaded(0)
        panel.program_edit.setText("com.example.demo")
        if args.monkey_ready:
            from tests.test_monkey_preparation import _success
            panel._begin_monkey_preparation()
            pending = panel._monkey_preparation
            panel.on_monkey_preparation_finished(pending.request_id, _success(pending))
        frame._open_workspace_feature("apps", "overview")
        QTest.qWait(350)
        card = next(card for card in frame.findChildren(HeaderCardWidget)
                    if card.headerLabel.text() == "Monkey")
        outer = frame._workspace_feature_hosts["apps"].content_scroll
        inner = frame._workspace_feature_hosts["apps"].overview.body
        inner.ensureWidgetVisible(card, 0, 0)
        inner.verticalScrollBar().setValue(card.mapTo(inner.widget(), QPoint()).y())
        outer.ensureWidgetVisible(card, 0, 0)
        QTest.qWait(200)
        target = Path(__file__).parent
        suffix = f"{args.label}-{args.theme.lower()}-{args.width}-font{args.font}"
        frame.grab().save(str(target / f"monkey-frame-{suffix}.png"))
        card.grab().save(str(target / f"monkey-card-{suffix}.png"))
        host = frame._workspace_feature_hosts["system"]
        host.set_device_context(["demo-device"], ["demo-device"])
        assert frame._open_workspace_feature("system", "performance", device_id="demo-device")
        page = host.stack.currentWidget()
        page.package_edit.setText("com.example.demo")
        if args.expanded:
            page._diagnostic_tools.toggle_button.setChecked(True)
            page.monkey_check.setChecked(True)
        QTest.qWait(350)
        frame.grab().save(str(target / f"performance-frame-{suffix}.png"))
        page.grab().save(str(target / f"performance-page-{suffix}.png"))
        print({"label": suffix, "frame": [frame.width(), frame.height()],
               "monkey": [card.width(), card.height()], "performance": [page.width(), page.height()],
               "performance_scroll": host.content_scroll.horizontalScrollBar().maximum()})
        if args.expanded:
            for name, widget in (("results", page._results_group), ("view", page._results_group.view),
                                 ("stack", page._chart_stack), ("log", page.log_view),
                                 ("config", page._config_group)):
                print(name, widget.geometry(), "min", widget.minimumSize(),
                      "hint", widget.minimumSizeHint(), "hfw", widget.heightForWidth(widget.width()))
        page.request_dispose()
        frame.left_panel.shutdown()
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        QTest.qWait(100)
        for translator in translators:
            app.removeTranslator(translator)


if __name__ == "__main__":
    main()
