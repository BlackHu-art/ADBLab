"""验证 Monkey 批次只在运行终态和停止屏障满足后释放一次。"""

import pytest

pytestmark = pytest.mark.unit


def _batch(*devices, batch_id="batch-a"):
    from adblab.application.monkey_batch import MonkeyBatchCoordinator, MonkeyRunSnapshot

    coordinator = MonkeyBatchCoordinator()
    snapshots = {
        device: MonkeyRunSnapshot(
            batch_id=batch_id, index=index, parameters={"seed": 42},
            started_at=100.0, device_label=f"Device {index}", app_version="1.0",
        )
        for index, device in enumerate(devices, 1)
    }
    assert coordinator.reserve(snapshots) == ()
    return coordinator, snapshots


def test_reservation_rejects_entire_conflicting_batch_without_losing_current_owner():
    coordinator, snapshots = _batch("demo-a")
    _, replacements = _batch("demo-a", "demo-b", batch_id="batch-b")
    assert coordinator.reserve(replacements) == ("demo-a",)
    assert coordinator.pending() == (("demo-a", snapshots["demo-a"]),)


@pytest.mark.parametrize("ack_first", [True, False])
def test_stop_ack_and_run_terminal_form_order_independent_barrier(ack_first):
    coordinator, _ = _batch("demo-a")
    assert coordinator.request_stop("demo-a", "batch-a") == "batch-a"
    assert coordinator.request_stop("demo-a", "batch-a") is None
    result = {"success": False, "cancelled": True, "seed": 42}
    if ack_first:
        assert coordinator.record_stop_result("demo-a", "batch-a", success=True)
        assert coordinator.take_finished("demo-a", "batch-a") is None
        assert coordinator.record_terminal("demo-a", "batch-a", result)
    else:
        assert coordinator.record_terminal("demo-a", "batch-a", result)
        assert coordinator.take_finished("demo-a", "batch-a") is None
        assert coordinator.record_stop_result("demo-a", "batch-a", success=True)
    finished = coordinator.take_finished("demo-a", "batch-a")
    assert finished.result["cancelled"]
    assert finished.snapshot.parameters["seed"] == 42
    assert coordinator.pending() == ()
    assert coordinator.take_finished("demo-a", "batch-a") is None
    assert not coordinator.record_terminal("demo-a", "batch-a", result)
    assert not coordinator.record_stop_result("demo-a", "batch-a", success=True)


def test_old_batch_results_and_stop_requests_cannot_change_new_owner():
    coordinator, snapshots = _batch("demo-a", batch_id="batch-new")
    assert coordinator.request_stop("demo-a", "batch-old") is None
    assert not coordinator.record_terminal("demo-a", "batch-old", {"success": True})
    assert not coordinator.record_stop_result("demo-a", "batch-old", success=True)
    assert coordinator.take_finished("demo-a", "batch-old") is None
    assert coordinator.pending() == (("demo-a", snapshots["demo-a"]),)
    assert coordinator.record_terminal("demo-a", "batch-new", {"success": True})
    assert coordinator.take_finished("demo-a", "batch-new").result["success"]


def test_repeated_terminal_during_stop_wait_keeps_first_result():
    coordinator, _ = _batch("demo-a")
    coordinator.request_stop("demo-a", "batch-a")
    assert coordinator.record_terminal("demo-a", "batch-a", {"success": False})
    assert not coordinator.record_terminal("demo-a", "batch-a", {"success": True})
    assert coordinator.record_stop_result("demo-a", "batch-a", success=True)
    assert not coordinator.take_finished("demo-a", "batch-a").result["success"]


def test_stop_submission_failure_releases_request_for_retry():
    coordinator, _ = _batch("demo-a")
    assert coordinator.request_stop("demo-a") == "batch-a"
    assert coordinator.stop_submission_failed("demo-a", "batch-a")
    assert coordinator.request_stop("demo-a") == "batch-a"
    assert not coordinator.stop_submission_failed("demo-a", "batch-old")
    assert coordinator.request_stop("demo-a") is None


def test_stop_failure_preserves_run_result_and_removes_only_stop_barrier():
    coordinator, _ = _batch("demo-a")
    coordinator.request_stop("demo-a")
    coordinator.record_terminal("demo-a", "batch-a", {"success": False, "error": "run failed"})
    assert coordinator.record_stop_result("demo-a", "batch-a", success=False)
    assert coordinator.take_finished("demo-a", "batch-a").result["error"] == "run failed"


def test_start_failure_rolls_back_one_target_without_releasing_other_targets():
    coordinator, _ = _batch("demo-a", "demo-b")
    finished = coordinator.fail_start("demo-a", "batch-a", "queue rejected", finished_at=120)
    assert finished.device == "demo-a"
    assert finished.result == {"success": False, "error": "queue rejected", "finished_at": 120}
    assert tuple(device for device, _ in coordinator.pending()) == ("demo-b",)
    assert coordinator.fail_start("demo-a", "batch-a", "duplicate", finished_at=121) is None
    assert coordinator.fail_start("demo-b", "batch-old", "late", finished_at=121) is None


@pytest.mark.parametrize("resources_stopped", [True, False])
def test_shutdown_uses_cached_terminal_without_downgrading_it(resources_stopped):
    coordinator, _ = _batch("demo-a")
    coordinator.request_stop("demo-a")
    finished = coordinator.finish_for_shutdown(
        "demo-a", "batch-a", {"terminal": True, "success": True, "finished_at": 110},
        resources_stopped=resources_stopped, finished_at=120,
    )
    assert finished.result["success"] and finished.result["finished_at"] == 110
    assert coordinator.pending() == ()
    assert coordinator.finish_for_shutdown(
        "demo-a", "batch-a", None, resources_stopped=True, finished_at=130,
    ) is None


@pytest.mark.parametrize("resources_stopped", [True, False])
def test_shutdown_without_terminal_preserves_partial_artifacts_and_stop_certainty(
    resources_stopped,
):
    coordinator, _ = _batch("demo-a")
    finished = coordinator.finish_for_shutdown(
        "demo-a", "batch-a", {"monkey_log": "partial.log", "seed": 42},
        resources_stopped=resources_stopped, finished_at=120,
    )
    assert not finished.result["success"]
    assert finished.result["cancelled"] is resources_stopped
    assert finished.result["archive_incomplete"] is not resources_stopped
    assert finished.result["monkey_log"] == "partial.log"
    assert finished.result["finished_at"] == 120


def test_standalone_stop_keeps_legacy_empty_batch_and_cannot_release_new_run():
    coordinator, _ = _batch()
    assert coordinator.request_stop("demo-a") == ""
    assert coordinator.request_stop("demo-a") is None
    assert coordinator.record_stop_result("demo-a", "", success=True)
    assert coordinator.request_stop("demo-a") is None
    _, snapshots = _batch("demo-a")
    assert coordinator.reserve(snapshots) == ()
    assert not coordinator.record_stop_result("demo-a", "", success=True)
    assert coordinator.take_finished("demo-a", "batch-a") is None
