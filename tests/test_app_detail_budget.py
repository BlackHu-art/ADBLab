"""应用详情小批次的原生启动兼容与总预算边界。"""

from types import SimpleNamespace

import pytest

from core import adb_query
from core.exec import CommandResult
from models import app_manager_worker as module


@pytest.mark.parametrize("fast", [False, True])
def test_detail_batch_has_backend_budget_without_retry_after_failed_command(monkeypatch, fast):
    monkeypatch.setattr(adb_query, "adb_runtime", lambda: SimpleNamespace(
        can_shell_fast=lambda *_args: fast,
    ))
    monkeypatch.setattr(adb_query, "resolve_adb_program", lambda: "mock-adb")
    worker = module.AppManagerWorker("test-device", "load_detail_batch")
    now = [100.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])
    rows, timeouts = [], []
    worker.app_detail_batch.connect(lambda *args: rows.append(args))

    def execute(*_args, timeout, cancellable):
        assert cancellable
        timeouts.append(timeout)
        now[0] += min(timeout, 6)
        if timeout < 6:
            return CommandResult(False, error="Timeout")
        return CommandResult(
            True, "__ADBLAB_PKG_BEGIN_0__\nversionName=1.0\nversionCode=1\n__ADBLAB_PKG_END_0__",
        )

    monkeypatch.setattr(worker, "_adb", execute)
    worker._load_detail_batch(["com.example.app"])
    assert timeouts == [5.0 if fast else 15.0]
    assert bool(rows) is (not fast)
