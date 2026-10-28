"""Logcat 大批绘制让出事件循环，并保持过滤、保留及阅读语义。"""

import threading
from collections import deque
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QTextCursor

from gui.dialogs.live_logcat import LiveLogcatPage, LogcatBatch, LogcatWorker
from tests.test_phase2_live_logcat_gate import FakeQtTaskSupervisor
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def page(qt_application):
    page = LiveLogcatPage(device_ip="synthetic", task_supervisor=FakeQtTaskSupervisor())
    page.resize(760, 540)
    page.activate()
    qt_application.processEvents()
    yield page
    if page.worker is not None:
        page.worker._finished_event.set()
        page._on_worker_finished(page.worker)
    from shiboken6 import isValid
    if isValid(page):
        page.close()


def _feed(page, count, *, prefix="record", level="I", width=225):
    lines = [f"{prefix} {index:05d} " + "x" * width for index in range(count)]
    for line in lines:
        page._on_line(line, level)
    return lines


def _finish(page, app):
    wait_until(app, lambda: not page._line_flush_timer.isActive())


@pytest.mark.parametrize("during_dialog", [False, True])
def test_export_rejects_disposed_page_before_and_after_dialog(
    page, monkeypatch, tmp_path, during_dialog,
):
    calls = []

    def choose(*_args):
        calls.append("dialog")
        if during_dialog:
            page.request_dispose()
        return str(tmp_path / "closed.txt"), ""

    monkeypatch.setattr("gui.dialogs.live_logcat_stream.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr("gui.dialogs.live_logcat_stream.LogcatExportWorker.start",
                        lambda _worker: calls.append("start"))
    if not during_dialog:
        page.request_dispose()
    page._export()
    assert calls == (["dialog"] if during_dialog else [])
    assert page._stream_controller._export_worker is None


def test_export_modal_return_rejects_deleted_qobject(page, qt_application, monkeypatch, tmp_path):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    def choose(*_args):
        page.request_dispose()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(page)
        return str(tmp_path / "deleted.txt"), ""

    monkeypatch.setattr("gui.dialogs.live_logcat_stream.QFileDialog.getSaveFileName", choose)
    page._export()
    assert page._stream_controller._export_worker is None


def test_export_cancel_and_busy_do_not_create_work(page, monkeypatch):
    calls = []
    monkeypatch.setattr("gui.dialogs.live_logcat_stream.QFileDialog.getSaveFileName",
                        lambda *_args: (calls.append("dialog") or "", ""))
    page._export()
    assert calls == ["dialog"]
    assert page._stream_controller._export_worker is None
    page._stream_controller._export_in_progress = True
    page._export()
    assert calls == ["dialog"]
    page._stream_controller._export_in_progress = False


def test_export_failure_retains_feedback_and_releases_owner(
    page, qt_application, monkeypatch, tmp_path,
):
    errors = []
    monkeypatch.setattr("gui.dialogs.live_logcat_stream.QFileDialog.getSaveFileName",
                        lambda *_args: (str(tmp_path / "missing" / "export.txt"), ""))
    monkeypatch.setattr("gui.dialogs.live_logcat_stream.FluentMessageBox.critical",
                        lambda _owner, title, message: errors.append((title, message)))
    page._export()
    wait_until(qt_application, lambda: page._stream_controller._export_worker is None)
    assert len(errors) == 1
    assert errors[0][0] == "日志导出失败"
    assert errors[0][1]
    assert page._task_supervisor.supervisor.active_count == 0


def test_export_start_failure_restores_action_and_owner(page, monkeypatch, tmp_path):
    _feed(page, 1)
    page._flush_pending_lines()
    monkeypatch.setattr("gui.dialogs.live_logcat_stream.QFileDialog.getSaveFileName",
                        lambda *_args: (str(tmp_path / "export.txt"), ""))

    def fail_start(_worker):
        raise RuntimeError("synthetic thread start failure")

    errors = []
    monkeypatch.setattr("gui.dialogs.live_logcat_stream.LogcatExportWorker.start", fail_start)
    monkeypatch.setattr("gui.dialogs.live_logcat_stream.FluentMessageBox.critical",
                        lambda *_args: errors.append(True))
    page._export()
    assert errors == [True]
    assert page._stream_controller._export_worker is None
    assert page._task_supervisor.supervisor.active_count == 0
    assert page.export_action.isEnabled()


