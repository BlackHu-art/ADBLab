"""只读验证合成 Logcat 流对实际主窗口工作区的影响。"""

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
from gui.styles import BaseStyles
from models.device_store import DeviceStore
from tests.test_main_window_layout import (
    _FakeScreen, _FakeScreenAdapter, _MainFrameSettings, build_main_frame,
)

app = QApplication.instance() or QApplication([])
font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
    QFontDatabase.addApplicationFont(str(font_directory / filename))
settings = _MainFrameSettings()
settings.values = dict(DEFAULTS)
settings.values.update(theme="Light", mica_enabled=False, ui_font_size=12,
                       font_family="Microsoft YaHei UI", window_width=1100,
                       window_height=700, continuous_scan=False)
with (patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)),
      patch.object(DeviceStore, "get_full_devices_info", return_value=[])):
    BaseStyles.reload_from_settings()
    frame = build_main_frame(
        settings=settings,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(1600, 1000))),
    )
    frame.show()
    frame.resize(1100, 700)
    host = frame._workspace_feature_hosts["system"]
    host.set_device_context(["demo-device"], ["demo-device"])
    assert frame._open_workspace_feature("system", "logcat", device_id="demo-device")
    page = host.stack.currentWidget()
    QTest.qWait(100)

    def report(label):
        output_rect = QRect(page.output.mapTo(host.content_scroll.viewport(), QPoint()),
                            page.output.size())
        visible = output_rect.intersected(host.content_scroll.viewport().rect())
        print(label, {
            "frame": frame.size().toTuple(), "page": page.size().toTuple(),
            "page_min": page.minimumSizeHint().toTuple(),
            "page_hfw": page.heightForWidth(page.width()),
            "stack_hfw": host.stack.heightForWidth(host.stack.width()),
            "outer_viewport": host.content_scroll.viewport().size().toTuple(),
            "output": page.output.size().toTuple(),
            "output_hint": page.output.sizeHint().toTuple(),
            "output_min": page.output.minimumHeight(),
            "visible_output_height": visible.height(),
            "outer_range": host.content_scroll.verticalScrollBar().maximum(),
            "inner_range": page.output.verticalScrollBar().maximum(),
            "entries": len(page.entries), "blocks": page.output.blockCount(),
        })

    report("empty")
    for total, label in ((1000, "one-thousand"), (8500, "over-cap")):
        for index in range(total):
            page._on_line(f"09-06 18:00:00.000 100 100 I Demo: synthetic line {index} "
                          + "abcdefghijklm " * (20 if total > 1000 else 1), "I", 100)
        page._flush_pending_lines()
        QTest.qWait(80)
        report(label)
    bar = page.output.verticalScrollBar()
    bar.setValue(bar.maximum() // 3)
    before = page.output.firstVisibleBlock().text()
    for index in range(100):
        page._on_line(f"09-06 18:00:00.000 100 100 W Demo: follow-up {index}", "W", 100)
    page._flush_pending_lines()
    QTest.qWait(80)
    print("history_anchor", {"preserved": before == page.output.firstVisibleBlock().text(),
                             "at_tail": bar.value() == bar.maximum()})
    print("levels", [(page.level_combo.itemText(i), page.level_combo.itemData(i))
                     for i in range(page.level_combo.count())])
    frame.resize(860, 540)
    QTest.qWait(100)
    report("small")
    frame.grab().save(str(Path(__file__).with_name("logcat-small-overcap.png")))
    page.request_dispose()
    frame.left_panel.shutdown()
    frame._unbind_window_screen()
    frame._close_ready = True
    frame.close()
    QTest.qWait(60)
