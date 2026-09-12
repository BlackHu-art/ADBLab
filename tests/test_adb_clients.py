"""验证 ADB 客户端候选探测：版本解析、失败分类、缓存与并发上限。"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from unittest.mock import Mock

import pytest

from core.exec import CommandResult
from services import adb_clients
from utils.adb_resolver import AdbCandidate

VERSION_OUTPUT = (
    "Android Debug Bridge version 1.0.41\n"
    "Version 37.0.0-14910828\n"
    "Installed as C:/bundle/adb.exe\n"
)


@pytest.fixture(autouse=True)
def clear_cache() -> Iterator[None]:
    adb_clients.clear_client_probe_cache()
    yield
    adb_clients.clear_client_probe_cache()


def test_parse_client_version_reads_bridge_and_build_lines():
    assert adb_clients.parse_client_version(VERSION_OUTPUT) == "1.0.41 (37.0.0)"
    assert adb_clients.parse_client_version("Android Debug Bridge version 1.0.39") == "1.0.39"
    assert adb_clients.parse_client_version("Daemon not running") == ""


def test_missing_candidate_is_reported_without_running_anything(tmp_path):
    run = Mock()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(adb_clients.CommandRunner, "run", run)
        probes = adb_clients.detect_clients(
            [AdbCandidate("env", str(tmp_path / "missing.exe"))]
        )

    assert probes[0].exists is False
    assert probes[0].error == adb_clients.ERROR_MISSING
    run.assert_not_called()


def test_successful_probe_reports_version_and_reuses_cache(tmp_path, monkeypatch):
    executable = tmp_path / "adb.exe"
    executable.write_bytes(b"stub")
    calls = []

    def run(cmd, **_kwargs):
        calls.append(cmd)
        return CommandResult(True, output=VERSION_OUTPUT)

    monkeypatch.setattr(adb_clients.CommandRunner, "run", run)
    candidate = AdbCandidate("bundled", str(executable))

    first = adb_clients.detect_clients([candidate])
    second = adb_clients.detect_clients([candidate])

    assert first[0].executable is True
    assert first[0].version == "1.0.41 (37.0.0)"
    assert second[0].version == "1.0.41 (37.0.0)"
    assert len(calls) == 1
    assert calls[0][1] == "version"


@pytest.mark.parametrize(
    "error, expected",
    [
        ("Timeout(2s)", adb_clients.ERROR_TIMEOUT),
        ("Cancelled", adb_clients.ERROR_CANCELLED),
        ("[WinError 2] 系统找不到指定的文件。", adb_clients.ERROR_UNAVAILABLE),
    ],
)
def test_probe_failures_are_classified(tmp_path, monkeypatch, error, expected):
    executable = tmp_path / "adb.exe"
    executable.write_bytes(b"stub")
    monkeypatch.setattr(
        adb_clients.CommandRunner, "run",
        lambda *_args, **_kwargs: CommandResult(False, error=error),
    )

    probes = adb_clients.detect_clients([AdbCandidate("PATH", str(executable))])

    assert probes[0].executable is False
    assert probes[0].error == expected


def test_non_adb_output_is_rejected(tmp_path, monkeypatch):
    executable = tmp_path / "adb.exe"
    executable.write_bytes(b"stub")
    monkeypatch.setattr(
        adb_clients.CommandRunner, "run",
        lambda *_args, **_kwargs: CommandResult(True, output="hello world"),
    )

    probes = adb_clients.detect_clients([AdbCandidate("PATH", str(executable))])

    assert probes[0].executable is False
    assert probes[0].error == adb_clients.ERROR_NOT_ADB


def test_probe_concurrency_stays_bounded(tmp_path, monkeypatch):
    paths = [tmp_path / f"adb{index}.exe" for index in range(4)]
    for path in paths:
        path.write_bytes(b"stub")
    lock = threading.Lock()
    state = {"running": 0, "peak": 0}

    def run(_cmd, **_kwargs):
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        time.sleep(0.05)
        with lock:
            state["running"] -= 1
        return CommandResult(True, output=VERSION_OUTPUT)

    monkeypatch.setattr(adb_clients.CommandRunner, "run", run)

    probes = adb_clients.detect_clients(
        [AdbCandidate("PATH", str(path)) for path in paths]
    )

    assert len(probes) == 4
    assert state["peak"] <= 2


def test_cancelled_probe_short_circuits_without_running(tmp_path):
    executable = tmp_path / "adb.exe"
    executable.write_bytes(b"stub")

    probes = adb_clients.detect_clients(
        [AdbCandidate("PATH", str(executable))], cancelled=lambda: True
    )

    assert probes[0].error == adb_clients.ERROR_CANCELLED
