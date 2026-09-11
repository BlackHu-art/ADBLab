"""验证 MobilePerf 只在父进程最终开发控制台按明确级别着色。"""

from __future__ import annotations

import io
import re
import sys
from unittest.mock import Mock

import pytest

from core.exec import ProcessRunner
from services import mobileperf_runner as runner_module
from services.mobileperf_runner import MobilePerfRunner


class _TerminalStream(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def console(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("PYCHARM_HOSTED", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    def install():
        stdout, stderr = io.StringIO(), _TerminalStream()
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(sys, "stderr", stderr)
        return stdout, stderr

    return install


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"])
def test_explicit_mobileperf_level_is_colored_only_in_parent_console(console, level):
    stdout, stderr = console()
    runner = MobilePerfRunner(process_runner=Mock(spec=ProcessRunner))
    message = f"[2026-09-11 19:00:00,000]{level}:mobileperf:startup:采集标记"

    runner._write_diagnostic(message)

    rendered = stderr.getvalue()
    assert re.match(r"\x1b\[[0-9;]+m", rendered)
    assert rendered.endswith("\x1b[0m\n")
    assert re.sub(r"\x1b\[[0-9;]*m", "", rendered) == message + "\n"
    assert stdout.getvalue() == ""


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"])
def test_redirected_mobileperf_diagnostic_keeps_plain_text(console, monkeypatch, level):
    stdout, _stderr = console()
    redirected = io.StringIO()
    monkeypatch.setattr(sys, "stderr", redirected)
    runner = MobilePerfRunner(process_runner=Mock(spec=ProcessRunner))
    message = f"[2026-09-11 19:00:00,000]{level}:mobileperf:startup:采集标记"

    runner._write_diagnostic(message)

    assert redirected.getvalue() == message + "\n"
    assert stdout.getvalue() == ""


@pytest.mark.parametrize(
    "message",
    [
        "ERROR occurred while reading output",
        "  File <redacted>, line 1",
        "[2026-09-11 19:00:00,000]VERBOSE:mobileperf:startup:采集标记",
        "[2026-09-11 19:00:00,000]ERROR:other:startup:其他协议",
        "ordinary prefix [2026-09-11 19:00:00,000]ERROR:mobileperf:startup:正文",
    ],
)
def test_unclassified_child_diagnostic_keeps_original_text(console, message):
    stdout, stderr = console()
    runner = MobilePerfRunner(process_runner=Mock(spec=ProcessRunner))

    runner._write_diagnostic(message)

    assert stderr.getvalue() == message + "\n"
    assert stdout.getvalue() == ""


def test_mobileperf_redacts_run_values_before_console_formatting(console, monkeypatch):
    _stdout, stderr = console()
    runner = MobilePerfRunner(process_runner=Mock(spec=ProcessRunner))
    formatted: list[tuple[str, str, object]] = []

    def capture_format(level, text, stream):
        formatted.append((level, text, stream))
        return text

    monkeypatch.setattr(runner_module, "colorize_console", capture_format, raising=False)
    message = "[2026-09-11 19:00:00,000]DEBUG:mobileperf:startup:device-secret mail-secret"
    expected = "[2026-09-11 19:00:00,000]DEBUG:mobileperf:startup:<redacted> <redacted>"

    runner._write_diagnostic(message, ("device-secret", "mail-secret"))

    assert formatted == [("DEBUG", expected, stderr)]
    assert stderr.getvalue() == expected + "\n"
