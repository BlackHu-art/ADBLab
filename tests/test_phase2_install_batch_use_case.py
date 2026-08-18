import inspect
import sys
import threading

import pytest

from adblab.application.install_batch import InstallBatchUseCase, InstallRequest
from adblab.application.operations import (
    OperationManager,
    OperationState,
    OperationTransitionError,
    OperationUnitResult,
)


class _RaiseAfterBeginManager(OperationManager):
    def mark_running(self, operation_id, **kwargs):
        super().mark_running(operation_id, **kwargs)
        raise RuntimeError("mark running failed")


class _RaiseDuringStartAndCleanupManager(_RaiseAfterBeginManager):
    def finish(self, operation_id, state, *, message="", **kwargs):
        super().finish(operation_id, state, message=message, **kwargs)
        raise RuntimeError("cleanup finish failed")


class _ObserveBeginManager(OperationManager):
    def __init__(self):
        super().__init__(id_factory=lambda: "unused")
        self.after_begin = None

    def begin(self, *args, **kwargs):
        snapshot = super().begin(*args, **kwargs)
        if self.after_begin is not None:
            self.after_begin(snapshot)
        return snapshot


class _RaiseAfterInsertManager(OperationManager):
    def begin(self, *args, **kwargs):
        super().begin(*args, **kwargs)
        raise RuntimeError("begin failed after insert")


class _FinishInsteadOfCancelManager(OperationManager):
    def request_cancel(self, operation_id, **kwargs):
        self.finish(
            operation_id,
            OperationState.FAILED,
            message="external terminal",
            expected_kind=kwargs.get("expected_kind"),
            expected_generation=kwargs.get("expected_generation"),
        )
        return False


def test_start_reserves_use_case_identity_before_manager_begin_is_observable():
    ids = iter(("op-a", "a-1"))
    manager = _ObserveBeginManager()
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    cancelled = []
    submitted = []
    manager.after_begin = lambda snapshot: cancelled.append(use_case.cancel(snapshot.operation_id))

    started = use_case.start(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
        lambda _operation_id, unit: submitted.append(unit.unit_id),
    )

    assert cancelled[0] is not None
    assert cancelled[0].snapshot.state is OperationState.CANCELLED
    assert started.terminal == cancelled[0]
    assert submitted == []
    assert manager.active_count == 0
    assert use_case._active_units == {}
    assert use_case._active_owner_tokens == {}


def test_protocol_failure_during_begin_is_returned_as_start_terminal():
    ids = iter(("op-a", "a-1"))
    manager = _ObserveBeginManager()
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    failures = []
    manager.after_begin = lambda snapshot: failures.append(
        use_case.fail_snapshot(snapshot, "protocol failure")
    )

    started = use_case.start(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
        lambda _operation_id, _unit: pytest.fail("terminal start must not submit"),
    )

    accepted, owner_token, outcome = failures[0]
    assert accepted is True
    assert owner_token is None
    assert outcome is not None
    assert outcome.snapshot.state is OperationState.FAILED
    assert started.terminal == outcome
    assert manager.active_count == 0


def test_begin_exception_after_manager_insert_cleans_manager_and_use_case_state():
    manager = _RaiseAfterInsertManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: "unit-1")

    with pytest.raises(RuntimeError, match="begin failed after insert"):
        use_case.start(
            "batch_install",
            (InstallRequest("device-a", "a.apk", "a.apk"),),
            lambda _operation_id, _unit: None,
            operation_id="operation-1",
        )

    assert manager.active_count == 0
    assert use_case._active_units == {}
    assert use_case._active_owner_tokens == {}
    assert use_case._active_kinds == {}
    assert use_case._active_generations == {}
    assert use_case._starting_operations == set()


