import threading
from unittest.mock import Mock, patch

import pytest

from adblab.application.device_batch import DeviceBatchUseCase
from adblab.application.envelope import OperationMetadata
from adblab.application.install_batch import InstallBatchUseCase, InstallRequest
from adblab.application.operations import (
    OperationManager,
    OperationState,
    OperationTransitionError,
)
from controllers import ADBController
from controllers._app import ADBAppMixin


class _BlockingRunningManager(OperationManager):
    def __init__(self):
        super().__init__()
        self.operation_visible = threading.Event()
        self.release_start = threading.Event()

    def mark_running(self, operation_id, **kwargs):
        running = super().mark_running(operation_id, **kwargs)
        self.operation_visible.set()
        assert self.release_start.wait(2)
        return running


class _RaiseAfterBeginManager(OperationManager):
    def mark_running(self, operation_id, **kwargs):
        super().mark_running(operation_id, **kwargs)
        raise RuntimeError("mark running failed")


def _controller():
    ids = (f"operation-{number}" for number in range(1, 100))
    controller = ADBAppMixin.__new__(ADBAppMixin)
    controller.signals = Mock()
    controller.log_service = Mock()
    controller.app_model = Mock()
    controller.operation_manager = OperationManager()
    controller._generate_operation_id = lambda: next(ids)
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=controller._generate_operation_id,
    )
    controller.device_batches = DeviceBatchUseCase(
        controller.operation_manager,
        id_factory=controller._generate_operation_id,
    )
    controller._batch_starts = {}
    controller._pending_lock = threading.Lock()
    controller._operation_handler_map = {
        "install_apk": controller._process_install_operation_result,
    }
    controller._install_terminal_lock = threading.RLock()
    controller._install_owned_operations = {}
    controller._install_starting_operations = set()
    controller._install_result_callbacks = {}
    controller._install_deferred_terminals = {}
    controller._install_orphaned_operations = {}
    return controller


def _full_controller():
    controller = ADBController.__new__(ADBController)
    template = _controller()
    controller.__dict__.update(template.__dict__)
    controller._operation_handler_map = {
        "install_apk": controller._process_install_operation_result,
    }
    return controller


def _assert_install_state_cleared(controller):
    assert controller.operation_manager.active_count == 0
    assert controller.install_batch_use_case._active_units == {}
    assert controller.install_batch_use_case._active_owner_tokens == {}
    assert controller.install_batch_use_case._active_kinds == {}
    assert controller.install_batch_use_case._active_generations == {}
    assert controller.install_batch_use_case._inactive_owner_tokens == {}
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}
    assert controller._install_orphaned_operations == {}


def _pause_after_install_terminalization(controller, method_name, action):
    real_method = getattr(controller.install_batch_use_case, method_name)
    terminalized = threading.Event()
    release_publication = threading.Event()
    results = []
    errors = []

    def pause_before_controller_publication(*args, **kwargs):
        outcome = real_method(*args, **kwargs)
        terminalized.set()
        assert release_publication.wait(2)
        return outcome

    setattr(
        controller.install_batch_use_case,
        method_name,
        Mock(side_effect=pause_before_controller_publication),
    )

    def run():
        try:
            results.append(action())
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert terminalized.wait(2)
    return thread, release_publication, results, errors


def _release_paused_publication(thread, release_publication):
    release_publication.set()
    thread.join(2)
    assert not thread.is_alive()


def _pause_before_first_submit(controller, action):
    manager = _BlockingRunningManager()
    controller.operation_manager = manager
    controller.install_batch_use_case = InstallBatchUseCase(
        manager,
        id_factory=controller._generate_operation_id,
    )
    results = []
    errors = []

    def run():
        try:
            results.append(action())
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert manager.operation_visible.wait(2)
    return manager, thread, results, errors


def _release_paused_start(manager, thread):
    manager.release_start.set()
    thread.join(2)
    assert not thread.is_alive()


def _active_metadata_and_result(manager, owner_token):
    snapshot = manager.active_snapshot()[0]
    unit_id = snapshot.unit_ids[0]
    metadata = OperationMetadata(
        version=1,
        operation_id=snapshot.operation_id,
        operation_kind=snapshot.kind,
        method_name="install_apk",
        task_id=unit_id,
        unit_id=unit_id,
        target_id="device-a",
        owner_token=owner_token,
        generation_token=snapshot.generation_token,
    )
    result = {
        "success": True,
        "device_ip": "device-a",
        "apk_path": "a.apk",
        "apk_name": "a.apk",
        "index": 1,
        "operation": "batch_install",
    }
    return snapshot, metadata, result


def _submitted(controller, operation_id=None):
    calls = controller.app_model.install_apk_async.call_args_list
    if operation_id is None:
        return calls
    return [call for call in calls if call.kwargs["_operation_id"] == operation_id]


def _metadata(call, **changes):
    values = {
        "version": 1,
        "operation_id": call.kwargs["_operation_id"],
        "operation_kind": call.kwargs["_operation_kind"],
        "method_name": "install_apk",
        "task_id": call.kwargs["_operation_task_id"],
        "unit_id": call.kwargs["_operation_unit_id"],
        "target_id": call.kwargs["_operation_target_id"],
        "owner_token": call.kwargs.get("_operation_owner_token"),
        "generation_token": call.kwargs.get("_operation_generation_token"),
    }
    values.update(changes)
    return OperationMetadata(**values)


def _metadata_with_owner(call, owner_token, **changes):
    return _metadata(call, owner_token=owner_token, **changes)


def _result(call, *, success=True, **changes):
    values = {
        "success": success,
        "device_ip": call.args[0],
        "apk_path": call.args[1],
        "apk_name": call.args[2],
        "index": call.args[3],
        "operation": call.args[4],
    }
    if not success:
        values["error"] = "install failed"
    values.update(changes)
    return values


def _finish(controller, call, *, success=True, **changes):
    return controller._process_install_operation_result(
        _result(call, success=success, **changes),
        _metadata(call),
    )


