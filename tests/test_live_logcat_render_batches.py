"""Logcat 大批绘制让出事件循环，并保持过滤、保留及阅读语义。"""

from collections import deque
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
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
    page.close()


def _feed(page, count, *, prefix="record", level="I", width=225):
    lines = [f"{prefix} {index:05d} " + "x" * width for index in range(count)]
    for line in lines:
        page._on_line(line, level)
    return lines


def _finish(page, app):
    wait_until(app, lambda: not page._line_flush_timer.isActive())


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
