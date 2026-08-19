"""验证 MobilePerfRunner 双管道排空、回调隔离和连续运行上下文。"""

from __future__ import annotations

import io
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from models.base.process_runner import ProcessRunner
from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner


class _CountingStream:
    """记录迭代消费数量的可关闭文本流。"""

    def __init__(self, lines: list[str]):
        self._lines = iter(lines)
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        line = next(self._lines)
        self.consumed += 1
        return line

    def close(self):
        self.closed = True


class _DelayedStream(_CountingStream):
    """等待测试放行后再产生内容，用于模拟延迟到达的 stderr。"""

    def __init__(self, lines: list[str]):
        super().__init__(lines)
        self.started = threading.Event()
        self.release = threading.Event()

    def __next__(self):
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("delayed stream was not released")
        return super().__next__()


def _completed_process(stdout, stderr):
    return SimpleNamespace(
        stdout=stdout,
        stderr=stderr,
        returncode=0,
        poll=lambda: 0,
    )


class _StoppableProcess:
    """模拟等待后退出、但 stderr reader 仍可能延迟收口的进程。"""

    def __init__(self, stdout, stderr):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


class _SnapshotRaceProcess(_StoppableProcess):
    """在旧 stop 完成进程快照后暂停，允许测试线程安装新运行。"""

    def __init__(self, stdout, stderr):
        super().__init__(stdout, stderr)
        self.stop_polled = threading.Event()
        self.resume_stop = threading.Event()

    def poll(self):
        if threading.current_thread().name == "old-mobileperf-stop":
            self.stop_polled.set()
            if not self.resume_stop.wait(timeout=5):
                raise TimeoutError("old stop was not resumed")
            return None
        return 0


class _TrackingProcessRunner:
    """维护 key 与进程映射，用于检测旧代停止是否误伤新代。"""

    def __init__(self, processes):
        self._pending = iter(processes)
        self._processes = {}
        self.start_keys: list[str] = []
        self.stop_keys: list[str] = []
        self.force_stop_keys: list[str] = []

    def start(self, key, cmd, **kwargs):
        process = next(self._pending)
        self._processes[key] = process
        self.start_keys.append(key)
        return process

    def stop(self, key, timeout=5):
        self.stop_keys.append(key)
        process = self._processes.pop(key, None)
        if process is None:
            return None
        process.stopped_by_runner = True
        return process.returncode

    def force_stop(self, key, timeout=2):
        self.force_stop_keys.append(key)
        process = self._processes.pop(key, None)
        if process is None:
            return False
        process.stopped_by_runner = True
        return True


def test_mobileperf_runner_drains_real_stdout_and_stderr_before_finish(tmp_path, monkeypatch):
    """真实子进程的两个高频管道必须全部排空后才能通知完成。"""
    diagnostic_output = io.StringIO()
    monkeypatch.setattr(sys, "stderr", diagnostic_output)
    runner = MobilePerfRunner(
        process_runner=ProcessRunner(),
        project_root=tmp_path,
        python_executable=sys.executable,
    )
    line_count = 300
    script = (
        "import sys\n"
        f"count = {line_count}\n"
        "for index in range(count):\n"
        "    sys.stdout.write(f'OUT-{index}\\n')\n"
        "    sys.stderr.write(f'ERR-{index}\\n')\n"
        "    if index % 20 == 0:\n"
        "        sys.stdout.flush()\n"
        "        sys.stderr.flush()\n"
        "sys.stdout.flush()\n"
        "sys.stderr.flush()\n"
    )
    runner._build_command = lambda: [sys.executable, "-u", "-c", script]
    batches: list[str] = []
    finished = threading.Event()

    runner.start(
        MobilePerfRunConfig(
            device_id="stress-device",
            package="com.example.stress",
            save_path=str(tmp_path / "results"),
        ),
        on_log=batches.append,
        on_finished=finished.set,
    )

    assert finished.wait(timeout=10)
    stdout_lines = "\n".join(batches).splitlines()
    diagnostics = diagnostic_output.getvalue()
    assert stdout_lines == [f"OUT-{index}" for index in range(line_count)]
    assert "ERR-0" in diagnostics
    assert f"ERR-{line_count - 1}" in diagnostics


def test_mobileperf_runner_callback_failures_do_not_interrupt_pipe_drain(tmp_path):
    """业务与诊断回调异常均不得中断后续管道消费。"""
    stdout = _CountingStream([f"OUT-{index}\n" for index in range(8)])
    stderr = _CountingStream([f"ERR-{index}\n" for index in range(8)])
    process = _completed_process(stdout, stderr)
    process_runner = Mock(spec=ProcessRunner)
    process_runner.start.return_value = process
    runner = MobilePerfRunner(process_runner=process_runner, project_root=tmp_path)
    runner.LOG_BATCH_SIZE = 2
    callback_calls = 0
    received: list[str] = []
    finished = threading.Event()

    def flaky_log_callback(payload: str):
        nonlocal callback_calls
        callback_calls += 1
        if callback_calls == 1:
            raise RuntimeError("expected callback failure")
        received.append(payload)

    runner._write_diagnostic = Mock(side_effect=RuntimeError("expected diagnostic failure"))
    runner.start(
        MobilePerfRunConfig(package="com.example.callback"),
        on_log=flaky_log_callback,
        on_finished=finished.set,
    )

    assert finished.wait(timeout=5)
    assert stdout.consumed == 8
    assert stderr.consumed == 8
    assert stdout.closed is True
    assert stderr.closed is True
    assert callback_calls == 4
    assert "\n".join(received).splitlines() == [f"OUT-{index}" for index in range(2, 8)]


