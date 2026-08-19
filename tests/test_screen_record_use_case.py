"""ScreenRecordUseCase 的纯逻辑契约测试（ADR-0003 Phase 3）。"""

from adblab.application.screen_record import ScreenRecordUseCase


def _use_case() -> ScreenRecordUseCase:
    return ScreenRecordUseCase()


def test_start_rejects_duplicate_device():
    use_case = _use_case()
    assert use_case.start("d1", "b1", "/save", 30) is True
    assert use_case.start("d1", "b2", "/save", 30) is False


def test_active_returns_record_and_finish_removes_it():
    use_case = _use_case()
    use_case.start("d1", "b1", "/save", 30, start_time=100.0)
    info = use_case.active("d1")
    assert info is not None
    assert info["batch_id"] == "b1"
    assert info["start_time"] == 100.0

    removed = use_case.finish("d1", "b1")
    assert removed is info
    assert use_case.active("d1") is None


def test_finish_rejects_mismatched_batch():
    use_case = _use_case()
    use_case.start("d1", "b1", "/save", 30)
    assert use_case.finish("d1", "b2") is None
    assert use_case.active("d1") is not None


def test_mark_started_rejects_mismatched_batch():
    use_case = _use_case()
    use_case.start("d1", "b1", "/save", 30)
    assert use_case.mark_started("d1", "b2", "/remote.mp4", "a.mp4") is False
    assert use_case.mark_started("d1", "b1", "/remote.mp4", "a.mp4") is True
    info = use_case.active("d1")
    assert info["remote_path"] == "/remote.mp4"
    assert info["filename"] == "a.mp4"


def test_mark_pull_submitted_is_idempotent_and_batch_checked():
    use_case = _use_case()
    use_case.start("d1", "b1", "/save", 30)
    assert use_case.mark_pull_submitted("d1", "b2") is False
    assert use_case.mark_pull_submitted("d1", "b1") is True
    assert use_case.mark_pull_submitted("d1", "b1") is False


def test_stop_request_is_idempotent_and_clearable():
    use_case = _use_case()
    use_case.start("d1", "b1", "/save", 30)
    assert use_case.request_stop("d1", "b1") is True
    assert use_case.request_stop("d1", "b1") is False
    assert use_case.stop_requested("d1", "b1") is True
    use_case.clear_stop_request("d1", "b1")
    assert use_case.stop_requested("d1", "b1") is False


def test_stop_succeeded_flag_round_trip():
    use_case = _use_case()
    use_case.start("d1", "b1", "/save", 30)
    assert use_case.is_stop_succeeded("d1", "b1") is False
    assert use_case.mark_stop_succeeded("d1", "b1") is True
    assert use_case.is_stop_succeeded("d1", "b1") is True
    assert use_case.is_stop_succeeded("d1", "b2") is False