def test_cancel_rejects_generation_that_disappears_during_cancel_cas():
    ids = iter(("op-a", "a-1"))
    manager = _FinishInsteadOfCancelManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    started = use_case.start(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
        lambda _operation_id, _unit: None,
    )

    accepted, terminal = use_case.cancel_owned(
        started.operation_id,
        owner_token=None,
    )

    assert accepted is False
    assert terminal is None
    assert manager.active_count == 0
    assert use_case._active_units == {}
    assert use_case._active_owner_tokens == {}
    assert use_case._active_kinds == {}
    assert use_case._active_generations == {}
    assert use_case._inactive_owner_tokens == {}


def test_two_install_batches_keep_distinct_operations_and_units():
    ids = iter(("op-a", "a-1", "a-2", "op-b", "b-1"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    submitted = []

    first = use_case.start(
        "batch_install",
        (
            InstallRequest("device-a", "a.apk", "a.apk"),
            InstallRequest("device-b", "a.apk", "a.apk"),
        ),
        lambda operation_id, unit: submitted.append((operation_id, unit)),
    )
    second = use_case.start(
        "batch_install",
        (InstallRequest("device-c", "b.apk", "b.apk"),),
        lambda operation_id, unit: submitted.append((operation_id, unit)),
    )

    assert first.operation_id == "op-a"
    assert second.operation_id == "op-b"
    assert {unit.unit_id for unit in first.units}.isdisjoint(
        {unit.unit_id for unit in second.units}
    )
    assert [operation_id for operation_id, _unit in submitted] == [
        "op-a",
        "op-a",
        "op-b",
    ]
    assert (
        use_case.complete(
            first.operation_id,
            first.units[1].unit_id,
            succeeded=False,
            message="offline",
        )
        is None
    )
    second_outcome = use_case.complete(
        second.operation_id,
        second.units[0].unit_id,
        succeeded=True,
        message="ok",
    )
    first_outcome = use_case.complete(
        first.operation_id,
        first.units[0].unit_id,
        succeeded=True,
        message="ok",
    )

    assert second_outcome is not None
    assert second_outcome.snapshot.operation_id == "op-b"
    assert second_outcome.snapshot.state is OperationState.SUCCEEDED
    assert first_outcome is not None
    assert first_outcome.snapshot.operation_id == "op-a"
    assert first_outcome.snapshot.state is OperationState.PARTIAL
    assert manager.active_count == 0


def test_start_accepts_explicit_operation_id_without_consuming_generated_operation_id():
    ids = iter(("unit-1", "generated-operation", "unit-2"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))

    explicit = use_case.start(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
        lambda _operation_id, _unit: None,
        operation_id="explicit-operation",
    )
    generated = use_case.start(
        "batch_install",
        (InstallRequest("device-b", "b.apk", "b.apk"),),
        lambda _operation_id, _unit: None,
    )

    assert explicit.operation_id == "explicit-operation"
    assert explicit.units[0].unit_id == "unit-1"
    assert generated.operation_id == "generated-operation"
    assert generated.units[0].unit_id == "unit-2"


@pytest.mark.parametrize("operation_id", ["", "  ", 123])
def test_explicit_operation_id_must_be_a_non_empty_string(operation_id):
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: "unit-1")

    with pytest.raises(ValueError, match="operation_id must be a non-empty string"):
        use_case.start(
            "batch_install",
            (InstallRequest("device-a", "a.apk", "a.apk"),),
            lambda _operation_id, _unit: None,
            operation_id=operation_id,
        )

    assert manager.active_count == 0


def test_explicit_duplicate_operation_id_is_rejected_without_replacing_active_operation():
    manager = OperationManager(id_factory=lambda: "unused")
    manager.begin("existing", operation_id="duplicate")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: "unit-1")

    with pytest.raises(OperationTransitionError, match="Duplicate operation id"):
        use_case.start(
            "batch_install",
            (InstallRequest("device-a", "a.apk", "a.apk"),),
            lambda _operation_id, _unit: None,
            operation_id="duplicate",
        )

    assert manager.get("duplicate").kind == "existing"
    assert manager.active_count == 1


