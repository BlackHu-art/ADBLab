"""验证开发控制台按级别着色，重定向与不可用终端保留纯文本。"""

import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.log_service import LogService


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def console_environment(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    for name in ("NO_COLOR", "PYCHARM_HOSTED", "WT_SESSION", "ANSICON", "ConEmuANSI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")


@pytest.mark.parametrize("level,code,stream_name", [
    ("DEBUG", "90", "stdout"), ("INFO", "36", "stdout"), ("SUCCESS", "32", "stdout"),
    ("WARNING", "33", "stderr"), ("ERROR", "31", "stderr"), ("CRITICAL", "35", "stderr"),
])
def test_levels_use_distinct_colors_on_their_existing_stream(monkeypatch, level, code, stream_name):
    streams = {"stdout": Terminal(), "stderr": Terminal()}
    for name, stream in streams.items():
        monkeypatch.setattr(sys, name, stream)
    LogService.write_developer_console(level.lower(), "日志正文")
    rendered = streams[stream_name].getvalue()
    assert rendered.startswith(f"\x1b[{code}m")
    assert f"[{level}]" in rendered
    assert rendered.endswith("日志正文\x1b[0m\n")
    assert streams["stderr" if stream_name == "stdout" else "stdout"].getvalue() == ""


def test_pycharm_pipe_console_gets_color_without_isatty(monkeypatch):
    monkeypatch.setenv("PYCHARM_HOSTED", "1")
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "r", encoding="utf-8") as reader:
        with os.fdopen(write_fd, "w", encoding="utf-8") as writer:
            with monkeypatch.context() as context:
                context.setattr(sys, "stdout", writer)
                assert not writer.isatty()
                LogService.write_developer_console("INFO", "selected adb")
        assert reader.read().startswith("\x1b[36m")


@pytest.mark.parametrize("hosted", [False, True])
def test_redirected_file_never_receives_color(monkeypatch, tmp_path, hosted):
    if hosted:
        monkeypatch.setenv("PYCHARM_HOSTED", "1")
    path = tmp_path / "console.txt"
    with path.open("w", encoding="utf-8") as stream:
        with monkeypatch.context() as context:
            context.setattr(sys, "stderr", stream)
            LogService.write_developer_console("ERROR", "plain error")
    output = path.read_text(encoding="utf-8")
    assert "plain error" in output
    assert "\x1b" not in output


def test_pycharm_memory_capture_stays_plain(monkeypatch):
    monkeypatch.setenv("PYCHARM_HOSTED", "1")
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    LogService.write_developer_console("DEBUG", "captured")
    assert "captured" in stream.getvalue()
    assert "\x1b" not in stream.getvalue()


@pytest.mark.parametrize("name,value", [("NO_COLOR", "1"), ("TERM", "dumb")])
def test_color_opt_out_keeps_console_readable(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    stream = Terminal()
    monkeypatch.setattr(sys, "stdout", stream)
    LogService.write_developer_console("INFO", "plain info")
    assert "plain info" in stream.getvalue()
    assert "\x1b" not in stream.getvalue()


def test_color_capability_failure_does_not_drop_log(monkeypatch):
    class BrokenTerminal(Terminal):
        def isatty(self):
            raise OSError("closed descriptor")

    stream = BrokenTerminal()
    monkeypatch.setattr(sys, "stdout", stream)
    LogService.write_developer_console("INFO", "retained")
    assert "retained" in stream.getvalue()
    assert "\x1b" not in stream.getvalue()


def test_colored_records_are_complete_across_threads(monkeypatch):
    stream = Terminal()
    monkeypatch.setattr(sys, "stdout", stream)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(
            lambda index: LogService.write_developer_console("INFO", str(index)), range(40),
        ))
    lines = stream.getvalue().splitlines()
    assert len(lines) == 40
    assert all(line.startswith("\x1b[36m") and line.endswith("\x1b[0m") for line in lines)


def test_frozen_console_stays_silent_even_with_color_support(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    stream = Terminal()
    monkeypatch.setattr(sys, "stderr", stream)
    LogService.write_developer_console("CRITICAL", "hidden")
    assert stream.getvalue() == ""


@pytest.mark.parametrize("terminal_hint", [None, "WT_SESSION", "ANSICON"])
def test_windows_terminal_requires_known_color_support(monkeypatch, terminal_hint):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("TERM", raising=False)
    if terminal_hint:
        monkeypatch.setenv(terminal_hint, "test-terminal")
    stream = Terminal()
    monkeypatch.setattr(sys, "stdout", stream)
    LogService.write_developer_console("INFO", "windows console")
    assert "windows console" in stream.getvalue()
    assert ("\x1b[36m" in stream.getvalue()) is bool(terminal_hint)


def test_unknown_level_does_not_inherit_previous_color(monkeypatch):
    stream = Terminal()
    monkeypatch.setattr(sys, "stdout", stream)
    LogService.write_developer_console("INFO", "colored")
    LogService.write_developer_console("CUSTOM", "unclassified")
    first, second = stream.getvalue().splitlines()
    assert first.endswith("\x1b[0m")
    assert "[CUSTOM]" in second
    assert "\x1b" not in second
