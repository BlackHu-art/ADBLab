"""提供 Logcat 过滤、内容更新、采集与日志摄入的流式控制器。"""

import os
import re
import tempfile
import uuid
import weakref
from collections import deque
from datetime import datetime
from math import ceil

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog, QPlainTextEdit

from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.dialogs.lifecycle import is_qobject_alive, safe_disconnect
from gui.i18n import tr
from utils.adb_values import normalize_android_package

from .worker import (
    LEVEL_ORDER,
    CurrentPackageWorker,
    LogcatBatch,
    LogcatTermination,
    LogcatTerminationKind,
    LogcatWorker,
)


class LogcatExportWorker(QThread):
    """在后台把已冻结的可见日志写入目标文件，GUI 线程只收完成结果。"""

    completed = Signal(bool, str)

    def __init__(self, text: str, path: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._path = path

    def run(self):
        directory = os.path.dirname(os.path.abspath(self._path))
        tmp_path = ""
        try:
            fd, tmp_path = tempfile.mkstemp(prefix=".logcat_", suffix=".tmp", dir=directory)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self._text)
            os.replace(tmp_path, self._path)
        except Exception as exc:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            message = str(exc) if isinstance(exc, OSError) else type(exc).__name__
            self.completed.emit(False, message)
            return
        self.completed.emit(True, "")