def test_use_case_registry_duplicate_uses_operation_transition_error():
    manager = OperationManager(id_factory=lambda: "unused")
    ids = iter(("first-unit", "second-unit"))
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    first = use_case.start(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
        lambda _operation_id, _unit: None,
        operation_id="duplicate",
    )

    with pytest.raises(OperationTransitionError, match="Duplicate operation id"):
        use_case.start(
            "batch_install",
            (InstallRequest("device-b", "b.apk", "b.apk"),),
            lambda _operation_id, _unit: None,
            operation_id="duplicate",
        )

    assert use_case.active_snapshot(first.operation_id) is not None
    outcome = use_case.complete(
        first.operation_id,
        first.units[0].unit_id,
        succeeded=True,
        message="ok",
    )
    assert outcome is not None
    assert outcome.snapshot.state is OperationState.SUCCEEDED


def test_retry_accepts_explicit_child_operation_id_and_preserves_parent_identity():
    ids = iter(("parent-unit", "child-unit"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    parent = use_case.start(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
        lambda _operation_id, _unit: None,
        operation_id="parent-operation",
    )
    outcome = use_case.complete(
        parent.operation_id,
        parent.units[0].unit_id,
        succeeded=False,
        message="failed",
    )

    child = use_case.retry_failed(
        outcome,
        lambda _operation_id, _unit: None,
        operation_id="child-operation",
    )

    assert child.operation_id == "child-operation"
    snapshot = manager.get(child.operation_id)
    assert snapshot.parent_operation_id == "parent-operation"


def test_start_failure_after_manager_begin_propagates_and_cleans_all_application_state():
    manager = _RaiseAfterBeginManager()
    use_case = InstallBatchUseCase(manager, id_factory=lambda: "unit-1")

    with pytest.raises(RuntimeError, match="mark running failed"):
        use_case.start(
            "batch_install",
            (InstallRequest("device-a", "a.apk", "a.apk"),),
            lambda _operation_id, _unit: None,
            operation_id="operation-1",
        )

    assert manager.active_count == 0
    assert use_case._active_units == {}
    assert use_case._starting_operations == set()
    assert use_case._start_terminals == {}
    assert use_case._inflight_units == {}


def test_start_cleanup_failure_does_not_mask_the_original_start_exception():
    manager = _RaiseDuringStartAndCleanupManager()
    use_case = InstallBatchUseCase(manager, id_factory=lambda: "unit-1")

    with pytest.raises(RuntimeError, match="mark running failed") as raised:
        use_case.start(
            "batch_install",
            (InstallRequest("device-a", "a.apk", "a.apk"),),
            lambda _operation_id, _unit: None,
            operation_id="operation-1",
        )

    assert manager.active_count == 0
    assert any("cleanup finish failed" in note for note in raised.value.__notes__)


@pytest.mark.parametrize("field", ["device_id", "apk_path", "apk_name"])
@pytest.mark.parametrize("invalid", ["", "   ", None])
def test_install_request_rejects_blank_fields(field, invalid):
    values = {
        "device_id": "device-a",
        "apk_path": "demo.apk",
        "apk_name": "demo.apk",
    }
    values[field] = invalid

    with pytest.raises(ValueError, match=field):
        InstallRequest(**values)


def test_install_batch_start_rejects_empty_requests_and_blank_kind():
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: "generated")

    with pytest.raises(ValueError, match="requests"):
        use_case.start("batch_install", (), lambda _operation_id, _unit: None)
    with pytest.raises(ValueError, match="kind"):
        use_case.start(
            "   ",
            (InstallRequest("device-a", "demo.apk", "demo.apk"),),
            lambda _operation_id, _unit: None,
        )

    assert manager.active_count == 0


def test_partial_install_and_retry_only_failed_units_with_parent_identity():
    ids = iter(("op-a", "a-1", "a-2", "op-retry", "retry-1"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    submitted = []
    start = use_case.start(
        "batch_install",
        (
            InstallRequest("device-a", "a.apk", "a.apk"),
            InstallRequest("device-b", "a.apk", "a.apk"),
        ),
        lambda operation_id, unit: submitted.append((operation_id, unit)),
    )

    assert (
        use_case.complete(
            start.operation_id,
            start.units[0].unit_id,
            succeeded=True,
            message="ok",
        )
        is None
    )
    outcome = use_case.complete(
        start.operation_id,
        start.units[1].unit_id,
        succeeded=False,
        message="offline",
    )

    assert outcome is not None
    assert outcome.snapshot.state is OperationState.PARTIAL
    assert outcome.failed_units == (start.units[1],)
    retry = use_case.retry_failed(
        outcome,
        lambda operation_id, unit: submitted.append((operation_id, unit)),
    )
    assert retry is not None
    assert tuple(unit.request for unit in retry.units) == (start.units[1].request,)
    assert manager.get(retry.operation_id).parent_operation_id == start.operation_id


def test_cancel_marks_pending_units_and_ignores_late_results():
    ids = iter(("op-a", "a-1", "a-2"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    start = use_case.start(
        "batch_install",
        (
            InstallRequest("device-a", "a.apk", "a.apk"),
            InstallRequest("device-b", "a.apk", "a.apk"),
        ),
        lambda _operation_id, _unit: None,
    )

    outcome = use_case.cancel(start.operation_id)

    assert outcome is not None
    assert outcome.snapshot.state is OperationState.CANCELLED
    assert outcome.snapshot.cancel_requested is True
    assert {result.state for result in outcome.snapshot.unit_results} == {OperationState.CANCELLED}
    assert (
        use_case.complete(
            start.operation_id,
            start.units[0].unit_id,
            succeeded=True,
            message="late",
        )
        is None
    )
    assert manager.active_count == 0


def test_active_unit_unknown_and_duplicate_results_preserve_one_terminal():
    ids = iter(("op-a", "a-1", "a-2"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    start = use_case.start(
        "batch_install",
        (
            InstallRequest("device-a", "a.apk", "a.apk"),
            InstallRequest("device-b", "b.apk", "b.apk"),
        ),
        lambda _operation_id, _unit: None,
    )

    assert use_case.active_unit(start.operation_id, start.units[0].unit_id) == start.units[0]
    assert use_case.active_unit(start.operation_id, "unknown") is None
    with pytest.raises(ValueError, match="Unknown install unit"):
        use_case.complete(start.operation_id, "unknown", succeeded=False, message="unknown")
    assert (
        use_case.complete(
            start.operation_id,
            start.units[0].unit_id,
            succeeded=True,
            message="ok",
        )
        is None
    )
    assert (
        use_case.complete(
            start.operation_id,
            start.units[0].unit_id,
            succeeded=True,
            message="duplicate",
        )
        is None
    )

    outcome = use_case.complete(
        start.operation_id,
        start.units[1].unit_id,
        succeeded=True,
        message="ok",
    )

    assert outcome is not None
    assert outcome.snapshot.state is OperationState.SUCCEEDED
    assert len(outcome.snapshot.unit_results) == 2
    assert use_case.active_unit(start.operation_id, start.units[0].unit_id) is None


def test_fail_closes_batch_and_submission_error_can_return_terminal_start():
    ids = iter(("op-a", "a-1", "op-b", "b-1"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    first = use_case.start(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
        lambda _operation_id, _unit: None,
    )

    failed = use_case.fail(first.operation_id, message="protocol mismatch")

    assert failed is not None
    assert failed.snapshot.state is OperationState.FAILED
    assert failed.snapshot.message == "protocol mismatch"
    assert failed.units == first.units
    assert (
        use_case.complete(
            first.operation_id,
            first.units[0].unit_id,
            succeeded=True,
            message="late",
        )
        is None
    )

    def reject_submission(_operation_id, _unit):
        raise RuntimeError("queue unavailable")

    second = use_case.start(
        "batch_install",
        (InstallRequest("device-b", "b.apk", "b.apk"),),
        reject_submission,
    )

    assert second.terminal is not None
    assert second.terminal.snapshot.state is OperationState.FAILED
    assert second.terminal.snapshot.unit_results[0].message == "Install task submission failed"
    assert manager.active_count == 0


def test_retry_returns_none_when_outcome_has_no_failed_units():
    ids = iter(("op-a", "a-1"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    start = use_case.start(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
        lambda _operation_id, _unit: None,
    )
    outcome = use_case.complete(
        start.operation_id,
        start.units[0].unit_id,
        succeeded=True,
        message="ok",
    )

    assert outcome is not None
    assert use_case.retry_failed(outcome, lambda _operation_id, _unit: None) is None
    assert manager.active_count == 0


def test_synchronous_completion_returns_terminal_from_start():
    ids = iter(("op-a", "a-1", "a-2"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    submitted = []

    def complete_immediately(operation_id, unit):
        submitted.append(unit.unit_id)
        use_case.complete(operation_id, unit.unit_id, succeeded=True, message="ok")

    start = use_case.start(
        "batch_install",
        (
            InstallRequest("device-a", "a.apk", "a.apk"),
            InstallRequest("device-b", "b.apk", "b.apk"),
        ),
        complete_immediately,
    )

    assert submitted == ["a-1", "a-2"]
    assert start.terminal is not None
    assert start.terminal.snapshot.state is OperationState.SUCCEEDED
    assert manager.active_count == 0


def test_synchronous_cancel_stops_submitting_pending_units_and_returns_terminal():
    ids = iter(("op-a", "a-1", "a-2"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    submitted = []
    cancelled = []

    def cancel_on_first(operation_id, unit):
        submitted.append(unit.unit_id)
        cancelled.append(use_case.cancel(operation_id))

    start = use_case.start(
        "batch_install",
        (
            InstallRequest("device-a", "a.apk", "a.apk"),
            InstallRequest("device-b", "b.apk", "b.apk"),
        ),
        cancel_on_first,
    )

    assert submitted == ["a-1"]
    assert cancelled == [None]
    assert start.terminal is not None
    assert start.terminal.snapshot.state is OperationState.CANCELLED


def test_synchronous_fail_stops_submitting_pending_units_and_returns_terminal():
    ids = iter(("op-a", "a-1", "a-2"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    submitted = []
    failed = []

    def fail_on_first(operation_id, unit):
        submitted.append(unit.unit_id)
        failed.append(use_case.fail(operation_id, message="protocol mismatch"))

    start = use_case.start(
        "batch_install",
        (
            InstallRequest("device-a", "a.apk", "a.apk"),
            InstallRequest("device-b", "b.apk", "b.apk"),
        ),
        fail_on_first,
    )

    assert submitted == ["a-1"]
    assert failed[0] is not None
    assert start.terminal == failed[0]
    assert start.terminal.snapshot.state is OperationState.FAILED


def test_concurrent_cancel_during_submit_prevents_the_next_submission():
    ids = iter(("op-a", "a-1", "a-2"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    first_submission_started = threading.Event()
    release_first_submission = threading.Event()
    submitted = []
    starts = []

    def blocking_submit(_operation_id, unit):
        submitted.append(unit.unit_id)
        if unit.index == 1:
            first_submission_started.set()
            release_first_submission.wait(2)

    thread = threading.Thread(
        target=lambda: starts.append(
            use_case.start(
                "batch_install",
                (
                    InstallRequest("device-a", "a.apk", "a.apk"),
                    InstallRequest("device-b", "b.apk", "b.apk"),
                ),
                blocking_submit,
            )
        )
    )
    thread.start()
    assert first_submission_started.wait(2)

    cancelled = use_case.cancel("op-a")
    release_first_submission.set()
    thread.join(2)

    assert not thread.is_alive()
    assert cancelled is None
    assert submitted == ["a-1"]
    assert starts[0].terminal is not None
    assert starts[0].terminal.snapshot.state is OperationState.CANCELLED


def test_submission_failure_continues_and_synchronous_success_finishes_partial():
    ids = iter(("op-a", "a-1", "a-2"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    submitted = []

    def submit(operation_id, unit):
        submitted.append(unit.unit_id)
        if unit.index == 1:
            raise RuntimeError("queue unavailable")
        use_case.complete(operation_id, unit.unit_id, succeeded=True, message="ok")

    start = use_case.start(
        "batch_install",
        (
            InstallRequest("device-a", "a.apk", "a.apk"),
            InstallRequest("device-b", "b.apk", "b.apk"),
        ),
        submit,
    )

    assert submitted == ["a-1", "a-2"]
    assert start.terminal is not None
    assert start.terminal.snapshot.state is OperationState.PARTIAL
    assert [result.state for result in start.terminal.snapshot.unit_results] == [
        OperationState.FAILED,
        OperationState.SUCCEEDED,
    ]


def test_public_completion_and_failure_signatures_match_the_design_contract():
    complete = inspect.signature(InstallBatchUseCase.complete).parameters
    fail = inspect.signature(InstallBatchUseCase.fail).parameters

    assert complete["succeeded"].kind is inspect.Parameter.KEYWORD_ONLY
    assert complete["message"].kind is inspect.Parameter.KEYWORD_ONLY
    assert complete["message"].default is inspect.Parameter.empty
    assert fail["message"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert fail["message"].default is inspect.Parameter.empty


def test_conflicting_duplicate_result_keeps_the_first_result_without_side_effects():
    ids = iter(("op-a", "a-1", "a-2"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    start = use_case.start(
        "batch_install",
        (
            InstallRequest("device-a", "a.apk", "a.apk"),
            InstallRequest("device-b", "b.apk", "b.apk"),
        ),
        lambda _operation_id, _unit: None,
    )

    assert (
        use_case.complete(
            start.operation_id,
            start.units[0].unit_id,
            succeeded=True,
            message="ok",
        )
        is None
    )
    assert (
        use_case.complete(
            start.operation_id,
            start.units[0].unit_id,
            succeeded=False,
            message="conflict",
        )
        is None
    )

    snapshot = manager.get(start.operation_id)
    assert snapshot is not None
    assert snapshot.unit_results == (
        OperationUnitResult(start.units[0].unit_id, OperationState.SUCCEEDED, "ok"),
    )


def test_direct_manager_finish_removes_stale_active_unit_identity():
    ids = iter(("op-a", "a-1"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    start = use_case.start(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
        lambda _operation_id, _unit: None,
    )

    terminal = manager.finish(start.operation_id, OperationState.FAILED, message="external")

    assert terminal is not None
    assert manager.active_count == 0
    assert use_case.active_unit(start.operation_id, start.units[0].unit_id) is None


class _FinishDuringRecordManager(OperationManager):
    def record_unit_result(self, operation_id, result, **kwargs):
        self.finish(operation_id, OperationState.FAILED, message="external race")
        return None


def test_manager_finish_racing_with_record_cleans_stale_active_unit_identity():
    ids = iter(("op-a", "a-1"))
    manager = _FinishDuringRecordManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    start = use_case.start(
        "batch_install",
        (InstallRequest("device-a", "a.apk", "a.apk"),),
        lambda _operation_id, _unit: None,
    )

    outcome = use_case.complete(
        start.operation_id,
        start.units[0].unit_id,
        succeeded=True,
        message="late",
    )

    assert outcome is None
    assert manager.active_count == 0
    assert use_case.active_unit(start.operation_id, start.units[0].unit_id) is None


def _start_line_containing(text):
    lines, first_line = inspect.getsourcelines(InstallBatchUseCase.start)
    return next(first_line + offset for offset, line in enumerate(lines) if text in line)


def test_cancel_caller_returns_without_waiting_for_reserved_callback():
    ids = iter(("op-a", "a-1"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    before_callback = threading.Event()
    release_callback = threading.Event()
    cancel_started = threading.Event()
    cancel_finished = threading.Event()
    submitted = []
    starts = []
    cancellations = []
    submit_line = _start_line_containing("submit(operation.operation_id, unit)")

    def trace(frame, event, _arg):
        if (
            frame.f_code is InstallBatchUseCase.start.__code__
            and event == "line"
            and frame.f_lineno == submit_line
        ):
            before_callback.set()
            release_callback.wait(2)
        return trace

    def run_start():
        sys.settrace(trace)
        try:
            starts.append(
                use_case.start(
                    "batch_install",
                    (InstallRequest("device-a", "a.apk", "a.apk"),),
                    lambda _operation_id, unit: submitted.append(unit.unit_id),
                )
            )
        finally:
            sys.settrace(None)

    def run_cancel():
        cancel_started.set()
        cancellations.append(use_case.cancel("op-a"))
        cancel_finished.set()

    start_thread = threading.Thread(target=run_start)
    cancel_thread = threading.Thread(target=run_cancel)
    start_thread.start()
    assert before_callback.wait(2)
    cancel_thread.start()
    assert cancel_started.wait(2)
    cancel_finished_before_release = cancel_finished.wait(0.2)
    release_callback.set()
    start_thread.join(2)
    cancel_thread.join(2)

    assert not start_thread.is_alive()
    assert not cancel_thread.is_alive()
    assert cancel_finished_before_release is True
    assert submitted == ["a-1"]
    assert cancellations == [None]
    assert starts[0].terminal is not None
    assert starts[0].terminal.snapshot.state is OperationState.CANCELLED


def test_cancel_before_submission_reservation_prevents_callback_invocation():
    ids = iter(("op-a", "a-1"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    before_reservation = threading.Event()
    release_reservation = threading.Event()
    submitted = []
    starts = []
    reservation_line = _start_line_containing("for unit in units:") + 1

    def trace(frame, event, _arg):
        if (
            frame.f_code is InstallBatchUseCase.start.__code__
            and event == "line"
            and frame.f_lineno == reservation_line
        ):
            before_reservation.set()
            release_reservation.wait(2)
        return trace

    def run_start():
        sys.settrace(trace)
        try:
            starts.append(
                use_case.start(
                    "batch_install",
                    (InstallRequest("device-a", "a.apk", "a.apk"),),
                    lambda _operation_id, unit: submitted.append(unit.unit_id),
                )
            )
        finally:
            sys.settrace(None)

    thread = threading.Thread(target=run_start)
    thread.start()
    assert before_reservation.wait(2)

    cancelled = use_case.cancel("op-a")
    release_reservation.set()
    thread.join(2)

    assert not thread.is_alive()
    assert cancelled is not None
    assert submitted == []
    assert starts[0].terminal == cancelled


def test_reserved_synchronous_completion_wins_after_nonblocking_cancel():
    ids = iter(("op-a", "a-1"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    before_callback = threading.Event()
    release_callback = threading.Event()
    cancel_started = threading.Event()
    cancel_finished = threading.Event()
    starts = []
    cancellations = []
    submit_line = _start_line_containing("submit(operation.operation_id, unit)")

    def trace(frame, event, _arg):
        if (
            frame.f_code is InstallBatchUseCase.start.__code__
            and event == "line"
            and frame.f_lineno == submit_line
        ):
            before_callback.set()
            release_callback.wait(2)
        return trace

    def submit(operation_id, unit):
        use_case.complete(operation_id, unit.unit_id, succeeded=True, message="ok")

    def run_start():
        sys.settrace(trace)
        try:
            starts.append(
                use_case.start(
                    "batch_install",
                    (InstallRequest("device-a", "a.apk", "a.apk"),),
                    submit,
                )
            )
        finally:
            sys.settrace(None)

    def run_cancel():
        cancel_started.set()
        cancellations.append(use_case.cancel("op-a"))
        cancel_finished.set()

    start_thread = threading.Thread(target=run_start)
    cancel_thread = threading.Thread(target=run_cancel)
    start_thread.start()
    assert before_callback.wait(2)
    cancel_thread.start()
    assert cancel_started.wait(2)
    cancel_finished_before_release = cancel_finished.wait(0.2)
    release_callback.set()
    start_thread.join(2)
    cancel_thread.join(2)

    assert not start_thread.is_alive()
    assert not cancel_thread.is_alive()
    assert cancel_finished_before_release is True
    assert cancellations == [None]
    assert starts[0].terminal is not None
    assert starts[0].terminal.snapshot.state is OperationState.SUCCEEDED


def test_external_cancel_and_synchronous_self_cancel_do_not_deadlock():
    ids = iter(("op-a", "a-1"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    callback_started = threading.Event()
    callback_can_self_cancel = threading.Event()
    starts = []
    external_cancellations = []
    self_cancellations = []

    def submit(operation_id, _unit):
        callback_started.set()
        assert callback_can_self_cancel.wait(2)
        self_cancellations.append(use_case.cancel(operation_id))

    def run_start():
        starts.append(
            use_case.start(
                "batch_install",
                (InstallRequest("device-a", "a.apk", "a.apk"),),
                submit,
            )
        )

    def run_external_cancel():
        external_cancellations.append(use_case.cancel("op-a"))

    start_thread = threading.Thread(target=run_start, daemon=True)
    start_thread.start()
    assert callback_started.wait(2)
    cancel_thread = threading.Thread(target=run_external_cancel, daemon=True)
    cancel_thread.start()
    assert manager.token("op-a").wait(2)
    callback_can_self_cancel.set()
    start_thread.join(0.5)
    cancel_thread.join(0.5)

    assert not start_thread.is_alive()
    assert not cancel_thread.is_alive()
    assert external_cancellations == [None]
    assert self_cancellations == [None]
    assert starts[0].terminal is not None
    assert starts[0].terminal.snapshot.state is OperationState.CANCELLED
    assert manager.active_count == 0
    assert use_case._inflight_units == {}
    assert use_case._start_terminals == {}


def test_two_reserved_callbacks_can_cross_cancel_without_deadlock():
    ids = iter(("op-a", "a-1", "op-b", "b-1"))
    manager = OperationManager(id_factory=lambda: "unused")
    use_case = InstallBatchUseCase(manager, id_factory=lambda: next(ids))
    callbacks_ready = threading.Barrier(2)
    cancellations_done = threading.Barrier(2)
    operation_ids = {}
    cancellation_results = []
    starts = []

    def submit(operation_id, unit):
        operation_ids[unit.request.device_id] = operation_id
        callbacks_ready.wait(2)
        other_device = "device-b" if unit.request.device_id == "device-a" else "device-a"
        cancellation_results.append(use_case.cancel(operation_ids[other_device]))
        cancellations_done.wait(2)

    def run_start(device_id, apk_name):
        starts.append(
            use_case.start(
                "batch_install",
                (InstallRequest(device_id, apk_name, apk_name),),
                submit,
            )
        )

    first_thread = threading.Thread(
        target=run_start,
        args=("device-a", "a.apk"),
        daemon=True,
    )
    second_thread = threading.Thread(
        target=run_start,
        args=("device-b", "b.apk"),
        daemon=True,
    )
    first_thread.start()
    second_thread.start()
    first_thread.join(0.5)
    second_thread.join(0.5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert cancellation_results == [None, None]
    assert len(starts) == 2
    assert {start.operation_id for start in starts} == {"op-a", "op-b"}
    assert all(start.terminal is not None for start in starts)
    assert all(start.terminal.snapshot.state is OperationState.CANCELLED for start in starts)
    assert manager.active_count == 0
    assert use_case._inflight_units == {}
    assert use_case._start_terminals == {}
