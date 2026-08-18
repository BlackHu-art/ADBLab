import os
import threading
from dataclasses import replace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from adblab.application.cancellation import CancellationError, CancellationToken
from adblab.application.envelope import (
    OperationEnvelope,
    OperationMetadata,
    attach_operation_metadata,
    split_operation_metadata,
)
from adblab.application.operations import (
    ConflictingOperationResultError,
    IncompleteOperationError,
    OperationArtifact,
    OperationManager,
    OperationState,
    OperationTransitionError,
    OperationUnitResult,
)
from controllers._base import _ADBControllerBase
from core.perf_trace import split_perf
from models.adb_model import ADBModelCore, async_command


def _manager(ids=("operation-1", "operation-2")):
    values = iter(ids)
    ticks = iter(range(1, 100))
    return OperationManager(
        id_factory=lambda: next(values),
        clock=lambda: float(next(ticks)),
    )


def test_operation_state_machine_cleans_terminal_entry_and_ignores_duplicate_finish():
    manager = _manager()
    queued = manager.begin("single")
    running = manager.mark_running(queued.operation_id)

    assert running.state is OperationState.RUNNING
    terminal = manager.finish(queued.operation_id, OperationState.SUCCEEDED)

    assert terminal.state is OperationState.SUCCEEDED
    assert terminal.progress == 100
    assert terminal.finished_at is not None
    assert manager.get(queued.operation_id) is None
    assert manager.finish(queued.operation_id, OperationState.FAILED) is None
    assert manager.active_count == 0


def test_operation_rejects_invalid_transition_and_backwards_progress():
    manager = _manager()
    operation = manager.begin("single")

    with pytest.raises(OperationTransitionError):
        manager.mark_finalizing(operation.operation_id)

    manager.mark_running(operation.operation_id)
    manager.update_progress(operation.operation_id, 50)
    with pytest.raises(OperationTransitionError):
        manager.update_progress(operation.operation_id, 49)


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ([OperationState.SUCCEEDED, OperationState.SUCCEEDED], OperationState.SUCCEEDED),
        ([OperationState.CANCELLED, OperationState.CANCELLED], OperationState.CANCELLED),
        ([OperationState.FAILED, OperationState.FAILED], OperationState.FAILED),
        ([OperationState.FAILED, OperationState.CANCELLED], OperationState.FAILED),
        ([OperationState.SUCCEEDED, OperationState.FAILED], OperationState.PARTIAL),
        ([OperationState.SUCCEEDED, OperationState.CANCELLED], OperationState.PARTIAL),
    ],
)
def test_fanout_aggregation_has_explicit_partial_failure_semantics(states, expected):
    manager = _manager()
    operation = manager.begin("screenshot", unit_ids=("task-a", "task-b"))
    manager.mark_running(operation.operation_id)
    for unit_id, state in zip(operation.unit_ids, states):
        manager.record_unit_result(
            operation.operation_id,
            OperationUnitResult(unit_id, state),
        )

    terminal = manager.finish_from_unit_results(operation.operation_id)

    assert terminal.state is expected
    assert manager.active_count == 0


def test_fanout_rejects_missing_unknown_and_conflicting_unit_results():
    manager = _manager()
    operation = manager.begin("screenshot", unit_ids=("task-a", "task-b"))
    manager.mark_running(operation.operation_id)
    first = OperationUnitResult("task-a", OperationState.SUCCEEDED)
    manager.record_unit_result(operation.operation_id, first)

    assert manager.record_unit_result(operation.operation_id, first).unit_results == (first,)
    with pytest.raises(ValueError):
        manager.record_unit_result(
            operation.operation_id,
            OperationUnitResult("unknown", OperationState.FAILED),
        )
    with pytest.raises(ConflictingOperationResultError):
        manager.record_unit_result(
            operation.operation_id,
            OperationUnitResult("task-a", OperationState.FAILED),
        )
    with pytest.raises(IncompleteOperationError):
        manager.finish_from_unit_results(operation.operation_id)
    with pytest.raises(OperationTransitionError):
        manager.finish(operation.operation_id, OperationState.SUCCEEDED)


