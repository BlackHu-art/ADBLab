"""完成错误须跨停止入口与重试保留，但不能重放已结束资源操作。"""

import pytest

from core.tasks.supervision import StopDisposition, TaskSupervisor


def _stop(supervisor, scope):
    if scope == "single":
        return supervisor.stop("cleanup", graceful_timeout=0.1, force_timeout=0.1)
    if scope == "owner":
        results = supervisor.stop_owner("window", deadline=0.1)
    else:
        results = supervisor.stop_all(deadline=0.1)
    assert len(results) == 1
    return results[0]


def _register(supervisor, *, running, error_type):
    calls = []
    state = {"running": running}

    def request_stop():
        calls.append("request")

    def wait(_timeout):
        calls.append("wait")
        state["running"] = False
        return True

    def force_stop(_timeout):
        calls.append("force")
        state["running"] = False
        return True

    supervisor.register(
        "cleanup",
        owner_id="window",
        kind="shutdown",
        request_stop=request_stop,
        wait=wait,
        is_running=lambda: state["running"],
        force_stop=force_stop,
        error_type=error_type,
    )
    return calls


@pytest.mark.parametrize("scope", ["single", "owner", "all"])
@pytest.mark.parametrize("error_raises", [False, True])
def test_precompleted_cleanup_failure_remains_failed_without_replaying_operations(
    scope, error_raises,
):
    supervisor = TaskSupervisor()

    def completion_error():
        if error_raises:
            raise OSError("completion status unavailable")
        return "OSError"

    calls = _register(supervisor, running=False, error_type=completion_error)

    for _attempt in range(2):
        result = _stop(supervisor, scope)
        assert result.disposition == StopDisposition.FAILED
        assert result.error_type == "OSError"
        assert result.stopped is False
        assert supervisor.active_count == 1
        snapshot, = supervisor.active_snapshot()
        assert snapshot.task_id == "cleanup"
        assert snapshot.running is False
    assert calls == []


@pytest.mark.parametrize("scope", ["single", "owner", "all"])
def test_failed_completion_stays_failed_on_next_stop_without_replaying_operations(scope):
    supervisor = TaskSupervisor()
    calls = _register(supervisor, running=True, error_type=lambda: "RuntimeError")

    first = _stop(supervisor, scope)
    assert first.disposition == StopDisposition.FAILED
    assert first.error_type == "RuntimeError"
    assert calls == ["request", "wait"]

    second = _stop(supervisor, scope)
    assert second.disposition == StopDisposition.FAILED
    assert second.error_type == "RuntimeError"
    assert calls == ["request", "wait"]
    assert supervisor.active_count == 1
    assert not any(item.running for item in supervisor.active_snapshot())


@pytest.mark.parametrize("scope", ["single", "owner", "all"])
@pytest.mark.parametrize("error_type", [None, lambda: ""])
def test_precompleted_task_without_error_is_removed_without_replaying_operations(scope, error_type):
    supervisor = TaskSupervisor()
    calls = _register(supervisor, running=False, error_type=error_type)

    result = _stop(supervisor, scope)

    assert result.disposition == StopDisposition.ALREADY_STOPPED
    assert result.error_type == ""
    assert result.stopped is True
    assert supervisor.active_count == 0
    assert supervisor.active_snapshot() == ()
    assert calls == []
