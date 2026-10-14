"""本地脚本代替 ADB，保留真实执行器、客户端锁和长进程生命周期。"""

import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from core import adb_runtime
from core import exec as execution
from models.adb_testing import ADBTesting

pytestmark = pytest.mark.integration

_ADB_SCRIPT = """
import sys, time, zipfile
from pathlib import Path
root = Path(sys.argv[1])
args = sys.argv[2:]
if 'getprop' in args:
    print('13')
elif 'bugreport' in args:
    (root / 'started').touch()
    deadline = time.monotonic() + 10
    while not (root / 'release').exists():
        if time.monotonic() >= deadline:
            raise SystemExit(2)
        time.sleep(.01)
    with zipfile.ZipFile(Path(args[-1]) / 'bugreport-fixture.zip', 'w') as archive:
        archive.writestr('bugreport-fixture.txt', 'fixture report')
elif 'logcat' in args:
    print('fixture log')
else:
    raise SystemExit(3)
"""


@pytest.mark.parametrize("finish", ["success", "shutdown"])
def test_log_export_finishes_while_bugreport_is_still_running(monkeypatch, tmp_path, finish):
    model = ADBTesting()
    monkeypatch.setattr(model, "_convert_bugreport_to_html", Mock())
    monkeypatch.setattr(execution, "_adb_runtime", None)
    monkeypatch.setattr(execution, "resolve_command", lambda command: list(command))
    children = []

    def popen(command, **kwargs):
        kwargs.pop("isolate", None)
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", _ADB_SCRIPT, str(tmp_path), *command[1:]], **kwargs,
        )
        children.append(child)
        return child

    monkeypatch.setattr(execution, "popen_native", popen)
    monkeypatch.setattr(adb_runtime, "popen_native", popen)

    def run_native(command, **kwargs):
        kwargs.pop("isolate", None)
        return subprocess.run(
            [sys.executable, "-u", "-c", _ADB_SCRIPT, str(tmp_path), *command[1:]], **kwargs,
        )

    monkeypatch.setattr(execution, "run_native", run_native)
    reports, logs = [], []
    report_worker = threading.Thread(target=lambda: reports.append(
        model.capture_bugreport_async.__wrapped__(model, "demo", str(tmp_path / "reports"), 1),
    ))
    log_path = tmp_path / "log.txt"
    log_worker = threading.Thread(target=lambda: logs.append(
        model.retrieve_device_logs_async.__wrapped__(model, "demo", str(log_path)),
    ))
    try:
        report_worker.start()
        deadline = time.monotonic() + 3
        while not (tmp_path / "started").exists() and time.monotonic() < deadline:
            threading.Event().wait(.01)
        assert (tmp_path / "started").exists(), reports
        log_worker.start()
        log_worker.join(2)
        assert not log_worker.is_alive(), "日志导出被 Bugreport 的全局客户端锁阻塞"
        assert logs[0]["success"] and log_path.read_text().strip() == "fixture log"
        assert report_worker.is_alive(), "验证并发时 Bugreport 必须仍在运行"
        if finish == "shutdown":
            model.shutdown()
        else:
            (tmp_path / "release").touch()
        report_worker.join(3)
        assert not report_worker.is_alive(), "报告没有完成或响应关闭"
        assert reports[0]["success"] is (finish == "success"), reports
        if finish == "success":
            folder = Path(reports[0]["bugreport_path"])
            assert (folder / "bugreport-fixture.txt").read_text() == "fixture report"
        else:
            assert reports[0]["cancelled"]
            assert list((tmp_path / "reports").iterdir()) == []
        assert model._procs.active_keys == []
        assert all(child.poll() is not None for child in children)
    finally:
        (tmp_path / "release").touch()
        model.shutdown()
        report_worker.join(3)
        if log_worker.ident is not None:
            log_worker.join(3)
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
