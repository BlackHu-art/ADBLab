"""以隔离设置和合成会话核对性能页布局，不执行 ADB 或真实采集。"""

import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

OUTPUT = Path(__file__).resolve().parent
ROOT = Path.cwd()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["LOCALAPPDATA"] = str(OUTPUT / "isolated-user")
os.environ["APPDATA"] = str(OUTPUT / "isolated-user")
os.environ["XDG_CONFIG_HOME"] = str(OUTPUT / "isolated-user")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="Light")
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--font", type=int, default=12)
    parser.add_argument("--language", default="zh_CN")
    parser.add_argument("--expanded", action="store_true")
    parser.add_argument("--running", action="store_true")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    translators = install_translators(app, args.language)
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        if (fonts / name).exists():
            QFontDatabase.addApplicationFont(str(fonts / name))
    settings = _MainFrameSettings()
    settings.values = dict(DEFAULTS)
    settings.values.update(
        theme=args.theme, mica_enabled=False, font_family="Microsoft YaHei UI",
        ui_font_size=args.font, log_font_size=12, window_width=args.width,
        window_height=args.height, save_directory="E:/ADBLab-results",
        continuous_scan=False,
    )
    settings.save_directory = "E:/ADBLab-results"
    with (
        patch.object(AppSettings, "instance", classmethod(lambda cls: settings)),
        patch.object(DeviceStore, "get_full_devices_info", return_value=[]),
        patch.object(RunLibrary, "for_user", classmethod(lambda cls: cls())),
    ):
        BaseStyles.reload_from_settings()
        BaseStyles.switch_theme(args.theme)
        frame = build_main_frame(
            settings=settings,
            screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(2560, 1440))),
        )
        frame.show()
        frame.resize(args.width, args.height)
        frame._on_devices_updated(["demo-device"])
        frame.left_panel._devices_tab.set_selected_devices(["demo-device"])
        host = frame._workspace_feature_hosts["system"]
        host.set_device_context(["demo-device"], ["demo-device"])
        assert frame._open_workspace_feature("system", "performance", device_id="demo-device")
        page = host.stack.currentWidget()
        page._runner = _RunnerProbe()
        page.package_edit.setText("com.example.demo")
        page.log_view.setPlainText("[INFO] 已连接合成设备，采样间隔 5 秒\n[INFO] 示例数据仅用于布局检查\n[WARNING] 一次采样耗时较长，等待下一次采样")
        if args.expanded:
            page._diagnostic_tools.toggle_button.setChecked(True)
            page.monkey_check.setChecked(True)
        if args.running:
            page.timeout_input.setText("60")
            page._run_duration_seconds = 3600
            page._run_elapsed_seconds = 1512
            page._set_running(True)
            page._set_progress(42)
        QTest.qWait(350)
        scroll = host.content_scroll
        bar = scroll.delegate.vScrollBar
        print("OVERLAY", bar.geometry(), "card", page._configuration_group.geometry(), "margins", page._config_group.layout().contentsMargins())
        label = f"{args.theme.lower()}-{args.width}x{args.height}-font{args.font}-{args.language}-dpi{page.devicePixelRatioF():g}"
        if args.expanded:
            label += "-expanded"
        if args.running:
            label += "-running"
        scroll.verticalScrollBar().setValue(0)
        QTest.qWait(100)
        frame.grab().save(str(OUTPUT / f"performance-frame-{label}.png"))
        page.grab().save(str(OUTPUT / f"performance-page-{label}.png"))
        errors = []
        for name in ("status_label", "detail_label"):
            label_widget = getattr(page.progress_display, name)
            if label_widget.height() < label_widget.heightForWidth(label_widget.width()):
                errors.append(f"{name}: height {label_widget.height()} < required {label_widget.heightForWidth(label_widget.width())}")
        for name in ("start_btn", "stop_btn", "package_edit", "frequency_input", "timeout_input", "save_path_edit", "log_view", "result_btn", "perfetto_btn"):
            widget = getattr(page, name)
            try:
                assert_contained(widget, page)
                assert_scroll_target_reachable(scroll, widget)
            except AssertionError as exc:
                errors.append(f"{name}: {exc}")
        for name in ("run_preset_bar", "header_card", "_configuration_group", "_results_group", "_chart_stack", "log_view"):
            widget = getattr(page, name)
            print(name, widget.geometry(), "hint", widget.sizeHint(), "min", widget.minimumSize())
        scroll.ensureWidgetVisible(page.result_btn, 0, 4)
        QTest.qWait(100)
        frame.grab().save(str(OUTPUT / f"performance-results-{label}.png"))
        print(json.dumps({
            "label": label, "frame": [frame.width(), frame.height()],
            "page": [page.width(), page.height()], "horizontal_max": scroll.horizontalScrollBar().maximum(),
            "errors": errors, "preset": [page.run_preset_bar.width(), page.run_preset_bar.height()],
        }, ensure_ascii=False))
        page._set_running(False)
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