def test_overlapping_install_batches_keep_identity_and_emit_only_terminal_results():
    controller = _controller()
    with patch.object(
        __import__("controllers._app", fromlist=["QFileDialog"]).QFileDialog,
        "getOpenFileNames",
        side_effect=[(["a.apk"], ""), (["b.apk"], "")],
    ):
        operation_a = controller.batch_install_apk(["device-a", "device-b"])
        operation_b = controller.batch_install_apk(["device-a", "device-b"])

    tasks_a = _submitted(controller, operation_a)
    tasks_b = _submitted(controller, operation_b)
    assert operation_a != operation_b
    assert controller.signals.operation_completed.emit.call_count == 0
    assert {call.kwargs["_operation_id"] for call in tasks_a} == {operation_a}
    assert {call.kwargs["_operation_id"] for call in tasks_b} == {operation_b}
    assert {call.kwargs["_operation_task_id"] for call in tasks_a}.isdisjoint(
        {call.kwargs["_operation_task_id"] for call in tasks_b}
    )

    for call in (tasks_a[0], tasks_b[0], tasks_a[1], tasks_b[1]):
        _finish(controller, call)

    assert controller.signals.operation_completed.emit.call_count == 2
    assert controller.operation_manager.active_count == 0
    assert "install" not in controller._batch_starts
    assert "batch_install" not in controller._batch_starts


def test_cancel_before_first_submit_emits_one_terminal_after_start_handoff():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        manager, thread, results, errors = _pause_before_first_submit(
            controller,
            lambda: controller.batch_install_apk(["device-a"]),
        )
    snapshot = manager.active_snapshot()[0]

    assert controller.cancel_install_batch(snapshot.operation_id) is True
    _release_paused_start(manager, thread)

    assert errors == []
    assert results == [snapshot.operation_id]
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_deferred_terminals == {}


def test_protocol_failure_before_first_submit_emits_one_terminal_after_start_handoff():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        manager, thread, results, errors = _pause_before_first_submit(
            controller,
            lambda: controller.batch_install_apk(["device-a"]),
        )
    snapshot = manager.active_snapshot()[0]

    controller._fail_operation_protocol(snapshot, "metadata mismatch")
    _release_paused_start(manager, thread)

    assert errors == []
    assert results == [snapshot.operation_id]
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_deferred_terminals == {}


def test_valid_result_before_first_submit_emits_one_terminal_after_start_handoff():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        manager, thread, results, errors = _pause_before_first_submit(
            controller,
            lambda: controller.batch_install_apk(["device-a"]),
        )
    snapshot = manager.active_snapshot()[0]
    ownership = controller._install_owned_operations[snapshot.operation_id]
    snapshot, metadata, result = _active_metadata_and_result(manager, ownership)

    controller._process_install_operation_result(result, metadata)
    _release_paused_start(manager, thread)

    assert errors == []
    assert results == [snapshot.operation_id]
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}


def test_retry_cancel_before_first_submit_emits_one_child_terminal_after_handoff():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        parent_id = controller.batch_install_apk(["device-a"])
    parent_call = _submitted(controller, parent_id)[0]
    parent_outcome = _finish(controller, parent_call, success=False)
    controller.signals.operation_completed.emit.reset_mock()

    manager, thread, results, errors = _pause_before_first_submit(
        controller,
        lambda: controller.retry_failed_install_batch(parent_outcome),
    )
    child = manager.active_snapshot()[0]

    assert child.parent_operation_id == parent_id
    assert controller.cancel_install_batch(child.operation_id) is True
    _release_paused_start(manager, thread)

    assert errors == []
    assert results == [child.operation_id]
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_deferred_terminals == {}


def test_queued_log_error_happens_after_terminal_handoff_without_state_leak():
    controller = _controller()

    def complete_during_submit(*args, **kwargs):
        call = Mock(args=args, kwargs=kwargs)
        controller._process_install_operation_result(_result(call), _metadata(call))

    def fail_queued_log(_level, message, **_kwargs):
        if message.startswith("Queued "):
            raise RuntimeError("log unavailable")

    controller.app_model.install_apk_async.side_effect = complete_during_submit
    controller.log_service.log.side_effect = fail_queued_log

    with (
        patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")),
        pytest.raises(RuntimeError, match="log unavailable"),
    ):
        controller.batch_install_apk(["device-a"])

    controller.signals.operation_completed.emit.assert_called_once()
    assert controller.operation_manager.active_count == 0
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}


def test_generated_id_collision_cannot_release_another_normal_start_reservation():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["parent.apk"], "")):
        parent_id = controller.batch_install_apk(["device-parent"])
    parent_call = _submitted(controller, parent_id)[0]
    failed_parent = _finish(controller, parent_call, success=False)
    controller.signals.operation_completed.emit.reset_mock()
    controller._generate_operation_id = Mock(return_value="shared-operation")
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=lambda: "unit-1",
    )
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        manager, thread, results, errors = _pause_before_first_submit(
            controller,
            lambda: controller.batch_install_apk(["device-a"]),
        )
        with pytest.raises(OperationTransitionError, match="Duplicate operation id"):
            controller.retry_failed_install_batch(failed_parent)
    snapshot = manager.active_snapshot()[0]

    assert snapshot.operation_id == "shared-operation"
    assert controller._install_starting_operations == {"shared-operation"}
    assert controller.cancel_install_batch(snapshot.operation_id) is True
    assert controller.signals.operation_completed.emit.call_count == 0
    _release_paused_start(manager, thread)

    assert errors == []
    assert results == [snapshot.operation_id]
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_deferred_terminals == {}


