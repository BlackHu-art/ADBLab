"""用合成日志渲染真实 MainFrame，不执行 ADB 或保存用户设置。"""

import argparse
import json
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

from core.exec import CommandRunner
from core.settings_manager import AppSettings, DEFAULTS
from gui.i18n import install_translators
from gui.styles import BaseStyles
from models.device_store import DeviceStore
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="Light")
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--font", type=int, default=12)
    parser.add_argument("--log-font", type=int, default=12)
    parser.add_argument("--language", default="zh_CN")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(font_directory / filename))
    translators = install_translators(app, args.language)
    settings = _MainFrameSettings()
    settings.values = dict(DEFAULTS)
    settings.values.update(
        theme=args.theme, mica_enabled=False, font_family="Microsoft YaHei UI",
        ui_font_size=args.font, log_font_size=args.log_font, language=args.language,
        window_width=args.width, window_height=args.height, continuous_scan=False,
    )
    with (
        patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)),
        patch.object(DeviceStore, "get_full_devices_info", return_value=[]),
        patch.object(CommandRunner, "run", side_effect=AssertionError("Unexpected device I/O")),
    ):
        BaseStyles.reload_from_settings()
        BaseStyles.switch_theme(args.theme)
        frame = build_main_frame(
            settings=settings,
            screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(2560, 1440))),
        )
        page = None
        try:
            frame.show()
            frame.resize(args.width, args.height)
            frame._on_devices_updated(["demo-device"])
            frame.left_panel._devices_tab.set_selected_devices(["demo-device"])
            host = frame._workspace_feature_hosts["system"]
            host.set_device_context(["demo-device"], ["demo-device"])
            assert frame._open_workspace_feature("system", "logcat", device_id="demo-device")
            page = host.stack.currentWidget()
            page.activate()
            page.pkg_input.setText("com.example.demo")
            page._set_running_actions(True)
            page.status_bar.setText(
                "Collecting · synthetic log preview" if args.language == "en_US"
                else "正在采集 · 合成日志预览"
            )
            QTest.qWait(250)
            samples = {
                "D": "Decoded frame and queued next sample",
                "I": "Application resumed; session is ready",
                "W": "Slow render detected; frame exceeded 32 ms",
                "E": "Request timed out; retry scheduled",
            }
            for index in range(160):
                level = "DIWE"[index % 4]
                message = samples[level]
                if index == 18:
                    message = "Long diagnostic payload: " + "trace-fragment-0123456789 " * 90
                text = f"09-06 18:10:{index % 60:02d}.345 1001 1024 {level} Demo: {message} [{index}]"
                page._on_line(text, level, 1001)
            page._flush_pending_lines()
            page.level_combo.setCurrentIndex(page.level_combo.findData("W"))
            QTest.qWait(80)
            bar = page.output.verticalScrollBar()
            bar.setValue(6)
            assert not page.follow_btn.isChecked()
            anchor = page.output.firstVisibleBlock().text()
            for index in range(5):
                level = "W" if index % 2 == 0 else "E"
                page._on_line(
                    f"09-06 18:11:00.000 1001 1024 {level} Demo: New background log [{index}]",
                    level, 1001,
                )
            page._flush_pending_lines()
            QTest.qWait(80)
            assert page.output.firstVisibleBlock().text() == anchor
            assert page._unseen_lines == 5
            assert not page.follow_btn.isChecked()
            assert page.output.horizontalScrollBar().maximum() > 0
            assert bar.maximum() > 0
            assert page.level_combo.currentData() == "W"
            assert len(page.entries) == 165
            output_lines = page.output.toPlainText().splitlines()
            assert len(output_lines) == 85
            assert all(" W Demo:" in line or " E Demo:" in line for line in output_lines)

            controls = (
                page.level_combo, page.pkg_input, page.btn_get_pkg, page.start_btn,
                page.stop_btn, page.follow_btn, page.wrap_btn, page.export_btn,
                page.clear_btn, page.status_bar, page.reading_status,
            )
            for control in controls:
                rect = QRect(control.mapTo(page, QPoint()), control.size())
                assert page.rect().contains(rect), (control.objectName(), rect, page.rect())
                assert control.height() >= control.fontMetrics().height()
            assert page.reading_status.height() >= page.reading_status.heightForWidth(
                page.reading_status.width()
            )

            scroll = host.content_scroll
            assert scroll.horizontalScrollBar().maximum() == 0
            suffix = (f"{args.theme.lower()}-{args.width}x{args.height}-ui{args.font}"
                      f"-log{args.log_font}-{args.language}")
            target = Path(__file__).parent
            scroll.verticalScrollBar().setValue(0)
            QTest.qWait(60)
            frame.grab().save(str(target / f"logcat-frame-{suffix}.png"))
            page.grab().save(str(target / f"logcat-page-{suffix}.png"))
            # QScrollArea 对文本框会优先定位文本光标；阅读验收按用户滚动条定位整个日志区域。
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            QTest.qWait(50)
            output_rect = QRect(page.output.mapTo(scroll.viewport(), QPoint()), page.output.size())
            visible_output = output_rect.intersected(scroll.viewport().rect())
            print('GEOMETRY', {'page':page.size().toTuple(), 'min':page.minimumSizeHint().toTuple(),
                  'hfw':page.heightForWidth(page.width()), 'stack':host.stack.size().toTuple(),
                  'range':scroll.verticalScrollBar().maximum(), 'value':scroll.verticalScrollBar().value(),
                  'output':output_rect.getRect(), 'viewport':scroll.viewport().rect().getRect()})
            assert visible_output.height() == page.output.height(), (
                visible_output, output_rect, scroll.viewport().rect()
            )
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            QTest.qWait(50)
            frame.grab().save(str(target / f"logcat-reading-{suffix}.png"))
            status_rect = QRect(page.reading_status.mapTo(scroll.viewport(), QPoint()),
                                page.reading_status.size())
            assert scroll.viewport().rect().contains(status_rect)
            report = {
                "suffix": suffix, "synthetic": True,
                "frame": frame.size().toTuple(), "page": page.size().toTuple(),
                "viewport": scroll.viewport().size().toTuple(),
                "output": page.output.size().toTuple(),
                "output_font": page.output.font().pointSize(),
                "visible_output_height": visible_output.height(),
                "outer_scroll_max": scroll.verticalScrollBar().maximum(),
                "horizontal_output_max": page.output.horizontalScrollBar().maximum(),
                "records": len(page.entries), "visible_records": len(output_lines),
                "paused_new_records": page._unseen_lines,
                "reading_status": page.reading_status.text(),
            }
            (target / f"logcat-review-{suffix}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, ensure_ascii=True))
        finally:
            if page is not None:
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
