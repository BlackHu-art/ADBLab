import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from adblab.application.action_results import ActionResults
from adblab.application.envelope import split_operation_metadata
from controllers._base import _ADBControllerBase
from core.perf_trace import split_perf
from models.adb_advanced import ADBAdvanced
from models.adb_model import ADBModelCore, async_command
from models.adb_testing import ADBTesting


def test_native_readonly_query_cancels_in_flight_but_write_keeps_default(monkeypatch):
    import time

    from core import exec as execution
    from core.adb_transport import ExecutionResult

    model = ADBAdvanced()
    entered = threading.Event()
    release = threading.Event()
    result = []

    def capture(_cmd, _timeout, cancelled):
        entered.set()
        while not release.wait(0.005):
            if cancelled():
                return ExecutionResult(kind="cancelled")
        return ExecutionResult(b"done")

    def native(*_args, **_kwargs):
        entered.set()
        release.wait(2)
        return SimpleNamespace(stdout="done", stderr="", returncode=0)

    monkeypatch.setattr(execution, "_adb_runtime", None)
    monkeypatch.setattr(execution, "resolve_adb_program", lambda: "adb")
    monkeypatch.setattr(execution, "native_capture", capture)
    monkeypatch.setattr(execution.subprocess, "run", native)
    worker = threading.Thread(target=lambda: result.append(
        ADBAdvanced.get_kernel_version_async.__wrapped__(model, "device-1")
    ))
    try:
        worker.start()
        assert entered.wait(1)
        started = time.monotonic()
        model.begin_shutdown()
        worker.join(0.5)
        assert not worker.is_alive(), "只读查询关闭后仍等待原生超时"
        assert time.monotonic() - started < 0.5
        assert result[0]["cancelled"] is True
        assert execution.CommandRunner.active_count() == 0
    finally:
        release.set()
        worker.join(2)

    calls = []
    monkeypatch.setattr(execution.CommandRunner, "run", lambda cmd, **kw: (
        calls.append((cmd, kw)) or execution.CommandResult(True)
    ))
    ADBAdvanced.settings_put_async.__wrapped__(model, "device-1", "system", "key", "value")
    assert "cancelled" not in calls[0][1]


def test_controller_shutdown_waits_for_owned_queued_commands():
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class BlockingModel(ADBModelCore):
        @async_command
        def work_async(self):
            entered.set()
            release.wait(2)
            return {"success": True}

    from PySide6.QtCore import QThreadPool

    model = BlockingModel()
    model.thread_pool = QThreadPool()
    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.action_results = ActionResults(lambda _result: None)
    controller.device_model = model
    controller.app_model = ADBModelCore()
    controller.testing_model = ADBModelCore()
    controller.advanced_model = ADBModelCore()
    controller.log_service = Mock()
    controller.executor = Mock()
    worker = threading.Thread(target=lambda: (controller.shutdown(), finished.set()))
    try:
        model.work_async()
        assert entered.wait(1)
        worker.start()
        assert not finished.wait(0.15), "控制器在模型任务尚未退出时报告完成"
        release.set()
        worker.join(2)
        assert finished.is_set()
        assert model.thread_pool.activeThreadCount() == 0
    finally:
        release.set()
        if worker.ident is not None:
            worker.join(2)
        model.thread_pool.waitForDone(2000)


def test_short_command_wait_reports_live_command_until_native_exit(monkeypatch):
    from core import exec as execution

    entered = threading.Event()
    release = threading.Event()

    def native(*_args, **_kwargs):
        entered.set()
        release.wait(2)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(execution, "_adb_runtime", None)
    monkeypatch.setattr(execution.subprocess, "run", native)
    worker = threading.Thread(target=lambda: execution.CommandRunner.run(["test-client"]))
    try:
        worker.start()
        assert entered.wait(1)
        assert not execution.CommandRunner.wait_for_idle(0.01)
        release.set()
        assert execution.CommandRunner.wait_for_idle(1)
    finally:
        release.set()
        worker.join(2)


class _QueuedPool:
    def __init__(self):
        self.tasks = []

    def start(self, task):
        self.tasks.append(task)


class _AdmissionModel(ADBModelCore):
    def __init__(self):
        super().__init__()
        self.calls = 0

    @async_command
    def sample_async(self):
        self.calls += 1
        return {"success": True}


