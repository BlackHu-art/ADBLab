"""验证剩余预算耗尽时不会误入旧的无限等待查询边界。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mobileperf.android import process_status
from mobileperf.android.tools import androiddevice


@pytest.mark.parametrize("boundary", ["pid", "status"])
def test_sampler_does_not_pass_zero_budget_to_the_adb_query(monkeypatch, boundary):
    # 最后一次停止检查通过后，模拟任务在实际计算查询预算前被调度器挂起。
    readings = iter([0, 0, 0, 0, 0, 2] if boundary == "pid" else [0] * 7 + [2])
    monkeypatch.setattr(process_status, "time", SimpleNamespace(
        monotonic=lambda: next(readings, 2), time=lambda: 0,
    ))
    queried = []

    def pid(_package, *, timeout, **_options):
        queried.append(("pid", timeout))
        return 42

    def status(_command, *, timeout, **_options):
        queried.append(("status", timeout))
        return "FDSize:\t64\nThreads:\t8\n"

    sampler = process_status.ProcessStatusSampler(SimpleNamespace(
        get_pid_from_pck=pid, run_shell_cmd=status,
    ), "com.example.app", 5)
    assert sampler.read(timeout=1) is None
    assert queried == ([] if boundary == "pid" else [("pid", 1)])


def _adb_for_query_test():
    adb = androiddevice.ADB.__new__(androiddevice.ADB)
    adb._device_id = "test-device"
    adb._adb_path = "adb"
    adb._execution = None
    adb.before_connect = adb.after_connect = True
    return adb


@pytest.mark.parametrize("timeout", [0, None, -1])
def test_cancelled_sync_shell_does_not_start_an_unbounded_native_process(monkeypatch, timeout):
    adb = _adb_for_query_test()
    monkeypatch.setattr(androiddevice, "logger", Mock())
    process = Mock()
    process.communicate.return_value = (b"output", b"")
    process.poll.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr(androiddevice.subprocess, "Popen", popen)

    assert adb._run_cmd_once("shell", "ps -A", timeout=timeout, cancelled=lambda: True) == ""
    popen.assert_not_called()


def test_uncancelled_infinite_native_query_keeps_its_existing_wait_contract(monkeypatch):
    adb = _adb_for_query_test()
    monkeypatch.setattr(androiddevice, "logger", Mock())
    process = Mock()
    process.communicate.return_value = (b"output", b"")
    process.poll.return_value = 0
    monkeypatch.setattr(androiddevice.subprocess, "Popen", Mock(return_value=process))

    assert adb._run_cmd_once("shell", "echo output", timeout=0, cancelled=lambda: False) == "output"
    process.communicate.assert_called_once_with(timeout=None)
