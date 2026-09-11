"""验证 MobilePerfRunner 双管道排空、回调隔离和连续运行上下文。"""

from __future__ import annotations

import io
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.exec import ProcessRunner
from services import mobileperf_runner as runner_module
from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner


def _wait_for_mode(path: Path, expected: str) -> None:
    deadline = time.monotonic() + 2
    while not path.exists() or path.read_text(encoding="utf-8") != expected:
        assert time.monotonic() < deadline, "mode file was not published"
        threading.Event().wait(0.01)


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


def test_mobileperf_failed_stop_keeps_running_state_and_can_be_retried(tmp_path):
    """停止未确认退出时保留准入屏障和进程跟踪，后续停止必须能重试。"""
    process = _StoppableProcess(None, None)

    def wait_for_exit(timeout=None):
        if process.returncode is None:
            raise subprocess.TimeoutExpired("mobileperf-test", timeout)
        return process.returncode

    process.wait = wait_for_exit
    process_runner = Mock(spec=ProcessRunner)
    process_runner.start.return_value = process
    stop_attempts = []

    def stop_process(key, timeout=5):
        stop_attempts.append(key)
        if len(stop_attempts) > 1:
            process.returncode = 0
        return process.returncode

    process_runner.stop.side_effect = stop_process
    runner = MobilePerfRunner(process_runner=process_runner, project_root=tmp_path)
    runner.PIPE_EXIT_POLL_SECONDS = 0
    finished = Mock()
    config = MobilePerfRunConfig(package="com.example.retry")
    runner.start(config, on_finished=finished)
    context = runner._active_context
    runner._join_context_readers(context, timeout=1)

    try:
        assert runner.stop(timeout=0) is None
        assert runner.is_running() is True
        assert runner.last_exit_code is None
        finished.assert_not_called()
        with pytest.raises(RuntimeError, match="already running"):
            runner.start(config)
        assert runner.stop(timeout=0) == 0
    finally:
        process.returncode = 0
        runner.stop(timeout=0)

    assert len(stop_attempts) == 2
    assert stop_attempts[0] == stop_attempts[1]
    assert runner.is_running() is False
    finished.assert_called_once_with()


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
    """第二次运行开始后，首轮延迟 stderr 仍使用首轮脱敏值；其迟到完成通知被抑制。"""
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
    # 旧运行已非活动上下文，迟到完成通知应被抑制，避免误触发新运行完成。
    assert first_finished.is_set() is False
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


def test_runner_publishes_live_mode_off_caller_thread_and_joins_writer(tmp_path, monkeypatch):
    """运行中的模式文件随后台状态更新，完成通知前同步线程与临时目录均释放。"""
    mode = ["native"]
    runtime = SimpleNamespace(snapshot=lambda: SimpleNamespace(selection_mode=mode[0]))
    monkeypatch.setattr(runner_module, "adb_runtime", lambda: runtime)
    stream = _DelayedStream([])
    process = _StoppableProcess(stream, None)
    process_runner = Mock(spec=ProcessRunner)
    process_runner.start.return_value = process
    runner = MobilePerfRunner(process_runner=process_runner, project_root=tmp_path)
    finished = threading.Event()
    published = threading.Event()
    writes = []
    original = runner_module.os.replace

    def replace(source, destination):
        original(source, destination)
        path = Path(destination)
        if path.name == "mobileperf.adb-mode":
            writes.append((path.read_text(encoding="utf-8"), threading.current_thread()))
            published.set()

    monkeypatch.setattr(runner_module.os, "replace", replace)
    runner.start(MobilePerfRunConfig(), on_finished=finished.set)
    context = runner._active_context
    assert context is not None
    env = process_runner.start.call_args.kwargs["env"]
    path = Path(env["MOBILEPERF_ADB_MODE_FILE"])
    try:
        assert published.wait(2)
        assert path.read_text(encoding="utf-8") == "native"
        for next_mode in ("fast", "auto"):
            published.clear()
            mode[0] = next_mode
            assert published.wait(2)
            assert path.read_text(encoding="utf-8") == next_mode
        assert [value for value, _thread in writes] == ["native", "fast", "auto"]
        assert all(thread is not threading.current_thread() for _value, thread in writes)
    finally:
        process.returncode = 0
        stream.release.set()
        runner.stop(timeout=0)
    assert finished.wait(2)
    assert context.mode_thread is not None and not context.mode_thread.is_alive()
    assert not path.parent.exists()


