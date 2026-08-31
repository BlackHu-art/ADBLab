"""验证应用日志与开发调试日志之间的隔离契约。"""

from __future__ import annotations

import io
import logging
import sys
import threading
import time
from collections.abc import Callable, Iterator

import pytest

from core.log_service import LogLevel, LogService
from gui.panels.log_panel import LogPanel
from gui.styles import BaseStyles


@pytest.fixture
def create_log_service() -> Iterator[Callable[[], LogService]]:
    """为每个用例隔离进程级日志服务，避免停止状态在用例之间传播。"""
    previous_instance = LogService._instance
    LogService._instance = None
    created: list[LogService] = []

    def factory() -> LogService:
        service = LogService()
        if service not in created:
            created.append(service)
        return service

    try:
        yield factory
    finally:
        for service in created:
            if service._state == service._STATE_ACCEPTING:
                service.shutdown()
        LogService._instance = previous_instance


def test_debug_only_writes_to_source_stderr(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "stderr", stream)
    service = create_log_service()
    batch_records: list[list[tuple[str, str, str]]] = []
    single_records: list[tuple[str, str]] = []
    service.logs_received.connect(batch_records.append)
    service.log_received.connect(lambda level, message: single_records.append((level, message)))

    service.log(LogLevel.DEBUG, "仅供开发者查看")
    service._flush_buffer()

    assert "[DEBUG]" in stream.getvalue()
    assert "仅供开发者查看" in stream.getvalue()
    assert batch_records == []
    assert single_records == []
    assert service._buffer == []


def test_developer_console_can_be_used_without_constructing_log_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    previous_instance = LogService._instance
    LogService._instance = None
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "stderr", stream)
    try:
        LogService.write_developer_console("ERROR", "设备存储加载失败")
        assert LogService._instance is None
    finally:
        LogService._instance = previous_instance

    assert "[ERROR]" in stream.getvalue()
    assert "设备存储加载失败" in stream.getvalue()


def test_debug_is_silent_when_frozen_or_stderr_is_unavailable(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stderr", stream)
    service = create_log_service()

    service.log(LogLevel.DEBUG, "打包模式不可见")
    assert stream.getvalue() == ""

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "stderr", None)
    service.log(LogLevel.DEBUG, "标准错误流不可用")
    assert service._buffer == []

    class UnwritableStream:
        def write(self, _message: str) -> None:
            raise OSError("不可写")

        def flush(self) -> None:
            raise OSError("不可刷新")

    monkeypatch.setattr(sys, "stderr", UnwritableStream())
    service.log(LogLevel.DEBUG, "标准错误流不可写")
    assert service._buffer == []


def test_debug_lines_are_atomic_across_worker_threads(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "stderr", stream)
    service = create_log_service()
    workers = [
        threading.Thread(
            target=service.log,
            args=(LogLevel.DEBUG, f"worker-{index}"),
            daemon=True,
        )
        for index in range(20)
    ]

    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=1)

    lines = stream.getvalue().splitlines()
    assert len(lines) == len(workers)
    assert all(line.count("[DEBUG]") == 1 for line in lines)


def test_initialization_preserves_root_logger_handlers(
    create_log_service: Callable[[], LogService],
) -> None:
    root_logger = logging.getLogger()
    existing_handler = logging.NullHandler()
    root_logger.addHandler(existing_handler)
    try:
        create_log_service()
        assert existing_handler in root_logger.handlers
    finally:
        root_logger.removeHandler(existing_handler)


def test_log_panel_renders_records_verbatim(
    create_log_service: Callable[[], LogService],
) -> None:
    """面板不再二次过滤级别：DEBUG 拦截是 LogService 的单一职责。"""

    create_log_service()
    panel = LogPanel()
    try:
        panel._append_logs(
            [
                ("12:00:00", LogLevel.DEBUG, "直接调用可见"),
                ("12:00:01", LogLevel.INFO, "允许显示"),
            ]
        )
        panel._flush_pending_rows()

        assert [entry[1:] for entry in panel._entries] == [
            (LogLevel.DEBUG, "直接调用可见"),
            (LogLevel.INFO, "允许显示"),
        ]
        assert "直接调用可见" in panel.text_output.toPlainText()
        assert "允许显示" in panel.text_output.toPlainText()
    finally:
        panel.close()


def test_log_panel_batch_records_carry_source_timestamps(
    create_log_service: Callable[[], LogService],
) -> None:
    create_log_service()
    panel = LogPanel()
    try:
        panel._append_logs([("12:00:00", LogLevel.INFO, "带时间戳")])
        panel._flush_pending_rows()

        timestamp, level, message = panel._entries[0]
        assert timestamp == "12:00:00"
        assert level == LogLevel.INFO
        assert message == "带时间戳"
        # 数据层保留时间戳，但界面不渲染时间列（避免与级别列重叠）。
        assert "带时间戳" in panel.text_output.toPlainText()
        assert "12:00:00" not in panel.text_output.toPlainText()
    finally:
        panel.close()


def test_log_panel_applies_new_line_limit_immediately(
    create_log_service: Callable[[], LogService],
) -> None:
    create_log_service()
    panel = LogPanel()
    try:
        panel._entries = [
            ("12:00:00", LogLevel.INFO, f"line-{index}") for index in range(105)
        ]
        panel._rerender_all()

        panel.set_max_lines(100)

        assert panel._max_lines == 100
        assert panel._entries[0][2] == "line-5"
        assert "line-0" not in panel.text_output.toPlainText()
    finally:
        panel.close()