def test_export_finished_retains_thread_until_join_confirmed(page, qt_application, monkeypatch):
    worker = QThread(page)
    stream = page._stream_controller
    stream._export_worker = worker
    stream._export_in_progress = True
    joined = {"value": False}
    monkeypatch.setattr(stream, "_export_joined", lambda *_args: joined["value"])
    stream._on_export_finished()
    assert stream._export_worker is worker
    assert stream._export_in_progress
    page.close()
    assert not page._close_ready
    joined["value"] = True
    stream._on_export_finished()
    wait_until(qt_application, lambda: page._close_ready)
    assert stream._export_worker is None


def test_started_export_is_owned_until_single_page_dispose_joins(
    qt_application, monkeypatch, tmp_path,
):
    from PySide6.QtCore import Signal

    from core.tasks.qt_supervisor import QtTaskSupervisor

    release = threading.Event()

    class Export(QThread):
        completed = Signal(bool, str)

        def __init__(self, _text, _path, parent):
            super().__init__(parent)

        def run(self):
            release.wait(3)
            self.completed.emit(True, "")

    adapter = QtTaskSupervisor()
    page = LiveLogcatPage(device_ip="synthetic", task_supervisor=adapter)
    stream = page._stream_controller
    monkeypatch.setattr("gui.dialogs.live_logcat_stream.LogcatExportWorker", Export)
    calls = []
    monkeypatch.setattr("gui.dialogs.live_logcat_stream.QFileDialog.getSaveFileName",
                        lambda *_args: (calls.append("dialog") or str(tmp_path / "export.txt"), ""))
    try:
        page._export()
        worker = stream._export_worker
        assert worker is not None and worker.isRunning()
        page._export()
        assert calls == ["dialog"]
        assert adapter.supervisor.active_count == 1
        assert page.request_dispose() is False
        assert not page._close_ready
        assert stream._export_worker is worker
        release.set()
        assert worker.wait(2000)
        wait_until(qt_application, lambda: page._close_ready)
        assert adapter.supervisor.active_count == 0
        assert stream._export_worker is None
    finally:
        release.set()
        if stream._export_worker is not None:
            stream._export_worker.wait(2000)
        adapter._pool.waitForDone(2000)
        page.close()


def test_hidden_backlog_yields_before_all_records_reach_document(page, qt_application):
    page.deactivate()
    page.hide()
    lines = _feed(page, page.MAX_BUFFER)
    page.activate()
    page._flush_pending_lines()
    observed = []
    QTimer.singleShot(0, lambda: observed.append(page.output.document().blockCount()))
    wait_until(qt_application, lambda: bool(observed))
    assert 0 < observed[0] < len(lines)
    _finish(page, qt_application)
    assert page.output.toPlainText().splitlines() == lines
    assert page.cache_ring.value() == page.MAX_BUFFER
    assert page.output.verticalScrollBar().value() == page.output.verticalScrollBar().maximum()


def test_level_rebuild_yields_and_replaces_cancelled_filter_work(page, qt_application):
    info = _feed(page, 900, prefix="info", level="I")
    errors = _feed(page, 900, prefix="error", level="E")
    page._flush_pending_lines()
    _finish(page, qt_application)
    page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
    assert page._line_flush_timer.isActive()
    assert page.output.document().blockCount() < len(errors)
    page.level_combo.setCurrentIndex(0)
    newer = _feed(page, 3, prefix="after filter", level="W")
    _finish(page, qt_application)
    assert page.output.toPlainText().splitlines() == info + errors + newer


def test_clear_cancels_backlog_without_late_old_content(page, qt_application):
    _feed(page, 1800, prefix="discard")
    page._flush_pending_lines()
    assert page._line_flush_timer.isActive()
    page.clear_action.trigger()
    lines = _feed(page, 2, prefix="after clear")
    page._flush_pending_lines()
    _finish(page, qt_application)
    assert page.output.toPlainText().splitlines() == lines
    assert len(page.entries) == 2