def test_old_mode_writer_cannot_modify_new_run_file(tmp_path, monkeypatch):
    """旧代写入延迟到新采集开始后完成时，只能落入旧临时目录。"""
    mode = ["auto"]
    runtime = SimpleNamespace(snapshot=lambda: SimpleNamespace(selection_mode=mode[0]))
    monkeypatch.setattr(runner_module, "adb_runtime", lambda: runtime)
    first_stream, second_stream = _DelayedStream([]), _DelayedStream([])
    first = _StoppableProcess(first_stream, None)
    second = _StoppableProcess(second_stream, None)
    process_runner = Mock(spec=ProcessRunner)
    process_runner.start.side_effect = [first, second]
    runner = MobilePerfRunner(process_runner=process_runner, project_root=tmp_path)
    entered, release, written = threading.Event(), threading.Event(), threading.Event()
    runner.start(MobilePerfRunConfig())
    old_context = runner._active_context
    assert old_context is not None
    old_path = Path(process_runner.start.call_args.kwargs["env"]["MOBILEPERF_ADB_MODE_FILE"])
    _wait_for_mode(old_path, "auto")
    original = runner_module.os.replace

    def replace(source, destination):
        if Path(destination) == old_path:
            entered.set()
            assert release.wait(3)
        original(source, destination)
        if Path(destination) == old_path:
            written.set()

    monkeypatch.setattr(runner_module.os, "replace", replace)
    try:
        mode[0] = "fast"
        assert entered.wait(2)
        first.returncode = 0
        mode[0] = "native"
        runner.start(MobilePerfRunConfig())
        new_context = runner._active_context
        assert new_context is not None
        new_path = Path(process_runner.start.call_args.kwargs["env"]["MOBILEPERF_ADB_MODE_FILE"])
        _wait_for_mode(new_path, "native")
        assert new_path != old_path
        release.set()
        assert written.wait(2)
        assert new_path.read_text(encoding="utf-8") == "native"
        first_stream.release.set()
        runner._join_context_readers(old_context, timeout=2)
        assert not old_path.parent.exists()
        assert new_path.exists()
    finally:
        release.set()
        first_stream.release.set()
        second.returncode = 0
        second_stream.release.set()
        runner.stop(timeout=0)


def test_mode_write_failure_retries_without_publishing_partial_mode(tmp_path, monkeypatch):
    mode = ["native"]
    runtime = SimpleNamespace(snapshot=lambda: SimpleNamespace(selection_mode=mode[0]))
    monkeypatch.setattr(runner_module, "adb_runtime", lambda: runtime)
    stream = _DelayedStream([])
    process = _StoppableProcess(stream, None)
    process_runner = Mock(spec=ProcessRunner)
    process_runner.start.return_value = process
    runner = MobilePerfRunner(process_runner=process_runner, project_root=tmp_path)
    runner.start(MobilePerfRunConfig())
    path = Path(process_runner.start.call_args.kwargs["env"]["MOBILEPERF_ADB_MODE_FILE"])
    _wait_for_mode(path, "native")
    failed, retry, published = threading.Event(), threading.Event(), threading.Event()
    original = runner_module.os.replace

    def replace(source, destination):
        if Path(destination) == path:
            if not failed.is_set():
                failed.set()
                raise PermissionError("simulated mode-file contention")
            assert retry.wait(3)
        original(source, destination)
        if Path(destination) == path:
            published.set()

    monkeypatch.setattr(runner_module.os, "replace", replace)
    try:
        mode[0] = "fast"
        assert failed.wait(2)
        assert path.read_text(encoding="utf-8") == "native"
        retry.set()
        assert published.wait(2)
        assert path.read_text(encoding="utf-8") == "fast"
    finally:
        retry.set()
        process.returncode = 0
        stream.release.set()
        runner.stop(timeout=0)