def test_generated_id_collision_cannot_release_another_start_from_retry_or_empty_retry():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        failed_parent_id = controller.batch_install_apk(["device-a"])
        successful_parent_id = controller.batch_install_apk(["device-b"])
    failed_call = _submitted(controller, failed_parent_id)[0]
    successful_call = _submitted(controller, successful_parent_id)[0]
    failed_parent = _finish(controller, failed_call, success=False)
    successful_parent = _finish(controller, successful_call)
    controller.signals.operation_completed.emit.reset_mock()
    controller._generate_operation_id = Mock(return_value="shared-operation")
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=lambda: "unit-1",
    )
    manager, thread, results, errors = _pause_before_first_submit(
        controller,
        lambda: controller.retry_failed_install_batch(failed_parent),
    )
    child = manager.active_snapshot()[0]

    with pytest.raises(OperationTransitionError, match="Duplicate operation id"):
        controller._start_install_batch(
            "batch_install",
            (InstallRequest("device-b", "b.apk", "b.apk"),),
        )
    assert controller._install_starting_operations == {"shared-operation"}

    with pytest.raises(OperationTransitionError, match="Duplicate operation id"):
        controller.retry_failed_install_batch(successful_parent)
    assert controller._install_starting_operations == {"shared-operation"}

    assert controller.cancel_install_batch(child.operation_id) is True
    assert controller.signals.operation_completed.emit.call_count == 0
    _release_paused_start(manager, thread)

    assert errors == []
    assert results == [child.operation_id]
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_deferred_terminals == {}


def test_cancel_terminalization_keeps_normal_ownership_until_publication():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["parent.apk"], "")):
        parent_id = controller.batch_install_apk(["device-parent"])
    failed_parent = _finish(controller, _submitted(controller, parent_id)[0], success=False)
    controller.signals.operation_completed.emit.reset_mock()
    controller._generate_operation_id = Mock(return_value="shared-operation")
    first_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
    )
    thread, release_publication, results, errors = _pause_after_install_terminalization(
        controller,
        "cancel_owned",
        lambda: controller.cancel_install_batch(first_id),
    )

    try:
        with pytest.raises(OperationTransitionError, match="Duplicate operation id"):
            controller.retry_failed_install_batch(failed_parent)
    finally:
        _release_paused_publication(thread, release_publication)

    assert errors == []
    assert results == [True]
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}

    reused_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-b", "b.apk", "b.apk"),),
    )
    assert reused_id == "shared-operation"
    _finish(controller, _submitted(controller, reused_id)[-1])
    assert controller.operation_manager.active_count == 0
    assert controller._install_owned_operations == {}
    _finish(controller, _submitted(controller, reused_id)[-1])
    assert controller.signals.operation_completed.emit.call_count == 2
    assert controller._install_owned_operations == {}


def test_protocol_fail_terminalization_keeps_retry_ownership_until_publication():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        parent_id = controller.batch_install_apk(["device-a"])
    failed_parent = _finish(controller, _submitted(controller, parent_id)[0], success=False)
    controller.signals.operation_completed.emit.reset_mock()
    controller._generate_operation_id = Mock(return_value="shared-operation")
    child_id = controller.retry_failed_install_batch(failed_parent)
    child = controller.operation_manager.get(child_id)
    thread, release_publication, results, errors = _pause_after_install_terminalization(
        controller,
        "fail_snapshot",
        lambda: controller._fail_operation_protocol(child, "metadata mismatch"),
    )

    try:
        with pytest.raises(OperationTransitionError, match="Duplicate operation id"):
            controller._start_install_batch(
                "batch_install",
                (InstallRequest("device-b", "b.apk", "b.apk"),),
            )
    finally:
        _release_paused_publication(thread, release_publication)

    assert errors == []
    assert results[0].snapshot.state is OperationState.FAILED
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}


@pytest.mark.parametrize(
    ("route_op_type", "metadata_changes"),
    (
        ("install_apk", {}),
        ("install_apk", {"operation_kind": "install", "method_name": "wrong_method"}),
        ("wrong_method", {"operation_kind": "install", "method_name": "wrong_method"}),
    ),
)
def test_old_generation_envelope_cannot_change_reused_retry_generation(
    route_op_type,
    metadata_changes,
):
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileName", return_value=("parent.apk", "")):
        parent_id = controller.install_apk(["device-parent"])
    parent_call = _submitted(controller, parent_id)[0]
    failed_parent = _finish(controller, parent_call, success=False)

    controller._generate_operation_id = Mock(return_value="shared-operation")
    unit_ids = iter(("old-unit", "retry-unit"))
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=lambda: next(unit_ids),
    )
    old_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-old", "old.apk", "old.apk"),),
    )
    old_call = _submitted(controller, old_id)[0]
    old_owner = controller._install_owned_operations[old_id]
    old_metadata = _metadata_with_owner(old_call, old_owner, **metadata_changes)

    controller._route_operation_response(route_op_type, _result(old_call), old_metadata)
    assert controller.operation_manager.active_count == 0
    assert controller._install_owned_operations == {}

    retry_id = controller.retry_failed_install_batch(failed_parent)
    retry_call = _submitted(controller, retry_id)[-1]
    retry_owner = controller._install_owned_operations[retry_id]
    retry_metadata = _metadata_with_owner(retry_call, retry_owner)
    terminal_count = controller.signals.operation_completed.emit.call_count

    controller._route_operation_response(route_op_type, _result(old_call), old_metadata)

    assert controller.operation_manager.active_count == 1
    assert controller.operation_manager.get(retry_id) is not None
    assert controller._install_owned_operations == {retry_id: retry_owner}
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}
    assert controller.signals.operation_completed.emit.call_count == terminal_count

    controller._route_operation_response("install_apk", _result(retry_call), retry_metadata)

    assert controller.operation_manager.active_count == 0
    assert controller.install_batch_use_case._active_units == {}
    assert controller.install_batch_use_case._active_owner_tokens == {}
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}
    assert controller.signals.operation_completed.emit.call_count == terminal_count + 1


