"""提供异步命令装饰器和 ADB 模型基类。

本模块不导入同级功能模型。adb_device、adb_app 和 adb_testing 等模块分别继承
ADBModelCore，再由控制器独立组合使用，从而避免循环依赖。
"""

import threading
import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, overload

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal

from adblab.application.action_results import ActionEnvelope, capture_action_job
from adblab.application.envelope import OperationMetadata, attach_operation_metadata
from core.exec import CommandRunner
from core.perf_trace import attach_perf, build_async_perf, perf_counter


def _model_is_shutting_down(model) -> bool:
    """兼容轻量测试替身，并统一读取 model 的终态准入栅栏。"""

    probe = getattr(model, "is_shutting_down", None)
    return bool(probe()) if callable(probe) else False


def _shutdown_cancelled_result() -> dict[str, object]:
    """返回仍可进入既有结果 envelope 的终态取消结果。"""

    return {
        "success": False,
        "cancelled": True,
        "error": "Model is shutting down",
    }


class CommandTask(QRunnable):
    """把单个 @async_command 调用包装成 QRunnable，跨线程执行后回发 command_finished。"""

    def __init__(self, model, method_ref, queued_at, metadata, *args, **kwargs):
        super().__init__()
        self.model = model
        self.method_ref = method_ref
        self.queued_at = queued_at
        self.metadata = metadata
        self.action_job = capture_action_job(method_ref.__name__, args[0] if args else "")
        self.args = args
        self.kwargs = kwargs
        if self.action_job is not None and callable(kwargs.get("callback")):
            self.kwargs = dict(kwargs)
            self._original_callback = kwargs["callback"]
            self._last_progress_at = 0.0
            self.kwargs["callback"] = self._report_progress

    def _report_progress(self, message: str) -> None:
        """把阶段说明限频投递到模型所属线程，worker 不访问结果存储或控件。"""
        self._original_callback(message)
        now = perf_counter()
        if now - self._last_progress_at >= 0.2:
            self._last_progress_at = now
            self.model.action_progress.emit(self.action_job, str(message))

    def run(self):
        import shiboken6

        started_at = perf_counter()
        if _model_is_shutting_down(self.model):
            result = _shutdown_cancelled_result()
        else:
            try:
                result = self.method_ref(self.model, *self.args, **self.kwargs)
            except Exception as e:
                result = {"success": False, "error": str(e)}
        finished_at = perf_counter()
        perf = build_async_perf(
            self.method_ref.__name__, self.queued_at, started_at, finished_at
        )
        result = attach_operation_metadata(attach_perf(result, perf), self.metadata)
        if self.action_job is not None:
            result = ActionEnvelope(result, self.action_job)
        try:
            if not shiboken6.isValid(self.model):
                return
            self.model.command_finished.emit(self.method_ref.__name__, result)
        except RuntimeError:
            pass  # 结果投递期间 Qt 对象可能已经由 C++ 侧删除。


_F = TypeVar("_F", bound=Callable[..., Any])


@overload
def async_command(method: _F, *, long_running: bool = False) -> _F: ...


@overload
def async_command(
    method: None = None, *, long_running: bool = False
) -> Callable[[_F], _F]: ...