def test_queued_command_rechecks_terminal_fence_and_preserves_result_envelope():
    model = _AdmissionModel()
    pool = _QueuedPool()
    model.thread_pool = pool
    received = []
    model.command_finished.connect(lambda method, result: received.append((method, result)))

    model.sample_async(
        _operation_id="shutdown-operation",
        _operation_kind="sample",
        _operation_task_id="queued-command",
    )
    assert len(pool.tasks) == 1

    model.begin_shutdown()
    pool.tasks[0].run()

    assert model.calls == 0
    assert len(received) == 1
    method_name, wrapped = received[0]
    payload_with_perf, metadata = split_operation_metadata(wrapped)
    payload, perf = split_perf(payload_with_perf)
    assert method_name == "sample_async"
    assert payload == {
        "success": False,
        "cancelled": True,
        "error": "Model is shutting down",
    }
    assert metadata is not None
    assert metadata.operation_id == "shutdown-operation"
    assert metadata.task_id == "queued-command"
    assert perf["method"] == "sample_async"

    model.sample_async()
    assert len(pool.tasks) == 1
    assert len(received) == 1


def test_controller_closes_every_model_admission_before_model_cleanup():
    events = []

    class ModelProbe:
        def __init__(self, name):
            self.name = name

        def begin_shutdown(self):
            events.append(("fence", self.name))

        def shutdown(self):
            events.append(("cleanup", self.name))

    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.action_results = ActionResults(lambda _result: None)
    controller.device_model = ModelProbe("device")
    controller.app_model = ModelProbe("app")
    controller.testing_model = ModelProbe("testing")
    controller.advanced_model = ModelProbe("advanced")
    controller.log_service = Mock()
    controller.executor = Mock()

    with patch("controllers._base.ProcessRunner.stop_all_tracked"):
        controller.shutdown()

    assert events == [
        ("fence", "device"),
        ("fence", "app"),
        ("fence", "testing"),
        ("fence", "advanced"),
        ("cleanup", "testing"),
        ("cleanup", "advanced"),
    ]


def test_controller_shutdown_cancels_screen_record_already_queued_before_fence():
    advanced = ADBAdvanced()
    pool = _QueuedPool()
    advanced.thread_pool = pool
    advanced._rec_procs = Mock()
    received = []
    advanced.command_finished.connect(lambda _method, result: received.append(result))

    advanced.start_screen_record_async(
        "device-1",
        "C:/captures",
        _operation_id="record-operation",
        _operation_kind="screen_record_start",
        _operation_task_id="record-device-1",
    )
    assert len(pool.tasks) == 1

    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.action_results = ActionResults(lambda _result: None)
    controller.device_model = ADBModelCore()
    controller.app_model = ADBModelCore()
    controller.testing_model = SimpleNamespace(begin_shutdown=Mock(), shutdown=Mock())
    controller.advanced_model = advanced
    controller.log_service = Mock()
    controller.executor = Mock()
    with patch("controllers._base.ProcessRunner.stop_all_tracked"):
        controller.shutdown()

    pool.tasks[0].run()

    advanced._rec_procs.start.assert_not_called()
    advanced._rec_procs.stop_all.assert_called_once_with()
    payload_with_perf, metadata = split_operation_metadata(received[0])
    payload, _perf = split_perf(payload_with_perf)
    assert payload["success"] is False
    assert payload["cancelled"] is True
    assert metadata is not None
    assert metadata.operation_id == "record-operation"