def test_hidden_view_pauses_continuation_and_resumes_latest_buffer(page, qt_application):
    lines = _feed(page, 1800)
    page._flush_pending_lines()
    shown = page.output.toPlainText()
    assert len(shown.splitlines()) < len(lines)
    page.deactivate()
    page.hide()
    more = _feed(page, 4, prefix="while hidden")
    qt_application.processEvents()
    assert page.output.toPlainText() == shown
    assert not page._line_flush_timer.isActive()
    page.activate()
    _finish(page, qt_application)
    assert page.output.toPlainText().splitlines() == lines + more


def test_close_cancels_continuation_and_ignores_late_lines(page, qt_application):
    _feed(page, 1800)
    page._flush_pending_lines()
    shown = page.output.toPlainText()
    assert page._line_flush_timer.isActive()
    page.close()
    page._on_line("late", "E")
    qt_application.processEvents()
    assert not page._line_flush_timer.isActive()
    assert page.output.toPlainText() == shown


def test_restart_cancels_previous_render_and_stop_keeps_last_batch(
    page, qt_application, monkeypatch,
):
    monkeypatch.setattr(LogcatWorker, "start", lambda _worker: None)
    _feed(page, 1800, prefix="previous run")
    page._flush_pending_lines()
    assert page._line_flush_timer.isActive()
    page._start()
    worker = page.worker
    lines = _feed(page, 1800, prefix="current run")
    page._flush_pending_lines()
    page._stop()
    page._on_lines(worker, LogcatBatch((("last batch", "E", 0),)))
    _finish(page, qt_application)
    assert page.output.toPlainText().splitlines() == lines + ["last batch"]
    assert page.status_bar.compactText() == "停止中"
    assert not page.start_action.isEnabled()
    assert not page.stop_action.isEnabled()


def test_export_during_partial_render_saves_complete_filtered_snapshot(
    page, qt_application, monkeypatch, tmp_path,
):
    _feed(page, 900, prefix="info", level="I")
    errors = _feed(page, 900, prefix="error", level="E")
    page._flush_pending_lines()
    _finish(page, qt_application)
    page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
    assert page._line_flush_timer.isActive()
    assert page.export_action.isEnabled()
    destination = tmp_path / "export.txt"
    monkeypatch.setattr("core.settings_manager.AppSettings.instance", lambda: SimpleNamespace(
        save_directory=str(tmp_path),
    ))
    monkeypatch.setattr(
        "gui.dialogs.live_logcat_stream.QFileDialog.getSaveFileName",
        lambda *_args: (str(destination), ""),
    )
    page._export()
    wait_until(
        qt_application,
        lambda: page._stream_controller._export_worker is None and destination.exists(),
    )
    assert destination.read_text(encoding="utf-8").splitlines() == errors


def test_close_during_export_still_stops_logcat_cleanup(page, qt_application):
    class BlockingExport(QThread):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def run(self):
            self.started.set()
            self.release.wait(2)

    worker = BlockingExport()
    page._stream_controller._export_worker = worker
    page._stream_controller._export_in_progress = True
    worker.finished.connect(page._stream_controller._on_export_finished)
    try:
        worker.start()
        assert worker.started.wait(1)
        page.close()
        qt_application.processEvents()
        assert page.isHidden()
        assert not page._close_ready

        worker.release.set()
        assert worker.wait(2000)
        wait_until(qt_application, lambda: page._close_ready)
    finally:
        try:
            worker.release.set()
            worker.wait(2000)
        except RuntimeError:
            # finished 槽已 deleteLater，C++ 包装对象可能已释放。
            pass


