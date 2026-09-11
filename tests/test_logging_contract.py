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


def test_debug_only_writes_to_source_stdout(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    errors = io.StringIO()
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", errors)
    service = create_log_service()
    batch_records: list[list[tuple[str, str, str]]] = []
    single_records: list[tuple[str, str]] = []
    service.logs_received.connect(batch_records.append)
    service.log_received.connect(lambda level, message: single_records.append((level, message)))

    service.log(LogLevel.DEBUG, "仅供开发者查看")
    service._flush_buffer()

    assert "[DEBUG]" in stream.getvalue()
    assert "仅供开发者查看" in stream.getvalue()
    assert errors.getvalue() == ""
    assert batch_records == []
    assert single_records == []
    assert service._buffer == []


@pytest.mark.parametrize(
    "level,expected_level,stream_name",
    [
        ("debug", "DEBUG", "stdout"),
        (" info ", "INFO", "stdout"),
        ("Success", "SUCCESS", "stdout"),
        ("warning", "WARNING", "stderr"),
        ("Error", "ERROR", "stderr"),
        (" CRITICAL ", "CRITICAL", "stderr"),
    ],
)
def test_legacy_log_calls_print_once_and_preserve_ui_and_diagnostic_routing(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
    level: str,
    expected_level: str,
    stream_name: str,
) -> None:
    streams = {"stdout": io.StringIO(), "stderr": io.StringIO()}
    monkeypatch.delattr(sys, "frozen", raising=False)
    for name, stream in streams.items():
        monkeypatch.setattr(sys, name, stream)
    service = create_log_service()
    service.diagnostics.private_values = ("synthetic-device",)
    batches, singles = [], []
    service.logs_received.connect(batches.append)
    service.log_received.connect(lambda severity, message: singles.append((severity, message)))
    message = "操作阶段=%s 设备=%s token=%s 路径=%s"
    args = ("完成", "synthetic-device", "synthetic-token", r"C:\private\report.txt")

    service.log(level, message, *args)

    console = streams[stream_name].getvalue()
    assert console.count(f"[{expected_level}]") == 1
    assert "操作阶段=完成" in console
    assert "synthetic-device" not in console
    assert "synthetic-token" not in console
    assert r"C:\private\report.txt" not in console
    assert "<device>" in console and "<redacted>" in console and "<path>" in console
    assert streams["stderr" if stream_name == "stdout" else "stdout"].getvalue() == ""

    service._flush_buffer()
    service.shutdown()

    assert streams[stream_name].getvalue() == console
    if expected_level == "DEBUG":
        assert batches == singles == []
    else:
        assert [[row[1:] for row in batch] for batch in batches] == [
            [(expected_level, message % args)],
        ]
        assert singles == [(expected_level, message % args)]
    journal = service.diagnostics.text()
    if expected_level in {"WARNING", "ERROR", "CRITICAL"}:
        assert journal.count(f"[{expected_level}]") == 1
        assert "操作阶段=完成" in journal
        assert "synthetic-device" not in journal and "synthetic-token" not in journal
    else:
        assert journal == ""


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"])
def test_legacy_log_calls_remain_silent_when_frozen_without_losing_ui_logs(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
    level: str,
) -> None:
    streams = {"stdout": io.StringIO(), "stderr": io.StringIO()}
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    for name, stream in streams.items():
        monkeypatch.setattr(sys, name, stream)
    service = create_log_service()
    emitted = []
    service.log_received.connect(lambda severity, message: emitted.append((severity, message)))

    service.log(level, "打包模式操作记录", flush_immediately=True)

    assert all(stream.getvalue() == "" for stream in streams.values())
    assert emitted == ([] if level == "DEBUG" else [(level, "打包模式操作记录")])


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


@pytest.mark.parametrize(
    "level,expected_level,expected_stream",
    [
        ("debug", "DEBUG", "stdout"),
        (" info ", "INFO", "stdout"),
        ("Success", "SUCCESS", "stdout"),
        ("warning", "WARNING", "stderr"),
        ("Error", "ERROR", "stderr"),
        (" CRITICAL ", "CRITICAL", "stderr"),
    ],
)
def test_developer_console_routes_normalized_levels(
    monkeypatch: pytest.MonkeyPatch,
    level: str,
    expected_level: str,
    expected_stream: str,
) -> None:
    streams = {"stdout": io.StringIO(), "stderr": io.StringIO()}
    previous_instance = LogService._instance
    monkeypatch.delattr(sys, "frozen", raising=False)
    for name, stream in streams.items():
        monkeypatch.setattr(sys, name, stream)

    LogService.write_developer_console(level, "控制台路由标记")

    assert LogService._instance is previous_instance
    for name, stream in streams.items():
        if name == expected_stream:
            assert f"[{expected_level}]" in stream.getvalue()
            assert "控制台路由标记" in stream.getvalue()
        else:
            assert stream.getvalue() == ""


@pytest.mark.parametrize("level,stream_name", [("DEBUG", "stdout"), ("ERROR", "stderr")])
@pytest.mark.parametrize("unavailable", ["frozen", "missing", "closed"])
def test_developer_console_is_silent_when_its_stream_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    level: str,
    stream_name: str,
    unavailable: str,
) -> None:
    streams = {"stdout": io.StringIO(), "stderr": io.StringIO()}
    monkeypatch.setattr(sys, "frozen", unavailable == "frozen", raising=False)
    for name, stream in streams.items():
        monkeypatch.setattr(sys, name, stream)
    if unavailable == "missing":
        monkeypatch.setattr(sys, stream_name, None)
    elif unavailable == "closed":
        streams[stream_name].close()

    LogService.write_developer_console(level, "不可用的诊断输出")

    assert all(stream.getvalue() == "" for stream in streams.values() if not stream.closed)


def test_debug_is_silent_when_frozen_or_stdout_is_unavailable(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", stream)
    service = create_log_service()

    service.log(LogLevel.DEBUG, "打包模式不可见")
    assert stream.getvalue() == ""

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "stdout", None)
    service.log(LogLevel.DEBUG, "标准输出流不可用")
    assert service._buffer == []

    class UnwritableStream:
        def write(self, _message: str) -> None:
            raise OSError("不可写")

        def flush(self) -> None:
            raise OSError("不可刷新")

    monkeypatch.setattr(sys, "stdout", UnwritableStream())
    service.log(LogLevel.DEBUG, "标准输出流不可写")
    assert service._buffer == []


def test_debug_lines_are_atomic_across_worker_threads(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "stdout", stream)
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = {"stdout": io.StringIO(), "stderr": io.StringIO()}
    monkeypatch.delattr(sys, "frozen", raising=False)
    for name, stream in streams.items():
        monkeypatch.setattr(sys, name, stream)
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
    assert streams["stdout"].getvalue().count("关闭前日志") == 1
    assert streams["stderr"].getvalue() == ""


def test_worker_request_shutdown_is_nonblocking_and_completes_on_owner_thread(
    create_log_service: Callable[[], LogService],
    qt_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = {"stdout": io.StringIO(), "stderr": io.StringIO()}
    monkeypatch.delattr(sys, "frozen", raising=False)
    for name, stream in streams.items():
        monkeypatch.setattr(sys, name, stream)
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
    assert streams["stdout"].getvalue().count("异步关闭前日志") == 1
    assert streams["stderr"].getvalue() == ""


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
