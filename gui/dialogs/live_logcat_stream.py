"""提供 Logcat 过滤、内容更新、采集与日志摄入的流式控制器。"""

import os
import tempfile
import uuid
from collections import deque
from datetime import datetime
from math import ceil

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPlainTextEdit

from gui.dialogs.live_logcat_worker import (
    LEVEL_ORDER,
    CurrentPackageWorker,
    LogcatBatch,
    LogcatTermination,
    LogcatTerminationKind,
    LogcatWorker,
)


class LiveLogcatStream:
    """组合进 LiveLogcatDialog 的流式控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    # ── 筛选 ────────────────────────────────────────────────────────────

    def _min_level(self):
        code = self._frame.level_combo.currentData()
        return LEVEL_ORDER.get(code, -1) if code else None

    def _passes(self, level: str, tag_part: str) -> bool:
        minimum = self._min_level()
        if minimum is not None and LEVEL_ORDER.get(level, -1) < minimum:
            return False
        tag_filter = self._frame.tag_input.text().strip()
        if tag_filter and tag_filter.lower() not in tag_part.lower():
            return False
        return True

    def _rebuild(self):
        self._frame._line_flush_timer.stop()
        self._frame._pending_visible_lines.clear()
        self._frame.output.clear()
        visible = [t for t, lv, tg, _ in self._frame.entries if self._passes(lv, tg)]
        if visible:
            self._frame.output.setPlainText("\n".join(visible) + "\n")
        self._update_content_actions(bool(visible))

    def _schedule_filter_rebuild(self, _text: str = ""):
        """合并连续输入，避免每个按键都完整重建日志文档。"""

        self._frame._filter_rebuild_timer.start()

    def _update_content_actions(self, has_visible_content: bool | None = None):
        """按已知可见状态更新动作，避免复制整份日志文档。"""

        if has_visible_content is None:
            has_visible_content = not self._frame.output.document().isEmpty()
        self._frame.clear_btn.setEnabled(bool(self._frame.entries) or has_visible_content)
        self._frame.export_btn.setEnabled(has_visible_content)

    # ── 操作 ────────────────────────────────────────────────────────────

    def _fetch_current_pkg(self):
        if self._frame._pkg_worker and self._frame._pkg_worker.isRunning():
            return
        self._frame.status_bar.showMessage("Fetching current package...")
        self._frame.btn_get_pkg.setEnabled(False)
        worker = CurrentPackageWorker(self._frame.device_ip)
        worker.package_ready.connect(self._frame._on_current_pkg)
        worker.status_changed.connect(self._frame._on_status)
        finished_handler = self._frame._on_pkg_worker_finished_signal
        worker._dialog_finished_handler = finished_handler
        worker.finished.connect(finished_handler, Qt.ConnectionType.QueuedConnection)
        task_id = f"current-package-{uuid.uuid4()}"
        worker._supervisor_task_id = task_id
        try:
            self._frame._task_supervisor.supervisor.register(
                task_id,
                owner_id=self._frame._supervisor_owner_id,
                kind="current_package_probe",
                request_stop=worker.requestInterruption,
                wait=lambda timeout, _worker=worker: _worker.wait(max(0, ceil(timeout * 1000))),
                is_running=worker.isRunning,
            )
        except Exception:
            self._frame._disconnect_pkg_worker(worker)
            worker.deleteLater()
            self._frame.btn_get_pkg.setEnabled(True)
            self._frame.status_bar.showMessage("Unable to supervise package lookup")
            return
        self._frame._pkg_worker = worker
        worker.start()

    def _start(self):
        from gui.dialogs import live_logcat as _live_logcat

        if self._frame.worker and self._frame.worker.is_active():
            return
        self._frame._worker_release_timer.stop()
        self._frame.entries.clear()
        self._frame._pending_visible_lines.clear()
        self._frame._line_flush_timer.stop()
        self._frame.output.clear()
        self._update_content_actions(False)
        pkg = self._frame.pkg_input.text().strip()
        tag = self._frame.tag_input.text().strip()
        worker = _live_logcat.LogcatWorker(self._frame.device_ip, package=pkg, tag=tag)
        task_id = f"live-logcat-{uuid.uuid4()}"
        lines_handler = self._frame._on_lines_signal
        dropped_handler = self._frame._on_dropped_signal
        status_handler = self._frame._on_worker_status_signal
        ended_handler = self._frame._on_worker_terminated_signal
        finished_handler = self._frame._on_worker_finished_signal
        worker._dialog_lines_handler = lines_handler
        worker._dialog_dropped_handler = dropped_handler
        worker._dialog_status_handler = status_handler
        worker._dialog_ended_handler = ended_handler
        worker._dialog_finished_handler = finished_handler
        worker._supervisor_task_id = task_id
        connection_type = Qt.ConnectionType.QueuedConnection
        worker.lines_ready.connect(lines_handler, connection_type)
        worker.dropped_ready.connect(dropped_handler, connection_type)
        worker.status_changed.connect(status_handler, connection_type)
        worker.terminated.connect(ended_handler, connection_type)
        worker.finished.connect(finished_handler, connection_type)
        try:
            self._frame._task_supervisor.supervisor.register(
                task_id,
                owner_id=self._frame._supervisor_owner_id,
                kind="live_logcat",
                request_stop=worker.request_stop,
                wait=worker.wait_for_stop,
                is_running=worker.is_active,
                force_stop=worker.force_stop,
            )
        except Exception:
            self._frame.status_bar.showMessage("Unable to supervise logcat task")
            worker.deleteLater()
            return
        self._frame.worker = worker
        self._frame._supervisor_task_id = task_id
        self._frame._set_running_actions(True)
        worker.start()

    def _stop(self):
        if self._frame.worker and self._frame._supervisor_task_id:
            self._frame.status_bar.showMessage("Stopping...")
            self._frame._set_running_actions(True, stopping=True)
            self._frame._task_supervisor.stop_async(self._frame._supervisor_task_id)

    def _clear(self):
        self._frame.entries.clear()
        self._frame._pending_visible_lines.clear()
        self._frame._line_flush_timer.stop()
        self._frame.output.clear()
        self._frame.status_bar.showMessage("Cleared")
        self._update_content_actions(False)

    def _toggle_wrap(self):
        if self._frame.wrap_btn.isChecked():
            self._frame.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            self._frame.output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._frame.wrap_btn.setText("Wrap")
            self._frame.status_bar.showMessage("Line wrap: ON")
        else:
            self._frame.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self._frame.output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self._frame.wrap_btn.setText("No Wrap")
            self._frame.status_bar.showMessage("Line wrap: OFF - horizontal scroll enabled")

    def _export(self):
        from core.settings_manager import AppSettings

        save_dir = AppSettings.instance().save_directory
        name = f"logcat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        fp, _ = QFileDialog.getSaveFileName(
            self._frame,
            "Export",
            os.path.join(save_dir, name),
            "Text Files (*.txt);;All Files (*)",
        )
        if fp:
            try:
                text = self._frame.output.toPlainText()
                # 先写临时文件再原子替换，避免中途失败留下半截日志文件。
                directory = os.path.dirname(os.path.abspath(fp))
                fd, tmp_path = tempfile.mkstemp(prefix=".logcat_", suffix=".tmp", dir=directory)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(text)
                    os.replace(tmp_path, fp)
                except BaseException:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
                self._frame.status_bar.showMessage(f"Exported to {fp}")
            except OSError as e:
                QMessageBox.critical(
                    self._frame,
                    "Error",
                    str(e),
                    QMessageBox.StandardButton.Ok,
                    QMessageBox.StandardButton.NoButton,
                )

    # ── 信号槽 ──────────────────────────────────────────────────────────

    def _on_lines_signal(self, batch: LogcatBatch):
        """通过对话框 QObject 槽接收批次，避免匿名回调越过窗口生命周期。"""
        worker = self._frame.sender()
        if worker is not None:
            self._on_lines(worker, batch)

    def _on_dropped_signal(self, count: int):
        """接收当前工作线程报告的背压丢弃数量。"""
        worker = self._frame.sender()
        if worker is not None:
            self._on_dropped(worker, count)

    def _on_worker_status_signal(self, message: str):
        """接收当前工作线程的状态变更。"""
        worker = self._frame.sender()
        if worker is not None:
            self._on_worker_status(worker, message)

    def _on_worker_terminated_signal(self, result: LogcatTermination):
        """接收当前工作线程的终止语义。"""
        worker = self._frame.sender()
        if worker is not None:
            self._on_worker_terminated(worker, result)

    def _on_worker_finished_signal(self):
        """在线程 finished 信号到达 GUI 线程后释放工作对象。"""
        worker = self._frame.sender() or self._frame.worker
        if worker is not None:
            self._frame._on_worker_finished(worker)

    def _on_pkg_worker_finished_signal(self):
        """在包名查询线程 finished 信号到达 GUI 线程后释放工作对象。"""
        worker = self._frame.sender() or self._frame._pkg_worker
        if worker is not None:
            self._frame._on_pkg_worker_finished(worker)

    @staticmethod
    def _extract_tag(line: str) -> str:
        """从 threadtime 格式日志中提取 TAG 字段。"""
        parts = line.split(None, 6)
        if len(parts) >= 6:
            tag_raw = parts[5]
            if tag_raw.endswith(":"):
                return tag_raw[:-1]
        return ""

    def _on_line(self, text: str, level: str, pid: int = 0):
        if self._frame._closing:
            return
        tag_part = self._extract_tag(text)
        if not isinstance(self._frame.entries, deque):
            self._frame.entries = deque(self._frame.entries, maxlen=self._frame.MAX_BUFFER)
        self._frame.entries.append((text, level, tag_part, pid))
        if self._passes(level, tag_part):
            self._frame._pending_visible_lines.append(text)
            self._schedule_line_flush()
        self._frame.clear_btn.setEnabled(True)

    def _on_lines(self, worker: LogcatWorker, batch: LogcatBatch):
        try:
            if self._frame._closing or self._frame.worker is not worker:
                return
            if batch.dropped_before:
                self._frame.status_bar.showMessage(
                    f"Logcat running; {batch.dropped_before} lines dropped under load"
                )
            for text, level, pid in batch.lines:
                self._on_line(text, level, pid)
        finally:
            worker.acknowledge_batch()

    def _on_dropped(self, worker: LogcatWorker, count: int):
        if not self._frame._closing and self._frame.worker is worker:
            self._frame.status_bar.showMessage(f"Logcat running; {count} lines dropped under load")

    def _schedule_line_flush(self):
        if not self._frame._line_flush_timer.isActive():
            self._frame._line_flush_timer.start(75)

    def _flush_pending_lines(self):
        if self._frame._closing or not self._frame._pending_visible_lines:
            return
        lines = self._frame._pending_visible_lines
        self._frame._pending_visible_lines = deque(maxlen=self._frame.MAX_BUFFER)
        # 高频 logcat 输出合并成一次 QTextDocument 更新，Stop/过滤按钮会更容易抢到事件循环。
        self._frame.output.appendPlainText("\n".join(lines))
        self._frame.output.moveCursor(QTextCursor.MoveOperation.End)
        self._frame.output.ensureCursorVisible()
        self._update_content_actions(True)

    def _on_status(self, msg: str):
        if self._frame._closing:
            return
        self._frame.status_bar.showMessage(msg)

    def _on_worker_status(self, worker: LogcatWorker, msg: str):
        if self._frame.worker is worker:
            self._on_status(msg)

    def _on_worker_terminated(self, worker: LogcatWorker, result: LogcatTermination):
        if self._frame._closing or self._frame.worker is not worker:
            return
        if result.kind is LogcatTerminationKind.CANCELLED:
            self._frame.status_bar.showMessage("Logcat stop requested")
        elif result.kind is LogcatTerminationKind.START_FAILED:
            self._frame.status_bar.showMessage("Logcat failed to start")
        else:
            self._frame.status_bar.showMessage("Logcat ended unexpectedly")
