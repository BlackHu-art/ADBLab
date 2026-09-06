"""只渲染三个隔离性能页场景，记录诊断区的真实布局与滚动边界。"""

import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

SCENARIOS = {
    "light": ("Light", 1100, 1000, 12, "zh_CN", "1"),
    "dark-large": ("Dark", 860, 1000, 22, "zh_CN", "1"),
    "english-125": ("Light", 1100, 1000, 12, "en_US", "1.25"),
}
parser = argparse.ArgumentParser()
parser.add_argument("scenario", choices=SCENARIOS)
args = parser.parse_args()
theme, width, height, font_size, language, scale = SCENARIOS[args.scenario]
OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[1]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = scale
for variable in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME"):
    os.environ[variable] = str(OUTPUT / "isolated-user")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

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
from tests.ui_geometry_helpers import assert_contained, assert_scroll_target_reachable


def mapped(widget, owner):
    return QRect(widget.mapTo(owner, QPoint()), widget.size())


def dimensions(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def main():
    app = QApplication([])
    translators = install_translators(app, language)
    font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(font_directory / name))
    settings = _MainFrameSettings()
    settings.values = dict(DEFAULTS)
    settings.values.update(
        theme=theme, mica_enabled=False, continuous_scan=False,
        font_family="Microsoft YaHei UI", ui_font_size=font_size, log_font_size=12,
        window_width=width, window_height=height, save_directory=str(OUTPUT / "results"),
    )
    settings.save_directory = str(OUTPUT / "results")
    with (
        patch.object(AppSettings, "instance", classmethod(lambda cls: settings)),
        patch.object(DeviceStore, "get_full_devices_info", return_value=[]),
        patch.object(RunLibrary, "for_user", classmethod(lambda cls: cls())),
        patch.object(CommandRunner, "run", side_effect=AssertionError("Device I/O prohibited")),
    ):
        BaseStyles.reload_from_settings()
        BaseStyles.switch_theme(theme)
        frame = build_main_frame(
            settings=settings,
            screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(2560, 1800))),
        )
        page = None
        errors = []
        try:
            frame.show()
            frame.resize(width, height)
            frame._on_devices_updated(["demo-device"])
            frame.left_panel._devices_tab.set_selected_devices(["demo-device"])
            host = frame._workspace_feature_hosts["system"]
            host.set_device_context(["demo-device"], ["demo-device"])
            assert frame._open_workspace_feature("system", "performance", device_id="demo-device")
            page = host.stack.currentWidget()
            page._runner = _RunnerProbe()
            page.package_edit.setText("com.example.demo")
            page.log_view.setPlainText("[INFO] Synthetic preview only; no device command executed")
            QTest.qWait(350)
            scroll = host.content_scroll
            diagnostics = page._diagnostic_tools
            fields = {
                "dumpheap": page.dumpheap_input,
                "exception": page.exception_edit,
                "phone_logs": page.phone_log_edit,
                "dumpheap_unit": page.dumpheap_unit_label,
            }
            labels = {
                str(label.property("configurationKey")): label
                for label in diagnostics.findChildren(QLabel, "fieldLabel")
            }
            title = diagnostics.findChild(QLabel, "performanceDiagnosticsTitle")
            if title is not None:
                labels["title"] = title
            report = {
                "scenario": args.scenario, "theme": theme, "language": language,
                "frame": [frame.width(), frame.height()], "font": font_size,
                "dpr": frame.devicePixelRatioF(), "diagnostics": dimensions(diagnostics.geometry()),
                "fields": {}, "labels": {}, "errors": errors,
            }
            for name, widget in {**fields, **labels}.items():
                if not widget.isVisibleTo(page):
                    errors.append(f"{name}: not visible by default")
                try:
                    assert_contained(widget, diagnostics)
                    assert_scroll_target_reachable(scroll, widget)
                except AssertionError as exc:
                    errors.append(f"{name}: {exc}")
            for name, widget in fields.items():
                report["fields"][name] = dimensions(mapped(widget, diagnostics))
            for name, label in labels.items():
                required = label.heightForWidth(label.width())
                report["labels"][name] = {
                    "text": label.text(), "rect": dimensions(mapped(label, diagnostics)),
                    "required_height": required, "point_size": label.font().pointSize(),
                }
                if label.height() < required:
                    errors.append(f"{name}: label clipped {label.height()} < {required}")
            field_rectangles = [mapped(widget, diagnostics) for widget in fields.values()]
            for index, first in enumerate(field_rectangles):
                for second in field_rectangles[index + 1:]:
                    if first.intersects(second):
                        errors.append(f"fields overlap: {first!r}, {second!r}")
            unit = page.dumpheap_unit_label
            unit_text_width = unit.fontMetrics().horizontalAdvance(unit.text())
            if unit.width() < unit_text_width:
                errors.append(f"unit width {unit.width()} < text {unit_text_width}")
            report["horizontal_max"] = scroll.horizontalScrollBar().maximum()
            if report["horizontal_max"]:
                errors.append("outer horizontal scroll is nonzero")
            bar = scroll.delegate.vScrollBar
            bar_left = bar.mapTo(scroll, QPoint()).x()
            content_right = max(mapped(widget, scroll).right() for widget in fields.values())
            report["scrollbar_clearance"] = bar_left - content_right - 1
            if report["scrollbar_clearance"] < 0:
                errors.append("diagnostic field overlaps overlay scrollbar")
            scroll.verticalScrollBar().setValue(0)
            QTest.qWait(80)
            frame.grab().save(str(OUTPUT / f"{args.scenario}-top.png"))
            scroll.ensureWidgetVisible(diagnostics, 0, 12)
            QTest.qWait(80)
            frame.grab().save(str(OUTPUT / f"{args.scenario}-diagnostics.png"))
            (OUTPUT / f"{args.scenario}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print(json.dumps(report, ensure_ascii=True))
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
        if errors:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