def test_log_panel_text_output_is_wrapped_in_card_container(
    create_log_service: Callable[[], LogService],
) -> None:
    """视觉重设计最小化：正文外包卡片容器，text_output 公开契约保持不变。"""

    create_log_service()
    panel = LogPanel()
    try:
        assert panel.logViewCard.objectName() == "logViewCard"
        assert panel.text_output.parent() is panel.logViewCard
        assert panel.text_output.accessibleName() == "Operation log"
        # 主题钩子：卡片样式随当前主题色重建。
        assert BaseStyles.color("PANEL_BG") in panel.logViewCard.styleSheet()
        assert BaseStyles.color("BORDER_COLOR") in panel.logViewCard.styleSheet()
        # 正文渲染契约不受包壳影响。
        panel._append_logs([("12:00:00", LogLevel.INFO, "卡片内渲染")])
        panel._flush_pending_rows()
        assert "卡片内渲染" in panel.text_output.toPlainText()
    finally:
        panel.close()


def test_log_panel_toolbar_clear_button_wipes_entries(
    create_log_service: Callable[[], LogService],
) -> None:
    """工具条卡片化：清空图标按钮保留 objectName 契约并复用既有 clear()。"""

    create_log_service()
    panel = LogPanel()
    try:
        panel._append_logs([("12:00:00", LogLevel.INFO, "待清空")])
        panel._flush_pending_rows()
        assert "待清空" in panel.text_output.toPlainText()

        assert panel.logToolbarCard.objectName() == "logToolbarCard"
        assert panel.logClearButton.objectName() == "logClearButton"
        assert panel.logClearButton.property("iconName") == "broom.svg"
        assert panel.logClearButton.toolTip() == "Clear Log"

        panel.logClearButton.click()

        assert panel._entries == []
        assert panel.text_output.toPlainText() == ""
    finally:
        panel.close()


def test_log_panel_level_filter_badge_tracks_selection_and_filters_intake(
    create_log_service: Callable[[], LogService],
) -> None:
    """彩色徽标映射 LOG_* 级别色；级别过滤只作用于新到达批次，历史行保留。"""

    create_log_service()
    panel = LogPanel()
    try:
        panel._append_logs([("12:00:00", LogLevel.INFO, "过滤前历史行")])
        panel._flush_pending_rows()

        assert panel.logLevelBadge.objectName() == "logLevelBadge"
        assert panel.logLevelBadge.text() == "ALL"

        # 选中 ERROR 项（All/DEBUG/INFO/SUCCESS/WARNING/ERROR/CRITICAL 的第 5 项）。
        panel.logLevelFilter.setCurrentIndex(5)

        assert panel.logLevelBadge.text() == "ERROR"
        assert BaseStyles.color("LOG_ERROR") in panel.logLevelBadge.styleSheet()
        assert "过滤前历史行" in panel.text_output.toPlainText()  # 历史行不回溯隐藏

        panel._append_logs(
            [
                ("12:00:01", LogLevel.INFO, "被级别过滤拦截"),
                ("12:00:02", LogLevel.ERROR, "保留错误"),
            ]
        )
        panel._flush_pending_rows()

        assert "保留错误" in panel.text_output.toPlainText()
        assert "被级别过滤拦截" not in panel.text_output.toPlainText()
    finally:
        panel.close()


def test_shutdown_is_idempotent_and_rejects_late_logs(
    create_log_service: Callable[[], LogService],
) -> None:
    service = create_log_service()
    emitted: list[tuple[str, str]] = []
    service.log_received.connect(lambda level, message: emitted.append((level, message)))
    service.log(LogLevel.INFO, "关闭前日志")

    service.shutdown()
    service.shutdown()
    service.log(LogLevel.ERROR, "关闭后日志", flush_immediately=True)

    assert LogService() is service
    assert service._state == service._STATE_STOPPED
    assert service._buffer == []
    assert emitted == [(LogLevel.INFO, "关闭前日志")]
    assert not service._timer.isActive()


def test_worker_request_shutdown_is_nonblocking_and_completes_on_owner_thread(
    create_log_service: Callable[[], LogService],
    qt_application,
) -> None:
    service = create_log_service()
    emitted: list[tuple[str, str]] = []
    accepted: list[bool] = []
    service.log_received.connect(lambda level, message: emitted.append((level, message)))
    service.log(LogLevel.INFO, "异步关闭前日志")
    assert service._timer.isActive()

    worker = threading.Thread(
        target=lambda: accepted.append(service.request_shutdown()),
        daemon=True,
    )
    started = time.perf_counter()
    worker.start()
    worker.join(timeout=0.2)

    assert not worker.is_alive()
    assert time.perf_counter() - started < 0.2
    assert accepted == [True]
    assert service._state == service._STATE_STOPPING
    service.log(LogLevel.ERROR, "请求关闭后的晚到日志", flush_immediately=True)

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and service._state != service._STATE_STOPPED:
        qt_application.processEvents()
        time.sleep(0.005)

    assert service._state == service._STATE_STOPPED
    assert not service._timer.isActive()
    assert service._buffer == []
    assert emitted == [(LogLevel.INFO, "异步关闭前日志")]


def test_shutdown_rejects_worker_thread_call(
    create_log_service: Callable[[], LogService],
) -> None:
    service = create_log_service()
    errors: list[Exception] = []

    def shutdown_from_worker() -> None:
        try:
            service.shutdown()
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=shutdown_from_worker, daemon=True)
    worker.start()
    worker.join(timeout=0.2)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "request_shutdown()" in str(errors[0])
    assert service._state == service._STATE_ACCEPTING