def test_mobileperf_runner_old_stderr_uses_its_own_run_context(
    tmp_path,
    monkeypatch,
):
    """第二次运行开始后，首轮延迟 stderr 仍使用首轮脱敏值和完成回调。"""
    diagnostic_output = io.StringIO()
    monkeypatch.setattr(sys, "stderr", diagnostic_output)
    first_stdout = _CountingStream(["first-output\n"])
    first_stderr = _DelayedStream(["old-device late diagnostic\n"])
    second_stdout = _CountingStream(["second-output\n"])
    second_stderr = _CountingStream(["new-device current diagnostic\n"])
    process_runner = Mock(spec=ProcessRunner)
    process_runner.start.side_effect = [
        _StoppableProcess(first_stdout, first_stderr),
        _completed_process(second_stdout, second_stderr),
    ]
    runner = MobilePerfRunner(process_runner=process_runner, project_root=tmp_path)
    first_logs: list[str] = []
    second_logs: list[str] = []
    first_finished = threading.Event()
    second_finished = threading.Event()

    runner.start(
        MobilePerfRunConfig(device_id="old-device", package="com.example.first"),
        on_log=first_logs.append,
        on_finished=first_finished.set,
    )
    first_context = runner._active_context
    assert first_context is not None
    assert first_stderr.started.wait(timeout=5)
    assert first_context.stdout_done.wait(timeout=5)
    assert first_finished.is_set() is False
    assert runner.stop(timeout=0) == 0
    assert first_finished.is_set() is False

    runner.start(
        MobilePerfRunConfig(device_id="new-device", package="com.example.second"),
        on_log=second_logs.append,
        on_finished=second_finished.set,
    )
    assert second_finished.wait(timeout=5)

    first_stderr.release.set()
    assert first_finished.wait(timeout=5)
    for thread in (first_context.log_thread, first_context.diagnostic_thread):
        assert thread is not None
        thread.join(timeout=1)
        assert thread.is_alive() is False
    assert first_context.config_cleaned is True

    diagnostics = diagnostic_output.getvalue()
    assert "old-device" not in diagnostics
    assert "new-device" not in diagnostics
    assert "late diagnostic" in diagnostics
    assert "current diagnostic" in diagnostics
    assert first_logs == ["first-output"]
    assert second_logs == ["second-output"]


def test_mobileperf_runner_old_stop_never_writes_new_generation_stop_file(tmp_path):
    """旧 stop 已快照 context 后，新运行的停止文件不得被旧线程创建。"""
    old_stdout = _DelayedStream(["old-output\n"])
    old_process = _SnapshotRaceProcess(old_stdout, _CountingStream([]))
    new_stdout = _DelayedStream(["new-output\n"])
    new_process = _StoppableProcess(new_stdout, _CountingStream([]))
    old_process.stopped_by_runner = False
    new_process.stopped_by_runner = False
    process_runner = _TrackingProcessRunner([old_process, new_process])
    runner = MobilePerfRunner(process_runner=process_runner, project_root=tmp_path)
    stop_result: dict[str, int | None] = {}

    runner.start(MobilePerfRunConfig(package="com.example.old"))
    assert old_stdout.started.wait(timeout=5)

    stop_thread = threading.Thread(
        target=lambda: stop_result.setdefault("code", runner.stop(timeout=0)),
        name="old-mobileperf-stop",
    )
    stop_thread.start()
    assert old_process.stop_polled.wait(timeout=5)

    runner.start(MobilePerfRunConfig(package="com.example.new"))
    new_context = runner._active_context
    assert new_context is not None
    new_stop_path = new_context.stop_path
    assert not Path(new_stop_path).exists()

    old_process.resume_stop.set()
    stop_thread.join(timeout=5)
    assert stop_thread.is_alive() is False
    assert stop_result == {"code": 0}
    assert not Path(new_stop_path).exists()
    assert len(process_runner.start_keys) == 2
    assert process_runner.start_keys[0] != process_runner.start_keys[1]
    assert process_runner.stop_keys == [process_runner.start_keys[0]]
    assert old_process.stopped_by_runner is True
    assert new_process.stopped_by_runner is False
    assert runner.force_stop(timeout=0.25) is True
    assert process_runner.force_stop_keys == [process_runner.start_keys[1]]
    assert new_process.stopped_by_runner is True

    old_stdout.release.set()
    new_stdout.release.set()
    runner.stop(timeout=0)