def test_old_protocol_snapshot_cannot_fail_reused_generation():
    controller = _controller()
    controller._generate_operation_id = Mock(return_value="shared-operation")
    unit_ids = iter(("old-unit", "new-unit"))
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=lambda: next(unit_ids),
    )
    old_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-old", "old.apk", "old.apk"),),
    )
    old_snapshot = controller.operation_manager.get(old_id)
    old_call = _submitted(controller, old_id)[0]
    controller._route_operation_response("install_apk", _result(old_call), _metadata(old_call))

    new_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-new", "new.apk", "new.apk"),),
    )
    new_owner = controller._install_owned_operations[new_id]
    terminal_count = controller.signals.operation_completed.emit.call_count

    outcome = controller._fail_operation_protocol(old_snapshot, "old protocol failure")

    assert outcome is None
    assert controller.operation_manager.active_count == 1
    assert controller.operation_manager.get(new_id) is not None
    assert controller._install_owned_operations == {new_id: new_owner}
    assert controller.signals.operation_completed.emit.call_count == terminal_count


@pytest.mark.parametrize(
    ("route_failure", "log_marker"),
    (
        ("metadata_mismatch", "Operation metadata mismatch"),
        ("missing_handler", "No vNext operation handler registered"),
        ("handler_exception", "Operation handler error"),
    ),
)
def test_route_error_log_failure_still_closes_claimed_install_operation(
    route_failure,
    log_marker,
):
    controller = _controller()
    operation_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
    )
    submitted = _submitted(controller, operation_id)[0]
    metadata = _metadata(submitted)
    if route_failure == "metadata_mismatch":
        metadata = _metadata(submitted, method_name="wrong_method")
    elif route_failure == "missing_handler":
        controller._operation_handler_map.pop("install_apk")
    else:
        controller._operation_handler_map["install_apk"] = Mock(
            side_effect=RuntimeError("handler failed")
        )

    def fail_target_log(_level, message, **_kwargs):
        if log_marker in message:
            raise RuntimeError(f"route log unavailable: {route_failure}")

    controller.log_service.log.side_effect = fail_target_log

    with pytest.raises(RuntimeError, match=f"route log unavailable: {route_failure}"):
        controller._route_operation_response("install_apk", _result(submitted), metadata)

    _assert_install_state_cleared(controller)
    controller.signals.operation_completed.emit.assert_called_once()


def test_route_log_error_remains_primary_when_terminal_release_log_also_fails():
    controller = _controller()
    operation_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
    )
    submitted = _submitted(controller, operation_id)[0]
    metadata = _metadata(submitted, method_name="wrong_method")

    def fail_route_and_terminal_logs(_level, message, **_kwargs):
        if "Operation metadata mismatch" in message:
            raise RuntimeError("route log unavailable")
        if "operation finished" in message:
            raise RuntimeError("terminal debug log unavailable")

    controller.log_service.log.side_effect = fail_route_and_terminal_logs

    with pytest.raises(RuntimeError, match="route log unavailable") as raised:
        controller._route_operation_response("install_apk", _result(submitted), metadata)

    assert any("terminal debug log unavailable" in note for note in raised.value.__notes__)
    controller.signals.operation_completed.emit.assert_called_once()
    _assert_install_state_cleared(controller)


def test_generic_operation_with_opaque_owner_token_routes_through_full_controller_mro():
    controller = _full_controller()
    operation = controller.operation_manager.begin(
        "generic",
        operation_id="generic-operation",
    )
    controller.operation_manager.mark_running(operation.operation_id)
    handler = Mock(
        side_effect=lambda _result, metadata: controller.operation_manager.finish(
            metadata.operation_id,
            OperationState.SUCCEEDED,
        )
    )
    controller._operation_handler_map = {"generic_method": handler}
    metadata = OperationMetadata(
        1,
        operation.operation_id,
        "generic",
        "generic_method",
        "generic-task",
        owner_token=object(),
    )

    terminal = controller._route_operation_response(
        "generic_method",
        {"success": True},
        metadata,
    )

    assert terminal.state is OperationState.SUCCEEDED
    handler.assert_called_once_with({"success": True}, metadata)
    assert controller.operation_manager.active_count == 0


def test_released_install_owner_token_disguised_as_generic_is_stale_dropped():
    controller = _full_controller()
    controller._generate_operation_id = Mock(return_value="shared-operation")
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=lambda: "old-unit",
    )
    old_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-old", "old.apk", "old.apk"),),
    )
    old_call = _submitted(controller, old_id)[0]
    old_owner = controller._install_owned_operations[old_id]
    controller._route_operation_response("install_apk", _result(old_call), _metadata(old_call))

    generic = controller.operation_manager.begin(
        "generic",
        operation_id=old_id,
    )
    generic = controller.operation_manager.mark_running(generic.operation_id)
    handler = Mock()
    controller._operation_handler_map = {"generic_method": handler}
    stale_metadata = OperationMetadata(
        1,
        old_id,
        "generic",
        "generic_method",
        "generic-task",
        owner_token=old_owner,
    )

    assert (
        controller._route_operation_response(
            "generic_method",
            {"success": True},
            stale_metadata,
        )
        is None
    )

    handler.assert_not_called()
    assert controller.operation_manager.get(old_id) is generic


@pytest.mark.parametrize(
    ("route_op_type", "metadata_changes"),
    (
        (
            "generic_method",
            {
                "operation_kind": "screenshot",
                "method_name": "generic_method",
            },
        ),
        (
            "install_apk",
            {
                "owner_token": None,
                "operation_kind": "batch_install",
                "method_name": "install_apk",
            },
        ),
    ),
)
def test_released_install_envelope_cannot_attack_reused_generic_operation(
    route_op_type,
    metadata_changes,
):
    controller = _controller()
    controller._generate_operation_id = Mock(return_value="shared-operation")
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=lambda: "old-unit",
    )
    old_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-old", "old.apk", "old.apk"),),
    )
    old_call = _submitted(controller, old_id)[0]
    old_metadata = _metadata(old_call, **metadata_changes)
    controller._route_operation_response(
        "install_apk",
        _result(old_call),
        _metadata(old_call),
    )
    assert controller._install_owned_operations == {}

    generic = controller.operation_manager.begin(
        "screenshot",
        unit_ids=("generic-unit",),
        operation_id=old_id,
    )
    generic = controller.operation_manager.mark_running(generic.operation_id)
    controller._route_operation_response(route_op_type, _result(old_call), old_metadata)

    assert controller.operation_manager.get(old_id) is generic
    assert controller.operation_manager.active_count == 1
    assert controller.signals.operation_completed.emit.call_count == 1