def async_command(method=None, *, long_running: bool = False) -> Any:
    """将同步方法提交到 QThreadPool，并通过信号发送标准化结果。

    long_running=True 时提交到专用长任务池，避免长任务占满全局池导致短命令饥饿。
    """

    if method is None:
        return lambda m: async_command(m, long_running=long_running)

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        if _model_is_shutting_down(self):
            return
        queued_at = perf_counter()
        operation_id = kwargs.pop("_operation_id", None)
        operation_kind = kwargs.pop("_operation_kind", None)
        operation_unit_id = kwargs.pop("_operation_unit_id", None)
        operation_task_id = kwargs.pop("_operation_task_id", None)
        operation_target_id = kwargs.pop("_operation_target_id", None)
        expected_artifact_path = kwargs.pop("_operation_expected_artifact_path", None)
        operation_owner_token = kwargs.pop("_operation_owner_token", None)
        operation_generation_token = kwargs.pop("_operation_generation_token", None)
        metadata = None
        if operation_id is not None:
            method_name = method.__name__.removesuffix("_async")
            metadata = OperationMetadata(
                version=1,
                operation_id=operation_id,
                operation_kind=operation_kind or method_name,
                method_name=method_name,
                task_id=operation_task_id or str(uuid.uuid4()),
                unit_id=operation_unit_id,
                target_id=operation_target_id,
                expected_artifact_path=expected_artifact_path,
                owner_token=operation_owner_token,
                generation_token=operation_generation_token,
            )

        task = CommandTask(
            self,
            method,
            queued_at,
            metadata,
            *args,
            **kwargs,
        )
        pool = self.long_pool if long_running else self.thread_pool
        try:
            pool.start(task)
        except Exception as exc:
            payload = attach_operation_metadata(
                {"success": False, "error": f"任务提交失败：{type(exc).__name__}"}, metadata,
            )
            if task.action_job is not None:
                payload = ActionEnvelope(payload, task.action_job)
            self.command_finished.emit(method.__name__, payload)
            raise

    return wrapper


class ADBModelCore(QObject):
    """提供信号、线程池和命令执行等共享基础设施。

    每个功能模型均独立继承该类，并拥有自己的 command_finished 信号及线程池入口。
    """

    command_finished = Signal(str, object)  # 参数依次为方法名和执行结果。
    action_progress = Signal(object, str)

    def __init__(self):
        super().__init__()
        self._shutdown_started = threading.Event()
        self.thread_pool = QThreadPool.globalInstance()
        self.long_pool = QThreadPool()
        self.long_pool.setMaxThreadCount(max(2, QThread.idealThreadCount() // 2))

    def begin_shutdown(self) -> None:
        """永久关闭异步命令准入；model 实例进入终态后不得复用。"""

        self._shutdown_started.set()

    def is_shutting_down(self) -> bool:
        """返回终态准入栅栏是否已经关闭。"""

        return self._shutdown_started.is_set()

    def wait_for_commands(self) -> None:
        """由后台关闭线程等待已提交任务释放；GUI 主线程不得调用此阻塞边界。"""
        for pool in (self.thread_pool, self.long_pool):
            wait = getattr(pool, "waitForDone", None)
            if callable(wait):
                wait()

    def _run_readonly(
        self, cmd: list, timeout: float = 30, shell: bool = False, *,
        cancelled: Callable[[], bool] | None = None, **extra,
    ) -> dict:
        """只读查询共享调用方和模型关闭信号；写操作必须保留独立的取消契约。"""
        return self._run(
            cmd, timeout=timeout, shell=shell,
            cancelled=lambda: self.is_shutting_down() or bool(cancelled and cancelled()),
            **extra,
        )

    @classmethod
    def _run(
        cls, cmd: list, timeout: float = 30, shell: bool = False, *,
        native_only: bool = False, cancelled: Callable[[], bool] | None = None, **extra,
    ) -> dict:
        """执行命令，返回 {"success": True, ...} 或 {"success": False, "error": ...}。

        extra 关键字参数会合并到返回字典（如 device_ip、package 等）。
        全项目 @async_command 方法的统一入口。shell=False 时仍由设备端 sh 二次解释，动态值需 quote。
        """
        options = {}
        if native_only:
            options["native_only"] = True
        if cancelled is not None:
            options["cancelled"] = cancelled
        r = CommandRunner.run(cmd, timeout=timeout, shell=shell, **options)
        if r.success:
            return {"success": True, "output": r.output, **extra}
        if r.stale:
            return {"success": False, "stale": True, "error": r.error, **extra}
        if r.error == "Cancelled":
            return {"success": False, "cancelled": True, "error": r.error, **extra}
        return {"success": False, "error": r.error, **extra}

    @staticmethod
    def _fetch_device_info(
        commands: dict[str, list[str]], timeout: int = 5
    ) -> dict[str, str]:
        """在指定设备上批量执行 Shell 命令并收集结果；失败即提前退出。"""
        device_info = {}
        for key, cmd in commands.items():
            r = CommandRunner.run(cmd, timeout=timeout)
            if not r.success:
                break
            device_info[key] = r.output
        return device_info
