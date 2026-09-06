"""使用隔离主窗口检查 Monkey 空白背景与控件底色，不访问设备或用户数据。"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=("before", "after"))
parser.add_argument("theme", choices=("Light", "Dark"))
args = parser.parse_args()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "1"
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

if args.phase == "before":
    spec = importlib.util.spec_from_file_location(
        "gui.panels.app_panel", OUTPUT / "app_panel.before.py",
    )
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)

from tests.test_main_window_layout import (
    _FakeScreen, _FakeScreenAdapter, _MainFrameSettings, build_main_frame,
)


def main():
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
        window_width=1100, window_height=1100, save_directory=str(OUTPUT / "results"),
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
        try:
            frame.show()
            frame.resize(1100, 1100)
            frame._on_devices_updated(["demo-device"])
            frame._global_device_bar.selection_requested.emit(["demo-device"])
            assert frame._open_workspace_feature("apps", "overview")
            panel = frame.left_panel._apps_tab
            panel.program_edit.setText("com.example.demo")
            host = frame._workspace_feature_hosts["apps"]
            scroll = host.overview.body
            QTest.qWait(350)
            report = {
                "phase": args.phase, "theme": args.theme, "pixels": {},
                "source": "Isolated MainFrame QWidget.grab; no desktop/device capture",
                "mica_enabled": False,
                "app_panel_source": panel.__class__.__module__,
            }

            def sample(name, widget, point):
                scroll.ensureWidgetVisible(widget, 0, 0)
                QTest.qWait(50)
                location = widget.mapTo(frame, point)
                viewport = scroll.viewport()
                viewport_location = viewport.mapFrom(frame, location)
                assert viewport.rect().contains(viewport_location), (name, location)
                assert frame.rect().contains(location), (name, location)
                # 卡片左侧与采样点同高的空隙作为同一合成图内的父背景对照。
                gap = panel.monkey_section.mapTo(frame, QPoint(-6, 0))
                gap.setY(location.y())
                pixmap = frame.grab()
                image = pixmap.toImage()
                dpr = pixmap.devicePixelRatio()
                def pixel(position):
                    return image.pixelColor(
                        round(position.x() * dpr), round(position.y() * dpr),
                    ).name()
                report["pixels"][name] = {
                    "sample": pixel(location), "parent_gap": pixel(gap),
                    "position": [location.x(), location.y()],
                    "size": [widget.width(), widget.height()],
                    "widget": type(widget).__name__,
                }

            sample("package_blank", panel.monkey_package_card, QPoint(8, 10))
            sample("parameters_blank", panel.monkey_parameters_card, QPoint(8, 10))
            sample("events_input", panel.monkey_events, QPoint(45, 8))
            sample("get_package_button", panel.monkey_get_package_btn, QPoint(8, 8))
            for tag, target in (
                ("overview", panel.monkey_package_card),
                ("parameters", panel.monkey_parameters_card),
            ):
                scroll.ensureWidgetVisible(target, 0, 0)
                top = target.mapTo(scroll.widget(), QPoint()).y() - 65
                scroll.verticalScrollBar().setValue(max(0, top))
                QTest.qWait(80)
                frame.grab().save(str(OUTPUT / f"{args.phase}-{args.theme.lower()}-{tag}.png"))
            report["horizontal_max"] = scroll.horizontalScrollBar().maximum()
            report["frame"] = [frame.width(), frame.height()]
            assert report["horizontal_max"] == 0
            (OUTPUT / f"{args.phase}-{args.theme.lower()}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print(json.dumps(report))
        finally:
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
