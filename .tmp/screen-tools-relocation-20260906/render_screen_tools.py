"""使用内存设置和合成截图检查实际主窗，不访问设备或用户数据。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for variable in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME"):
    os.environ[variable] = str(OUTPUT / "isolated-user")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame

from core.exec import CommandRunner
from core.settings_manager import AppSettings, DEFAULTS
from gui.i18n import install_translators
from gui.styles import BaseStyles
from models.device_store import DeviceStore
from services.run_library import RunLibrary
from tests.test_main_window_layout import (
    _FakeScreen, _FakeScreenAdapter, _MainFrameSettings, build_main_frame,
)
from tests.ui_geometry_helpers import (
    assert_contained, assert_non_overlapping, assert_scroll_target_reachable,
    assert_text_fits, mapped_rect,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--font", type=int, default=12)
    parser.add_argument("--theme", default="Light")
    parser.add_argument("--language", default="zh_CN")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        font_file = Path("C:/Windows/Fonts") / name
        if font_file.exists():
            QFontDatabase.addApplicationFont(str(font_file))
    translators = install_translators(app, args.language)
    settings = _MainFrameSettings()
    settings.values = dict(DEFAULTS)
    settings.values.update(
        theme=args.theme, mica_enabled=False, font_family="Microsoft YaHei UI",
        ui_font_size=args.font, log_font_size=12, window_width=args.width,
        window_height=args.height, continuous_scan=False,
    )
    settings.save_directory = str(OUTPUT)
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
            screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(args.width, args.height))),
        )
        try:
            frame.show()
            frame.resize(args.width, args.height)
            frame._on_devices_updated(["demo-a", "demo-b"])
            frame._global_device_bar.selection_requested.emit(["demo-a", "demo-b"])
            image = QPixmap(540, 960)
            image.fill(QColor("#e9eff9"))
            painter = QPainter(image)
            painter.fillRect(0, 0, 540, 160, QColor("#1867bc"))
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Segoe UI", 24))
            painter.drawText(38, 104, "Preview screen")
            painter.setPen(QColor("#17304e"))
            painter.setFont(QFont("Segoe UI", 19))
            painter.drawText(38, 245, "Synthetic screenshot")
            painter.drawText(38, 300, "No device connection")
            for y in (380, 490, 600):
                painter.fillRect(38, y, 464, 74, QColor("white"))
            painter.end()
            image_path = str(OUTPUT / "synthetic-screen.png")
            image.save(image_path)
            frame._open_workspace_feature("apps", "media", payload=[image_path])
            apps = frame.left_panel._apps_tab
            apps.email_text_sender.setText("demo@example.com")
            apps.record_duration.setCurrentText("60s")
            host = frame._workspace_feature_hosts["apps"]
            page = host.stack.currentWidget()
            QTest.qWait(400)
            controls = (
                apps.email_text_sender, apps.btn_send_text, apps.btn_screenshot,
                apps.record_duration, apps.btn_screen_record, apps.btn_stop_record,
            )
            assert_non_overlapping(controls, apps.text_screen_tools)
            for control in controls:
                assert_contained(control, apps.text_screen_tools)
                assert_scroll_target_reachable(host.content_scroll, control)
            for button in (apps.btn_send_text, apps.btn_screenshot, apps.btn_screen_record, apps.btn_stop_record):
                assert_text_fits(button)
            assert_scroll_target_reachable(host.content_scroll, page._bottom_bar)
            host.content_scroll.verticalScrollBar().setValue(0)
            QTest.qWait(80)
            tag = f"screen-tools-{args.theme.lower()}-{args.width}x{args.height}-font{args.font}-{args.language}"
            frame.grab().save(str(OUTPUT / f"{tag}.png"))
            report = {
                "frame": [frame.width(), frame.height()], "font": args.font,
                "language": args.language, "theme": args.theme,
                "tools": mapped_rect(apps.text_screen_tools, page).getRect(),
                "canvas": mapped_rect(page.findChild(QFrame, "canvasFrame"), page).getRect(),
                "viewport": mapped_rect(host.content_scroll.viewport(), frame).getRect(),
                "scroll_max": host.content_scroll.verticalScrollBar().maximum(),
                "horizontal_scroll_max": host.content_scroll.horizontalScrollBar().maximum(),
                "buttons_readable_and_reachable": True,
                "bottom_actions_reachable": True,
                "view_minimum": str(page._view.minimumSize()),
                "view_minimum_hint": str(page._view.minimumSizeHint()),
                "page_minimum": str(page.minimumSize()),
                "page_minimum_hint": str(page.minimumSizeHint()),
                "page_size_hint": str(page.sizeHint()),
                "page_hfw": page.heightForWidth(page.width()),
                "layout_hfw": page.layout().heightForWidth(page.width()),
                "layout_min_hfw": page.layout().minimumHeightForWidth(page.width()),
                "view_size_hint": str(page._view.sizeHint()),
                "tools_min_hint": str(apps.text_screen_tools.minimumSizeHint()),
                "bottom_min_hint": str(page._bottom_dock.minimumSizeHint()),
                "header_min_hint": str(page.header_card.minimumSizeHint()),
            }
            (OUTPUT / f"{tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False))
            assert host.content_scroll.horizontalScrollBar().maximum() == 0
        finally:
            frame.run_library.shutdown()
            frame.left_panel.shutdown()
            frame._unbind_window_screen()
            frame._close_ready = True
            frame.close()
            frame.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            for translator in translators:
                app.removeTranslator(translator)


if __name__ == "__main__":
    main()
