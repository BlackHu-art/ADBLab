"""验证控制台日志级别过滤、诊断旁路与启动配置优先级。"""

from __future__ import annotations

import io
import logging
import sys
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from core.exec import ProcessRunner
from core.log_service import LogLevel, LogService
from core.settings_manager import DEFAULTS, _normalise_setting
from services.mobileperf_runner import MobilePerfRunner
from utils import console_colors


@pytest.fixture(autouse=True)
def restore_console_level() -> Iterator[None]:
    """每个用例后恢复进程级控制台级别，避免污染其它测试的控制台断言。"""

    original = console_colors.console_level()
    yield
    console_colors.set_console_level(original)


@pytest.fixture
def create_log_service() -> Iterator[Callable[[], LogService]]:
    """隔离进程级日志服务，避免停止状态在用例之间传播。"""

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
            service._timer.deleteLater()
            service.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        LogService._instance = previous_instance


def _install_streams(monkeypatch: pytest.MonkeyPatch) -> dict[str, io.StringIO]:
    """在用例执行阶段替换标准流；pytest 捕获在夹具阶段会覆盖 sys.stdout。"""

    monkeypatch.delattr(sys, "frozen", raising=False)
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    return {"stdout": stdout, "stderr": stderr}


def test_default_level_keeps_every_level_on_its_existing_stream(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = _install_streams(monkeypatch)
    service = create_log_service()
    assert console_colors.console_level() == "DEBUG"
    for level in ("DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"):
        service.log(level, f"消息-{level}")
    service._flush_buffer()

    for level in ("DEBUG", "INFO", "SUCCESS"):
        assert f"消息-{level}" in streams["stdout"].getvalue()
    for level in ("WARNING", "ERROR", "CRITICAL"):
        assert f"消息-{level}" in streams["stderr"].getvalue()


@pytest.mark.parametrize(
    "threshold,hidden,visible",
    [("INFO", "DEBUG", "INFO"), ("WARNING", "INFO", "WARNING"), ("ERROR", "WARNING", "ERROR")],
)
def test_threshold_hides_lower_levels_only(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
    threshold: str,
    hidden: str,
    visible: str,
) -> None:
    streams = _install_streams(monkeypatch)
    service = create_log_service()
    console_colors.set_console_level(threshold)

    service.log(hidden, f"隐藏-{hidden}")
    service.log(visible, f"可见-{visible}")
    service._flush_buffer()

    printed = streams["stdout"].getvalue() + streams["stderr"].getvalue()
    assert f"隐藏-{hidden}" not in printed
    assert f"可见-{visible}" in printed


def test_off_silences_console_but_keeps_diagnostics_and_signals(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = _install_streams(monkeypatch)
    service = create_log_service()
    console_colors.set_console_level("OFF")
    received: list[tuple[str, str]] = []
    service.log_received.connect(lambda level, message: received.append((level, message)))

    service.log(LogLevel.WARNING, "关闭控制台后仍要留档")
    service._flush_buffer()

    assert streams["stdout"].getvalue() == ""
    assert streams["stderr"].getvalue() == ""
    assert received == [(LogLevel.WARNING, "关闭控制台后仍要留档")]
    assert "关闭控制台后仍要留档" in service.diagnostics.text()


def test_success_and_unknown_levels_follow_info_rank(
    create_log_service: Callable[[], LogService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = _install_streams(monkeypatch)
    service = create_log_service()
    console_colors.set_console_level("INFO")
    service.log("SUCCESS", "成功消息")
    service.log("CUSTOM", "自定义级别")
    service._flush_buffer()
    assert "成功消息" in streams["stdout"].getvalue()
    assert "自定义级别" in streams["stdout"].getvalue()

    console_colors.set_console_level("WARNING")
    service.log("CUSTOM", "被过滤的自定义级别")
    service._flush_buffer()
    assert "被过滤的自定义级别" not in streams["stdout"].getvalue()


def test_developer_console_is_gated_without_constructing_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = _install_streams(monkeypatch)
    previous_instance = LogService._instance
    LogService._instance = None
    try:
        console_colors.set_console_level("WARNING")
        LogService.write_developer_console("INFO", "低于阈值")
        LogService.write_developer_console("WARNING", "达到阈值")
        assert LogService._instance is None
    finally:
        LogService._instance = previous_instance

    assert "低于阈值" not in streams["stdout"].getvalue()
    assert "达到阈值" in streams["stderr"].getvalue()


def test_mobileperf_diagnostics_respect_level_and_keep_unclassified_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = _install_streams(monkeypatch)
    runner = MobilePerfRunner(process_runner=Mock(spec=ProcessRunner))
    console_colors.set_console_level("WARNING")

    runner._write_diagnostic("[2026-09-11 19:00:00,000]DEBUG:mobileperf:startup:调试正文")
    runner._write_diagnostic("[2026-09-11 19:00:00,000]ERROR:mobileperf:startup:错误正文")
    runner._write_diagnostic("  File <redacted>, line 1")

    rendered = streams["stderr"].getvalue()
    assert "调试正文" not in rendered
    assert "错误正文" in rendered
    assert "File <redacted>, line 1" in rendered


def test_console_level_probe_is_cached_per_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    class CountingTerminal(io.StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.probes = 0

        def isatty(self) -> bool:
            self.probes += 1
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    stream = CountingTerminal()
    console_colors.colorize_console("INFO", "第一次", stream)
    console_colors.colorize_console("INFO", "第二次", stream)
    assert stream.probes == 1


def test_startup_configuration_prefers_environment_over_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import main as main_module

    settings = SimpleNamespace(get=lambda key, default=None: "ERROR")
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    try:
        monkeypatch.setenv("ADBLAB_CONSOLE_LOG_LEVEL", "info")
        main_module._configure_console_logging(settings)
        assert console_colors.console_level() == "INFO"
        assert root_logger.level == logging.WARNING

        monkeypatch.setenv("ADBLAB_CONSOLE_LOG_LEVEL", "off")
        main_module._configure_console_logging(settings)
        assert console_colors.console_level() == "OFF"
        assert root_logger.level == logging.CRITICAL + 1

        monkeypatch.delenv("ADBLAB_CONSOLE_LOG_LEVEL")
        main_module._configure_console_logging(settings)
        assert console_colors.console_level() == "ERROR"
        assert root_logger.level == logging.ERROR
    finally:
        root_logger.setLevel(previous_level)


def test_settings_schema_registers_console_level() -> None:
    assert DEFAULTS["console_log_level"] == "DEBUG"
    assert _normalise_setting("console_log_level", " error ") == "ERROR"
    assert _normalise_setting("console_log_level", "verbose") == "DEBUG"
    assert _normalise_setting("console_log_level", None) == "DEBUG"
