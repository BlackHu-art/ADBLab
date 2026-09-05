"""验证多设备 Monkey 排队取消及设备批次的进程归属。"""

import threading
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QRunnable
from PySide6.QtTest import QSignalSpy

from controllers._app_monkey import ADBAppMonkeyMixin
from controllers.signals import ADBControllerSignals
from models.adb_testing import ADBTesting
from tests.ui_geometry_helpers import wait_until


@pytest.fixture
def model(qt_application, monkeypatch):
    instance = ADBTesting()
    instance._procs = Mock()
    instance._procs.stop.return_value = None
    instance._procs.start.return_value.poll.return_value = 0
    monkeypatch.setattr(instance, "_run", Mock(return_value={"success": True, "output": ""}))
    yield instance
    instance.shutdown()
    assert instance.long_pool.waitForDone(3000)
    instance.deleteLater()


def _run(model, tmp_path, batch_id="batch-a", device="demo-a"):
    return ADBTesting.run_monkey_test_async.__wrapped__(
        model, device, "com.example.target", {"events": 10}, device,
        str(tmp_path), 1, batch_id=batch_id,
    )


def _stop(model, batch_id="batch-a", device="demo-a"):
    return ADBTesting.kill_monkey_async.__wrapped__(model, device, 1, batch_id=batch_id)


def test_stop_queued_batch_prevents_all_commands_and_process_start(model, tmp_path):
    assert model.prepare_monkey_batch("demo-a", "batch-a")
    stopped = _stop(model)
    result = _run(model, tmp_path)

    assert stopped["success"] and stopped["already_stopped"]
    assert not result["success"] and result["batch_id"] == "batch-a"
    assert "Aborted" in result["error"]
    model._run.assert_not_called()
    model._procs.start.assert_not_called()
    assert not list(tmp_path.iterdir())
    assert model.prepare_monkey_batch("demo-a", "batch-b")


def test_cancelled_device_does_not_cancel_other_batch_target(model, tmp_path):
    assert model.prepare_monkey_batch("demo-a", "batch-a")
    assert model.prepare_monkey_batch("demo-b", "batch-a")
    _stop(model)

    assert not _run(model, tmp_path)["success"]
    assert _run(model, tmp_path, device="demo-b")["success"]
    assert [call.args[0] for call in model._procs.start.call_args_list] == [
        "demo-b_logcat", "demo-b_monkey",
    ]


def test_stop_during_initial_command_prevents_later_process_start(model, tmp_path):
    assert model.prepare_monkey_batch("demo-a", "batch-a")

    def command(args, **_kwargs):
        if args[-2:] == ["logcat", "-c"]:
            assert _stop(model)["success"]
        return {"success": True, "output": ""}

    model._run.side_effect = command
    result = _run(model, tmp_path)

    assert not result["success"] and "Aborted" in result["error"]
    model._procs.start.assert_not_called()


def test_late_old_stop_does_not_target_new_running_batch(model, tmp_path):
    assert model.prepare_monkey_batch("demo-a", "batch-a")
    assert _run(model, tmp_path)["success"]
    model._procs.reset_mock()
    assert model.prepare_monkey_batch("demo-a", "batch-b")

    def command(args, **_kwargs):
        if args[-2:] == ["logcat", "-c"]:
            stopped = _stop(model, "batch-a")
            assert stopped["already_stopped"]
            model._procs.stop.assert_not_called()
        return {"success": True, "output": ""}

    model._run.side_effect = command
    result = _run(model, tmp_path, "batch-b")

    assert result["success"] and result["batch_id"] == "batch-b"
    assert model._procs.start.call_count == 2
    assert model._run.call_count == 2


def test_late_old_worker_does_not_release_or_stop_new_batch(model, tmp_path):
    assert model.prepare_monkey_batch("demo-a", "batch-b")

    assert not _run(model, tmp_path, "batch-a")["success"]
    model._procs.stop.assert_not_called()
    model._procs.start.assert_not_called()
    assert _run(model, tmp_path, "batch-b")["success"]


def test_actual_thread_pool_queue_preserves_stop_before_execution(
    model, tmp_path, qt_application,
):
    entered = threading.Event()
    release = threading.Event()

    class Blocker(QRunnable):
        def run(self):
            entered.set()
            release.wait(3)

    model.long_pool.setMaxThreadCount(1)
    model.long_pool.start(Blocker())
    try:
        assert entered.wait(1)
        finished = QSignalSpy(model.command_finished)
        assert model.prepare_monkey_batch("demo-a", "batch-a")
        model.run_monkey_test_async(
            "demo-a", "com.example.target", {"events": 10}, "demo_a",
            str(tmp_path), 1, batch_id="batch-a",
        )
        assert _stop(model)["success"]
        release.set()
        wait_until(qt_application, lambda: finished.count() == 1)
        assert finished.at(0)[0] == "run_monkey_test_async"
        assert not finished.at(0)[1]["success"]
        assert finished.at(0)[1]["batch_id"] == "batch-a"
        model._procs.start.assert_not_called()
        model._run.assert_not_called()
    finally:
        release.set()
        assert model.long_pool.waitForDone(3000)


def _controller(model, tmp_path):
    controller = ADBAppMonkeyMixin.__new__(ADBAppMonkeyMixin)
    controller.testing_model = model
    controller.signals = ADBControllerSignals()
    controller.log_service = Mock()
    controller._emit_operation = Mock()
    controller._get_screenshot_dir = Mock(return_value=str(tmp_path))
    controller._monkey_running = set()
    controller._monkey_lock = threading.RLock()
    return controller


@pytest.mark.parametrize("failure", ["registration", "submission"])
def test_controller_submission_failure_finishes_target_and_preserves_other_batches(
    model, tmp_path, monkeypatch, failure,
):
    if failure == "registration":
        assert model.prepare_monkey_batch("demo-a", "batch-old")
    submit = Mock(side_effect=RuntimeError("queue rejected"))
    monkeypatch.setattr(model, "run_monkey_test_async", submit)
    controller = _controller(model, tmp_path)
    finished = QSignalSpy(controller.signals.monkey_target_finished)

    controller.run_monkey_test(
        ["demo-a"], {"package_name": "com.example.target", "events": 10, "throttle": 0},
        "batch-new",
    )

    assert not controller._monkey_running
    assert not controller._monkey_batch_by_device
    assert finished.count() == 1 and finished.at(0) == ["batch-new", "demo-a"]
    if failure == "registration":
        submit.assert_not_called()
        assert _run(model, tmp_path, "batch-old")["success"]
    else:
        submit.assert_called_once()
        assert model.prepare_monkey_batch("demo-a", "batch-after")


def test_controller_registers_before_dispatch_so_immediate_stop_is_retained(
    model, tmp_path, monkeypatch,
):
    controller = _controller(model, tmp_path)
    results = []

    def submit(*_args, **_kwargs):
        assert _stop(model)["success"]
        results.append(_run(model, tmp_path))

    monkeypatch.setattr(model, "run_monkey_test_async", submit)
    controller.run_monkey_test(
        ["demo-a"], {"package_name": "com.example.target", "events": 10, "throttle": 0},
        "batch-a",
    )

    assert len(results) == 1 and not results[0]["success"]
    model._procs.start.assert_not_called()
    controller._process_run_monkey_test_result(results[0])
    assert not controller._monkey_running


def test_shutdown_clears_queued_batches_and_rejects_future_registration(model):
    assert model.prepare_monkey_batch("demo-a", "batch-a")
    model.shutdown()

    assert not model._monkey_batches
    assert not model.prepare_monkey_batch("demo-a", "batch-b")
    model._procs.start.assert_not_called()
