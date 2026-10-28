"""隔离进程验证真实主窗销毁等待 Logcat 导出，不访问设备或外部进程。"""

import json
import platform
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
platform.uname()


def deny_external_io(event, _args):
    """探针只使用本地合成数据；禁止真实网络、ADB 和外部 helper。"""
    if event in {"socket.connect", "subprocess.Popen", "os.system", "os.startfile",
                 "os.startfile/2"}:
        raise RuntimeError("PROBE_BOUNDARY_BLOCKED:" + event)


sys.addaudithook(deny_external_io)

def run_probe():
    from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThread, Signal
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid

    from core.settings_manager import AppSettings
    from gui.features import FeatureSessionKey, FeatureSessionRegistry
    from gui.features.logcat import LiveLogcatPage
    from tests.test_main_window_layout import build_main_frame

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    settings = AppSettings.instance()
    release = threading.Event()
    state = {"main_destroyed": False, "page_destroyed": False}

    class Export(QThread):
        completed = Signal(bool, str)

        def __init__(self, _text, _path, parent):
            super().__init__(parent)

        def run(self):
            if not release.wait(3):
                raise RuntimeError("export release timeout")
            self.completed.emit(True, "")

    frame = build_main_frame(settings=settings)
    frame.SHUTDOWN_DEADLINE_SECONDS = 0.04
    frame.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    frame.destroyed.connect(lambda: state.update(main_destroyed=True))
    registry = FeatureSessionRegistry(frame)
    key = FeatureSessionKey("logcat", "synthetic")
    page, _ = registry.get_or_create(key, lambda _key: LiveLogcatPage(
        frame, device_ip="synthetic", task_supervisor=frame.task_supervisor,
    ))
    page.destroyed.connect(lambda: state.update(page_destroyed=True))

    class Host:
        def register_shutdown_tasks(self, *args, **kwargs):
            return registry.register_shutdown_tasks(*args, **kwargs)

        def shutdown(self):
            registry.request_dispose_all()

    host = Host()
    host.registry = registry
    frame._workspace_feature_hosts["synthetic_export"] = host
    frame.show()
    page._on_line("synthetic log", "I")
    with (
        patch("gui.features.logcat.stream.LogcatExportWorker", Export),
        patch("gui.features.logcat.stream.QFileDialog.getSaveFileName",
              return_value=(str(Path(settings.save_directory) / "synthetic.txt"), "")),
    ):
        page._export()
    worker = page._stream_controller._export_worker
    assert worker is not None and worker.isRunning()
    frame.close()
    assert not frame._close_ready
    app.processEvents()
    assert isValid(frame) and not frame._close_ready and worker.isRunning()
    state["blocked_before_join"] = True
    deadline = time.monotonic() + 2
    while (
        not getattr(frame, "_shutdown_native_join_pending", False)
        and time.monotonic() < deadline
    ):
        app.processEvents()
        time.sleep(0.001)
    assert isValid(frame) and not frame._close_ready and worker.isRunning()
    assert frame._shutdown_native_join_pending
    assert time.monotonic() >= frame._shutdown_deadline_at
    assert not state["main_destroyed"] and not state["page_destroyed"]
    state["blocked_after_deadline"] = True
    release.set()
    assert worker.wait(2000)
    deadline = time.monotonic() + 5
    while isValid(frame) and time.monotonic() < deadline:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.001)
    assert state["page_destroyed"] and state["main_destroyed"], state
    settings.close()
    print(json.dumps(state), flush=True)


if __name__ == "__main__":
    run_probe()
