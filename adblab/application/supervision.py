"""维护与业务操作状态相互独立的资源生命周期注册表。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import Event, Lock, RLock, Thread


class StopDisposition(str, Enum):
    """描述资源停止请求的最终处置结果。"""

    GRACEFUL = "graceful"
    FORCED = "forced"
    ALREADY_STOPPED = "already_stopped"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskStopResult:
    """记录单个受监督资源的停止结果，不表示业务成功与否。"""

    task_id: str
    owner_id: str
    disposition: StopDisposition
    error_type: str = ""

    @property
    def stopped(self) -> bool:
        return self.disposition in {
            StopDisposition.GRACEFUL,
            StopDisposition.FORCED,
            StopDisposition.ALREADY_STOPPED,
        }


@dataclass(frozen=True)
class SupervisedTaskSnapshot:
    """提供受监督资源当前运行状态的只读快照。"""

    task_id: str
    owner_id: str
    kind: str
    running: bool


@dataclass
class _SupervisedTask:
    task_id: str
    owner_id: str
    kind: str
    request_stop: Callable[[], object]
    wait: Callable[[float], bool]
    is_running: Callable[[], bool]
    force_stop: Callable[[float], object] | None
    error_type: Callable[[], str] | None


class ThreadedShutdownTask:
    """在独立线程中执行一次旧式非 Qt 关闭函数，避免阻塞调用方。"""

    def __init__(self, shutdown: Callable[[], object], *, name: str) -> None:
        if not callable(shutdown):
            raise TypeError("shutdown must be callable")
        self._shutdown = shutdown
        self._name = name
        self._lock = Lock()
        self._started = False
        self._finished = Event()
        self.error_type = ""

    def request_stop(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        Thread(target=self._run, name=self._name, daemon=True).start()

    def wait(self, timeout: float) -> bool:
        return self._finished.wait(max(0.0, float(timeout)))

    def is_running(self) -> bool:
        return not self._finished.is_set()

    def get_error_type(self) -> str:
        return self.error_type

    def _run(self) -> None:
        try:
            self._shutdown()
        except Exception as exc:
            self.error_type = type(exc).__name__
        finally:
            self._finished.set()


class TaskSupervisor:
    """注册和停止运行资源，但不推断资源对应的业务结果。"""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._lock = RLock()
        self._tasks: dict[str, _SupervisedTask] = {}
        self._stopping: set[str] = set()
        self._clock = clock or time.monotonic

    def register(
        self,
        task_id: str,
        *,
        owner_id: str,
        kind: str,
        request_stop: Callable[[], object],
        wait: Callable[[float], bool],
        is_running: Callable[[], bool],
        force_stop: Callable[[float], object] | None = None,
        error_type: Callable[[], str] | None = None,
    ) -> SupervisedTaskSnapshot:
        """注册资源停止回调，并拒绝无效回调和重复任务标识。"""
        task_id = self._non_empty(task_id, "task_id")
        owner_id = self._non_empty(owner_id, "owner_id")
        kind = self._non_empty(kind, "kind")
        for callback_name, callback in (
            ("request_stop", request_stop),
            ("wait", wait),
            ("is_running", is_running),
        ):
            if not callable(callback):
                raise TypeError(f"{callback_name} must be callable")
        if force_stop is not None and not callable(force_stop):
            raise TypeError("force_stop must be callable")
        if error_type is not None and not callable(error_type):
            raise TypeError("error_type must be callable")
        task = _SupervisedTask(
            task_id=task_id,
            owner_id=owner_id,
            kind=kind,
            request_stop=request_stop,
            wait=wait,
            is_running=is_running,
            force_stop=force_stop,
            error_type=error_type,
        )
        with self._lock:
            if task_id in self._tasks:
                raise ValueError(f"Duplicate supervised task id: {task_id}")
            self._tasks[task_id] = task
        return SupervisedTaskSnapshot(task_id, owner_id, kind, bool(is_running()))

    def unregister(self, task_id: str) -> bool:
        with self._lock:
            return self._tasks.pop(task_id, None) is not None

    def active_snapshot(self) -> tuple[SupervisedTaskSnapshot, ...]:
        with self._lock:
            tasks = tuple(self._tasks.values())
        snapshots = []
        for task in tasks:
            try:
                running = bool(task.is_running())
            except Exception:
                running = True
            snapshots.append(
                SupervisedTaskSnapshot(
                    task.task_id,
                    task.owner_id,
                    task.kind,
                    running,
                )
            )
        return tuple(snapshots)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._tasks)

    def stop(
        self,
        task_id: str,
        *,
        graceful_timeout: float,
        force_timeout: float,
    ) -> TaskStopResult | None:
        """在优雅停止和强制停止各自的预算内停止一个资源。"""
        task = self._claim(task_id)
        if task is None:
            return None
        try:
            running, error_type = self._running(task)
            if error_type:
                return self._result(task, StopDisposition.FAILED, error_type)
            if not running:
                self._remove_if_same(task)
                return self._result(task, StopDisposition.ALREADY_STOPPED)

            request_error = self._request(task)
            graceful_end = self._clock() + max(0.0, float(graceful_timeout))
            if self._wait(task, max(0.0, graceful_end - self._clock())):
                completion_error = self._completion_error(task)
                if completion_error:
                    return self._result(task, StopDisposition.FAILED, completion_error)
                self._remove_if_same(task)
                return self._result(task, StopDisposition.GRACEFUL, request_error)

            if task.force_stop is None:
                completion_error = self._completion_error(task)
                return self._result(
                    task,
                    StopDisposition.TIMED_OUT,
                    request_error or completion_error,
                )
            force_end = self._clock() + max(0.0, float(force_timeout))
            forced, force_error = self._force(
                task,
                max(0.0, force_end - self._clock()),
            )
            if self._wait(task, max(0.0, force_end - self._clock())):
                completion_error = self._completion_error(task)
                if completion_error:
                    return self._result(task, StopDisposition.FAILED, completion_error)
                self._remove_if_same(task)
                disposition = StopDisposition.FORCED if forced else StopDisposition.GRACEFUL
                return self._result(
                    task,
                    disposition,
                    force_error or request_error,
                )
            return self._result(
                task,
                StopDisposition.TIMED_OUT,
                force_error or request_error or self._completion_error(task),
            )
        finally:
            self._release_claim(task.task_id)

    def stop_owner(
        self,
        owner_id: str,
        *,
        deadline: float,
    ) -> tuple[TaskStopResult, ...]:
        """在共享截止预算内停止指定 owner 的全部未认领资源。"""
        owner_id = self._non_empty(owner_id, "owner_id")
        return self._stop_selected(
            lambda task: task.owner_id == owner_id,
            deadline=deadline,
        )

    def stop_all(self, *, deadline: float) -> tuple[TaskStopResult, ...]:
        """在同一绝对截止时间内向所有未认领任务广播停止请求。"""
        return self._stop_selected(lambda _task: True, deadline=deadline)

    def _stop_selected(
        self,
        predicate: Callable[[_SupervisedTask], bool],
        *,
        deadline: float,
    ) -> tuple[TaskStopResult, ...]:
        with self._lock:
            tasks = [
                task
                for task in self._tasks.values()
                if predicate(task) and task.task_id not in self._stopping
            ]
            self._stopping.update(task.task_id for task in tasks)
        if not tasks:
            return ()

        results: dict[str, TaskStopResult] = {}
        request_errors: dict[str, str] = {}
        duration = max(0.0, float(deadline))
        started = self._clock()
        graceful_end = started + duration * 0.7
        final_end = started + duration
        try:
            active = []
            for task in tasks:
                running, error_type = self._running(task)
                if error_type:
                    results[task.task_id] = self._result(
                        task,
                        StopDisposition.FAILED,
                        error_type,
                    )
                elif not running:
                    self._remove_if_same(task)
                    results[task.task_id] = self._result(
                        task,
                        StopDisposition.ALREADY_STOPPED,
                    )
                else:
                    active.append(task)

            # 先广播全部取消请求，再允许单个任务消耗优雅停止预算，避免后续任务延迟收到请求。
            for task in active:
                request_errors[task.task_id] = self._request(task)

            survivors = []
            for task in active:
                if self._wait(task, max(0.0, graceful_end - self._clock())):
                    completion_error = self._completion_error(task)
                    if completion_error:
                        results[task.task_id] = self._result(
                            task,
                            StopDisposition.FAILED,
                            completion_error,
                        )
                    else:
                        self._remove_if_same(task)
                        results[task.task_id] = self._result(
                            task,
                            StopDisposition.GRACEFUL,
                            request_errors[task.task_id],
                        )
                else:
                    survivors.append(task)

            force_results: dict[str, tuple[bool, str]] = {}
            for task in survivors:
                remaining = max(0.0, final_end - self._clock())
                if task.force_stop is None:
                    force_results[task.task_id] = (False, "")
                else:
                    force_results[task.task_id] = self._force(task, remaining)

            for task in survivors:
                forced, force_error = force_results[task.task_id]
                if self._wait(task, max(0.0, final_end - self._clock())):
                    completion_error = self._completion_error(task)
                    if completion_error:
                        results[task.task_id] = self._result(
                            task,
                            StopDisposition.FAILED,
                            completion_error,
                        )
                    else:
                        self._remove_if_same(task)
                        results[task.task_id] = self._result(
                            task,
                            StopDisposition.FORCED if forced else StopDisposition.GRACEFUL,
                            force_error or request_errors[task.task_id],
                        )
                else:
                    results[task.task_id] = self._result(
                        task,
                        StopDisposition.TIMED_OUT,
                        force_error or request_errors[task.task_id] or self._completion_error(task),
                    )
            return tuple(results[task.task_id] for task in tasks)
        finally:
            for task in tasks:
                self._release_claim(task.task_id)

    @staticmethod
    def _wait(task: _SupervisedTask, timeout: float) -> bool:
        try:
            waited = bool(task.wait(max(0.0, float(timeout))))
            return waited and not bool(task.is_running())
        except Exception:
            return False

    def _claim(self, task_id: str) -> _SupervisedTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task_id in self._stopping:
                return None
            self._stopping.add(task_id)
            return task

    def _release_claim(self, task_id: str) -> None:
        with self._lock:
            self._stopping.discard(task_id)

    @staticmethod
    def _running(task: _SupervisedTask) -> tuple[bool, str]:
        try:
            return bool(task.is_running()), ""
        except Exception as exc:
            return True, type(exc).__name__

    @staticmethod
    def _request(task: _SupervisedTask) -> str:
        try:
            task.request_stop()
            return ""
        except Exception as exc:
            return type(exc).__name__

    @staticmethod
    def _force(task: _SupervisedTask, timeout: float) -> tuple[bool, str]:
        try:
            force_stop = task.force_stop
            if force_stop is None:
                raise TypeError("force_stop must be callable")
            return bool(force_stop(max(0.0, float(timeout)))), ""
        except Exception as exc:
            return False, type(exc).__name__

    @staticmethod
    def _completion_error(task: _SupervisedTask) -> str:
        if task.error_type is None:
            return ""
        try:
            return str(task.error_type() or "")
        except Exception as exc:
            return type(exc).__name__

    @staticmethod
    def _result(
        task: _SupervisedTask,
        disposition: StopDisposition,
        error_type: str = "",
    ) -> TaskStopResult:
        return TaskStopResult(task.task_id, task.owner_id, disposition, error_type)

    def _remove_if_same(self, task: _SupervisedTask) -> None:
        with self._lock:
            if self._tasks.get(task.task_id) is task:
                del self._tasks[task.task_id]

    @staticmethod
    def _non_empty(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()