def test_cancel_pending_units_uses_current_results_and_finishes_atomically():
    manager = OperationManager()
    generation = object()
    operation = manager.begin(
        "screenshot",
        unit_ids=("unit-a", "unit-b"),
        generation_token=generation,
    )
    manager.mark_running(
        operation.operation_id,
        expected_kind="screenshot",
        expected_generation=generation,
    )
    succeeded = OperationUnitResult("unit-a", OperationState.SUCCEEDED, "captured")
    manager.record_unit_result(
        operation.operation_id,
        succeeded,
        expected_kind="screenshot",
        expected_generation=generation,
    )

    terminal = manager.cancel_pending_units(
        operation.operation_id,
        unit_message="Screenshot cancelled",
        expected_kind="screenshot",
        expected_generation=generation,
    )

    assert terminal is not None
    assert terminal.state is OperationState.PARTIAL
    assert terminal.cancel_requested is True
    assert terminal.unit_results == (
        succeeded,
        OperationUnitResult("unit-b", OperationState.CANCELLED, "Screenshot cancelled"),
    )
    assert manager.active_count == 0
    assert (
        manager.cancel_pending_units(
            operation.operation_id,
            unit_message="Screenshot cancelled",
            expected_kind="screenshot",
            expected_generation=generation,
        )
        is None
    )


def test_cancel_pending_units_finishes_after_cancel_intent_was_already_recorded():
    manager = OperationManager()
    operation = manager.begin("screenshot", unit_ids=("unit-a",))
    manager.mark_running(operation.operation_id)
    assert manager.request_cancel(operation.operation_id) is True

    terminal = manager.cancel_pending_units(
        operation.operation_id,
        unit_message="Screenshot cancelled",
    )

    assert terminal is not None
    assert terminal.state is OperationState.CANCELLED
    assert terminal.cancel_requested is True
    assert terminal.unit_results == (
        OperationUnitResult("unit-a", OperationState.CANCELLED, "Screenshot cancelled"),
    )
    assert manager.active_count == 0


def test_cancel_pending_units_preserves_all_completed_success_results():
    manager = OperationManager()
    operation = manager.begin("screenshot", unit_ids=("unit-a",))
    manager.mark_running(operation.operation_id)
    succeeded = OperationUnitResult("unit-a", OperationState.SUCCEEDED, "captured")
    manager.record_unit_result(operation.operation_id, succeeded)

    terminal = manager.cancel_pending_units(operation.operation_id)

    assert terminal is not None
    assert terminal.state is OperationState.SUCCEEDED
    assert terminal.cancel_requested is True
    assert terminal.unit_results == (succeeded,)
    assert manager.active_count == 0


def test_operation_artifacts_are_idempotent_and_bound_to_expected_units():
    manager = _manager()
    operation = manager.begin("screenshot", unit_ids=("task-a",))
    artifact = OperationArtifact("D:/results/current.png", "screenshot", "task-a")

    first = manager.add_artifact(operation.operation_id, artifact)
    second = manager.add_artifact(operation.operation_id, artifact)

    assert first.artifacts == (artifact,)
    assert second.artifacts == (artifact,)
    with pytest.raises(ValueError):
        manager.add_artifact(
            operation.operation_id,
            OperationArtifact("D:/results/other.png", "screenshot", "unknown"),
        )


def test_cancellation_is_idempotent_intent_and_does_not_choose_terminal_state():
    manager = _manager()
    operation = manager.begin("single")
    token = manager.token(operation.operation_id)

    assert manager.request_cancel(operation.operation_id) is True
    assert manager.request_cancel(operation.operation_id) is False
    assert token.is_cancelled is True
    assert manager.get(operation.operation_id).state is OperationState.QUEUED
    assert manager.get(operation.operation_id).cancel_requested is True
    terminal = manager.finish(operation.operation_id, OperationState.CANCELLED)
    assert terminal.state is OperationState.CANCELLED
    assert manager.request_cancel(operation.operation_id) is False