def test_install_route_claim_prevents_id_reuse_until_handler_releases():
    controller = _controller()
    controller._generate_operation_id = Mock(return_value="shared-operation")
    unit_ids = iter(("old-unit", "new-unit"))
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=lambda: next(unit_ids),
    )
    old_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-old", "old.apk", "old.apk"),),
    )
    old_call = _submitted(controller, old_id)[0]
    old_metadata = _metadata(old_call)
    real_handler = controller._process_install_operation_result
    handler_entered = threading.Event()
    release_handler = threading.Event()
    errors = []

    def pause_handler(result, metadata, **kwargs):
        handler_entered.set()
        assert release_handler.wait(2)
        return real_handler(result, metadata, **kwargs)

    controller._operation_handler_map["install_apk"] = pause_handler

    def route_old_result():
        try:
            controller._route_operation_response(
                "install_apk",
                _result(old_call),
                old_metadata,
            )
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=route_old_result)
    thread.start()
    assert handler_entered.wait(2)

    assert controller.cancel_install_batch(old_id) is True
    with pytest.raises(OperationTransitionError, match="Duplicate operation id"):
        controller._start_install_batch(
            "batch_install",
            (InstallRequest("device-new", "new.apk", "new.apk"),),
        )

    release_handler.set()
    thread.join(2)
    assert not thread.is_alive()
    assert errors == []
    assert controller.operation_manager.active_count == 0
    assert controller._install_owned_operations == {}
    controller.signals.operation_completed.emit.assert_called_once()

    new_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-new", "new.apk", "new.apk"),),
    )
    assert new_id == "shared-operation"


@pytest.mark.parametrize("mutation", ["cancel", "fail"])
def test_old_generation_cancel_or_fail_cannot_mutate_reused_generation(mutation):
    controller = _controller()
    controller._generate_operation_id = Mock(return_value="shared-operation")
    unit_ids = iter(("old-unit", "new-unit"))
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=lambda: next(unit_ids),
    )
    old_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-old", "old.apk", "old.apk"),),
    )
    old_call = _submitted(controller, old_id)[0]
    old_owner = controller._install_owned_operations[old_id]
    old_metadata = _metadata_with_owner(old_call, old_owner)
    mutation_method = "cancel_owned" if mutation == "cancel" else mutation
    real_mutation = getattr(controller.install_batch_use_case, mutation_method)
    mutation_entered = threading.Event()
    release_mutation = threading.Event()
    results = []
    errors = []

    def pause_before_mutation(*args, **kwargs):
        mutation_entered.set()
        assert release_mutation.wait(2)
        return real_mutation(*args, **kwargs)

    setattr(
        controller.install_batch_use_case,
        mutation_method,
        Mock(side_effect=pause_before_mutation),
    )

    def run_old_mutation():
        try:
            if mutation == "cancel":
                results.append(controller.cancel_install_batch(old_id))
            else:
                results.append(
                    controller._fail_install_operation(
                        old_id,
                        "old failure",
                        ownership=old_owner,
                    )
                )
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_old_mutation)
    thread.start()
    assert mutation_entered.wait(2)

    controller._route_operation_response("install_apk", _result(old_call), old_metadata)
    assert controller.operation_manager.active_count == 0
    assert controller._install_owned_operations == {}

    new_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-new", "new.apk", "new.apk"),),
    )
    new_call = _submitted(controller, new_id)[-1]
    new_owner = controller._install_owned_operations[new_id]
    new_metadata = _metadata_with_owner(new_call, new_owner)

    release_mutation.set()
    thread.join(2)
    assert not thread.is_alive()

    assert errors == []
    assert results == ([False] if mutation == "cancel" else [None])
    assert controller.operation_manager.active_count == 1
    assert controller.operation_manager.get(new_id) is not None
    assert controller._install_owned_operations == {new_id: new_owner}
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}

    controller._route_operation_response("install_apk", _result(new_call), new_metadata)

    assert controller.operation_manager.active_count == 0
    assert controller.install_batch_use_case._active_units == {}
    assert controller.install_batch_use_case._active_owner_tokens == {}
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}
    assert controller.signals.operation_completed.emit.call_count == 2


@pytest.mark.parametrize(
    "log_failure",
    ("terminal_debug", "completion"),
)
def test_terminal_log_failure_still_attempts_signal_and_cleans_state(log_failure):
    controller = _controller()
    operation_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
    )
    submitted = _submitted(controller, operation_id)[0]

    def fail_target_log(_level, message, **kwargs):
        if log_failure == "terminal_debug" and "operation finished" in message:
            raise RuntimeError("terminal debug log unavailable")
        if log_failure == "completion" and kwargs.get("flush_immediately"):
            raise RuntimeError("completion log unavailable")

    controller.log_service.log.side_effect = fail_target_log

    with pytest.raises(RuntimeError, match=f"{log_failure.replace('_', ' ')} log unavailable"):
        _finish(controller, submitted)

    controller.signals.operation_completed.emit.assert_called_once()
    _assert_install_state_cleared(controller)


