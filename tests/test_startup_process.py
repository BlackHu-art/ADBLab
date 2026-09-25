"""启动显示进程独立绘制，并在异常、取消与退出时释放全部资源。"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QElapsedTimer, QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def _wait_until(predicate, timeout=5000):
    deadline = QElapsedTimer()
    deadline.start()
    while not predicate() and deadline.elapsed() < timeout:
        QTest.qWait(10)
    assert predicate()


def _records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


@pytest.fixture
def worker_probe(tmp_path, monkeypatch):
    from gui import startup_process

    trace = tmp_path / "frames.jsonl"
    helper = tmp_path / "worker.py"
    helper.write_text(
        "import json, sys, time\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "from gui.widgets import startup_splash\n"
        f"trace = {str(trace)!r}\n"
        "def record(**values):\n"
        "    with open(trace, 'a', encoding='utf-8') as output:\n"
        "        output.write(json.dumps(dict(time=time.perf_counter(), **values)) + '\\n')\n"
        "class ProbeSplash(startup_splash.StartupSplash):\n"
        "    def paintEvent(self, event):\n"
        "        super().paintEvent(event)\n"
        "        record(kind='paint', progress=self._progress)\n"
        "    def set_progress(self, value, *, animate=True):\n"
        "        super().set_progress(value, animate=animate)\n"
        "        record(kind='progress', value=value, animate=animate)\n"
        "startup_splash.StartupSplash = ProbeSplash\n"
        "from gui.startup_worker import run_startup_splash\n"
        "raise SystemExit(run_startup_splash(sys.argv[1]))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        startup_process, "_worker_command", lambda name: [sys.executable, str(helper), name],
    )
    return trace


@pytest.fixture
def splash(qt_application):
    from gui.startup_process import StartupSplashProcess

    proxy = StartupSplashProcess()
    yield proxy
    proxy.shutdown()
    proxy.deleteLater()


def test_worker_command_uses_source_entry_or_frozen_executable(monkeypatch):
    from gui.startup_process import _worker_command

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert _worker_command("socket") == [
        sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"),
        "--startup-splash", "socket",
    ]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert _worker_command("socket") == [sys.executable, "--startup-splash", "socket"]


def test_source_cli_worker_starts_and_finishes_without_user_data(splash, tmp_path, monkeypatch):
    from PySide6.QtNetwork import QLocalSocket

    for variable in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "LOCALAPPDATA"):
        monkeypatch.setenv(variable, str(tmp_path / variable))
    painted, cancelled = [], []
    splash.first_painted.connect(lambda: painted.append(True))
    splash.cancelled.connect(lambda: cancelled.append(True))
    splash.show()
    _wait_until(lambda: bool(painted))
    process = splash.findChild(QProcess)
    assert process.state() == QProcess.ProcessState.Running
    socket = splash.findChild(QLocalSocket)
    assert socket is not None
    splash.set_progress(65, animate=False)
    _wait_until(lambda: socket.bytesToWrite() == 0)
    splash.finish()
    _wait_until(lambda: process.state() == QProcess.ProcessState.NotRunning)
    assert process.exitCode() == 0
    assert process.exitStatus() == QProcess.ExitStatus.NormalExit
    assert painted == [True] and not cancelled
    assert not list(tmp_path.rglob("app_settings.json"))


def test_worker_reports_first_paint_and_receives_real_progress(worker_probe, splash):
    painted, cancelled = [], []
    splash.first_painted.connect(lambda: painted.append(True))
    splash.cancelled.connect(lambda: cancelled.append(True))
    splash.set_progress(35, animate=False)
    splash.show()
    _wait_until(lambda: bool(painted))
    _wait_until(lambda: any(row.get("progress") == 35 for row in _records(worker_probe)))
    assert len(painted) == 1
    splash.set_progress(75, animate=False)
    _wait_until(lambda: any(row.get("progress") == 75 for row in _records(worker_probe)))
    splash.finish()
    process = splash.findChild(QProcess)
    _wait_until(lambda: process.state() == QProcess.ProcessState.NotRunning)
    assert not cancelled


def test_worker_keeps_painting_while_parent_gui_is_blocked(worker_probe, splash):
    painted = []
    splash.first_painted.connect(lambda: painted.append(True))
    splash.show()
    _wait_until(lambda: bool(painted))
    splash.set_progress(80)
    started = time.perf_counter()
    # 明确模拟启动中的不可切分 GUI 构造，期间不泵送父进程 Qt 事件。
    while time.perf_counter() - started < .55:
        sum(range(500))
    ended = time.perf_counter()
    frames = [
        row for row in _records(worker_probe)
        if row["kind"] == "paint" and started < row["time"] < ended
        and 0 < row["progress"] < 80
    ]
    assert len(frames) >= 12
    assert len({row["progress"] for row in frames}) >= 12
    assert frames[-1]["time"] - frames[0]["time"] >= .3


@pytest.mark.parametrize("show_first", [False, True])
def test_finish_before_worker_ready_cannot_reopen_a_splash(worker_probe, splash, show_first):
    painted, cancelled = [], []
    splash.first_painted.connect(lambda: painted.append(True))
    splash.cancelled.connect(lambda: cancelled.append(True))
    if show_first:
        splash.show()
    splash.finish()
    splash.show()
    splash.set_progress(80)
    splash.shutdown()
    assert splash.findChild(QProcess).state() == QProcess.ProcessState.NotRunning
    assert not painted and not cancelled


def test_worker_start_failure_falls_back_and_preserves_progress(splash, monkeypatch):
    from gui import startup_process
    from gui.widgets.startup_splash import StartupSplash

    monkeypatch.setattr(
        startup_process, "_worker_command", lambda _name: ["/missing/splash-worker"],
    )
    painted, cancelled = [], []
    splash.first_painted.connect(lambda: painted.append(True))
    splash.cancelled.connect(lambda: cancelled.append(True))
    splash.set_progress(60, animate=False)
    splash.show()
    _wait_until(lambda: bool(painted))
    fallback = next(
        widget for widget in QApplication.topLevelWidgets()
        if isinstance(widget, StartupSplash)
    )
    assert fallback._progress == 60
    fallback.close()
    assert len(cancelled) == 1


@pytest.mark.parametrize("failure", ["start", "exit"])
def test_worker_failure_reports_reason_without_exposing_command(splash, monkeypatch, failure):
    from gui import startup_process

    command = (["C:/private/missing-splash"] if failure == "start" else
               [sys.executable, "-c", "raise SystemExit(17)"])
    monkeypatch.setattr(startup_process, "_worker_command", lambda _name: command)
    records = []
    splash.diagnostic.connect(records.append)
    painted = []
    splash.first_painted.connect(lambda: painted.append(True))
    splash.show()
    _wait_until(lambda: bool(painted))
    assert records
    report = " ".join(records)
    assert ("FailedToStart" if failure == "start" else "code=17") in report
    assert "private" not in report and sys.executable not in report


def test_worker_crash_after_ready_falls_back_without_duplicate_ready(worker_probe, splash):
    from gui.widgets.startup_splash import StartupSplash

    painted = []
    splash.first_painted.connect(lambda: painted.append(True))
    splash.show()
    _wait_until(lambda: bool(painted))
    splash.set_progress(70, animate=False)
    splash.findChild(QProcess).kill()
    _wait_until(lambda: any(
        isinstance(widget, StartupSplash) and widget.isVisible()
        for widget in QApplication.topLevelWidgets()
    ))
    assert len(painted) == 1


def test_parent_socket_disconnect_exits_worker(worker_probe, splash):
    from PySide6.QtNetwork import QLocalSocket

    painted = []
    splash.first_painted.connect(lambda: painted.append(True))
    splash.show()
    _wait_until(lambda: bool(painted))
    socket = splash.findChild(QLocalSocket)
    socket.abort()
    process = splash.findChild(QProcess)
    _wait_until(lambda: process.state() == QProcess.ProcessState.NotRunning)


def test_worker_without_parent_exits_before_timeout(worker_probe):
    helper = worker_probe.parent / "worker.py"
    result = subprocess.run(
        [sys.executable, str(helper), "adblab-missing-parent-" + helper.parent.name],
        timeout=3, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def _cancel_worker_after_first_frame(trace):
    helper = trace.parent / "worker.py"
    source = helper.read_text(encoding="utf-8")
    source = source.replace(
        "class ProbeSplash(startup_splash.StartupSplash):\n",
        "from PySide6.QtCore import QTimer\n"
        "class ProbeSplash(startup_splash.StartupSplash):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.first_painted.connect(lambda: QTimer.singleShot(80, self.close))\n",
    )
    helper.write_text(source, encoding="utf-8")


def test_worker_cancel_is_distinct_from_finish(worker_probe, splash):
    _cancel_worker_after_first_frame(worker_probe)
    cancelled = []
    splash.cancelled.connect(lambda: cancelled.append(True))
    splash.show()
    _wait_until(lambda: bool(cancelled))
    _wait_until(lambda: splash.findChild(QProcess).state() == QProcess.ProcessState.NotRunning)
    splash.finish()
    assert cancelled == [True]


def test_worker_exit_before_socket_callback_preserves_user_cancel(worker_probe, splash):
    from PySide6.QtNetwork import QLocalSocket

    _cancel_worker_after_first_frame(worker_probe)
    painted, cancelled = [], []
    splash.first_painted.connect(lambda: painted.append(True))
    splash.cancelled.connect(lambda: cancelled.append(True))
    splash.show()
    _wait_until(lambda: bool(painted))
    # 保留真实 socket 数据但延后其通知，模拟 finished 先进入父 GUI 的合法事件顺序。
    splash.findChild(QLocalSocket).blockSignals(True)
    assert splash.findChild(QProcess).waitForFinished(2000)
    assert cancelled == [True]


def test_unresponsive_worker_times_out_and_is_reaped(splash, monkeypatch):
    from gui import startup_process

    monkeypatch.setattr(startup_process, "_START_TIMEOUT_MS", 50)
    monkeypatch.setattr(
        startup_process, "_worker_command",
        lambda _name: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    painted = []
    splash.first_painted.connect(lambda: painted.append(True))
    splash.show()
    _wait_until(lambda: bool(painted))
    _wait_until(lambda: splash.findChild(QProcess).state() == QProcess.ProcessState.NotRunning)
    assert painted == [True]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="SIGTERM 忽略探针仅适用于 POSIX；Windows 使用 QProcess.kill",
)
def test_shutdown_kills_a_worker_that_ignores_terminate(tmp_path, splash, monkeypatch):
    from gui import startup_process

    ready_path = tmp_path / "running"
    code = (
        "import signal,time;from pathlib import Path;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        f"Path({str(ready_path)!r}).touch();time.sleep(30)"
    )
    monkeypatch.setattr(
        startup_process, "_worker_command", lambda _name: [sys.executable, "-c", code],
    )
    splash.show()
    _wait_until(ready_path.exists)
    started = time.perf_counter()
    splash.shutdown()
    assert time.perf_counter() - started < 2
    assert splash.findChild(QProcess).state() == QProcess.ProcessState.NotRunning
