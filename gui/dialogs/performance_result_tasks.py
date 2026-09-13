"""串行后台发现性能结果并解析曲线，GUI 只归档不可变快照和展示最新代次。"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot

from gui.i18n import tr
from services.mobileperf_runner import PerformanceArtifacts
from services.perf_chart_data import load_result_metrics


class PerformanceResultWorker(QThread):
    """结果发现必须完成归档义务；取消只跳过图表解析，不删除已有采集产物。"""

    artifacts_ready = Signal()

    def __init__(self, query, generation, active, exit_code, had_config, cancelled_run, parent,
                 present_result=True):
        super().__init__(parent)
        self.query = query
        self.generation = generation
        self.active = active
        self.exit_code = exit_code
        self.had_config = had_config
        self.cancelled_run = cancelled_run
        self.cancelled = threading.Event()
        self.artifacts = PerformanceArtifacts()
        self.metrics = {}
        self.chart_error = False
        self.present_result = present_result
        self.artifacts_delivered = False

    def abort(self):
        """非阻塞停止图表工作；正在执行的文件 I/O 保留真实退出屏障。"""
        self.cancelled.set()

    def run(self):
        try:
            self.artifacts = self.query.discover()
        except (OSError, ValueError, RuntimeError):
            self.artifacts = PerformanceArtifacts(error=True)
        self.artifacts_ready.emit()
        if self.cancelled.is_set() or not self.artifacts.result_dir:
            return
        try:
            self.metrics = load_result_metrics(
                self.artifacts.result_dir, cancelled=self.cancelled.is_set,
            )
            self.chart_error = not self.metrics and not self.cancelled.is_set()
        except (OSError, ValueError, RuntimeError):
            self.chart_error = True


class PerformanceResultLoader(QObject):
    """页面拥有单个活动读取线程，后续归档排队，曲线仅允许最新代次回填。"""

    def __init__(self, frame):
        super().__init__(frame)
        self.frame = frame
        self.generation = 0
        self._workers = []
        self._lock = threading.RLock()
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._poll)

    def invalidate(self):
        """新运行使旧图表失效，但既有运行的结果归档必须仍完成。"""
        self.generation += 1
        self.request_stop()

    def submit(self, query, *, active=None, exit_code=None, had_config=True, cancelled_run=False,
               present_result=True):
        worker = PerformanceResultWorker(
            query, self.generation, active, exit_code, had_config, cancelled_run, self,
            present_result=present_result,
        )
        if self.frame._closing:
            worker.abort()
        worker.artifacts_ready.connect(self._artifacts_ready, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._poll, Qt.ConnectionType.QueuedConnection)
        with self._lock:
            self._workers.append(worker)
            start = len(self._workers) == 1
        if start:
            self._start_worker(worker)

    def _start_worker(self, worker):
        """启动失败也交付错误归档；绝不在 GUI 补做发现或越过真实线程退出屏障。"""
        try:
            worker.start()
        except RuntimeError:
            if not worker.isRunning() and worker.wait(0):
                worker.artifacts = PerformanceArtifacts(error=True)
                worker.chart_error = True
                worker.artifacts_ready.emit()
            # 失败项无 finished 信号，用既有轮询在归档交付后推进队列。
            self._timer.start()

    @Slot()
    def _artifacts_ready(self):
        worker = self.sender()
        if not isinstance(worker, PerformanceResultWorker):
            return
        if worker.active is not None:
            self.frame._library_controller.finish(
                artifact_snapshot=worker.artifacts, active=worker.active,
                exit_code=worker.exit_code,
            )
        if (worker.present_result and worker.generation == self.generation
                and not self.frame._closing):
            self.frame._run_controller._present_finished_result(
                worker.artifacts, worker.had_config, worker.exit_code, worker.cancelled_run,
            )
        worker.artifacts_delivered = True

    @Slot()
    def _poll(self):
        with self._lock:
            worker = self._workers[0] if self._workers else None
        if worker is None:
            self._timer.stop()
            return
        # 线程退出与排队的归档槽交付是两个独立屏障，二者都满足才可释放页面。
        if worker.isRunning() or not worker.wait(0) or not worker.artifacts_delivered:
            self._timer.start()
            return
        if (worker.generation == self.generation and not worker.cancelled.is_set()
                and not self.frame._closing):
            self.frame.chart_view.set_series(
                {name: item.values for name, item in worker.metrics.items()},
            )
            self.frame.chart_status.setText(tr("Chart data could not be loaded.")
                                           if worker.chart_error else "")
        with self._lock:
            self._workers.remove(worker)
            following = self._workers[0] if self._workers else None
        worker.deleteLater()
        if following is not None:
            if self.frame._closing:
                following.abort()
            self._start_worker(following)
        else:
            self._timer.stop()
        if self.frame._closing:
            self.frame._poll_dispose_ready()

    def request_stop(self):
        """可从 supervisor 后台线程请求取消，不从后台接触控件或 QTimer。"""
        with self._lock:
            for worker in self._workers:
                worker.abort()

    def is_running(self):
        """列表保留到 GUI 终态回调且实际 QThread join 完成，包含排队归档义务。"""
        with self._lock:
            pending = (getattr(type(self.frame._runner), "freeze_result_query", None) is not None
                       and not self.frame._runner_finished_handled)
            return bool(self._workers) or pending

    def wait(self, timeout):
        """后台有界等待，GUI 事件循环继续处理归档与销毁回调。"""
        end = time.monotonic() + max(0, timeout)
        while self.is_running():
            remaining = end - time.monotonic()
            if remaining <= 0:
                return False
            threading.Event().wait(min(remaining, 0.01))
        return True
