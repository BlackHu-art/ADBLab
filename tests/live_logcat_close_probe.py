"""在独立进程中压力验证内嵌实时日志页的关闭生命周期。"""

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
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from gui.dialogs.live_logcat import LogcatWorker as RealLogcatWorker
from gui.features.base import FeatureSessionKey, FeatureSessionRegistry
from gui.features.logcat import LiveLogcatPage

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
        if self._stopped.is_set():
            return ""
        # Windows 的 Event.wait() 会把亚毫秒超时放大到系统时钟粒度；100 行
        # 可能因此虚耗约 1.5 秒。这里仅让出线程时间片，保持持续流量而不注入
        # 与被测生命周期无关的平台定时误差。
        time.sleep(0)
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
    """连续销毁正在输出的内嵌日志会话，并记录应用退出事件。"""
    state = {
        "phase": "stress",
        "cycle": 0,
        "destroyed": 0,
        "cycle_timings_ms": [],
        "main_close_phases": [],
        "last_window_closed_phases": [],
        "about_to_quit_phases": [],
        "error": None,
    }
    current = {}

    class ProbeMain(QMainWindow):
        def closeEvent(self, event):
            state["main_close_phases"].append(state["phase"])
            super().closeEvent(event)

    app = QApplication([])
    app.lastWindowClosed.connect(lambda: state["last_window_closed_phases"].append(state["phase"]))
    app.aboutToQuit.connect(lambda: state["about_to_quit_phases"].append(state["phase"]))
    frame = ProbeMain()
    stack = QStackedWidget(frame)
    frame.setCentralWidget(stack)
    registry = FeatureSessionRegistry(frame)
    task_supervisor = QtTaskSupervisor()
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
            current["destroyed_at"] = time.monotonic()
            state["cycle_timings_ms"].append(
                {
                    "construct": round(
                        (current["created_at"] - current["started_at"]) * 1000,
                        1,
                    ),
                    "show_and_traffic": round(
                        (current["traffic_at"] - current["created_at"]) * 1000,
                        1,
                    ),
                    "cleanup": round(
                        (current["destroyed_at"] - current["traffic_at"]) * 1000,
                        1,
                    ),
                    "entries_at_close": current["entries_at_close"],
                }
            )
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
            if registry.get(current["key"]) is not None:
                fail("destroyed logcat page is still retained")
                return
            state["destroyed"] += 1
            state["cycle"] += 1
            QTimer.singleShot(0, start_cycle)
            return
        if time.monotonic() >= current["deadline"]:
            fail("logcat page disposal timeout")
            return
        QTimer.singleShot(1, wait_for_destroy)

    def wait_for_traffic():
        page = current["page"]
        if len(page.entries) >= 100:
            current["traffic_at"] = time.monotonic()
            current["entries_at_close"] = len(page.entries)
            if registry.request_dispose(current["key"], "probe_cycle"):
                fail("active logcat page disposed before worker cleanup")
                return
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
        current["started_at"] = time.monotonic()
        current["deadline"] = time.monotonic() + TRAFFIC_TIMEOUT_SECONDS
        key = FeatureSessionKey("logcat", "target", state["cycle"])
        page, created = registry.get_or_create(
            key,
            lambda _key: LiveLogcatPage(
                device_ip="target",
                task_supervisor=task_supervisor,
            ),
        )
        if not created:
            fail("logcat page session was unexpectedly reused")
            return
        page.setParent(stack)
        stack.addWidget(page)
        registry.activate(key)
        stack.setCurrentWidget(page)
        current["created_at"] = time.monotonic()
        current["key"] = key
        current["page"] = page
        current["destroyed"] = False
        page.destroyed.connect(lambda *_args: current.__setitem__("destroyed", True))
        with patch("gui.dialogs.live_logcat.LogcatWorker", side_effect=make_worker):
            page._start()
        QTimer.singleShot(1, wait_for_traffic)

    QTimer.singleShot(0, start_cycle)
    QTimer.singleShot(
        8000,
        lambda: (
            fail("global lifecycle timeout")
            if state["phase"] not in {"deliberate", "failed"}
            else None
        ),
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