def test_stop_retains_context_until_delayed_mode_write_finishes(tmp_path, monkeypatch):
    """文件系统写入延迟时保留完成屏障，停止调用沿用有界reader等待。"""
    mode = ["auto"]
    runtime = SimpleNamespace(snapshot=lambda: SimpleNamespace(selection_mode=mode[0]))
    monkeypatch.setattr(runner_module, "adb_runtime", lambda: runtime)
    stream = _DelayedStream([])
    process = _StoppableProcess(stream, None)
    process_runner = Mock(spec=ProcessRunner)
    process_runner.start.return_value = process
    runner = MobilePerfRunner(process_runner=process_runner, project_root=tmp_path)
    finished = threading.Event()
    runner.start(MobilePerfRunConfig(), on_finished=finished.set)
    context = runner._active_context
    assert context is not None
    path = Path(process_runner.start.call_args.kwargs["env"]["MOBILEPERF_ADB_MODE_FILE"])
    _wait_for_mode(path, "auto")
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    original = runner_module.os.replace

    def replace(source, destination):
        if Path(destination) == path:
            entered.set()
            assert release.wait(4)
        original(source, destination)

    monkeypatch.setattr(runner_module.os, "replace", replace)

    def stop():
        runner.stop(timeout=0)
        stopped.set()

    stopping = threading.Thread(target=stop)
    try:
        mode[0] = "fast"
        assert entered.wait(2)
        stream.release.set()
        stopping.start()
        assert stopped.wait(2)
        assert not finished.is_set()
        assert path.parent.exists()
        assert runner.is_running(), "关闭监督器必须能看到尚未退出的非 daemon 模式线程"
        release.set()
        assert finished.wait(2)
        assert context.mode_thread is not None
        context.mode_thread.join(1)
        assert not context.mode_thread.is_alive()
        assert not path.parent.exists()
        assert not runner.is_running()
    finally:
        release.set()
        process.returncode = 0
        stream.release.set()
        if stopping.ident is not None:
            stopping.join(2)
        runner.stop(timeout=0)


def test_retired_mode_writer_stays_visible_after_new_run_finishes(tmp_path, monkeypatch):
    """旧代慢写入不能因新代先退出而脱离监督，空进程停止仍有界等待这些线程。"""
    mode = ["auto"]
    runtime = SimpleNamespace(snapshot=lambda: SimpleNamespace(selection_mode=mode[0]))
    monkeypatch.setattr(runner_module, "adb_runtime", lambda: runtime)
    first_stream, second_stream = _DelayedStream([]), _DelayedStream([])
    first = _StoppableProcess(first_stream, None)
    second = _StoppableProcess(second_stream, None)
    process_runner = Mock(spec=ProcessRunner)
    process_runner.start.side_effect = [first, second]
    runner = MobilePerfRunner(process_runner=process_runner, project_root=tmp_path)
    entered, release = threading.Event(), threading.Event()
    runner.start(MobilePerfRunConfig())
    old_context = runner._active_context
    assert old_context is not None
    old_path = Path(old_context.mode_path)
    _wait_for_mode(old_path, "auto")
    original = runner_module.os.replace

    def replace(source, destination):
        if Path(destination) == old_path:
            entered.set()
            assert release.wait(5)
        original(source, destination)

    monkeypatch.setattr(runner_module.os, "replace", replace)
    new_context = None
    try:
        mode[0] = "fast"
        assert entered.wait(2)
        first.returncode = 0
        mode[0] = "native"
        runner.start(MobilePerfRunConfig())
        new_context = runner._active_context
        assert new_context is not None and new_context is not old_context
        _wait_for_mode(Path(new_context.mode_path), "native")
        second.returncode = 0
        second_stream.release.set()
        runner._join_context_readers(new_context, timeout=2)
        assert runner._active_context is None
        first_stream.release.set()
        assert runner.is_running(), "旧代 writer 仍是 runner 拥有的活动资源"
        started = time.monotonic()
        runner.stop(timeout=0)
        assert time.monotonic() - started < 2
        assert old_context.mode_stop.is_set()
        assert runner.is_running()
        release.set()
        runner._join_context_readers(old_context, timeout=2)
        assert not runner.is_running()
        assert not old_path.parent.exists()
    finally:
        release.set()
        first.returncode = second.returncode = 0
        first_stream.release.set()
        second_stream.release.set()
        runner._join_context_readers(old_context, timeout=2)
        if new_context is not None:
            runner._join_context_readers(new_context, timeout=2)
        runner.stop(timeout=0)
