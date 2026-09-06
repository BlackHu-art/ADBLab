"""在隔离主窗口和窄窗口中渲染单行通知，不访问设备或用户数据。"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

OUTPUT = Path(__file__).resolve().parent
os.environ["QT_QPA_PLATFORM"] = "offscreen"
for variable in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
    os.environ[variable] = str(OUTPUT / "isolated-user")
sys.path.insert(0, str(Path.cwd()))

from PySide6.QtCore import QCoreApplication, QEvent, QSize
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from core.exec import CommandRunner
from core.settings_manager import AppSettings, DEFAULTS
from gui.notifications import show_toast
from gui.styles import BaseStyles
from models.device_store import DeviceStore
from services.run_library import RunLibrary
from tests.test_main_window_layout import (
    _FakeScreen, _FakeScreenAdapter, _MainFrameSettings, build_main_frame,
)

app = QApplication([])
for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
    QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / name))

for theme, size, width in (("Light", 12, 860), ("Dark", 22, 860), ("Dark", 22, 360)):
    settings = _MainFrameSettings()
    settings.values = dict(DEFAULTS, theme=theme, mica_enabled=False, continuous_scan=False,
                           font_family="Microsoft YaHei UI", ui_font_size=size,
                           window_width=width, window_height=800)
    with (
        patch.object(AppSettings, "instance", classmethod(lambda cls: settings)),
        patch.object(DeviceStore, "get_full_devices_info", return_value=[]),
        patch.object(RunLibrary, "for_user", classmethod(lambda cls: cls())),
        patch.object(CommandRunner, "run", side_effect=AssertionError("No device I/O")),
    ):
        BaseStyles.reload_from_settings()
        BaseStyles.switch_theme(theme)
        if width >= 860:
            owner = build_main_frame(
                settings=settings,
                screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(2560, 1440))),
            )
        else:
            owner = QWidget()
            owner.setStyleSheet(f"background:{BaseStyles.color('WINDOW_BG')};")
        owner.resize(width, 800)
        owner.show()
        QTest.qWait(100)
        toast = show_toast(
            owner, "截图已完成", "结果已加入“截图与屏幕”页面。", level="success",
            duration=-1, action_text="查看结果", on_action=lambda: None,
        )
        QTest.qWait(120)
        assert owner.rect().contains(toast.geometry())
        controls = (toast.iconWidget, toast.titleLabel, toast.content_edit,
                    toast.action_button, toast.closeButton)
        for control in controls:
            assert toast.rect().contains(control.geometry())
        filename = f"toast-single-{theme.lower()}-{width}-font{size}"
        if owner.devicePixelRatioF() != 1:
            filename += f"-dpi{owner.devicePixelRatioF():g}"
        assert owner.grab().save(str(OUTPUT / f"{filename}.png"))
        print(filename, "toast", toast.geometry(), "title", toast.titleLabel.text(),
              "body", toast.content_edit.geometry(), "body text width",
              toast.content_edit.fontMetrics().horizontalAdvance(toast.content_edit.text()),
              "action", toast.action_button.text(), flush=True)
        if width >= 860:
            owner.run_library.shutdown()
            owner.left_panel.shutdown()
            owner._unbind_window_screen()
            owner._close_ready = True
        owner.close()
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
