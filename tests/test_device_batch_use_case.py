"""DeviceBatchUseCase 的纯逻辑契约测试（ADR-0003 Phase 3）。"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from adblab.application.device_batch import DeviceBatchUseCase
from adblab.application.operations import (
    IncompleteOperationError,
    OperationManager,
    OperationTransitionError,
)


def _use_case() -> DeviceBatchUseCase:
    return DeviceBatchUseCase(OperationManager())


def test_all_success_summary_uses_legacy_message_format():
    use_case = _use_case()
    start = use_case.start("uninstall", ["d1", "d2"], label="Uninstall App")

    outcomes = [
        outcome
        for unit in start.units
        if (outcome := use_case.record_unit_result(unit.unit_id, unit.device, True)) is not None
    ]

    assert len(outcomes) == 1
    assert outcomes[0].success is True
    assert outcomes[0].succeeded_count == 2
    assert outcomes[0].failed_devices == ()
    assert outcomes[0].message == "🎯 Uninstall App completed; ✅ Success: 2; ❌ Failed: 0"


def test_partial_failure_reports_failure_flag_and_failed_devices():
    use_case = _use_case()
    start = use_case.start("clear_data", ["d1", "d2", "d3"], label="Clear App Data")
    unit_by_device = {unit.device: unit for unit in start.units}

    outcome = None
    for device, ok in (("d1", True), ("d2", False), ("d3", True)):
        unit = unit_by_device[device]
        result = use_case.record_unit_result(unit.unit_id, device, ok)
        if result is not None:
            outcome = result

    assert outcome is not None
    assert outcome.success is False
    assert outcome.failed_devices == ("d2",)
    assert outcome.succeeded_count == 2
    assert outcome.failed_count == 1
    assert outcome.message == "🎯 Clear App Data completed; ✅ Success: 2; ❌ Failed: 1"


def test_duplicate_and_late_results_are_ignored():
    use_case = _use_case()
    start = use_case.start("restart_app", ["d1"], label="Restart App")
    unit = start.units[0]

    first = use_case.record_unit_result(unit.unit_id, "d1", True)
    assert first is not None
    assert use_case.record_unit_result(unit.unit_id, "d1", False) is None

    with pytest.raises(OperationTransitionError):
        use_case.finish(start.operation_id)


def test_finish_before_all_units_reports_raises():
    use_case = _use_case()
    start = use_case.start("current_activity", ["d1", "d2"], label="Activity Info")
    use_case.record_unit_result(start.units[0].unit_id, "d1", True)

    with pytest.raises(IncompleteOperationError):
        use_case.finish(start.operation_id)


def test_progress_matches_legacy_tracker_format():
    use_case = _use_case()
    start = use_case.start("uninstall", ["d1", "d2"], label="Uninstall App")
    use_case.record_unit_result(start.units[0].unit_id, "d1", True)

    assert use_case.progress(start.operation_id) == "(1/2)"


def test_concurrent_records_summarize_once():
    use_case = _use_case()
    devices = [f"d{i}" for i in range(64)]
    start = use_case.start("uninstall", devices, label="Batch Install")
    terminal = {}

    def record(pair):
        device, ok = pair
        unit = next(unit for unit in start.units if unit.device == device)
        outcome = use_case.record_unit_result(unit.unit_id, device, ok)
        if outcome is not None:
            terminal["outcome"] = outcome

    outcomes = [True] * 63 + [False]
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(record, zip(devices, outcomes)))

    assert terminal["outcome"].success is False
    assert terminal["outcome"].message == (
        "🎯 Batch Install completed; ✅ Success: 63; ❌ Failed: 1"
    )
