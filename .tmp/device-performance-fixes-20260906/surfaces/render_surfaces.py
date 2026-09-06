"""在隔离 MainFrame 内对比性能分区空白像素，不执行设备命令。"""

import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

OUTPUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for variable in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME"):
    os.environ[variable] = str(OUTPUT / "isolated-user")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.exec import CommandRunner
from core.settings_manager import AppSettings, DEFAULTS
from gui.i18n import install_translators
from gui.styles import BaseStyles
from models.device_store import DeviceStore
from services.run_library import RunLibrary
from tests.test_main_window_layout import (
    _FakeScreen, _FakeScreenAdapter, _MainFrameSettings, build_main_frame,
)
from tests.test_performance_responsive import _RunnerProbe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("theme", choices=("Light", "Dark"))
    args = parser.parse_args()
    app = QApplication([])
    translators = install_translators(app, "zh_CN")
    font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(font_directory / name))
    settings = _MainFrameSettings()
    settings.values = dict(DEFAULTS)
    settings.values.update(
        theme=args.theme, mica_enabled=False, continuous_scan=False,
        font_family="Microsoft YaHei UI", ui_font_size=12, log_font_size=12,
        window_width=1100, window_height=1150, save_directory=str(OUTPUT / "results"),
    )
    settings.save_directory = str(OUTPUT / "results")
    with (
        patch.object(AppSettings, "instance", classmethod(lambda cls: settings)),
        patch.object(DeviceStore, "get_full_devices_info", return_value=[]),
        patch.object(RunLibrary, "for_user", classmethod(lambda cls: cls())),
        patch.object(CommandRunner, "run", side_effect=AssertionError("Device I/O prohibited")),
    ):
        BaseStyles.reload_from_settings()
        BaseStyles.switch_theme(args.theme)
        frame = build_main_frame(
            settings=settings,
            screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(2560, 1600))),
        )
        page = None
        try:
            frame.show()
            frame.resize(1100, 1150)
            frame._on_devices_updated(["demo-device"])
            frame.left_panel._devices_tab.set_selected_devices(["demo-device"])
            host = frame._workspace_feature_hosts["system"]
            host.set_device_context(["demo-device"], ["demo-device"])
            assert frame._open_workspace_feature("system", "performance", device_id="demo-device")
            page = host.stack.currentWidget()
            page._runner = _RunnerProbe()
            page.package_edit.setText("com.example.demo")
            page.log_view.setPlainText("[INFO] 此画面仅用于分区底色检查\n[INFO] 未执行设备命令")
            QTest.qWait(350)
            targets = {
                "actions": (page._action_row, QPoint(4, 10)),
                "plan_header": (page._configuration_sections[0], QPoint(4, 10)),
                "plan_body": (page._configuration_sections[0].view, QPoint(4, 10)),
                "results_header": (page._results_group, QPoint(4, 10)),
                "results_body": (page._results_group.view, QPoint(4, 10)),
            }
            report = {"phase": args.phase, "theme": args.theme, "pixels": {}}
            for name, (widget, point) in targets.items():
                host.content_scroll.ensureWidgetVisible(widget, 0, 0)
                QTest.qWait(40)
                position = widget.mapTo(frame, point)
                assert frame.rect().contains(position)
                report["pixels"][name] = frame.grab().toImage().pixelColor(position).name()
            for location, target in (("top", page._action_row), ("results", page.result_btn)):
                host.content_scroll.ensureWidgetVisible(target, 0, 0)
                if location == "top":
                    host.content_scroll.verticalScrollBar().setValue(0)
                QTest.qWait(70)
                frame.grab().save(str(OUTPUT / f"{args.phase}-{args.theme.lower()}-{location}.png"))
            report["horizontal_max"] = host.content_scroll.horizontalScrollBar().maximum()
            image = frame.grab().toImage()
            position = page.log_view.viewport().mapTo(
                frame, QPoint(3, page.log_view.viewport().height() // 2),
            )
            assert frame.rect().contains(position)
            report["log_background"] = image.pixelColor(position).name()
            report["source"] = "Isolated MainFrame QWidget.grab; no desktop/device capture"
            (OUTPUT / f"{args.phase}-{args.theme.lower()}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print(json.dumps(report))
        finally:
            if page is not None:
                page.request_dispose()
            frame.run_library.shutdown()
            frame.left_panel.shutdown()
            frame._unbind_window_screen()
            frame._close_ready = True
            frame.close()
            QTest.qWait(100)
            for translator in translators:
                app.removeTranslator(translator)


if __name__ == "__main__":
    main()
