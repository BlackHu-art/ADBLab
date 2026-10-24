"""验证注入模型的真实 Qt 信号、结果屏障与 Controller 关闭契约。"""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Signal

from adblab.application.action_results import ActionEnvelope, ActionSpec, capture_action_job
from controllers import ADBController
from controllers.model_dependencies import ControllerModels

pytestmark = pytest.mark.ui

MODEL_ATTRIBUTES = (
    "device_model", "app_model", "testing_model", "advanced_model",
)


class FakeModel(QObject):
    """只提供信号和关闭协议，不创建业务线程或访问设备。"""

    command_finished = Signal(str, object)
    action_progress = Signal(object, str)

    def __init__(self, name, events, failures):
        super().__init__()
        self.name = name
        self.events = events
        self.failures = failures

    def _record(self, operation):
        assert threading.current_thread() is not threading.main_thread()
        event = f"{self.name}.{operation}"
        self.events.append(event)
        if event in self.failures:
            raise self.failures[event]

    def begin_shutdown(self):
        self._record("begin")

    def shutdown(self):
        self._record("shutdown")

    def wait_for_commands(self):
        self._record("wait")

    def assert_cleanup_complete(self):
        self._record("verify")


class FakeDeviceStore:
    """隔离 Controller 构造时的历史加载，不接触真实存储。"""

    loads = 0

    @classmethod
    def load(cls):
        cls.loads += 1


def shutdown_in_background(controller):
    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(controller.shutdown).result(timeout=5)


@pytest.fixture
def wiring(qt_application, isolated_app_settings, monkeypatch):
    events = []
    failures = {}
    models = tuple(FakeModel(name, events, failures) for name in MODEL_ATTRIBUTES)
    bundle = ControllerModels(*models)
    monkeypatch.setattr("controllers._base.DeviceStore", FakeDeviceStore)
    monkeypatch.setattr(FakeDeviceStore, "loads", 0)
    monkeypatch.setattr(
        "controllers._base.ProcessRunner.stop_all_tracked",
        lambda: events.append("process.stop"),
    )
    controller = ADBController(Mock(), model_factory=lambda: bundle)
    # 保留真实 executor 的绑定方法；即使关闭测试中途失败也能回收已有资源。
    reclaim_executor = controller.executor.shutdown
    try:
        assert FakeDeviceStore.loads == 1
        yield SimpleNamespace(
            controller=controller, models=models, events=events, failures=failures,
        )
    finally:
        try:
            if not controller._shutting_down:
                shutdown_in_background(controller)
        finally:
            with ThreadPoolExecutor(max_workers=1) as worker:
                worker.submit(reclaim_executor, wait=True, cancel_futures=True).result(timeout=5)


def start_action(controller, key):
    job = controller.action_results.run(
        ActionSpec(key, "devices", key), ("synthetic-target",),
        lambda: capture_action_job("input_tap_async", "synthetic-target"),
    )
    assert job is not None
    return job


def tap_payload():
    return {
        "success": True, "device_ip": "synthetic-target", "x": 12, "y": 34,
        "output": "synthetic tap result",
    }


@pytest.mark.parametrize("model_attribute", MODEL_ATTRIBUTES)
def test_each_injected_model_routes_result_and_progress_once(wiring, model_attribute):
    controller = wiring.controller
    model = getattr(controller, model_attribute)
    results = []
    operations = []
    controller.signals.action_result_changed.connect(results.append)
    controller.signals.operation_completed.connect(
        lambda *args: operations.append(args),
    )
    job = start_action(controller, model_attribute)
    results.clear()

    model.action_progress.emit(job, "synthetic progress")

    assert len(results) == 1
    assert results[0].request_id == job.request_id
    assert results[0].message == "synthetic progress"
    assert results[0].state == "running"
    assert operations == []
    results.clear()

    model.command_finished.emit("input_tap_async", ActionEnvelope(tap_payload(), job))

    assert operations == [("input_tap", True, "Tap (12,34) on synthetic-target")]
    completed = [result for result in results if result.state == "succeeded"]
    assert len(completed) == 1
    assert completed[0] == controller.action_results.recent()[0]
    assert completed[0].request_id == job.request_id
    assert len(completed[0].items) == 1
    assert completed[0].items[0].job_id == job.job_id
    assert completed[0].items[0].detail == "synthetic tap result"


@pytest.mark.parametrize("fails_midway", [False, True], ids=["normal", "first-error"])
def test_injected_models_keep_shutdown_order_and_first_error(wiring, monkeypatch, fails_midway):
    controller = wiring.controller
    first_error = RuntimeError("synthetic testing shutdown failure")
    later_error = ValueError("synthetic device wait failure")
    if fails_midway:
        wiring.failures["testing_model.shutdown"] = first_error
        wiring.failures["device_model.wait"] = later_error
    close_results = controller.action_results.close
    shutdown_executor = controller.executor.shutdown

    def close():
        wiring.events.append("results.close")
        close_results()

    def stop_executor(*, wait, cancel_futures):
        assert wait is True and cancel_futures is True
        wiring.events.append("executor.shutdown")
        shutdown_executor(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(controller.action_results, "close", close)
    monkeypatch.setattr(controller.executor, "shutdown", stop_executor)
    controller.executor.submit(lambda: None).result(timeout=5)

    if fails_midway:
        with pytest.raises(RuntimeError) as caught:
            shutdown_in_background(controller)
        assert caught.value is first_error
        assert any("ValueError" in note for note in first_error.__notes__)
    else:
        shutdown_in_background(controller)

    assert wiring.events == [
        "results.close",
        "device_model.begin", "app_model.begin", "testing_model.begin", "advanced_model.begin",
        "testing_model.shutdown", "advanced_model.shutdown",
        "process.stop", "executor.shutdown",
        "device_model.wait", "app_model.wait", "testing_model.wait", "advanced_model.wait",
        "device_model.verify", "testing_model.verify",
    ]
    assert controller._shutting_down is True
    closed_submission = Mock()
    assert controller.action_results.run(
        ActionSpec("closed", "devices", "closed"), (), closed_submission,
    ) is None
    closed_submission.assert_not_called()
    with pytest.raises(RuntimeError, match="cannot schedule new futures after shutdown"):
        controller.executor.submit(lambda: None)


def test_shutdown_uses_current_model_attributes(wiring):
    replacement = FakeModel("replacement", wiring.events, wiring.failures)
    wiring.controller.device_model = replacement

    shutdown_in_background(wiring.controller)

    assert "replacement.begin" in wiring.events
    assert "replacement.wait" in wiring.events
    assert "replacement.verify" in wiring.events
    assert not any(event.startswith("device_model.") for event in wiring.events)


def test_late_model_signals_are_ignored_after_shutdown(wiring, qt_application):
    controller = wiring.controller
    jobs = [start_action(controller, attribute) for attribute in MODEL_ATTRIBUTES]
    results = []
    operations = []
    controller.signals.action_result_changed.connect(results.append)
    controller.signals.operation_completed.connect(lambda *args: operations.append(args))

    shutdown_in_background(controller)
    results.clear()
    operations.clear()
    for model, job in zip(wiring.models, jobs, strict=True):
        model.action_progress.emit(job, "late progress")
        model.command_finished.emit("input_tap_async", ActionEnvelope(tap_payload(), job))
        # 无信封的兼容返回也必须被 Controller 的关闭屏障拒收。
        model.command_finished.emit("input_tap_async", tap_payload())
    qt_application.processEvents()

    assert results == []
    assert operations == []
    assert controller.action_results.recent() == ()
