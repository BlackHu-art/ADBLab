"""模拟材质视觉证据；仅渲染本进程控件，不使用真实用户设置或设备。"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "1"
parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=("before", "after"))
args = parser.parse_args()
if args.phase == "before" and (Path(__file__).parent / "before-samples.json").exists():
    raise SystemExit("旧实现基线已经保存，不得使用当前实现覆盖")
isolation = tempfile.TemporaryDirectory(prefix="adblab-mica-sim-")
os.environ["LOCALAPPDATA"] = isolation.name

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentWindow

from core.settings_manager import AppSettings
from gui.main_frame import MainFrame
from gui.styles import BaseStyles
from models.device_store import DeviceStore
from services.run_library import RunArtifact, RunLibrary, RunRecord
from tests.test_main_window_layout import (
    _FakeScreen, _FakeScreenAdapter, _MainFrameSettings, build_main_frame,
)
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until

app = QApplication([])
for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
    QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / filename))
data = Path(isolation.name)
output = Path(__file__).parent
settings = _MainFrameSettings()
settings.save_directory = str(data)
settings.values.update({
    "window_width": 1360, "window_height": 1000, "theme": "Light",
    "font_family": "Microsoft YaHei", "ui_font_size": 12,
    "continuous_device_scan": False, "mica_enabled": True,
})
controller = Mock()
controller.signals = Mock()
backdrop = QColor("#DCE5EF")

def simulate_mica(window, enabled):
    window._isMicaEnabled = bool(enabled)
    window.setBackgroundColor(window._normalBackgroundColor())

samples = []
with (
    patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)),
    patch("services.run_library.user_config_path", lambda filename: str(data / filename)),
    patch.object(DeviceStore, "get_basic_devices_info", return_value=[]),
    patch.object(DeviceStore, "get_full_devices_info", return_value=[]),
    patch("core.exec.CommandRunner.run", side_effect=AssertionError("禁止运行设备命令")),
    patch.object(FluentWindow, "setMicaEffectEnabled", simulate_mica),
    patch.object(MainFrame, "_normalBackgroundColor", lambda _self: QColor(backdrop)),
):
    source = RunLibrary(data / "test_runs.json")
    for index in range(8):
        finish = 1788678000 - index * 600
        source.record_run(RunRecord(
            str(index), "monkey" if index % 2 == 0 else "performance",
            "com.example.shopping" if index % 2 == 0 else "com.example.video",
            finish - 373, finish, ("succeeded", "failed", "partial", "cancelled")[index % 4],
            {"seed": 42, "event_count": 10000},
            (RunArtifact("运行日志", str(data / "run.log")),),
            "Pixel 测试机", "3.2.1 (104)", "测试已结束，结果附件保存在原输出目录。",
        ))
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme("Light")
    app.setFont(BaseStyles.get_default_font())
    frame = build_main_frame(
        settings=settings, controller=controller,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("simulated", QSize(1800, 1200))),
    )
    try:
        frame.show()
        frame.resize(1360, 1000)
        frame.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        frame.activateWindow()
        frame.windowHandle().requestActivate()
        QTest.qWait(100)
        frame.left_panel.set_device_discovery_state("empty")
        frame._sync_device_context()
        wait_until(app, lambda: len(frame.run_library.records) == 8)
        for color in ("#DCE5EF", "#E8E2DC"):
            backdrop = QColor(color)
            frame._refresh_window_chrome_theme()
            frame.titleBar.titleLabel.setText(
                f"ADBLab · 模拟材质（非原生 DWM）· {args.phase} · {color}"
            )
            for page_name in ("settings", "tasks", "performance"):
                if page_name == "performance":
                    host = frame._workspace_feature_hosts["system"]
                    host.set_device_context(["demo-device"], ["demo-device"])
                    frame._open_workspace_feature("system", "performance", device_id="demo-device")
                    page = host.registry.get(host.registry.current_key)
                    page.package_edit.setText("com.example.shopping")
                    page._append_log("INFO", "模拟采集日志，用于检查阅读底色。")
                    focus = page.log_view if args.phase == "after" else page.package_edit
                else:
                    frame._on_nav_requested(page_name)
                    focus = (
                        frame._settings_page.theme_card.combo_box
                        if page_name == "settings"
                        else (
                            frame._task_page.run_results.summary_edit
                            if args.phase == "after" else frame._task_page.run_results.search_edit
                        )
                    )
                animation = frame.stackedWidget.view._ani
                animation.setCurrentTime(animation.duration())
                wait_for_stable_geometry(app, (frame, frame._content_surface, frame.stackedWidget))
                for focused in (False, True):
                    frame.activateWindow()
                    frame.windowHandle().requestActivate()
                    if not focused:
                        focus.clearFocus()
                    (focus if focused else frame).setFocus(Qt.FocusReason.OtherFocusReason)
                    QTest.qWait(160)
                    assert focus.hasFocus() == focused, (page_name, focused, app.focusWidget())
                    pixmap = frame.grab()
                    image = pixmap.toImage()
                    ratio = image.devicePixelRatio()
                    point = frame.stackedWidget.mapTo(frame, QPoint(frame.stackedWidget.width() // 2, 2))
                    pixel = image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))
                    filename = f"{args.phase}-{color[1:].lower()}-{page_name}-{'focus' if focused else 'rest'}.png"
                    assert pixmap.save(str(output / filename))
                    sample = {
                        "phase": args.phase, "backdrop": color, "page": page_name,
                        "focus": focused, "surface_pixel": pixel.name(),
                        "focus_has_focus": focus.hasFocus(),
                        "focus_target": type(focus).__name__,
                        "focus_accessible_name": focus.accessibleName(),
                        "window_active": app.activeWindow() is frame,
                        "sample_point": [point.x(), point.y()], "image": filename,
                        "native_dwm": False,
                    }
                    viewport = getattr(focus, "viewport", None)
                    if callable(viewport):
                        reading = viewport()
                        reading_point = reading.mapTo(
                            frame, QPoint(reading.width() - 24, reading.height() - 24)
                        )
                        reading_pixel = image.pixelColor(
                            round(reading_point.x() * ratio), round(reading_point.y() * ratio)
                        )
                        sample["reading_pixel"] = reading_pixel.name()
                        sample["reading_sample_point"] = [reading_point.x(), reading_point.y()]
                        sample["text_palette"] = focus.palette().color(focus.foregroundRole()).name()
                    samples.append(sample)
        print(json.dumps(samples, ensure_ascii=False))
        (output / f"{args.phase}-samples.json").write_text(
            json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert controller.refresh_devices.call_count == 0
    finally:
        for host in frame._workspace_feature_hosts.values():
            for page in host.registry.pages():
                page.request_dispose("render_cleanup")
        frame.run_library.shutdown()
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        frame.deleteLater()
        QCoreApplication.sendPostedEvents(frame, QEvent.Type.DeferredDelete)
isolation.cleanup()