def test_cancellation_token_only_accepts_one_concurrent_request():
    token = CancellationToken()
    barrier = threading.Barrier(8)
    results = []

    def request():
        barrier.wait()
        results.append(token.request())

    threads = [threading.Thread(target=request) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1
    assert results.count(False) == 7
    with pytest.raises(CancellationError):
        token.raise_if_cancelled()


def test_concurrent_terminal_writes_have_exactly_one_winner():
    manager = _manager()
    operation = manager.begin("single")
    manager.mark_running(operation.operation_id)
    barrier = threading.Barrier(20)
    results = []

    def finish(state):
        barrier.wait()
        results.append(manager.finish(operation.operation_id, state))

    threads = [
        threading.Thread(
            target=finish,
            args=(OperationState.SUCCEEDED if index % 2 else OperationState.FAILED,),
        )
        for index in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(result is not None for result in results) == 1
    assert manager.active_count == 0


def test_operation_generation_is_opaque_and_compare_safe_across_reused_ids():
    manager = OperationManager(id_factory=lambda: "unused")
    first_generation = object()
    first = manager.begin(
        "install",
        operation_id="shared-id",
        unit_ids=("old-unit",),
        generation_token=first_generation,
    )

    assert first.generation_token is first_generation
    assert "generation_token" not in repr(first)
    assert replace(first, generation_token=object()) == first
    assert manager.get("shared-id", expected_kind="screenshot") is None
    assert manager.get("shared-id", expected_generation=object()) is None
    assert (
        manager.mark_running(
            "shared-id",
            expected_kind="install",
            expected_generation=first_generation,
        )
        is not None
    )
    terminal = manager.finish(
        "shared-id",
        OperationState.FAILED,
        expected_kind="install",
        expected_generation=first_generation,
    )
    assert terminal is not None

    second_generation = object()
    second = manager.begin(
        "screenshot",
        operation_id="shared-id",
        unit_ids=("new-unit",),
        generation_token=second_generation,
    )
    current = manager.mark_running(
        "shared-id",
        expected_kind="screenshot",
        expected_generation=second_generation,
    )

    assert (
        manager.request_cancel(
            "shared-id",
            expected_kind="install",
            expected_generation=first_generation,
        )
        is False
    )
    assert (
        manager.record_unit_result(
            "shared-id",
            OperationUnitResult("new-unit", OperationState.FAILED),
            expected_kind="install",
            expected_generation=first_generation,
        )
        is None
    )
    assert (
        manager.finish(
            "shared-id",
            OperationState.FAILED,
            expected_kind="install",
            expected_generation=first_generation,
        )
        is None
    )
    assert current is not None
    assert current.generation_token is second.generation_token
    assert manager.get("shared-id") == current
    assert manager.get("shared-id").cancel_requested is False
    assert manager.get("shared-id").unit_results == ()


@pytest.mark.parametrize(
    "mutation",
    (
        lambda manager, operation_id: manager.mark_finalizing(
            operation_id,
            expected_generation=object(),
        ),
        lambda manager, operation_id: manager.update_progress(
            operation_id,
            50,
            expected_generation=object(),
        ),
        lambda manager, operation_id: manager.add_artifact(
            operation_id,
            OperationArtifact("shot.png", "screenshot", "task-a"),
            expected_generation=object(),
        ),
        lambda manager, operation_id: manager.finish_from_unit_results(
            operation_id,
            expected_generation=object(),
        ),
        lambda manager, operation_id: manager.cancel_pending_units(
            operation_id,
            expected_generation=object(),
        ),
    ),
)
def test_every_operation_mutation_rejects_wrong_generation_before_validation(mutation):
    manager = OperationManager(id_factory=lambda: "unused")
    generation = object()
    operation = manager.begin(
        "screenshot",
        operation_id="shared-id",
        unit_ids=("task-a",),
        generation_token=generation,
    )

    assert mutation(manager, operation.operation_id) is None
    assert manager.get(operation.operation_id) == operation


def test_unguarded_mutations_keep_legacy_input_validation_for_missing_operation():
    manager = OperationManager(id_factory=lambda: "unused")

    with pytest.raises(ValueError, match="progress must be between 0 and 100"):
        manager.update_progress("missing", 101)
    with pytest.raises(ValueError, match="finish state must be terminal"):
        manager.finish("missing", OperationState.RUNNING)


def test_guarded_mutations_reject_stale_generation_before_input_validation():
    manager = OperationManager(id_factory=lambda: "unused")
    operation = manager.begin("sample", operation_id="operation-1")

    assert (
        manager.update_progress(
            operation.operation_id,
            101,
            expected_generation=object(),
        )
        is None
    )
    assert (
        manager.finish(
            operation.operation_id,
            OperationState.RUNNING,
            expected_generation=object(),
        )
        is None
    )
    assert manager.get(operation.operation_id) == operation


@pytest.mark.parametrize("payload", [{"_operation": "business"}, ["a"], "text", None])
def test_operation_envelope_round_trips_arbitrary_legacy_payload(payload):
    metadata = OperationMetadata(1, "operation-1", "sample", "sample", "task-1")

    wrapped = attach_operation_metadata(payload, metadata)
    result, extracted = split_operation_metadata(wrapped)

    assert isinstance(wrapped, OperationEnvelope)
    assert result == payload
    assert extracted == metadata


class _ImmediatePool:
    def start(self, task):
        task.run()


class _FailingPool:
    def start(self, _task):
        raise RuntimeError("queue unavailable")


class _EnvelopeModel(ADBModelCore):
    @async_command
    def sample_async(self, value):
        if value == "raise":
            raise RuntimeError("business failure")
        return value


def test_async_command_keeps_signal_signature_and_strips_reserved_operation_kwargs():
    _app = QApplication.instance() or QApplication([])
    model = _EnvelopeModel()
    model.thread_pool = _ImmediatePool()
    received = []
    model.command_finished.connect(lambda method, result: received.append((method, result)))

    model.sample_async(
        {"success": True},
        _operation_id="operation-1",
        _operation_kind="sample",
    )

    method_name, wrapped = received[0]
    payload_with_perf, metadata = split_operation_metadata(wrapped)
    payload, perf = split_perf(payload_with_perf)
    assert method_name == "sample_async"
    assert payload == {"success": True}
    assert metadata.operation_id == "operation-1"
    assert metadata.operation_kind == "sample"
    assert metadata.method_name == "sample"
    assert perf["method"] == "sample_async"


def test_async_command_carries_manager_generation_without_forwarding_it_to_model_method():
    _app = QApplication.instance() or QApplication([])
    model = _EnvelopeModel()
    model.thread_pool = _ImmediatePool()
    received = []
    model.command_finished.connect(lambda _method, result: received.append(result))
    generation = object()

    model.sample_async(
        {"success": True},
        _operation_id="operation-1",
        _operation_kind="sample",
        _operation_generation_token=generation,
    )

    _payload, metadata = split_operation_metadata(received[0])
    assert metadata.generation_token is generation


def test_async_command_carries_owner_token_without_forwarding_it_to_model_method():
    _app = QApplication.instance() or QApplication([])
    model = _EnvelopeModel()
    model.thread_pool = _ImmediatePool()
    received = []
    model.command_finished.connect(lambda _method, result: received.append(result))
    owner_token = object()

    model.sample_async(
        {"success": True},
        _operation_id="operation-1",
        _operation_kind="sample",
        _operation_owner_token=owner_token,
    )

    payload_with_perf, metadata = split_operation_metadata(received[0])
    payload, _perf = split_perf(payload_with_perf)
    assert payload == {"success": True}
    assert getattr(metadata, "owner_token", None) is owner_token


def test_async_command_reports_business_runtime_error_with_same_operation_metadata():
    _app = QApplication.instance() or QApplication([])
    model = _EnvelopeModel()
    model.thread_pool = _ImmediatePool()
    received = []
    model.command_finished.connect(lambda _method, result: received.append(result))

    model.sample_async(
        "raise",
        _operation_id="operation-1",
        _operation_kind="sample",
    )

    payload_with_perf, metadata = split_operation_metadata(received[0])
    payload, _perf = split_perf(payload_with_perf)
    assert payload["success"] is False
    assert "business failure" in payload["error"]
    assert metadata.operation_id == "operation-1"


def test_async_command_submission_failure_is_synchronous_for_owner_cleanup():
    model = _EnvelopeModel()
    model.thread_pool = _FailingPool()

    with pytest.raises(RuntimeError, match="queue unavailable"):
        model.sample_async(
            "value",
            _operation_id="operation-1",
            _operation_kind="sample",
        )


def _controller_for_operations():
    controller = _ADBControllerBase.__new__(_ADBControllerBase)
    controller.log_service = Mock()
    controller.operation_manager = OperationManager(id_factory=lambda: "operation-1")
    controller._operation_handler_map = {}
    controller._handler_map = {"sample": Mock()}
    controller._settings = Mock()
    controller._settings.get.return_value = 10_000
    return controller


def test_controller_routes_metadata_only_to_registered_vnext_handler():
    controller = _controller_for_operations()
    operation = controller.operation_manager.begin("sample")
    controller.operation_manager.mark_running(operation.operation_id)
    handler = Mock()
    controller._register_operation_handler("sample", handler)
    metadata = OperationMetadata(1, operation.operation_id, "sample", "sample", "task-1")

    _ADBControllerBase._handle_async_response(
        controller,
        "sample_async",
        attach_operation_metadata({"success": True}, metadata),
    )

    handler.assert_called_once_with({"success": True}, metadata)
    controller._handler_map["sample"].assert_not_called()


def test_controller_drops_stale_metadata_instead_of_falling_back_to_legacy_handler():
    controller = _controller_for_operations()
    metadata = OperationMetadata(1, "stale", "sample", "sample", "task-1")

    _ADBControllerBase._handle_async_response(
        controller,
        "sample_async",
        attach_operation_metadata({"success": True}, metadata),
    )

    controller._handler_map["sample"].assert_not_called()
    assert "stale" in controller.log_service.log.call_args.args[1].lower()


def test_controller_handler_exception_fails_and_cleans_operation_once():
    controller = _controller_for_operations()
    operation = controller.operation_manager.begin("sample")
    controller.operation_manager.mark_running(operation.operation_id)
    controller._register_operation_handler("sample", Mock(side_effect=RuntimeError("boom")))
    metadata = OperationMetadata(1, operation.operation_id, "sample", "sample", "task-1")

    controller._route_operation_response("sample", {"success": True}, metadata)

    assert controller.operation_manager.get(operation.operation_id) is None
    assert any(
        "Operation handler error" in call.args[1]
        for call in controller.log_service.log.call_args_list
    )
