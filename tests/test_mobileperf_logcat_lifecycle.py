"""验证 MobilePerf logcat 采集停止时的尾部补写、回收顺序与空闲重启边界。

测试只连接假 adb 进程，不访问真实设备；同步手段使用 Event 与有界 join，
不把固定 sleep 当作等待条件。
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mobileperf.android import logcat as logcat_module
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.logcat import LogcatMonitor
from mobileperf.android.tools import androiddevice
from mobileperf.android.tools.androiddevice import ADB


class _LogcatProcess:
    """假 adb logcat 客户端：先交出缓冲行，之后按需阻塞或立即报告 EOF。

    poll() 在被 terminate/kill 之前始终返回 None，用于表达"客户端仍然存活"；
    block=True 时缓冲耗尽后阻塞读取，只有终止信号才能释放。
    """

    def __init__(self, lines=(), *, block=True):
        payload = "".join(f"{line}\n" for line in lines).encode("utf-8")
        self.returncode = None
        self.terminated = 0
        self.killed = 0
        self._released = threading.Event()
        process = self

        class Output(io.BytesIO):
            def readline(self, *args):
                value = super().readline(*args)
                if value:
                    return value
                if block and not process._released.is_set():
                    # 缓冲耗尽后模拟真实客户端阻塞在管道读取上，只有终止才释放。
                    if not process._released.wait(2):
                        raise RuntimeError("test process was not stopped")
                    value = super().readline(*args)
                return value

        self.stdout = Output(payload)
        self.stdin = io.BytesIO()
        self.stderr = io.BytesIO()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = -15
        self._released.set()

    def kill(self):
        self.killed += 1
        self.returncode = -9
        self._released.set()

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake-adb", timeout)
        return self.returncode


class _ShellStub:
    """替代 ADB.run_shell_cmd：同步命令返回空文本，异步命令返回同一个假进程。"""

    def __init__(self, process):
        self.process = process
        self.calls = []

    def __call__(self, cmd, **kwds):
        self.calls.append((cmd, kwds))
        if kwds.get("sync", True):
            return ""
        return self.process

    @property
    def spawns(self):
        """异步 spawn 记录，对应 logcat 客户端的实际启动次数。"""
        return [call for call in self.calls if call[1].get("sync") is False]


class _LineProbe:
    """作为 logcat handler 记录收到的行，并在收满预期行数时置位事件。"""

    def __init__(self, expected):
        self.lines = []
        self.done = threading.Event()
        self._expected = expected

    def __call__(self, line):
        self.lines.append(line)
        if len(self.lines) >= self._expected:
            self.done.set()


def _install_fast_clock(monkeypatch, on_sleep=None):
    """把模块内的 1 秒空转压缩到毫秒级，避免测试被固定 sleep 拖慢。

    on_sleep 在每次空转前执行，用于确定性地注入"停止恰好落在空转窗口内"的时序。
    """
    real_sleep = time.sleep

    def sleep(seconds):
        if on_sleep is not None:
            on_sleep()
        real_sleep(min(seconds, 0.001))

    clock = SimpleNamespace(time=time.time, monotonic=time.monotonic, sleep=sleep)
    monkeypatch.setattr(androiddevice, "time", clock)
    monkeypatch.setattr(logcat_module, "time", clock)


@pytest.fixture
def runtime(tmp_path):
    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    yield tmp_path
    RuntimeData.end_run()


@pytest.fixture
def logcat_device(monkeypatch):
    """构造只连假进程的 ADB，走真实的 start_logcat/stop_logcat 生命周期。"""
    monkeypatch.setattr(ADB, "get_adb_path", staticmethod(lambda: "adb"))

    def build(lines=(), **kwds):
        process = _LogcatProcess(lines, **kwds)
        shell = _ShellStub(process)
        adb = ADB("demo-device")
        adb.run_shell_cmd = shell
        return adb, shell

    return build


def _read_log_content(directory, expected_lines):
    """断言只生成一个 logcat 文件，且内容与已读行完全一致。"""
    files = list(Path(directory).glob("logcat_*.log"))
    assert len(files) == 1
    assert "None" not in files[0].name
    assert files[0].read_text(encoding="utf-8") == "".join(
        f"{line}\n" for line in expected_lines
    )
    return files[0]


@pytest.mark.parametrize("line_count", [3, 100, 101])
def test_stop_flushes_unflushed_tail_without_duplicating(
    logcat_device, runtime, monkeypatch, line_count
):
    """停止时必须补写内存中的日志；已按 100 行阈值落盘的部分不得重复写。"""
    _install_fast_clock(monkeypatch)
    lines = [f"{index:03d} log line" for index in range(line_count)]
    adb, shell = logcat_device(lines)
    probe = _LineProbe(line_count)
    adb._logcat_handle.append(probe)

    adb.start_logcat(str(runtime), [], " -b all")
    thread = adb._logcat_thread
    assert probe.done.wait(2), "reader 未读入预期行数"

    adb.stop_logcat()

    assert not thread.is_alive()
    assert adb._log_pipe.terminated == 1
    assert adb._log_pipe.killed == 0
    _read_log_content(runtime, lines)
    assert len(shell.spawns) == 1


def test_stop_terminates_client_once_and_closes_streams(logcat_device, runtime, monkeypatch):
    """正常停止路径只 terminate 一次，并在 reader 退出后才关闭管道流。"""
    _install_fast_clock(monkeypatch)
    adb, shell = logcat_device(["only line"])
    probe = _LineProbe(1)
    adb._logcat_handle.append(probe)

    adb.start_logcat(str(runtime), [], " -b all")
    assert probe.done.wait(2), "reader 未读入预期行数"

    adb.stop_logcat()
    adb.stop_logcat()  # 重复停止必须安全

    process = adb._log_pipe
    assert process.terminated == 1
    assert process.killed == 0
    assert process.stdout.closed and process.stderr.closed
    assert not adb._logcat_thread.is_alive()
    assert len(shell.spawns) == 1
    _read_log_content(runtime, ["only line"])


def test_stop_logcat_is_safe_before_start(logcat_device):
    """从未启动或重复调用 stop_logcat 都不得抛错。"""
    adb, _shell = logcat_device()

    adb.stop_logcat()
    adb.stop_logcat()

    assert getattr(adb, "_log_pipe", None) is None
    assert adb._logcat_running is False


def test_idle_restart_does_not_rebuild_client_after_stop(logcat_device, runtime, monkeypatch):
    """停止落在 1 秒空转窗口内时，空闲重启分支不得再 spawn 无人终止的客户端。"""
    adb, shell = logcat_device([], block=False)
    idle_sleeps = []
    stop_window_entered = threading.Event()

    def on_sleep():
        idle_sleeps.append(True)
        if len(idle_sleeps) == 1000:
            # 第 1000 次空转正好是 log_is_none 达到重启判定点的那一次：
            # 此时 reader 已通过循环条件检查，停止流程只能靠分支内守卫兜住。
            adb._logcat_running = False
            stop_window_entered.set()

    _install_fast_clock(monkeypatch, on_sleep)
    adb.start_logcat(str(runtime), [], " -b all")
    thread = adb._logcat_thread

    assert stop_window_entered.wait(5), "reader 未进入空闲重启判定点"
    thread.join(2)

    assert not thread.is_alive()
    assert len(shell.spawns) == 1
    adb.stop_logcat()
    assert adb._log_pipe.terminated == 1


def _build_monitor(monkeypatch, lines):
    """构造接入假进程的 LogcatMonitor，其设备侧 ADB 仍是真实实现。"""
    monkeypatch.setattr(ADB, "get_adb_path", staticmethod(lambda: "adb"))
    monitor = LogcatMonitor("demo-device", "com.example.app")
    process = _LogcatProcess(lines)
    monitor.device.adb.run_shell_cmd = _ShellStub(process)
    return monitor, process


def test_logcat_monitor_stop_terminates_client_and_clears_handlers(runtime, monkeypatch):
    """Monitor.stop 走完整停止链路：终止客户端、补写尾部并摘除回调。"""
    _install_fast_clock(monkeypatch)
    monitor, process = _build_monitor(monkeypatch, ["monitor line"])
    probe = _LineProbe(1)
    monitor.add_log_handle(probe)

    monitor.start("2026_09_19_00_00_00")
    assert probe.done.wait(2), "reader 未读入预期行数"
    thread = monitor.device.adb._logcat_thread

    monitor.stop()

    assert not thread.is_alive()
    assert process.terminated == 1
    # stop 只摘除自己注册的回调，测试探针保持不动。
    assert monitor.device.adb._logcat_handle == [probe]
    assert monitor.running is False
    _read_log_content(runtime, ["monitor line"])


def test_logcat_monitor_stop_still_terminates_when_handler_removal_fails(runtime, monkeypatch):
    """handler 移除失败（重复 stop 的既有语义）不得让 adb logcat 客户端漏停。"""
    _install_fast_clock(monkeypatch)
    monitor, process = _build_monitor(monkeypatch, [])
    monitor.start("2026_09_19_00_00_00")
    # 模拟二次 stop：目标 handler 已被移除，remove_log_handle 会抛 ValueError。
    monitor.device.adb._logcat_handle.remove(monitor.launchtime.handle_launchtime)

    with contextlib.suppress(ValueError):
        monitor.stop()

    assert process.terminated == 1


def test_exception_handler_bounds_stack_query_and_honors_stop(runtime, monkeypatch):
    """异常堆栈查询必须带超时，并在采集停止后放弃发起设备查询。"""
    monitor, _process = _build_monitor(monkeypatch, [])
    monitor.device.adb.get_process_stack_from_pid = Mock()
    monitor.set_exception_list(["fatal exception"])
    RuntimeData.old_pid = 4321

    monitor.handle_exception("09-19 00:00:00.000  1000  1000 E AndroidRuntime: fatal exception")

    call = monitor.device.adb.get_process_stack_from_pid.call_args
    assert call.args[0] == 4321
    assert call.kwargs["timeout"] == 2
    cancelled = call.kwargs["cancelled"]
    monitor.device.adb._logcat_running = True
    assert cancelled() is False
    monitor.device.adb._logcat_running = False
    assert cancelled() is True
