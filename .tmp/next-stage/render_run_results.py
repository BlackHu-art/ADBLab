"""使用临时记录渲染结果面板，不读取用户历史或访问设备。"""

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget

from gui.run_library import RunLibraryController
from gui.styles import BaseStyles
from gui.styles.typography import FontConfig, typography_manager
from gui.widgets.run_results import RunResultsWidget
from services.run_library import RunArtifact, RunLibrary, RunRecord
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until

app = QApplication([])
for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
    QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / filename))

with tempfile.TemporaryDirectory(prefix="adblab-results-preview-") as directory:
    source = RunLibrary(Path(directory) / "results.json")
    for index in range(8):
        end = time.time() - index * 1800
        source.record_run(RunRecord(
            str(index), "monkey" if index % 2 == 0 else "performance",
            "com.example.shopping" if index % 2 == 0 else "com.example.video",
            end - 373, end, ("succeeded", "failed", "partial", "cancelled")[index % 4],
            {"seed": 42, "event_count": 10000, "throttle_ms": 300, "ignore_crashes": False},
            (RunArtifact("运行日志", str(Path(directory) / "monkey.log")),),
            device_label="Pixel 测试机", app_version="3.2.1 (104)",
            message="测试完成，运行日志已保存在输出目录。",
        ))
    controller = RunLibraryController(source)
    wait_until(app, lambda: len(controller.records) == 8)
    for theme, width, height, size in (("Light", 1080, 740, 12), ("Dark", 540, 860, 22)):
        BaseStyles.switch_theme(theme)
        config = FontConfig("Microsoft YaHei", size, 12, "Consolas")
        BaseStyles._sync_legacy_values(config)
        typography_manager.apply(config)
        app.setFont(QFont("Microsoft YaHei", size))
        panel = RunResultsWidget(controller)
        content = QWidget()
        content.setAutoFillBackground(True)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(panel)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.resize(width, height)
        scroll.show()
        panel.parameters_section.toggle_button.setChecked(True)
        wait_for_stable_geometry(app, (scroll, content, panel, panel.table, panel.action_row))
        assert scroll.horizontalScrollBar().maximum() == 0
        prefix = ROOT / ".tmp/next-stage" / f"run-results-{theme.lower()}-{width}-font{size}"
        assert scroll.grab().save(str(prefix) + ".png")
        scroll.ensureWidgetVisible(panel.reuse_button)
        app.processEvents()
        assert scroll.grab().save(str(prefix) + "-bottom.png")
        print(theme, "content", content.size(), "table", panel.table.size(), "scroll", scroll.verticalScrollBar().maximum())
        scroll.close()
        scroll.deleteLater()
        QCoreApplication.sendPostedEvents(scroll, QEvent.Type.DeferredDelete)
    assert controller.shutdown()
    controller.deleteLater()
    QCoreApplication.sendPostedEvents(controller, QEvent.Type.DeferredDelete)
