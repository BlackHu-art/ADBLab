"""验证 Monkey 停止仅影响所属任务，失败保留清理义务。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mobileperf.android.monkey import Monkey, MonkeyError
from models.adb_testing import ADBTesting


def test_stop_without_owned_batch_does_not_issue_remote_kill(qt_application):
    model = ADBTesting()
    model._run = Mock(return_value={"success": True, "output": ""})
    try:
        result = ADBTesting.kill_monkey_async.__wrapped__(model, "demo", 0)
        assert result["success"] and result["already_stopped"]
        model._run.assert_not_called()
    finally:
        model.shutdown()
        model.deleteLater()


def test_performance_monkey_does_not_accept_unconfirmed_remote_stop():
    monitor = Monkey.__new__(Monkey)
    monitor.running = True
    import threading
    monitor._stop_event = threading.Event()
    monitor._owns_process = True
    monitor._log_pipe = None
    monitor._monkey_thread = None
    monitor._lifecycle_lock = threading.RLock()
    monitor._lease = SimpleNamespace(stop=Mock(return_value=False))
    monitor.device = SimpleNamespace(adb=SimpleNamespace(kill_process=Mock(return_value="denied")))
    with pytest.raises(MonkeyError):
        monitor.stop_monkey()
    assert monitor._owns_process


def test_lease_rejects_unconfirmed_stop_and_retries_same_identity():
    from core.monkey_process import MonkeyProcessLease
    lease = MonkeyProcessLease()
    run = Mock(return_value="Permission denied")
    assert not lease.stop(run)
    assert not lease.released
    command = run.call_args.args[0]
    assert "pkill" not in command and "killall" not in command
    assert "identity" in command and "/proc/" in command
    run.return_value = f"ADBLAB_MONKEY_STOPPED_{lease.token}\n"
    assert lease.stop(run)
    assert lease.stop(run)
    assert run.call_count == 2


def test_launch_uses_unique_lease_and_quotes_package():
    from core.monkey_process import MonkeyProcessLease
    first, second = MonkeyProcessLease(), MonkeyProcessLease()
    assert first.path != second.path
    import shlex
    script = shlex.split(first.command(["monkey", "-p", "com.demo; echo bad", "1"]))[2]
    assert "exec monkey -p 'com.demo; echo bad' 1" in script
    assert script.index('mv "$d/identity.tmp"') < script.index('if [ -e "$d/cancel" ]')


def test_stop_during_unsubmitted_model_batch_never_creates_lease(qt_application):
    model = ADBTesting()
    model._run = Mock()
    try:
        model.prepare_monkey_batch("demo", "batch")
        result = ADBTesting.kill_monkey_async.__wrapped__(model, "demo", 0, "batch")
        assert result["success"]
        assert model._monkey_batches["demo"].lease is None
        model._run.assert_not_called()
    finally:
        model.shutdown()
        model.deleteLater()


def test_spawn_failure_does_not_acquire_remote_lease(qt_application):
    model = ADBTesting()
    model._run = Mock()
    model._procs.start = Mock(side_effect=OSError("test spawn denied"))
    try:
        model.prepare_monkey_batch("demo", "batch")
        with pytest.raises(OSError):
            model._start_testing_process(
                "demo_monkey", ["adb", "-s", "demo", "shell", "monkey", "1"],
                monkey_batch=("demo", "batch"),
            )
        assert model._monkey_batches["demo"].lease is None
        model._run.assert_not_called()
    finally:
        model.shutdown()
        model.deleteLater()


def test_shutdown_retains_remote_failure_and_reports_it_after_other_cleanup(qt_application):
    model = ADBTesting()
    model.prepare_monkey_batch("demo", "batch")
    state = model._monkey_batches["demo"]
    state.lease = SimpleNamespace(stop=Mock(return_value=False))
    try:
        model.shutdown()
        assert model._monkey_batches["demo"] is state
        with pytest.raises(RuntimeError, match="cleanup"):
            model.assert_cleanup_complete()
        state.lease.stop.return_value = True
        model.shutdown()
        model.assert_cleanup_complete()
    finally:
        state.lease = None
        model.shutdown()
        model.deleteLater()