def test_terminal_signal_and_log_errors_preserve_signal_as_primary_and_note_log_error():
    controller = _controller()
    operation_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
    )
    submitted = _submitted(controller, operation_id)[0]
    controller.signals.operation_completed.emit.side_effect = RuntimeError("signal unavailable")

    def fail_completion_log(_level, _message, **kwargs):
        if kwargs.get("flush_immediately"):
            raise RuntimeError("completion log unavailable")

    controller.log_service.log.side_effect = fail_completion_log

    with pytest.raises(RuntimeError, match="signal unavailable") as raised:
        _finish(controller, submitted)

    assert any("completion log unavailable" in note for note in raised.value.__notes__)
    controller.signals.operation_completed.emit.assert_called_once()
    _assert_install_state_cleared(controller)


def test_terminal_emit_error_releases_ownership_and_allows_id_reuse():
    controller = _controller()
    controller._generate_operation_id = Mock(return_value="shared-operation")
    operation_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
    )
    call = _submitted(controller, operation_id)[0]
    controller.signals.operation_completed.emit.side_effect = RuntimeError("signal unavailable")

    with pytest.raises(RuntimeError, match="signal unavailable"):
        _finish(controller, call)

    assert controller.operation_manager.active_count == 0
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}

    controller.signals.operation_completed.emit.side_effect = None
    reused_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-b", "b.apk", "b.apk"),),
    )
    assert reused_id == "shared-operation"
    reused_call = _submitted(controller, reused_id)[-1]

    outcome = _finish(controller, reused_call)

    assert outcome.snapshot.state is OperationState.SUCCEEDED
    assert controller.signals.operation_completed.emit.call_count == 2
    _assert_install_state_cleared(controller)


def test_result_handler_error_keeps_active_ownership_for_protocol_failure():
    controller = _controller()
    operation_id = controller._start_install_batch(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
    )
    call = _submitted(controller, operation_id)[0]
    ownership = controller._install_owned_operations[operation_id]
    snapshot = controller.operation_manager.get(operation_id)
    controller.install_batch_use_case.active_unit = Mock(side_effect=RuntimeError("handler failed"))

    with pytest.raises(RuntimeError, match="handler failed"):
        controller._process_install_operation_result(_result(call), _metadata(call))

    assert controller.operation_manager.get(operation_id) is snapshot
    assert controller._install_owned_operations == {operation_id: ownership}
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}

    outcome = controller._fail_operation_protocol(snapshot, "result handler failed")
    assert outcome.snapshot.state is OperationState.FAILED
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}


def test_start_error_after_manager_begin_propagates_without_operation_or_barrier_leak():
    controller = _controller()
    manager = _RaiseAfterBeginManager()
    controller.operation_manager = manager
    controller.install_batch_use_case = InstallBatchUseCase(
        manager,
        id_factory=controller._generate_operation_id,
    )

    with (
        patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")),
        pytest.raises(RuntimeError, match="mark running failed"),
    ):
        controller.batch_install_apk(["device-a"])

    assert manager.active_count == 0
    assert controller.install_batch_use_case._active_units == {}
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}


def test_single_apk_entry_uses_same_operation_identity_for_every_device():
    controller = _controller()
    with patch(
        "controllers._app.QFileDialog.getOpenFileName",
        return_value=("a.apk", ""),
    ):
        operation_id = controller.install_apk(["device-a", "device-b"])

    tasks = _submitted(controller, operation_id)
    assert len(tasks) == 2
    assert {call.args[4] for call in tasks} == {"install"}
    assert {call.kwargs["_operation_kind"] for call in tasks} == {"install"}
    assert {call.kwargs["_operation_id"] for call in tasks} == {operation_id}
    assert controller.signals.operation_completed.emit.call_count == 0
    assert "install" not in controller._batch_starts


def test_install_batch_partial_maps_to_compat_failure_and_reports_counts():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a", "device-b"])
    first, second = _submitted(controller, operation_id)

    assert _finish(controller, first) is None
    outcome = _finish(controller, second, success=False)

    assert outcome.snapshot.state is OperationState.PARTIAL
    controller.signals.operation_completed.emit.assert_called_once()
    operation, success, message = controller.signals.operation_completed.emit.call_args.args
    assert operation == "batch_install"
    assert success is False
    assert "1/2 succeeded" in message
    assert "1 failed" in message


def test_install_batch_submission_failures_are_immediately_terminal_once():
    controller = _controller()
    controller.app_model.install_apk_async.side_effect = RuntimeError("pool stopped")

    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a", "device-b"])

    assert operation_id
    assert controller.operation_manager.active_count == 0
    controller.signals.operation_completed.emit.assert_called_once()
    operation, success, message = controller.signals.operation_completed.emit.call_args.args
    assert operation == "batch_install"
    assert success is False
    assert "0/2 succeeded" in message
    assert "2 failed" in message


def test_install_batch_cancel_ignores_late_result_and_emits_once():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a", "device-b"])
    first, second = _submitted(controller, operation_id)
    assert _finish(controller, first) is None

    assert controller.cancel_install_batch(operation_id) is True
    counts = controller.signals.operation_completed.emit.call_count
    assert controller.cancel_install_batch(operation_id) is False
    assert _finish(controller, second) is None

    assert counts == 1
    assert controller.signals.operation_completed.emit.call_count == counts
    operation, success, message = controller.signals.operation_completed.emit.call_args.args
    assert operation == "batch_install"
    assert success is False
    assert "1/2 succeeded" in message
    assert "1 cancelled" in message
    assert controller.operation_manager.active_count == 0


def test_cancel_from_submission_callback_returns_true_and_terminal_is_emitted_after_handoff():
    controller = _controller()
    cancellation_results = []

    def cancel_during_submit(*_args, **kwargs):
        cancellation_results.append(controller.cancel_install_batch(kwargs["_operation_id"]))

    controller.app_model.install_apk_async.side_effect = cancel_during_submit
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])

    assert cancellation_results == [True]
    assert operation_id
    assert controller.operation_manager.active_count == 0
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller.signals.operation_completed.emit.call_args.args[1] is False