@pytest.mark.parametrize("wrapped", [False, True])
def test_backlog_eviction_keeps_retained_anchor_and_selection(
    page, qt_application, monkeypatch, wrapped,
):
    monkeypatch.setattr(page, "MAX_BUFFER", 2000)
    page.entries = deque(maxlen=2000)
    page._pending_visible_lines = deque(maxlen=2000)
    page.output.document().setMaximumBlockCount(2000)
    if wrapped:
        page.wrap_btn.click()
    original = _feed(page, 1800, width=520)
    page._flush_pending_lines()
    _finish(page, qt_application)
    cursor = QTextCursor(page.output.document().findBlockByNumber(1500))
    cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, 12)
    cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 20)
    page.output.setTextCursor(cursor)
    vertical = page.output.verticalScrollBar()
    vertical.setValue(page.output.document().findBlockByNumber(1400).firstLineNumber() + 1)
    horizontal = page.output.horizontalScrollBar()
    horizontal.setValue(120)
    anchor = page.output.firstVisibleBlock().text()
    line_offset = vertical.value() - page.output.firstVisibleBlock().firstLineNumber()
    selected = page.output.textCursor().selectedText()
    horizontal_position = horizontal.value()
    assert not page.follow_btn.isChecked()
    page.deactivate()
    lines = _feed(page, 700, prefix="incoming", width=520)
    page.activate()
    page._flush_pending_lines()
    _finish(page, qt_application)
    assert page.output.toPlainText().splitlines() == original[500:] + lines
    assert len(page.entries) == 2000
    assert page.output.firstVisibleBlock().text() == anchor
    assert vertical.value() - page.output.firstVisibleBlock().firstLineNumber() == line_offset
    assert horizontal.value() == horizontal_position
    assert page.output.textCursor().selectedText() == selected
    assert not page.follow_btn.isChecked()


def test_level_rebuild_preserves_matching_reading_anchor_and_selection(page, qt_application):
    for index in range(1800):
        page._on_line(f"record {index:05d} " + "x" * 260, "E" if index % 2 else "I")
    page._flush_pending_lines()
    _finish(page, qt_application)
    cursor = QTextCursor(page.output.document().findBlockByNumber(1501))
    cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 18)
    page.output.setTextCursor(cursor)
    page.output.verticalScrollBar().setValue(1401)
    page.output.horizontalScrollBar().setValue(100)
    anchor = page.output.firstVisibleBlock().text()
    selected = page.output.textCursor().selectedText()
    horizontal = page.output.horizontalScrollBar().value()
    page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
    _finish(page, qt_application)
    assert page.output.firstVisibleBlock().text() == anchor
    assert page.output.textCursor().selectedText() == selected
    assert page.output.horizontalScrollBar().value() == horizontal
    assert not page.follow_btn.isChecked()


def test_arrival_between_slices_evicts_pending_and_rendered_records_in_order(
    page, qt_application,
):
    lines = _feed(page, page.MAX_BUFFER, prefix="old")
    page._flush_pending_lines()
    assert 0 < page.output.document().blockCount() < len(lines)
    newer = _feed(page, 1200, prefix="new")
    _finish(page, qt_application)
    assert page.output.toPlainText().splitlines() == lines[1200:] + newer
    assert len(page.entries) == page.output.document().blockCount() == page.MAX_BUFFER


def test_eviction_slice_does_not_claim_pending_matching_content_is_empty(page, qt_application):
    _feed(page, 256)
    page._flush_pending_lines()
    newer = _feed(page, page.MAX_BUFFER, prefix="replacement")
    page._flush_pending_lines()
    assert page._line_flush_timer.isActive()
    assert page.output.placeholderText() == ""
    assert page.export_action.isEnabled()
    _finish(page, qt_application)
    assert page.output.toPlainText().splitlines() == newer


def test_package_switch_cancels_only_unrendered_old_generation(page, qt_application, monkeypatch):
    monkeypatch.setattr(LogcatWorker, "start", lambda _worker: None)
    page._start()
    _feed(page, 1800, prefix="old package")
    page._flush_pending_lines()
    displayed = page.output.toPlainText().splitlines()
    assert 0 < len(displayed) < 1800
    page._apply_package_filter("com.example.new")
    newer = _feed(page, 900, prefix="new package")
    _finish(page, qt_application)
    assert page.output.toPlainText().splitlines() == displayed + newer


def test_user_scroll_during_rebuild_supersedes_saved_reading_position(page, qt_application):
    _feed(page, 1800, level="E")
    page._flush_pending_lines()
    _finish(page, qt_application)
    page.output.verticalScrollBar().setValue(1400)
    page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
    assert page._line_flush_timer.isActive()
    page.output.verticalScrollBar().setValue(4)
    anchor = page.output.firstVisibleBlock().text()
    cursor = QTextCursor(page.output.document().findBlockByNumber(5))
    cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 8)
    page.output.setTextCursor(cursor)
    _feed(page, 3, prefix="arrived during rebuild", level="E")
    _finish(page, qt_application)
    assert page.output.firstVisibleBlock().text() == anchor
    assert page.output.textCursor().selectedText() == "record 0"
    assert page._unseen_lines == 3