class LiveLogcatStream:
    """组合进 LiveLogcatPage 的流式控制器，通过 ``self._frame`` 访问页面。"""

    RENDER_BATCH_LINES = 256
    RENDER_BATCH_CHARS = 256 * 1024

    def __init__(self, frame):
        # 控制器由页面持有，反向使用弱引用，避免 Qt 包装对象进入 Python 引用环。
        self._frame_ref = weakref.ref(frame)
        # 空态独立于会被清空、换行及应用查询覆盖的状态栏，仅消费本会话的采集事件。
        self._empty_capture_state = "idle"
        self._empty_filter_wait = ""
        self._empty_cleared = False
        self._render_generation = 0
        self._render_paused = False
        self._rebuild_reading = None
        self._rebuild_remaining = 0
        self._export_worker: LogcatExportWorker | None = None
        self._export_in_progress = False
        self._export_path = ""
        self._export_registrations = []

    @property
    def _frame(self):
        frame = self._frame_ref()
        if frame is None:
            raise RuntimeError("LiveLogcatPage has been released")
        return frame

    # ── 筛选 ────────────────────────────────────────────────────────────

    def _min_level(self):
        code = self._frame.level_combo.currentData()
        return LEVEL_ORDER.get(code, -1) if code else None

    def _passes(self, level: str) -> bool:
        minimum = self._min_level()
        if minimum is not None and LEVEL_ORDER.get(level, -1) < minimum:
            return False
        return True

    def _rebuild(self):
        if self._frame._closing:
            return
        reading = self._rebuild_reading or self._capture_rebuild_reading()
        self._cancel_render()
        self._frame._pending_evicted_visible = 0
        visible_entries = [entry for entry in self._frame.entries if self._passes(entry[1])]
        self._frame._rendered_visible_entries.clear()
        self._frame._pending_visible_entries.extend(visible_entries)
        self._frame._pending_visible_lines.extend(entry[0] for entry in visible_entries)
        self._rebuild_remaining = len(visible_entries)
        self._rebuild_reading = reading
        output = self._frame.output
        self._frame._updating_output = True
        try:
            output.clear()
        finally:
            self._frame._updating_output = False
        self._frame._unseen_lines = 0
        self._flush_pending_lines()

    def _cancel_render(self) -> None:
        """取消旧代次的待绘制内容；采集原始缓存由调用方按操作语义处理。"""
        self._render_generation += 1
        self._frame._line_flush_timer.stop()
        self._frame._pending_visible_lines.clear()
        self._frame._pending_visible_entries.clear()
        self._rebuild_reading = None
        self._rebuild_remaining = 0

    def _capture_rebuild_reading(self):
        """以记录身份保存筛选前的阅读点；相同文本的日志仍是不同记录。"""
        output = self._frame.output
        entries = list(self._frame._rendered_visible_entries)
        evicted = self._frame._pending_evicted_visible

        def endpoint(cursor):
            index = cursor.blockNumber() - evicted
            return (entries[index], cursor.positionInBlock()) if 0 <= index < len(entries) else None

        cursor = output.textCursor()
        anchor = QTextCursor(cursor)
        anchor.setPosition(cursor.anchor())
        block = output.firstVisibleBlock()
        return {
            "top": endpoint(QTextCursor(block)),
            "line_offset": max(0, output.verticalScrollBar().value() - block.firstLineNumber()),
            "vertical": output.verticalScrollBar().value(),
            "horizontal": output.horizontalScrollBar().value(),
            "cursor": endpoint(cursor),
            "anchor": endpoint(anchor),
        }

    def _restore_rebuild_reading(self) -> None:
        """分片重建尚未到达阅读点时保留目标，用户主动滚动或选择后停止恢复。"""
        reading = self._rebuild_reading
        if reading is None:
            return
        output = self._frame.output
        indexes = {
            id(entry): index for index, entry in enumerate(self._frame._rendered_visible_entries)
        }

        def position(endpoint):
            if endpoint is None or id(endpoint[0]) not in indexes:
                return None
            block = output.document().findBlockByNumber(indexes[id(endpoint[0])])
            return block.position() + min(endpoint[1], block.length() - 1)

        cursor_position = position(reading["cursor"])
        anchor_position = position(reading["anchor"])
        if cursor_position is not None and anchor_position is not None:
            cursor = QTextCursor(output.document())
            cursor.setPosition(anchor_position)
            cursor.setPosition(cursor_position, QTextCursor.MoveMode.KeepAnchor)
            output.setTextCursor(cursor)
        vertical = output.verticalScrollBar()
        if self._frame.follow_btn.isChecked():
            vertical.setValue(vertical.maximum())
        else:
            top_position = position(reading["top"])
            if top_position is None:
                vertical.setValue(reading["vertical"])
            else:
                cursor = QTextCursor(output.document())
                cursor.setPosition(top_position)
                vertical.setValue(cursor.block().firstLineNumber() + reading["line_offset"])
        output.horizontalScrollBar().setValue(reading["horizontal"])

    def _on_output_selection(self) -> None:
        """分片间的用户选择优先于筛选开始时保存的旧选区。"""
        if not self._frame._updating_output:
            self._rebuild_reading = None

    def _update_content_actions(self, has_visible_content: bool | None = None):
        """按已知可见状态更新动作，避免复制整份日志文档。"""

        if has_visible_content is None:
            has_visible_content = bool(
                self._frame._rendered_visible_entries or self._frame._pending_visible_entries
            )
        self._frame.clear_action.setEnabled(bool(self._frame.entries) or has_visible_content)
        self._frame.export_action.setEnabled(
            has_visible_content and not self._export_in_progress
        )
        self._refresh_empty_hint()
        self._refresh_reading_status()

    def _set_empty_capture_state(self, state: str) -> None:
        """只更新正文空态，不改变按钮准入、后台采集或停止屏障。"""
        self._empty_capture_state = state
        self._refresh_empty_hint()

    def _capture_released(self) -> None:
        """资源释放后收口等待提示，失败原因保留到下一次启动。"""
        if self._empty_capture_state not in ("idle", "start_failed", "failed"):
            self._empty_capture_state = "stopped"
        self._refresh_empty_hint()

    def _empty_hint(self) -> tuple[str, str]:
        state = self._empty_capture_state
        if state == "cleanup_pending":
            return tr("仍在等待采集结束"), tr("后台任务尚未完成清理，请稍候。")
        if state == "stopping":
            return tr("正在停止采集"), tr("完成后可以重新开始采集。")
        if state in ("start_failed", "failed"):
            title = tr("日志采集启动失败") if state == "start_failed" else tr("日志采集意外结束")
            detail = (
                tr("正在清理本次采集，请稍候。") if self._frame.worker is not None
                else tr("请检查设备连接，再点击上方「开始」重试。")
            )
            return title, detail
        if not self._frame._device_connected:
            detail = (
                tr("请检查设备连接，可点击上方「停止」结束本次采集。")
                if state in ("starting", "running") else tr("请连接当前设备后再开始采集。")
            )
            return tr("设备未连接"), detail
        if state == "starting":
            return tr("正在启动日志采集"), tr("正在准备日志流，请稍候。")
        if state == "running":
            if self._empty_filter_wait == "waiting":
                return (
                    tr("正在等待目标应用启动"),
                    tr("请在设备上打开目标应用，随后会自动显示日志。"),
                )
            if self._empty_filter_wait == "retrying":
                return (
                    tr("正在重试应用查询"),
                    tr("暂时无法获取应用进程，重试期间仅等待该应用的日志。"),
                )
            if self._empty_filter_wait == "switching":
                return tr("正在切换应用过滤"), tr("正在等待当前过滤条件下的新日志。")
        if self._frame.entries:
            detail = (
                tr("可调整日志等级，或等待符合条件的新日志。") if state == "running"
                else tr("可调整日志等级查看已有记录。")
            )
            return tr("当前条件下暂无日志"), detail
        if state == "running":
            detail = (
                tr("已清空显示，采集仍在继续。") if self._empty_cleared
                else tr("采集正在运行，新日志到达后会显示在这里。")
            )
            return tr("正在等待新日志"), detail
        if not self._frame._device_selected:
            return tr("尚未选择操作设备"), tr("请在顶部设备列表中勾选当前设备。")
        if state == "stopped":
            return tr("采集已停止"), tr("点击上方「开始」启动新的采集。")
        return tr("准备采集设备日志"), tr("点击上方「开始」，应用可留空以查看全部日志。")

    def _refresh_empty_hint(self) -> None:
        """提示不写入日志文档；有正文时隐藏，不影响导出、选区和阅读位置。"""
        if self._frame._closing:
            return
        output = self._frame.output
        # 头部淘汰可能独占一片；已有待绘制记录时不能短暂显示“暂无日志”。
        empty = output.document().isEmpty() and not self._frame._pending_visible_entries
        text = "\n".join(self._empty_hint()) if empty else ""
        if output.placeholderText() != text:
            output.setPlaceholderText(text)
            output.setAccessibleDescription(text)

    def _refresh_reading_status(self):
        """阅读状态与采集状态分开，计数按批次更新而不复制日志正文。"""
        message = tr("缓存 {count} / {limit} 行").format(
            count=len(self._frame.entries), limit=self._frame.MAX_BUFFER
        )
        if not self._frame.follow_btn.isChecked():
            message += tr(" · 已暂停跟随（{count} 行新日志）").format(
                count=self._frame._unseen_lines
            )
        hint = tr("仅保留最近 {limit} 行原始日志，超出后移除最旧记录；导出保存当前筛选结果").format(
            limit=self._frame.MAX_BUFFER,
        )
        ring = self._frame.cache_ring
        ring.setRange(0, self._frame.MAX_BUFFER)
        count = len(self._frame.entries)
        if ring.value() != count:
            ring.setValue(count)
            # 无动画 Fluent 圆环只写入数值；显式排队重绘避免原生进度阈值漏掉小批更新。
            ring.update()
        ring.setToolTip(f"{message}\n{hint}")
        ring.setAccessibleDescription(ring.toolTip())

    def _on_output_scroll(self, _value):
        """手动上翻暂停跟随；程序追加和重排不改变用户的阅读选择。"""
        if self._frame._updating_output or self._frame._closing:
            return
        self._rebuild_reading = None
        bar = self._frame.output.verticalScrollBar()
        follow = bar.value() == bar.maximum()
        self._frame.follow_action.setChecked(follow)
        if follow:
            self._frame._unseen_lines = 0
        self._refresh_reading_status()

    def _toggle_follow(self):
        """跟随只控制阅读位置，不停止设备采集或日志缓冲。"""
        if self._frame.follow_btn.isChecked():
            self._frame._unseen_lines = 0
            self._frame.output.verticalScrollBar().setValue(
                self._frame.output.verticalScrollBar().maximum()
            )
        self._refresh_reading_status()

    def _submit_package_filter(self):
        """只在用户按 Enter 后提交输入框内容，并使手动输入覆盖未完成的自动查询。"""

        self._frame._package_filter_revision += 1
        package_worker = self._frame._pkg_worker
        if package_worker is not None and package_worker.isRunning():
            package_worker.requestInterruption()
            # package_ready 可能已经进入 GUI 事件队列；主动断开可防止晚到结果覆盖手动输入。
            safe_disconnect(package_worker.package_ready, self._frame._on_current_pkg)
        self._apply_package_filter(self._frame.pkg_input.text())

    def _apply_package_filter(self, package: str):
        """把已提交的包名应用到当前 worker，或记录为下次启动配置。"""

        if self._frame._closing:
            return
        requested = package.strip()
        if requested:
            try:
                requested = normalize_android_package(requested)
            except ValueError:
                self._frame.status_bar.setText(
                    tr("包名格式无效，请输入有效包名后按 Enter"), tr("包名无效"),
                )
                return
        if self._frame._logcat_stopping:
            message = (
                tr('应用过滤将在下次采集时生效：{value0}').format(value0=requested)
                if requested
                else tr("下次采集将显示全部设备日志")
            )
            self._frame.status_bar.setText(message, tr("下次生效"))
            return
        worker = self._frame.worker
        if worker is not None and worker.is_active():
            if not self._frame._can_operate_device():
                self._frame.status_bar.setText(
                    tr("请在顶部勾选并连接当前设备后切换应用过滤"), tr("请连接设备"),
                )
                return
            if worker.update_package(requested):
                self._empty_filter_wait = "switching"
                self._refresh_empty_hint()
                # 旧代次尚未落屏的内容不能越过 Enter 提交形成的过滤边界。
                self._cancel_render()
                if self._frame._pending_evicted_visible and self._frame._view_active:
                    self._schedule_line_flush()
                message = (
                    tr('正在切换应用过滤：{value0}').format(value0=requested)
                    if requested
                    else tr("正在显示全部设备日志")
                )
                self._frame.status_bar.setText(
                    message, tr("切换过滤") if requested else tr("全部日志"),
                )
            return
        message = (
            tr("应用过滤已就绪：{value0}").format(value0=requested)
            if requested
            else tr("将显示全部设备日志")
        )
        self._frame.status_bar.setText(message, tr("过滤已就绪"))

    # ── 操作 ────────────────────────────────────────────────────────────

    def _fetch_current_pkg(self):
        if self._frame._closing or self._frame._logcat_stopping:
            return
        if not self._frame._can_operate_device():
            self._frame.status_bar.setText(
                tr("请先勾选并连接当前设备，再获取当前应用"), tr("请连接设备"),
            )
            self._frame._sync_device_actions()
            return
        if self._frame._pkg_worker and self._frame._pkg_worker.isRunning():
            return
        self._frame.status_bar.setText(tr("正在获取设备前台应用…"), tr("查询应用"))
        self._frame.btn_get_pkg.setEnabled(False)
        worker = CurrentPackageWorker(self._frame.device_ip)
        worker._package_filter_revision = self._frame._package_filter_revision
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
            self._frame._sync_device_actions()
            self._frame.status_bar.setText(tr("无法启动应用查询，请稍后重试"), tr("查询失败"))
            return
        self._frame._pkg_worker = worker
        worker.start()

    def _start(self):
        from . import page as _live_logcat

        if self._frame.worker and self._frame.worker.is_active():
            return
        if not self._frame._can_operate_device():
            self._frame.status_bar.setText(
                tr("请先勾选并连接当前设备，再开始采集"), tr("请连接设备"),
            )
            self._frame._set_running_actions(False)
            self._refresh_empty_hint()
            return
        self._frame._worker_release_timer.stop()
        self._cancel_render()
        self._frame.entries.clear()
        self._frame._rendered_visible_entries.clear()
        self._frame._pending_evicted_visible = 0
        self._frame.output.clear()
        self._frame.follow_action.setChecked(True)
        self._frame._unseen_lines = 0
        self._empty_capture_state = "starting"
        self._empty_filter_wait = ""
        self._empty_cleared = False
        self._update_content_actions(False)
        pkg = self._frame.pkg_input.text().strip()
        worker = _live_logcat.LogcatWorker(self._frame.device_ip, package=pkg)
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
            self._frame.status_bar.setText(tr("无法启动日志任务，请稍后重试"), tr("启动失败"))
            self._set_empty_capture_state("start_failed")
            worker.deleteLater()
            return
        self._frame.worker = worker
        self._frame._supervisor_task_id = task_id
        self._frame._logcat_stop_result_received = False
        self._frame._set_running_actions(True)
        self._frame.status_bar.setText(tr("正在启动日志采集…"), tr("启动中"))
        worker.start()

    def _stop(self):
        if self._frame.worker and self._frame._supervisor_task_id:
            self._frame.status_bar.setText(tr("正在停止采集…"), tr("停止中"))
            self._frame._set_running_actions(True, stopping=True)
            self._set_empty_capture_state("stopping")
            self._frame._task_supervisor.stop_async(self._frame._supervisor_task_id)

    def _clear(self):
        self._cancel_render()
        self._frame.entries.clear()
        self._frame._rendered_visible_entries.clear()
        self._frame._pending_evicted_visible = 0
        self._frame.output.clear()
        self._frame.follow_action.setChecked(True)
        self._frame._unseen_lines = 0
        self._empty_cleared = True
        self._frame.status_bar.setText(tr("已清空日志；运行中的采集会继续"), tr("已清空"))
        self._update_content_actions(False)

    def _toggle_wrap(self):
        output = self._frame.output
        reading_block = output.firstVisibleBlock()
        follow_tail = self._frame.follow_btn.isChecked()
        self._frame._updating_output = True
        try:
            self._apply_wrap()
            bar = output.verticalScrollBar()
            if follow_tail:
                bar.setValue(bar.maximum())
            elif reading_block.isValid():
                bar.setValue(reading_block.firstLineNumber())
            # Qt 重排会自动显露追加日志留下的尾部光标；完成重排后恢复阅读位置，保留选区。
            output.horizontalScrollBar().setValue(0)
            if self._rebuild_reading is not None:
                self._rebuild_reading["horizontal"] = 0
                self._rebuild_reading["line_offset"] = 0
        finally:
            self._frame._updating_output = False

    def _apply_wrap(self):
        if self._frame.wrap_btn.isChecked():
            # 无文档边距时长串排版可能残留数像素范围；换行模式不显示横向滚动条。
            self._frame.output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._frame.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            self._frame.status_bar.setText(tr("已开启自动换行"), tr("换行已开"))
        else:
            self._frame.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self._frame.output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._frame.status_bar.setText(
                tr("已关闭自动换行，可横向滚动查看完整日志"), tr("换行已关"),
            )

    def _export(self):
        from core.settings_manager import AppSettings

        if not self._can_export():
            return
        save_dir = AppSettings.instance().save_directory
        name = f"logcat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        fp, _ = QFileDialog.getSaveFileName(
            self._frame,
            tr("导出日志"),
            os.path.join(save_dir, name),
            tr("文本文件 (*.txt);;所有文件 (*)"),
        )
        if not fp or not self._can_export():
            return
        # 文档可能只完成部分绘制；逻辑可见队列包含完整筛选结果，且排除已淘汰记录。
        text = "\n".join(
            entry[0] for entries in (
                self._frame._rendered_visible_entries, self._frame._pending_visible_entries,
            ) for entry in entries
        )
        worker = LogcatExportWorker(text, fp, self._frame)
        worker.completed.connect(self._frame._on_export_completed)
        worker.finished.connect(self._frame._on_export_finished)
        self._export_worker = worker
        self._export_path = fp
        self._export_in_progress = True
        self._update_content_actions()
        try:
            self.register_shutdown_tasks(
                self._frame._task_supervisor.supervisor,
                owner_id=self._frame._supervisor_owner_id,
                task_prefix=f"{self._frame._supervisor_owner_id}-{uuid.uuid4()}",
            )
            worker.start()
        except RuntimeError as exc:
            self._release_export_worker()
            self._update_content_actions()
            FluentMessageBox.critical(self._frame, tr("日志导出失败"), str(exc))

    def _can_export(self) -> bool:
        """模态文件框前后均复核页面生命期，关闭后禁止新增本地任务。"""
        frame = self._frame_ref()
        return bool(
            frame is not None and is_qobject_alive(frame)
            and not frame._closing and not frame._close_pending and not frame._close_ready
            and not self._export_in_progress
        )

    @staticmethod
    def _export_joined(worker, timeout: float = 0.0) -> bool:
        """仅以原生线程 join 成功作为导出资源完成条件。"""
        if not is_qobject_alive(worker):
            return True
        return bool(worker.wait(max(0, ceil(timeout * 1000))))

    def register_shutdown_tasks(self, supervisor, *, owner_id: str, task_prefix: str):
        """将当前导出纳入现有关闭监督；同一监督器只登记一次。"""
        worker = self._export_worker
        if worker is None:
            return ()
        for registered, task_id in self._export_registrations:
            if registered is supervisor:
                return (task_id,)
        task_id = f"{task_prefix}-logcat-export"
        supervisor.register(
            task_id, owner_id=owner_id, kind="logcat_export",
            request_stop=worker.requestInterruption,
            wait=lambda timeout: LiveLogcatStream._export_joined(worker, timeout),
            is_running=lambda: not LiveLogcatStream._export_joined(worker),
        )
        self._export_registrations.append((supervisor, task_id))
        return (task_id,)

    def _release_export_worker(self) -> bool:
        """保留线程和监督归属直到 join 成功，不能以 finished 信号提前销毁。"""
        worker = self._export_worker
        if worker is None:
            return True
        if not self._export_joined(worker):
            return False
        for supervisor, task_id in self._export_registrations:
            supervisor.unregister(task_id)
        self._export_registrations.clear()
        self._export_worker = None
        self._export_in_progress = False
        if hasattr(worker, "completed"):
            safe_disconnect(worker.completed, self._frame._on_export_completed)
        safe_disconnect(worker.finished, self._frame._on_export_finished)
        worker.deleteLater()
        return True

    def _on_export_completed(self, success: bool, message: str) -> None:
        try:
            frame = self._frame
        except RuntimeError:
            return
        if not is_qobject_alive(frame) or frame._closing:
            return
        if success:
            frame.status_bar.setText(
                tr('日志已导出：{value0}').format(
                    value0=os.path.basename(self._export_path),
                ),
                tr("已导出"),
            )
            return
        FluentMessageBox.critical(frame, tr("日志导出失败"), message)

    def _on_export_finished(self) -> None:
        frame = self._frame_ref()
        if frame is None or not is_qobject_alive(frame):
            return
        if not self._release_export_worker():
            QTimer.singleShot(frame.CLEANUP_RECHECK_MS, frame, frame._on_export_finished)
            return
        try:
            self._update_content_actions()
        except RuntimeError:
            pass
        try:
            frame = self._frame
        except RuntimeError:
            return
        if getattr(frame, "_closing", False) and getattr(frame, "_close_pending", False):
            frame._try_finalize_close("logcat_export_finished")

    # ── 信号槽 ──────────────────────────────────────────────────────────

    def _on_lines_signal(self, batch: LogcatBatch):
        """通过页面 QObject 槽接收批次，避免匿名回调越过页面生命周期。"""
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

    def _on_line(self, text: str, level: str, pid: int = 0):
        if self._frame._closing:
            return
        if not isinstance(self._frame.entries, deque):
            self._frame.entries = deque(self._frame.entries, maxlen=self._frame.MAX_BUFFER)
        if len(self._frame.entries) == self._frame.MAX_BUFFER:
            oldest = self._frame.entries[0]
            rendered = self._frame._rendered_visible_entries
            pending = self._frame._pending_visible_entries
            if rendered and rendered[0] is oldest:
                rendered.popleft()
                self._frame._pending_evicted_visible += 1
            elif pending and pending[0] is oldest:
                pending.popleft()
                self._frame._pending_visible_lines.popleft()
                self._rebuild_remaining = max(0, self._rebuild_remaining - 1)
        entry = (text, level, pid)
        self._empty_cleared = False
        self._frame.entries.append(entry)
        if self._passes(level):
            self._frame._pending_visible_entries.append(entry)
            self._frame._pending_visible_lines.append(text)
        if getattr(self._frame, "_view_active", True):
            self._schedule_line_flush()
        self._frame.clear_action.setEnabled(True)

    def _on_lines(self, worker: LogcatWorker, batch: LogcatBatch):
        try:
            if self._frame._closing or self._frame.worker is not worker:
                return
            if batch.generation != worker.filter_generation:
                return
            if batch.dropped_before and not self._frame._logcat_stopping:
                self._frame.status_bar.setText(
                    tr("正在采集；高负载下已丢弃 {value0} 行日志").format(
                        value0=batch.dropped_before
                    ),
                    tr("已丢弃 {value0} 行").format(value0=batch.dropped_before),
                )
            for text, level, pid in batch.lines:
                self._on_line(text, level, pid)
        finally:
            worker.acknowledge_batch()

    def _on_dropped(self, worker: LogcatWorker, count: int):
        if (not self._frame._closing and self._frame.worker is worker
                and not self._frame._logcat_stopping):
            self._frame.status_bar.setText(
                tr("正在采集；高负载下已丢弃 {value0} 行日志").format(value0=count),
                tr("已丢弃 {value0} 行").format(value0=count),
            )

    def _schedule_line_flush(self):
        if not self._frame._line_flush_timer.isActive():
            self._frame._line_flush_timer.start(75)

    def _flush_pending_lines(self):
        self._frame._line_flush_timer.stop()
        if self._frame._closing or self._render_paused:
            return
        if not self._frame._pending_visible_lines and not self._frame._pending_evicted_visible:
            self._rebuild_reading = None
            self._update_content_actions()
            return
        generation = self._render_generation
        lines = []
        new_lines = 0
        char_count = 0
        # 淘汰也分片，先移除旧头部，避免 QTextDocument 的容量上限提前删除仍在阅读的记录。
        evicted = 0
        block = self._frame.output.document().firstBlock()
        while evicted < min(self._frame._pending_evicted_visible, self.RENDER_BATCH_LINES):
            size = block.length()
            if evicted and char_count + size > self.RENDER_BATCH_CHARS:
                break
            char_count += size
            evicted += 1
            block = block.next()
        self._frame._pending_evicted_visible -= evicted
        if not self._frame._pending_evicted_visible:
            while (self._frame._pending_visible_lines
                   and len(lines) + evicted < self.RENDER_BATCH_LINES):
                size = len(self._frame._pending_visible_lines[0]) + 1
                if (lines or evicted) and char_count + size > self.RENDER_BATCH_CHARS:
                    break
                char_count += size
                lines.append(self._frame._pending_visible_lines.popleft())
                self._frame._rendered_visible_entries.append(
                    self._frame._pending_visible_entries.popleft()
                )
                # 取消阅读位置恢复不等于新增记录，历史重绘不能计入暂停跟随的新日志数。
                if self._rebuild_remaining:
                    self._rebuild_remaining -= 1
                else:
                    new_lines += 1
        # 每片按行数和字符预算收口；超长单行独占一片而不截断，下一片经事件循环续排。
        output = self._frame.output
        horizontal_scroll = output.horizontalScrollBar()
        horizontal_position = horizontal_scroll.value()
        vertical_scroll = output.verticalScrollBar()
        vertical_position = vertical_scroll.value()
        follow_tail = self._frame.follow_btn.isChecked()
        if not follow_tail:
            reading_block = output.firstVisibleBlock()
            reading_anchor = QTextCursor(reading_block)
            reading_line_offset = max(0, vertical_position - reading_block.firstLineNumber())
        self._frame._updating_output = True
        try:
            if evicted:
                cursor = QTextCursor(output.document())
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                if evicted >= output.document().blockCount():
                    cursor.select(QTextCursor.SelectionType.Document)
                else:
                    cursor.movePosition(QTextCursor.MoveOperation.NextBlock,
                                        QTextCursor.MoveMode.KeepAnchor, evicted)
                cursor.removeSelectedText()
            if lines:
                output.appendPlainText("\n".join(lines))
            if generation != self._render_generation:
                return
            # QTextCursor 会跟踪头部删除后的记录位置；固定滚动值会随淘汰悄悄换成另一条日志。
            if follow_tail:
                vertical_scroll.setValue(vertical_scroll.maximum())
            else:
                vertical_scroll.setValue(
                    reading_anchor.block().firstLineNumber() + reading_line_offset
                    if reading_block.isValid() else 0
                )
            horizontal_scroll.setValue(horizontal_position)
            self._restore_rebuild_reading()
        finally:
            self._frame._updating_output = False
        if not follow_tail:
            self._frame._unseen_lines = min(
                self._frame.MAX_BUFFER, self._frame._unseen_lines + new_lines
            )
        self._update_content_actions()
        if self._frame._pending_visible_lines or self._frame._pending_evicted_visible:
            self._frame._line_flush_timer.start(1)
        else:
            self._rebuild_reading = None

    def _on_status(self, msg: str):
        if self._frame._closing:
            return
        # 兼容 worker 现有的原始字符串信号，只为已知状态提供摘要；未知诊断保留原文。
        compact = {
            "正在启动日志采集…": tr("启动中"),
            "正在采集": tr("采集中"),
            "正在采集，显示全部设备日志": tr("采集中"),
            "应用进程查询失败，正在重试；过滤期间不会显示其他应用日志": tr("查询重试"),
            "正在等待目标应用启动；过滤期间不会显示其他应用日志": tr("等待应用"),
            "未找到前台应用，请在设备上打开应用后重试": tr("未找到应用"),
            "日志采集无法继续，请检查设备连接后重试": tr("采集异常"),
            "包名格式无效，请输入有效包名后按 Enter": tr("包名无效"),
        }.get(msg)
        if re.fullmatch(r"正在采集 · 应用过滤生效（\d+ 个进程）", msg):
            compact = tr("过滤生效")
        elif msg.startswith("查询前台应用失败："):
            compact = tr("查询失败")
        self._frame.status_bar.setText(msg, compact)

    def _on_worker_status(self, worker: LogcatWorker, msg: str):
        if (not self._frame._closing and self._frame.worker is worker
                and not self._frame._logcat_stopping):
            if msg == "正在启动日志采集…":
                self._empty_capture_state = "starting"
            elif msg == "日志采集无法继续，请检查设备连接后重试":
                self._empty_capture_state = "failed"
            elif msg == "正在等待目标应用启动；过滤期间不会显示其他应用日志":
                self._empty_capture_state = "running"
                self._empty_filter_wait = "waiting"
            elif msg == "应用进程查询失败，正在重试；过滤期间不会显示其他应用日志":
                self._empty_capture_state = "running"
                self._empty_filter_wait = "retrying"
            elif msg.startswith("正在采集"):
                self._empty_capture_state = "running"
                self._empty_filter_wait = ""
            self._refresh_empty_hint()
            self._on_status(msg)

    def _on_worker_terminated(self, worker: LogcatWorker, result: LogcatTermination):
        if self._frame._closing or self._frame.worker is not worker:
            return
        # 监督器已报告停止结果后，晚到的线程终止信号不能倒退为“停止中”。
        if self._frame._logcat_stop_result_received:
            return
        if result.kind is LogcatTerminationKind.CANCELLED:
            self._set_empty_capture_state("stopping")
            self._frame.status_bar.setText(tr("已请求停止采集"), tr("停止中"))
        elif result.kind is LogcatTerminationKind.START_FAILED:
            self._set_empty_capture_state("start_failed")
            self._frame.status_bar.setText(
                tr("日志采集启动失败，请检查设备连接后重试"), tr("启动失败"),
            )
        else:
            self._set_empty_capture_state("failed")
            self._frame.status_bar.setText(
                tr("日志采集意外结束，请检查设备连接后重新开始"), tr("采集异常"),
            )