def test_cancel_after_use_case_start_returns_defers_terminal_until_controller_handoff():
    controller = _controller()
    real_start = controller.install_batch_use_case.start
    cancellations = []

    def cancel_before_controller_handoff(*args, **kwargs):
        started = real_start(*args, **kwargs)
        cancellations.append(controller.cancel_install_batch(started.operation_id))
        return started

    controller.install_batch_use_case.start = Mock(side_effect=cancel_before_controller_handoff)
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])

    assert cancellations == [True]
    assert operation_id
    assert controller.operation_manager.active_count == 0
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}


def test_synchronous_install_result_emits_terminal_exactly_once_after_start_handoff():
    controller = _controller()

    def complete_during_submit(*args, **kwargs):
        call = Mock(args=args, kwargs=kwargs)
        controller._process_install_operation_result(
            _result(call),
            _metadata(call),
        )

    controller.app_model.install_apk_async.side_effect = complete_during_submit
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])

    assert operation_id
    assert controller.operation_manager.active_count == 0
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}


def test_synchronous_install_protocol_failure_emits_terminal_exactly_once_after_handoff():
    controller = _controller()

    def fail_protocol_during_submit(*_args, **kwargs):
        snapshot = controller.operation_manager.get(kwargs["_operation_id"])
        controller._fail_operation_protocol(snapshot, "Operation metadata mismatch")

    controller.app_model.install_apk_async.side_effect = fail_protocol_during_submit
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])

    assert operation_id
    assert controller.operation_manager.active_count == 0
    controller.signals.operation_completed.emit.assert_called_once()
    operation, success, message = controller.signals.operation_completed.emit.call_args.args
    assert operation == "batch_install"
    assert success is False
    assert "0/1 succeeded" in message
    assert controller._install_owned_operations == {}
    assert controller._install_starting_operations == set()
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}


def test_retry_failed_install_batch_submits_only_failed_unit_with_parent_identity():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        parent_id = controller.batch_install_apk(["device-a", "device-b"])
    first, second = _submitted(controller, parent_id)
    _finish(controller, first)
    outcome = _finish(controller, second, success=False)
    submitted_before_retry = len(_submitted(controller))

    child_id = controller.retry_failed_install_batch(outcome)

    assert child_id != parent_id
    child_calls = _submitted(controller)[submitted_before_retry:]
    assert len(child_calls) == 1
    assert child_calls[0].args[:3] == ("device-b", "a.apk", "a.apk")
    child = controller.operation_manager.get(child_id)
    assert child.parent_operation_id == parent_id
    assert child.kind == "batch_install"


@pytest.mark.parametrize(
    ("metadata_changes", "payload_changes"),
    [
        ({"task_id": "wrong-task"}, {}),
        ({"unit_id": "wrong-unit"}, {}),
        ({"target_id": "wrong-target"}, {}),
        ({}, {"device_ip": "wrong-target"}),
        ({}, {"apk_path": "wrong.apk"}),
        ({}, {"apk_name": "wrong.apk"}),
    ],
)
def test_install_protocol_identity_mismatch_fails_closed(metadata_changes, payload_changes):
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])
    call = _submitted(controller, operation_id)[0]

    outcome = controller._process_install_operation_result(
        _result(call, **payload_changes),
        _metadata(call, **metadata_changes),
    )

    assert outcome.snapshot.state is OperationState.FAILED
    assert controller.operation_manager.active_count == 0
    controller.signals.operation_completed.emit.assert_called_once()
    operation, success, message = controller.signals.operation_completed.emit.call_args.args
    assert operation == "batch_install"
    assert success is False
    assert "0/1 succeeded" in message
    assert "1 failed" in message


@pytest.mark.parametrize(
    "metadata_changes",
    ({}, {"operation_kind": "wrong_kind", "method_name": "wrong_method"}),
)
def test_install_metadata_missing_owner_token_is_dropped_before_protocol_fail(metadata_changes):
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])
    call = _submitted(controller, operation_id)[0]
    ownership = controller._install_owned_operations[operation_id]
    metadata = _metadata(call, owner_token=None, **metadata_changes)

    outcome = controller._route_operation_response("install_apk", _result(call), metadata)

    assert outcome is None
    assert controller.operation_manager.active_count == 1
    assert controller.operation_manager.get(operation_id) is not None
    assert controller._install_owned_operations == {operation_id: ownership}
    assert controller._install_result_callbacks == {}
    assert controller._install_deferred_terminals == {}
    controller.signals.operation_completed.emit.assert_not_called()

    controller._route_operation_response("install_apk", _result(call), _metadata(call))
    assert controller.operation_manager.active_count == 0
    assert controller._install_owned_operations == {}
    controller.signals.operation_completed.emit.assert_called_once()


def test_install_invalid_payload_fails_closed_and_counts_entire_operation():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a", "device-b"])
    call = _submitted(controller, operation_id)[0]

    outcome = controller._process_install_operation_result("invalid", _metadata(call))

    assert outcome.snapshot.state is OperationState.FAILED
    operation, success, message = controller.signals.operation_completed.emit.call_args.args
    assert operation == "batch_install"
    assert success is False
    assert "0/2 succeeded" in message
    assert "2 failed" in message


def test_install_duplicate_and_terminal_late_callbacks_have_no_side_effects():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a", "device-b"])
    first, second = _submitted(controller, operation_id)

    assert _finish(controller, first) is None
    assert (
        controller._process_install_operation_result(
            _result(first, apk_name="conflicting-late-name.apk"),
            _metadata(first),
        )
        is None
    )
    assert controller.signals.operation_completed.emit.call_count == 0
    outcome = _finish(controller, second)
    counts = controller.signals.operation_completed.emit.call_count
    assert _finish(controller, first) is None

    assert outcome.snapshot.state is OperationState.SUCCEEDED
    assert counts == 1
    assert controller.signals.operation_completed.emit.call_count == counts
    assert controller.operation_manager.active_count == 0


