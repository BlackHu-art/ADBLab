"""在独立进程中压力验证实时日志窗口的关闭生命周期。"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

# 直接运行探针脚本时，把项目根目录加入模块搜索路径。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.dialogs.live_logcat import LogcatWorker as RealLogcatWorker
from gui.main_frame import MainFrame

CYCLES = 10
TRAFFIC_TIMEOUT_SECONDS = 2.0
DESTROY_TIMEOUT_SECONDS = 2.0


class StreamingProcess:
    """模拟持续输出且可被 ProcessRunner 正常终止的 logcat 进程。"""

    def __init__(self):
        self.stdout = self
        self.returncode = None
        self._stopped = threading.Event()
        self._line = 0

    def readline(self):
        if self._stopped.wait(0.0002):
            return ""
        self._line += 1
        return f"07-25 12:00:00.000  1  1 I Tag: line-{self._line}\n"

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self._stopped.set()

    def kill(self):
        self.returncode = -9
        self._stopped.set()

    def wait(self, timeout=None):
        if not self._stopped.wait(timeout):
            raise subprocess.TimeoutExpired("fake-logcat", timeout)
        return self.returncode

    def close(self):
        self._stopped.set()


def run_probe() -> int:
    """连续关闭正在输出的日志窗口，并分类记录主窗口和应用退出事件。"""
    state = {
        "phase": "stress",
        "cycle": 0,
        "destroyed": 0,
        "main_close_phases": [],
        "last_window_closed_phases": [],
        "about_to_quit_phases": [],
        "error": None,
    }
    current = {}

    class ProbeMain(MainFrame):
        def closeEvent(self, event):
            state["main_close_phases"].append(state["phase"])
            super().closeEvent(event)

    app = QApplication([])
    app.lastWindowClosed.connect(
        lambda: state["last_window_closed_phases"].append(state["phase"])
    )
    app.aboutToQuit.connect(
        lambda: state["about_to_quit_phases"].append(state["phase"])
    )
    with (
        patch.object(MainFrame, "_bootstrap_adb_async", lambda self: None),
        patch.object(MainFrame, "_start_device_discovery", lambda self: None),
    ):
        frame = ProbeMain()
    frame.show()

    def fail(message: str):
        if state["error"] is not None:
            return
        state["error"] = message
        state["phase"] = "failed"
        frame._close_ready = True
        frame.close()
        QTimer.singleShot(0, app.quit)

    def make_worker(*args, **kwargs):
        worker = RealLogcatWorker(*args, **kwargs)
        process = StreamingProcess()

        def fake_start(key, *_args, **_kwargs):
            # 保留生产路径的实例级进程跟踪，否则停止请求无法找到进程。
            worker._process_runner._procs[key] = process
            return process

        worker._process_runner.start = fake_start
        current["process"] = process
        return worker

    def wait_for_destroy():
        if current.get("destroyed", False):
            if not frame.isVisible():
                fail("main window hidden while closing logcat")
                return
            if (
                state["main_close_phases"]
                or state["last_window_closed_phases"]
                or state["about_to_quit_phases"]
            ):
                fail("application exit path observed during logcat close")
                return
            if frame._active_dialogs:
                fail("destroyed logcat dialog is still retained")
                return
            state["destroyed"] += 1
            state["cycle"] += 1
            QTimer.singleShot(0, start_cycle)
            return
        if time.monotonic() >= current["deadline"]:
            fail("logcat dialog destruction timeout")
            return
        QTimer.singleShot(1, wait_for_destroy)

    def wait_for_traffic():
        dialog = current["dialog"]
        if len(dialog.entries) >= 100:
            dialog.close()
            current["deadline"] = time.monotonic() + DESTROY_TIMEOUT_SECONDS
            QTimer.singleShot(1, wait_for_destroy)
            return
        if time.monotonic() >= current["deadline"]:
            fail("continuous logcat traffic did not arrive")
            return
        QTimer.singleShot(1, wait_for_traffic)

    def start_cycle():
        if state["cycle"] >= CYCLES:
            if (
                state["main_close_phases"]
                or state["last_window_closed_phases"]
                or state["about_to_quit_phases"]
            ):
                fail("application exit path occurred before deliberate close")
                return
            state["phase"] = "deliberate"
            frame._close_ready = True
            frame.close()
            return

        current.clear()
        current["deadline"] = time.monotonic() + TRAFFIC_TIMEOUT_SECONDS
        dialog = frame._register_dialog(
            LiveLogcatDialog(
                device_ip="target",
                task_supervisor=frame.task_supervisor,
                log_service=frame.log_service,
            ),
            LiveLogcatDialog,
            "target",
        )
        current["dialog"] = dialog
        current["destroyed"] = False
        dialog.destroyed.connect(lambda *_args: current.__setitem__("destroyed", True))
        dialog.show()
        with patch("gui.dialogs.live_logcat.LogcatWorker", side_effect=make_worker):
            dialog._start()
        QTimer.singleShot(1, wait_for_traffic)

    QTimer.singleShot(0, start_cycle)
    QTimer.singleShot(
        8000,
        lambda: fail("global lifecycle timeout")
        if state["phase"] not in {"deliberate", "failed"}
        else None,
    )
    app.exec()
    print(json.dumps(state, sort_keys=True))
    passed = (
        state["error"] is None
        and state["destroyed"] == CYCLES
        and state["main_close_phases"] == ["deliberate"]
        and state["last_window_closed_phases"] == ["deliberate"]
        and state["about_to_quit_phases"] == ["deliberate"]
    )
    return 0 if passed else 4


if __name__ == "__main__":
    raise SystemExit(run_probe())
