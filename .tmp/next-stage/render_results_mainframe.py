"""在完整设置、用户目录与设备依赖隔离下渲染真实任务中心宿主。"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ISOLATION = tempfile.TemporaryDirectory(prefix="adblab-task-host-")
os.environ["LOCALAPPDATA"] = ISOLATION.name

from PySide6.QtCore import QCoreApplication, QEvent, QSize
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from core.settings_manager import AppSettings
from gui.styles import BaseStyles
from services.run_library import RunArtifact, RunLibrary, RunRecord
from tests.test_main_window_layout import (
    _FakeScreen, _FakeScreenAdapter, _MainFrameSettings, build_main_frame,
)
from tests.ui_geometry_helpers import (
    assert_contained, assert_scroll_target_reachable, wait_for_stable_geometry, wait_until,
)

app = QApplication([])
for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
    QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / filename))
data = Path(ISOLATION.name)
settings = _MainFrameSettings()
settings.save_directory = str(data)
settings.values.update({
    "window_width": 1200, "window_height": 900,
    "theme": "Light", "font_family": "Microsoft YaHei", "ui_font_size": 12,
    "continuous_device_scan": False, "mica_enabled": False,
})
controller = Mock()
controller.signals = Mock()
with (
    patch.object(AppSettings, "instance", classmethod(lambda _cls: settings)),
    patch("services.run_library.user_config_path", lambda filename: str(data / filename)),
    patch("core.exec.CommandRunner.run", side_effect=AssertionError("unexpected device command")),
):
    source = RunLibrary(data / "test_runs.json")
    for index in range(8):
        finish = time.time() - index * 600
        source.record_run(RunRecord(
            str(index), "monkey" if index % 2 == 0 else "performance",
            "com.example.shopping" if index % 2 == 0 else "com.example.video",
            finish - 373, finish,
            ("succeeded", "failed", "partial", "cancelled")[index % 4],
            {"seed": 42, "event_count": 10000},
            (RunArtifact("运行日志", str(data / "run.log")),),
            "Pixel 测试机", "3.2.1 (104)", "测试已结束，结果附件保存在原输出目录。",
        ))
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme("Light")
    app.setFont(BaseStyles.get_default_font())
    frame = build_main_frame(
        settings=settings, controller=controller,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("preview", QSize(1600, 1100))),
    )
    try:
        for index in range(80):
            frame._task_history.record_completed("file_pull", True, f"模拟本次操作 {index}")
        frame.show()
        frame.resize(1200, 900)
        frame._on_nav_requested("tasks")
        results = frame._task_page.run_results
        wait_until(app, lambda: results.table.rowCount() == 8)
        frame._task_page.refresh()
        wait_for_stable_geometry(app, (frame, frame._task_page, results, results.table))
        assert frame.size() == QSize(1200, 900)
        assert not results.parameters_section.toggle_button.isChecked()
        assert results.selected_record is not None
        assert results.table.horizontalScrollBar().maximum() == 0
        for widget in (results.filters, results.table, results.action_row):
            assert_contained(widget, results)
        assert frame.grab().save(str(ROOT / ".tmp/next-stage/task-results-mainframe-light-1200x900.png"))
        assert_scroll_target_reachable(frame._task_page._scroll, results.reuse_button)
        assert frame.grab().save(str(ROOT / ".tmp/next-stage/task-results-mainframe-light-1200x900-bottom.png"))
        print("frame", frame.size(), "results", results.size(), "scroll", frame._task_page._scroll.verticalScrollBar().maximum())
        print("controller calls", controller.refresh_devices.call_count)
    finally:
        frame.run_library.shutdown()
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
        frame.deleteLater()
        QCoreApplication.sendPostedEvents(frame, QEvent.Type.DeferredDelete)
ISOLATION.cleanup()
