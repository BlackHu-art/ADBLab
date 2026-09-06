"""以合成方案检查性能采集页的方案入口，不连接设备或写入用户测试库。"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea
from core.settings_manager import AppSettings, DEFAULTS
from gui.dialogs.performance_launcher import PerformancePage
from gui.styles import BaseStyles
from tests.test_performance_library import _Library, _Runner

class _Settings:
    save_directory = "E:/ADBLab-results"
    values = dict(DEFAULTS)

    def get(self, key, default=None):
        return self.values.get(key, default)

app = QApplication.instance() or QApplication([])
fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
    QFontDatabase.addApplicationFont(str(fonts / name))
settings = _Settings()
settings.values = dict(DEFAULTS)
target = Path(__file__).parent
for width, size, theme in ((1092, 12, "Light"), (740, 22, "Dark"), (380, 22, "Dark")):
    settings.values.update(theme=theme, mica_enabled=False, ui_font_size=size,
                           font_family="Microsoft YaHei UI", log_font_size=size)
    with patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)):
        BaseStyles.reload_from_settings()
        BaseStyles.switch_theme(theme)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = PerformancePage("demo-device", "com.example.demo")
        page._runner = _Runner()
        library = _Library()
        page.set_run_library(library)
        library.save_preset("10分钟稳定性测试", "performance", page.capture_run_parameters())
        page.prepare_for_workspace()
        scroll.setWidget(page)
        scroll.resize(width, 900)
        scroll.show()
        QTest.qWait(150)
        bar = page.run_preset_bar
        for control in (bar.combo, bar.load_button, bar.save_button, bar.delete_button):
            bounds = QRect(control.mapTo(bar, QPoint()), control.size())
            print(width, size, control.objectName(), control.size(), control.font().pointSize(),
                  "contained", bar.rect().contains(bounds))
        suffix = f"{theme.lower()}-{width}-font{size}"
        scroll.grab().save(str(target / f"performance-library-{suffix}.png"))
        page.grab().save(str(target / f"performance-library-page-{suffix}.png"))
        bar.grab().save(str(target / f"performance-preset-bar-{suffix}.png"))
        page.request_dispose("render")
        scroll.close()
        app.processEvents()
