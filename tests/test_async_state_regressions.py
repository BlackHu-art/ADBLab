"""验证异步刷新及设备批次在逆序、提交失败与取消时的身份边界。"""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from adblab.application.device_batch import DeviceBatchUseCase
from adblab.application.operations import OperationManager
from controllers._app_install import ADBAppInstallMixin
from controllers._device import ADBDeviceMixin
from models.adb_app import ADBApp
from models.adb_device import ADBDevice
from utils import adb_resolver
from utils.adb_targets import normalize_adb_connect_target


@pytest.mark.parametrize("port", ["²", "9" * 5000], ids=["superscript", "too-long"])
def test_invalid_port_returns_error_without_raising(port):
    target, error = normalize_adb_connect_target(f"127.0.0.1:{port}")
    assert target == ""
    assert error


def test_resolver_switch_during_resolution_cannot_restore_old_cache(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(adb_resolver, "_candidates", lambda: [
        ("bundled", "bundled-old"), ("env", "env-new"),
    ])
    monkeypatch.setattr(adb_resolver.os, "access", lambda *_: True)

    def exists(path):
        if path == "bundled-old":
            entered.set()
            assert release.wait(3)
        return True

    monkeypatch.setattr(adb_resolver.os.path, "isfile", exists)
    adb_resolver.set_client_preference("auto")
    results = []
    worker = threading.Thread(target=lambda: results.append(adb_resolver.resolve_adb_path()))
    try:
        worker.start()
        assert entered.wait(2)
        adb_resolver.set_client_preference("env")
        assert adb_resolver.resolve_adb_path() == "env-new"
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert results == ["env-new"]
        assert adb_resolver.resolve_adb_path() == "env-new"
    finally:
        release.set()
        worker.join(3)
        adb_resolver.set_client_preference("auto")


def _controller(kind):
    controller = object.__new__(kind)
    controller._pending_lock = threading.Lock()
    controller._device_topology_lock = threading.Lock()
    controller._device_topology_generation = 0
    controller._device_topology = ()
    controller.signals = Mock()
    controller.log_service = Mock()
    controller._emit_operation = Mock()
    controller._log_perf_if_slow = Mock()
    controller._async_update_devices = Mock()
    controller.operation_manager = OperationManager()
    controller.device_batches = DeviceBatchUseCase(controller.operation_manager)
    controller._batch_starts = {}
    controller._handler_map = {
        key: getattr(controller, value) for key, value in kind._handlers.items()
    }
    return controller


@pytest.mark.parametrize("order", [(1, 0), (0, 1)])
@pytest.mark.ui
def test_only_latest_manual_discovery_publishes_in_any_completion_order(order):
    controller = _controller(ADBDeviceMixin)
    model = controller.device_model = ADBDevice()
    tasks = []
    model.thread_pool = SimpleNamespace(start=tasks.append)
    model.command_finished.connect(controller._handle_async_response)
    model._run_readonly = Mock()
    controller.refresh_devices()
    controller.refresh_devices()
    for index in order:
        model._run_readonly.return_value = {
            "success": True,
            "output": "List of devices attached\n" + ("synthetic\tdevice\n" if index == 0 else ""),
        }
        tasks[index].run()
    assert controller._device_topology == ()
    assert controller.signals.devices_updated.emit.call_args_list == [(([],),)]
    assert controller.device_discovery_token()[1] == 0


BATCHES = [
    ("uninstall_apk", "uninstall", "uninstall_app_async", ("app.synthetic",)),
    ("clear_app_data", "clear_data", "clear_app_data_async", ("app.synthetic",)),
    ("restart_app", "restart_app", "restart_app_async", ("app.synthetic",)),
    ("get_current_activity", "current_activity", "get_current_activity_async", ()),
]


@pytest.mark.parametrize("entry,kind,method,args", BATCHES)
@pytest.mark.ui
def test_device_batch_submission_failure_finishes_all_units_and_allows_retry(
    entry, kind, method, args,
):
    controller = _controller(ADBAppInstallMixin)
    model = controller.app_model = ADBApp()
    model.command_finished.connect(controller._handle_async_response)
    model.thread_pool = SimpleNamespace(start=Mock(side_effect=RuntimeError("pool closed")))
    getattr(controller, entry)(["synthetic-a", "synthetic-b"], *args)
    assert controller.operation_manager.active_count == 0
    assert kind not in controller._batch_starts
    tasks = []
    model.thread_pool = SimpleNamespace(start=tasks.append)
    getattr(controller, entry)(["synthetic-a"], *args)
    assert len(tasks) == 1


@pytest.mark.parametrize("entry,kind,method,args", BATCHES)
@pytest.mark.ui
def test_queued_batch_cancelled_before_execution_finishes_and_late_result_cannot_finish_retry(
    entry, kind, method, args,
):
    controller = _controller(ADBAppInstallMixin)
    model = controller.app_model = ADBApp()
    tasks, responses = [], []
    model.thread_pool = SimpleNamespace(start=tasks.append)
    model.command_finished.connect(lambda name, result: responses.append((name, result)))
    model.command_finished.connect(controller._handle_async_response)
    getattr(controller, entry)(["synthetic-a"], *args)
    model.begin_shutdown()
    tasks[0].run()
    assert controller.operation_manager.active_count == 0
    model = controller.app_model = ADBApp()
    model.thread_pool = SimpleNamespace(start=tasks.append)
    model.command_finished.connect(controller._handle_async_response)
    getattr(controller, entry)(["synthetic-a"], *args)
    assert controller.operation_manager.active_count == 1
    controller._handle_async_response(*responses[0])
    assert controller.operation_manager.active_count == 1
    model._run = Mock(return_value={"success": True, "output": "Success"})
    tasks[1].run()
    assert controller.operation_manager.active_count == 0


@pytest.mark.ui
def test_latest_discovery_submission_failure_settles_once_without_releasing_older_request():
    controller = _controller(ADBDeviceMixin)
    model = controller.device_model = ADBDevice()
    tasks = []
    model.thread_pool = SimpleNamespace(start=tasks.append)
    model.command_finished.connect(controller._handle_async_response)
    model._run_readonly = Mock(return_value={"success": True, "output": ""})
    controller.refresh_devices()
    model.thread_pool.start = Mock(side_effect=RuntimeError("closed pool"))
    controller.refresh_devices()
    assert controller.device_discovery_token()[1] == 1
    assert controller._emit_operation.call_count == 1
    tasks[0].run()
    assert controller.device_discovery_token()[1] == 0
    controller.signals.devices_updated.emit.assert_not_called()
    controller.publish_detected_devices(
        ["fresh-scan"], discovery_token=controller.device_discovery_token(),
    )
    assert controller._device_topology == ("fresh-scan",)


@pytest.mark.ui
@pytest.mark.parametrize("entry,kind,method,args", BATCHES)
def test_batch_mixed_outcomes_reverse_order_and_duplicate_finish_once(entry, kind, method, args):
    controller = _controller(ADBAppInstallMixin)
    model = controller.app_model = ADBApp()
    tasks, responses = [], []
    model.thread_pool = SimpleNamespace(start=tasks.append)
    model.command_finished.connect(lambda name, result: responses.append((name, result)))
    model.command_finished.connect(controller._handle_async_response)

    def execute(command, **_kwargs):
        if command[2] == "synthetic-a":
            raise RuntimeError("synthetic execution failure")
        return {"success": True, "output": "Success"}

    model._run = execute
    getattr(controller, entry)(["synthetic-a", "synthetic-b"], *args)
    tasks[1].run()
    assert controller.operation_manager.active_count == 1
    start = controller._batch_starts[kind]
    assert len(controller.operation_manager.get(start.operation_id).unit_results) == 1
    controller._handle_async_response(*responses[0])
    assert len(controller.operation_manager.get(start.operation_id).unit_results) == 1
    tasks[0].run()
    assert controller.operation_manager.active_count == 0
    summaries = [item.args for item in controller._emit_operation.call_args_list
                 if "completed;" in item.args[2]]
    assert len(summaries) == 1
    assert summaries[0][1] is False
    assert "Success: 1" in summaries[0][2]
    assert "Failed: 1" in summaries[0][2]


@pytest.mark.ui
@pytest.mark.parametrize("entry,kind,method,args", BATCHES)
@pytest.mark.parametrize("failure", ["submission", "execution"])
def test_action_batch_summary_does_not_fail_last_successful_device(
    entry, kind, method, args, failure,
):
    from adblab.application.action_results import ActionResults, ActionSpec

    controller = _controller(ADBAppInstallMixin)
    del controller._emit_operation
    snapshots, tasks = [], []
    controller.action_results = ActionResults(snapshots.append)
    model = controller.app_model = ADBApp()
    model.command_finished.connect(controller._handle_async_response)

    def submit(task):
        if failure == "submission" and task.args[0] == "synthetic-a":
            raise RuntimeError("synthetic submission failure")
        tasks.append(task)

    def execute(command, **_kwargs):
        if command[2] == "synthetic-a":
            raise RuntimeError("synthetic execution failure")
        return {"success": True, "output": "Success"}

    model.thread_pool = SimpleNamespace(start=submit)
    model._run = execute
    controller.action_results.run(
        ActionSpec(kind, "apps", "设备批次"), ("synthetic-a", "synthetic-b"),
        lambda: getattr(controller, entry)(["synthetic-a", "synthetic-b"], *args),
    )
    for task in tasks:
        task.run()

    assert controller.operation_manager.active_count == 0
    assert snapshots[-1].state == "partial"
    assert {item.target: item.state for item in snapshots[-1].items} == {
        "synthetic-a": "failed", "synthetic-b": "succeeded",
    }
    assert "completed;" not in snapshots[-1].items[-1].detail


@pytest.mark.ui
@pytest.mark.parametrize("entry,kind,method,args", BATCHES)
def test_action_cancelled_batch_and_successful_retry_keep_independent_states(
    entry, kind, method, args,
):
    from adblab.application.action_results import ActionResults, ActionSpec

    controller = _controller(ADBAppInstallMixin)
    del controller._emit_operation
    snapshots, tasks, responses = [], [], []
    controller.action_results = ActionResults(snapshots.append)
    model = controller.app_model = ADBApp()
    model.thread_pool = SimpleNamespace(start=tasks.append)
    model.command_finished.connect(lambda name, result: responses.append((name, result)))
    model.command_finished.connect(controller._handle_async_response)

    def submit():
        controller.action_results.run(
            ActionSpec(kind, "apps", "设备批次"), ("synthetic-a", "synthetic-b"),
            lambda: getattr(controller, entry)(["synthetic-a", "synthetic-b"], *args),
        )

    submit()
    model.begin_shutdown()
    for task in tasks:
        task.run()
    cancelled = snapshots[-1]
    assert cancelled.state == "cancelled"
    assert [item.state for item in cancelled.items] == ["cancelled", "cancelled"]
    assert controller.operation_manager.active_count == 0

    model = controller.app_model = ADBApp()
    model.thread_pool = SimpleNamespace(start=tasks.append)
    model.command_finished.connect(controller._handle_async_response)
    model._run = Mock(return_value={"success": True, "output": "Success"})
    submit()
    assert controller.operation_manager.active_count == 1
    for response in responses:
        controller._handle_async_response(*response)
    assert snapshots[-1].state == "running"
    for task in tasks[2:]:
        task.run()
    assert snapshots[-1].state == "succeeded"
    assert [item.state for item in snapshots[-1].items] == ["succeeded", "succeeded"]
    assert controller.operation_manager.active_count == 0


@pytest.mark.ui
def test_obsolete_discovery_action_is_cancelled_without_republishing_devices():
    from adblab.application.action_results import ActionResults, ActionSpec

    controller = _controller(ADBDeviceMixin)
    model = controller.device_model = ADBDevice()
    tasks, snapshots = [], []
    model.thread_pool = SimpleNamespace(start=tasks.append)
    model.command_finished.connect(controller._handle_async_response)
    model._run_readonly = Mock(return_value={"success": True, "output": ""})
    controller.action_results = ActionResults(snapshots.append)
    controller.action_results.run(
        ActionSpec("refresh_devices", "devices", "刷新设备"), (), controller.refresh_devices,
    )
    controller.refresh_devices()
    tasks[1].run()
    tasks[0].run()
    assert snapshots[-1].state == "cancelled"
    assert controller.signals.devices_updated.emit.call_count == 1


@pytest.mark.ui
@pytest.mark.parametrize("order", [(1, 0), (0, 1)])
def test_reordered_discovery_restores_panel_state_and_refresh_button(monkeypatch, order):
    from controllers.signals import ADBControllerSignals
    from gui.panels.side_panel import SidePanel
    from models.device_store import DeviceStore

    monkeypatch.setattr(DeviceStore, "get_basic_devices_info", lambda: [])
    monkeypatch.setattr(DeviceStore, "get_full_devices_info", lambda _devices: [])
    panel = SidePanel()
    panel.set_device_discovery_state("empty")
    controller = _controller(ADBDeviceMixin)
    controller.signals = ADBControllerSignals()
    controller.signals.devices_updated.connect(panel.update_device_list)
    controller.signals.device_refresh_superseded.connect(panel.on_device_refresh_superseded)
    panel.signals.refresh_devices_requested.connect(controller.refresh_devices)
    model = controller.device_model = ADBDevice()
    tasks = []
    model.thread_pool = SimpleNamespace(start=tasks.append)
    model.command_finished.connect(controller._handle_async_response)
    model._run_readonly = Mock(return_value={"success": True, "output": ""})
    try:
        assert panel.request_device_refresh()
        assert not panel._devices_tab.btn_refresh.isEnabled()
        controller.refresh_devices()
        tasks[order[0]].run()
        if order[0] == 0:
            assert panel._device_discovery_state == "scanning"
        tasks[order[1]].run()
        assert controller.device_discovery_token()[1] == 0
        assert panel._device_discovery_state == "empty"
        assert panel._devices_tab.btn_refresh.isEnabled()
        assert panel.request_device_refresh()
        model.begin_shutdown()
        tasks[-1].run()
    finally:
        panel.close()


@pytest.mark.ui
@pytest.mark.parametrize("phase", ["submission", "queued-cancel", "closed-admission"])
def test_result_context_preserves_action_and_operation_envelopes_on_failure(phase):
    from adblab.application.action_results import ActionEnvelope, ActionResults, ActionSpec
    from adblab.application.envelope import split_operation_metadata
    from core.perf_trace import split_perf

    model = ADBApp()
    tasks, responses = [], []
    model.thread_pool = SimpleNamespace(start=tasks.append)
    if phase == "submission":
        model.thread_pool.start = Mock(side_effect=RuntimeError("closed pool"))
    elif phase == "closed-admission":
        model.begin_shutdown()
    model.command_finished.connect(lambda _name, result: responses.append(result))
    actions = ActionResults(lambda _snapshot: None)
    owner, generation = object(), object()
    context = {"device_ip": "synthetic-a", "request": "frozen"}

    def submit():
        model.uninstall_app_async(
            "synthetic-a", "app.synthetic", 1, _result_context=context,
            _operation_id="operation", _operation_unit_id="unit",
            _operation_owner_token=owner, _operation_generation_token=generation,
        )

    try:
        actions.run(ActionSpec("uninstall", "apps", "卸载"), ("synthetic-a",), submit)
    except RuntimeError:
        assert phase == "submission"
    if phase == "queued-cancel":
        context["request"] = "changed"
        model.begin_shutdown()
        tasks[0].run()
    assert len(responses) == 1
    assert isinstance(responses[0], ActionEnvelope)
    payload, metadata = split_operation_metadata(responses[0].payload)
    payload, _perf = split_perf(payload)
    assert payload["success"] is False
    assert payload["device_ip"] == "synthetic-a"
    assert payload["request"] == "frozen"
    assert metadata.unit_id == "unit"
    assert metadata.owner_token is owner
    assert metadata.generation_token is generation
