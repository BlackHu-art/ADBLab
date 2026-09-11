"""验证应用日志与开发调试日志之间的隔离契约。"""

from __future__ import annotations

import io
import logging
import sys
import threading
import time
from collections.abc import Callable, Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from core.log_service import LogLevel, LogService


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
            service.shutdown()
            # 测试会反复创建单例；仅停用服务仍留下 Qt 信号回调环与无父级定时器，
            # 必须在 GUI 线程的安全边界释放原生对象，不能留给后续控件构造时的 GC。
            service._timer.deleteLater()
            service.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
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