def test_screen_record_start_and_shutdown_have_atomic_lifecycle_order():
    start_entered = threading.Event()
    allow_start_return = threading.Event()
    stop_called = threading.Event()
    order = []
    order_lock = threading.Lock()

    class RecordingRunner:
        def start(self, *_args, **_kwargs):
            with order_lock:
                order.append("start-entered")
            start_entered.set()
            assert allow_start_return.wait(2.0)
            with order_lock:
                order.append("start-returned")
            return SimpleNamespace(pid=123, poll=lambda: None)

        def stop_all(self):
            with order_lock:
                order.append("stop-all")
            stop_called.set()

    model = ADBAdvanced()
    model._rec_procs = RecordingRunner()
    result = []
    shutdown_started = threading.Event()

    def start_recording():
        result.append(
            ADBAdvanced.start_screen_record_async.__wrapped__(
                model,
                "device-1",
                "C:/captures",
            )
        )

    def shutdown_model():
        shutdown_started.set()
        model.shutdown()

    record_thread = threading.Thread(target=start_recording)
    shutdown_thread = threading.Thread(target=shutdown_model)
    with patch("models.adb_advanced.time.sleep"):
        record_thread.start()
        try:
            assert start_entered.wait(1.0)
            shutdown_thread.start()
            assert shutdown_started.wait(1.0)
            assert not stop_called.is_set()
            allow_start_return.set()
            record_thread.join(2.0)
            shutdown_thread.join(2.0)
        finally:
            allow_start_return.set()
            record_thread.join(2.0)
            if shutdown_thread.ident is not None:
                shutdown_thread.join(2.0)

    assert not record_thread.is_alive()
    assert not shutdown_thread.is_alive()
    assert order == ["start-entered", "start-returned", "stop-all"]
    assert result[0]["success"] is True


def test_testing_process_cannot_start_after_shutdown_stop_all():
    stop_entered = threading.Event()
    allow_stop_return = threading.Event()
    start_attempted = threading.Event()
    order = []

    class BlockingStopRunner:
        def __init__(self):
            self.start_calls = []

        def start(self, *args, **kwargs):
            self.start_calls.append((args, kwargs))
            order.append("start")
            return Mock()

        def stop_all(self):
            order.append("stop-entered")
            stop_entered.set()
            assert allow_stop_return.wait(2.0)
            order.append("stop-returned")

    model = ADBTesting()
    runner = BlockingStopRunner()
    model._procs = runner
    start_errors = []

    def start_process():
        start_attempted.set()
        try:
            model._start_testing_process("device-1_monkey", ["adb", "shell", "monkey"])
        except Exception as exc:
            start_errors.append(exc)

    shutdown_thread = threading.Thread(target=model.shutdown)
    start_thread = threading.Thread(target=start_process)
    shutdown_thread.start()
    try:
        assert stop_entered.wait(1.0)
        start_thread.start()
        assert start_attempted.wait(1.0)
        assert runner.start_calls == []
        allow_stop_return.set()
        shutdown_thread.join(2.0)
        start_thread.join(2.0)
    finally:
        allow_stop_return.set()
        shutdown_thread.join(2.0)
        if start_thread.ident is not None:
            start_thread.join(2.0)

    assert not shutdown_thread.is_alive()
    assert not start_thread.is_alive()
    assert runner.start_calls == []
    assert order == ["stop-entered", "stop-returned"]
    assert len(start_errors) == 1
    assert isinstance(start_errors[0], RuntimeError)
    assert str(start_errors[0]) == "Model is shutting down"


def test_testing_process_started_before_shutdown_is_stopped_after_start_returns():
    start_entered = threading.Event()
    allow_start_return = threading.Event()
    stop_called = threading.Event()
    order = []

    class StartFirstRunner:
        def start(self, *_args, **_kwargs):
            order.append("start-entered")
            start_entered.set()
            assert allow_start_return.wait(2.0)
            order.append("start-returned")
            return Mock()

        def stop_all(self):
            order.append("stop-all")
            stop_called.set()

    model = ADBTesting()
    model._procs = StartFirstRunner()
    start_result = []
    shutdown_started = threading.Event()

    def start_process():
        start_result.append(
            model._start_testing_process("device-1_logcat", ["adb", "logcat"])
        )

    def shutdown_model():
        shutdown_started.set()
        model.shutdown()

    start_thread = threading.Thread(target=start_process)
    shutdown_thread = threading.Thread(target=shutdown_model)
    start_thread.start()
    try:
        assert start_entered.wait(1.0)
        shutdown_thread.start()
        assert shutdown_started.wait(1.0)
        assert not stop_called.is_set()
        allow_start_return.set()
        start_thread.join(2.0)
        shutdown_thread.join(2.0)
    finally:
        allow_start_return.set()
        start_thread.join(2.0)
        if shutdown_thread.ident is not None:
            shutdown_thread.join(2.0)

    assert not start_thread.is_alive()
    assert not shutdown_thread.is_alive()
    assert len(start_result) == 1
    assert order == ["start-entered", "start-returned", "stop-all"]
