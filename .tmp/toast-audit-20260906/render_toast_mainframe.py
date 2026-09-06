"""在隔离的真实 MainFrame 中核对 Toast，不访问桌面、用户配置或设备。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for variable in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME"):
    os.environ[variable] = str(OUTPUT / "isolated-preview-user")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from core.exec import CommandRunner
from core.settings_manager import AppSettings, DEFAULTS
from gui.i18n import install_translators, tr
from gui.notifications import ToastNotification, show_toast
from gui.styles import BaseStyles
from models.device_store import DeviceStore
from services.run_library import RunLibrary
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)
from tests.test_performance_responsive import _RunnerProbe


def rectangle(widget, owner):
    rect = QRect(widget.mapTo(owner, QPoint()), widget.size())
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=("package", "action"))
    args = parser.parse_args()
    is_package = args.scenario == "package"
    theme, height, font_size = ("Dark", 1000, 12) if is_package else ("Light", 800, 22)
    app = QApplication.instance() or QApplication([])
    translators = install_translators(app, "zh_CN")
    font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        font_file = font_directory / name
        if font_file.exists():
            QFontDatabase.addApplicationFont(str(font_file))
    settings = _MainFrameSettings()
    settings.values = dict(DEFAULTS)
    settings.values.update(
        theme=theme, mica_enabled=False, font_family="Microsoft YaHei UI",
        ui_font_size=font_size, log_font_size=12, window_width=860,
        window_height=height, save_directory="E:/ADBLab-preview-results",
        continuous_scan=False,
    )
    settings.save_directory = "E:/ADBLab-preview-results"
    with (
        patch.object(AppSettings, "instance", classmethod(lambda cls: settings)),
        patch.object(DeviceStore, "get_full_devices_info", return_value=[]),
        patch.object(RunLibrary, "for_user", classmethod(lambda cls: cls())),
        patch.object(CommandRunner, "run", side_effect=AssertionError("Device I/O is prohibited")),
    ):
        BaseStyles.reload_from_settings()
        BaseStyles.switch_theme(theme)
        frame = build_main_frame(
            settings=settings,
            screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(2560, 1440))),
        )
        page = None
        try:
            frame.show()
            frame.resize(860, height)
            frame._on_devices_updated(["demo-device"])
            frame.left_panel._devices_tab.set_selected_devices(["demo-device"])
            host = frame._workspace_feature_hosts["system"]
            host.set_device_context(["demo-device"], ["demo-device"])
            assert frame._open_workspace_feature("system", "performance", device_id="demo-device")
            page = host.stack.currentWidget()
            runner = _RunnerProbe()
            page._runner = runner
            page.package_edit.clear()
            QTest.qWait(350)
            host.content_scroll.verticalScrollBar().setValue(0)
            frame.activateWindow()
            frame.windowHandle().requestActivate()
            action_calls = []
            if is_package:
                assert page.start_btn.isEnabled()
                assert page._can_operate_device()
                page.start_btn.click()
                toast, = frame.findChildren(ToastNotification)
                assert toast.titleLabel.text() == tr("Package Required")
                assert toast.content_edit.toPlainText() == tr("Please enter a package name.")
                assert runner.start_count == 0
            else:
                toast = show_toast(
                    frame, "截图已完成", "结果已加入“截图结果”页面。", level="success",
                    duration=-1, action_text="查看结果", on_action=lambda: action_calls.append(True),
                )
                assert toast is not None
            QTest.qWait(180)
            notice_rect = QRect(toast.pos(), toast.size())
            title_rect = QRect(frame.titleBar.mapTo(frame, QPoint()), frame.titleBar.size())
            assert frame.rect().contains(notice_rect)
            assert not title_rect.intersects(notice_rect)
            assert toast.content_edit.horizontalScrollBar().maximum() == 0
            assert toast.titleLabel.height() >= toast.titleLabel.heightForWidth(toast.titleLabel.width())
            report = {
                "scenario": args.scenario,
                "theme": theme,
                "requested_frame": [860, height],
                "frame": [frame.width(), frame.height()],
                "font_points": font_size,
                "device_pixel_ratio": frame.devicePixelRatioF(),
                "titlebar": rectangle(frame.titleBar, frame),
                "toast": rectangle(toast, frame),
                "title": toast.titleLabel.text(),
                "body": toast.content_edit.toPlainText(),
                "body_horizontal_max": toast.content_edit.horizontalScrollBar().maximum(),
                "body_vertical_max": toast.content_edit.verticalScrollBar().maximum(),
                "titlebar_overlap": False,
                "action": None,
                "runner_starts": runner.start_count,
                "source": "Isolated MainFrame QWidget.grab, no desktop capture or device I/O",
            }
            if toast.action_button is not None:
                button = toast.action_button
                action_rect = QRect(button.mapTo(toast, QPoint()), button.size())
                assert toast.rect().contains(action_rect)
                assert button.text() == "查看结果"
                assert button.width() >= button.sizeHint().width()
                report["action"] = {
                    "text": button.text(),
                    "frame_rectangle": rectangle(button, frame),
                    "size_hint": [button.sizeHint().width(), button.sizeHint().height()],
                }
            filename = f"toast-mainframe-{args.scenario}-{theme.lower()}-860x{height}-font{font_size}"
            assert frame.grab().save(str(OUTPUT / f"{filename}.png"))
            if toast.action_button is not None:
                QTest.mouseClick(toast.action_button, Qt.MouseButton.LeftButton)
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                app.processEvents()
                assert action_calls == [True]
                assert not isValid(toast)
                assert not frame.findChildren(ToastNotification)
                report["action_clicks"] = len(action_calls)
                report["closed_after_action"] = True
            else:
                toast.close()
            (OUTPUT / f"{filename}.json").write_text(
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


if __name__ == "__main__":
    main()