def test_install_operation_protocol_failure_uses_application_terminal_facade():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])
    snapshot = controller.operation_manager.get(operation_id)

    outcome = controller._fail_operation_protocol(snapshot, "Operation metadata mismatch")

    assert outcome.snapshot.state is OperationState.FAILED
    controller.signals.operation_completed.emit.assert_called_once()
    assert "0/1 succeeded" in controller.signals.operation_completed.emit.call_args.args[2]


def test_externally_terminalized_install_is_reconciled_without_fabricated_signal():
    controller = _controller()
    controller._generate_operation_id = Mock(side_effect=("shared-id", "shared-id"))
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=lambda: "unit-id",
    )
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])
    old_call = _submitted(controller, operation_id)[0]
    old_snapshot = controller.operation_manager.get(operation_id)

    controller.operation_manager.finish(
        operation_id,
        OperationState.FAILED,
        expected_kind=old_snapshot.kind,
        expected_generation=old_snapshot.generation_token,
        message="external owner",
    )
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["b.apk"], "")):
        reused = controller.batch_install_apk(["device-b"])
    assert reused == "shared-id"
    assert (
        controller._route_operation_response(
            "install_apk",
            _result(old_call),
            _metadata(old_call),
        )
        is None
    )
    controller.signals.operation_completed.emit.assert_not_called()
    new_call = _submitted(controller, reused)[-1]
    outcome = controller._route_operation_response(
        "install_apk",
        _result(new_call),
        _metadata(new_call),
    )
    assert outcome.snapshot.state is OperationState.SUCCEEDED
    controller.signals.operation_completed.emit.assert_called_once()


def test_next_unique_install_start_sweeps_all_externally_terminalized_owners():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        old_id = controller.batch_install_apk(["device-a"])
    old_snapshot = controller.operation_manager.get(old_id)
    controller.operation_manager.finish(
        old_id,
        OperationState.FAILED,
        expected_kind=old_snapshot.kind,
        expected_generation=old_snapshot.generation_token,
    )

    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["b.apk"], "")):
        new_id = controller.batch_install_apk(["device-b"])

    assert new_id != old_id
    assert set(controller._install_owned_operations) == {new_id}
    assert set(controller.install_batch_use_case._active_units) == {new_id}
    assert set(controller.install_batch_use_case._active_owner_tokens) == {new_id}
    controller.signals.operation_completed.emit.assert_not_called()


def test_starting_install_orphan_is_released_after_claim_and_start_barriers_close():
    controller = _controller()
    manager, thread, results, errors = _pause_before_first_submit(
        controller,
        lambda: controller._start_install_batch(
            "batch_install",
            (InstallRequest("device-a", "a.apk", "a.apk"),),
        ),
    )
    ownership = next(iter(controller._install_owned_operations.values()))
    snapshot, metadata, result = _active_metadata_and_result(manager, ownership)
    manager.finish(
        snapshot.operation_id,
        OperationState.FAILED,
        expected_kind=snapshot.kind,
        expected_generation=snapshot.generation_token,
    )

    assert controller._route_operation_response("install_apk", result, metadata) is None
    assert controller._install_orphaned_operations == {snapshot.operation_id: ownership}
    _release_paused_start(manager, thread)

    assert errors == []
    assert results == [snapshot.operation_id]
    _assert_install_state_cleared(controller)
    controller.app_model.install_apk_async.assert_not_called()
    controller.signals.operation_completed.emit.assert_not_called()


def test_last_of_two_stale_claims_releases_shared_orphan_ownership():
    controller = _controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])
    call = _submitted(controller, operation_id)[0]
    metadata = _metadata(call)
    accepted_one, ownership = controller._claim_operation_response("install_apk", metadata)
    accepted_two, same_ownership = controller._claim_operation_response(
        "install_apk",
        metadata,
    )
    assert accepted_one is accepted_two is True
    assert ownership is same_ownership
    snapshot = controller.operation_manager.get(operation_id)
    controller.operation_manager.finish(
        operation_id,
        OperationState.FAILED,
        expected_kind=snapshot.kind,
        expected_generation=snapshot.generation_token,
    )

    controller._release_operation_response(
        "install_apk",
        metadata,
        ownership,
        None,
    )
    controller._release_operation_response(
        "install_apk",
        metadata,
        ownership,
        None,
    )

    _assert_install_state_cleared(controller)
    controller.signals.operation_completed.emit.assert_not_called()


def test_cancel_screenshot_cannot_cancel_shared_manager_install_operation():
    controller = _full_controller()
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])
    before = controller.operation_manager.get(operation_id)

    assert controller.cancel_screenshot(operation_id) is False

    assert controller.operation_manager.get(operation_id) == before
    assert controller.operation_manager.get(operation_id).cancel_requested is False
    controller.signals.screenshot_captured.emit.assert_not_called()
    controller.signals.operation_completed.emit.assert_not_called()


def test_old_screenshot_protocol_failure_cannot_finish_reused_install_generation():
    controller = _full_controller()
    old_generation = object()
    old = controller.operation_manager.begin(
        "screenshot",
        operation_id="shared-id",
        unit_ids=("old-task",),
        generation_token=old_generation,
    )
    controller.operation_manager.finish(
        old.operation_id,
        OperationState.FAILED,
        expected_kind="screenshot",
        expected_generation=old_generation,
    )
    controller._generate_operation_id = Mock(side_effect=("shared-id",))
    controller.install_batch_use_case = InstallBatchUseCase(
        controller.operation_manager,
        id_factory=lambda: "new-unit",
    )
    with patch("controllers._app.QFileDialog.getOpenFileNames", return_value=(["a.apk"], "")):
        operation_id = controller.batch_install_apk(["device-a"])
    current = controller.operation_manager.get(operation_id)

    assert controller._fail_operation_protocol(old, "late protocol failure") is None
    assert controller.operation_manager.get(operation_id) == current
    assert current.kind == "batch_install"
    controller.signals.operation_completed.emit.assert_not_called()
