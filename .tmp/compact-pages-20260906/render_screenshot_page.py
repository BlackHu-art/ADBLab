"""用隔离设置渲染实际截图工作区，不访问设备或写入用户配置。"""

import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "1"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QEvent, QSize
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.settings_manager import AppSettings, DEFAULTS
from gui.i18n import install_translators
from gui.styles import BaseStyles
from tests.test_main_window_layout import (
    _FakeScreen, _FakeScreenAdapter, _MainFrameSettings, build_main_frame,
)


def main():
    app = QApplication([])
    translators = install_translators(app, "zh_CN")
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        if (fonts / name).exists():
            QFontDatabase.addApplicationFont(str(fonts / name))
    settings = _MainFrameSettings()
    settings.values = dict(DEFAULTS)
    settings.values.update(theme="Dark", mica_enabled=False, font_family="Microsoft YaHei UI",
                           ui_font_size=12, window_width=1360, window_height=900,
                           continuous_scan=False)
    with patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)):
        BaseStyles.reload_from_settings()
        BaseStyles.switch_theme("Dark")
        frame = build_main_frame(settings=settings,
                                screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(2560, 1440))))
        try:
            frame.show()
            frame.resize(1360, 900)
            assert frame._open_workspace_feature("apps", "media")
            QTest.qWait(350)
            page = frame._workspace_feature_hosts["apps"].stack.currentWidget()
            assert page.header_card.isHidden()
            target = Path(__file__).with_name("screenshot-frame-after-dark-1360.png")
            assert frame.grab().save(str(target))
            print(target)
        finally:
            for host in frame._workspace_feature_hosts.values():
                host.shutdown()
            frame._unbind_window_screen()
            frame._close_ready = True
            frame.close()
            frame.deleteLater()
            QCoreApplication.sendPostedEvents(frame, QEvent.Type.DeferredDelete)
    assert translators


if __name__ == "__main__":
    main()
