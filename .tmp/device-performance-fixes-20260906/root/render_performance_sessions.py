"""真实 MainFrame 的双设备采集预览，所有设置、设备和 runner 均为隔离替身。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for variable in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME"):
    os.environ[variable] = str(OUTPUT / "isolated-preview-user")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt
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
from tests.ui_geometry_helpers import assert_contained, assert_scroll_target_reachable


def rectangle(widget, owner):
    rect = QRect(widget.mapTo(owner, QPoint()), widget.size())
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def fake_runner():
    runner = Mock()
    runner.is_running.return_value = False
    runner.latest_result_dir.return_value = ""
    runner.latest_report_file.return_value = ""
    runner.last_config = None
    runner.last_exit_code = 0

    def start(config, **_callbacks):
        runner.last_config = config
        runner.is_running.return_value = True

    runner.start.side_effect = start
    runner.stop.side_effect = lambda: setattr(runner.is_running, "return_value", False)
    return runner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", type=int, default=12)
    args = parser.parse_args()
    width, height = (900, 1000) if args.font == 12 else (860, 800)
    theme = "Light" if args.font == 12 else "Dark"
    app = QApplication.instance() or QApplication([])
    translators = install_translators(app, "zh_CN")
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        if (font_dir / name).exists():
            QFontDatabase.addApplicationFont(str(font_dir / name))
    settings = _MainFrameSettings()
    settings.values = dict(DEFAULTS)
    settings.values.update(
        theme=theme, mica_enabled=False, font_family="Microsoft YaHei UI",
        ui_font_size=args.font, log_font_size=12, window_width=width,
        window_height=height, save_directory=str(OUTPUT / "synthetic-results"),
        continuous_scan=False,
    )
    settings.save_directory = str(OUTPUT / "synthetic-results")
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
            screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(2560, 1440))),
        )
        pages = []
        try:
            frame.show()
            frame.resize(width, height)
            devices = ["demo-a", "demo-b"]
            frame._on_devices_updated(devices)
            frame.left_panel._devices_tab.set_selected_devices(devices)
            host = frame._workspace_feature_hosts["system"]
            host.set_device_context(devices, devices)
            assert frame._open_workspace_feature("system", "performance", device_id=devices[0])
            table = host.performance_sessions.table
            for index, minutes in enumerate((10, 20)):
                if index:
                    item = table.item(index, 0)
                    QTest.mouseClick(
                        table.viewport(), Qt.MouseButton.LeftButton,
                        pos=table.visualItemRect(item).center(),
                    )
                    app.processEvents()
                page = host.stack.currentWidget()
                pages.append(page)
                assert page.device_ip == devices[index]
                page._runner = fake_runner()
                page.package_edit.setText(f"com.example.device{index + 1}")
                page.timeout_input.setValue(minutes)
                page.start_btn.click()
                assert page._runner.start.call_count == 1
                page._run_started_at = time.monotonic() - 120
                page._update_progress()
            QTest.qWait(350)
            assert host._selected_devices == tuple(devices)
            assert not frame._global_device_bar.close_button.isVisibleTo(frame)
            assert host.close_session_button.isHidden()
            assert table.rowCount() == 2
            assert table.item(0, 2).text().startswith("20%")
            assert table.item(1, 2).text().startswith("10%")
            assert_contained(table, host.performance_sessions)
            assert_contained(host.performance_sessions, host)
            assert table.horizontalScrollBar().maximum() == 0
            assert host.content_scroll.horizontalScrollBar().maximum() == 0
            for row in range(2):
                item = table.item(row, 0)
                assert table.viewport().rect().contains(table.visualItemRect(item))
                QTest.mouseClick(
                    table.viewport(), Qt.MouseButton.LeftButton,
                    pos=table.visualItemRect(item).center(),
                )
                app.processEvents()
                assert host.stack.currentWidget() is pages[row]
            page = pages[1]
            assert_scroll_target_reachable(host.content_scroll, page.stop_btn)
            viewport = host.content_scroll.viewport()
            scrollbar = host.content_scroll.verticalScrollBar()
            log_top = page.log_view.mapTo(host.content_scroll.widget(), QPoint()).y()
            scrollbar.setValue(log_top)
            app.processEvents()
            log_start = QRect(page.log_view.mapTo(viewport, QPoint()), page.log_view.size())
            assert 0 <= log_start.top() < viewport.height()
            scrollbar.setValue(log_top + page.log_view.height() - viewport.height())
            app.processEvents()
            log_end = QRect(page.log_view.mapTo(viewport, QPoint()), page.log_view.size())
            assert 0 <= log_end.bottom() < viewport.height()
            host.content_scroll.verticalScrollBar().setValue(0)
            app.processEvents()
            fluent_scrollbar = host.content_scroll.delegate.vScrollBar
            report = {
                "frame": [frame.width(), frame.height()], "font_points": args.font,
                "theme": theme, "global_close_hidden": True,
                "selected_devices": list(host._selected_devices),
                "rows": [[table.item(r, c).text() for c in range(3)] for r in range(2)],
                "list": rectangle(host.performance_sessions, frame),
                "table": rectangle(table, frame),
                "content_viewport": rectangle(host.content_scroll.viewport(), frame),
                "content_scrollbar": rectangle(fluent_scrollbar, frame),
                "scrollbar_visible": fluent_scrollbar.isVisibleTo(frame),
                "scrollbar_max": scrollbar.maximum(),
                "horizontal_scroll_max": host.content_scroll.horizontalScrollBar().maximum(),
                "rows_clicked": 2,
                "log_edge_reachable": True,
                "log_height": page.log_view.height(),
                "log_start_rect": log_start.getRect(),
                "log_end_rect": log_end.getRect(),
                "runner_starts": [p._runner.start.call_count for p in pages],
            }
            tag = f"performance-two-devices-{theme.lower()}-{width}x{height}-font{args.font}"
            assert frame.grab().save(str(OUTPUT / f"{tag}.png"))
            (OUTPUT / f"{tag}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print(json.dumps(report, ensure_ascii=False))
        finally:
            for page in pages:
                page._runner.is_running.return_value = False
                page.request_dispose()
            frame.run_library.shutdown()
            frame.left_panel.shutdown()
            frame._unbind_window_screen()
            frame._close_ready = True
            frame.close()
            QTest.qWait(100)
            frame.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            for translator in translators:
                app.removeTranslator(translator)


if __name__ == "__main__":
    main()
