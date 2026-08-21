"""提供异步命令装饰器和 ADB 模型基类。

本模块不导入同级功能模型。adb_device、adb_app 和 adb_testing 等模块分别继承
ADBModelCore，再由控制器独立组合使用，从而避免循环依赖。
"""

import uuid
from functools import wraps

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from adblab.application.envelope import OperationMetadata, attach_operation_metadata
from core.exec import CommandRunner
from core.perf_trace import attach_perf, build_async_perf, perf_counter


def async_command(method):
    """将同步方法提交到 QThreadPool，并通过信号发送标准化结果。"""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
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

        class CommandTask(QRunnable):
            def __init__(
                self,
                model,
                method_ref,
                queued_at,
                metadata,
                *args,
                **kwargs,
            ):
                super().__init__()
                self.model = model
                self.method_ref = method_ref
                self.queued_at = queued_at
                self.metadata = metadata
                self.args = args
                self.kwargs = kwargs

            def run(self):
                import shiboken6

                started_at = perf_counter()
                try:
                    result = self.method_ref(self.model, *self.args, **self.kwargs)
                except Exception as e:
                    result = {"success": False, "error": str(e)}

                finished_at = perf_counter()
                perf = build_async_perf(
                    self.method_ref.__name__,
                    self.queued_at,
                    started_at,
                    finished_at,
                )
                result = attach_operation_metadata(
                    attach_perf(result, perf),
                    self.metadata,
                )
                try:
                    if not shiboken6.isValid(self.model):
                        return
                    self.model.command_finished.emit(self.method_ref.__name__, result)
                except RuntimeError:
                    pass  # 结果投递期间 Qt 对象可能已经由 C++ 侧删除。

        task = CommandTask(
            self,
            method,
            queued_at,
            metadata,
            *args,
            **kwargs,
        )
        self.thread_pool.start(task)

    return wrapper


class ADBModelCore(QObject):
    """提供信号、线程池和命令执行等共享基础设施。

    每个功能模型均独立继承该类，并拥有自己的 command_finished 信号及线程池入口。
    """

    command_finished = Signal(str, object)  # 参数依次为方法名和执行结果。

    def __init__(self):
        super().__init__()
        self.thread_pool = QThreadPool.globalInstance()

    @classmethod
    def _run(cls, cmd: list, timeout: int = 30, shell: bool = False, **extra) -> dict:
        (
            """执行命令，返回 {"success": True, "output": ..., ...} 或 """
            """{"success": False, "error": ..., ...}。

        extra 关键字参数会合并到返回字典（如 device_ip、package 等）。
        全项目 @async_command 方法的统一入口。
        """
        )
        r = CommandRunner.run(cmd, timeout=timeout, shell=shell)
        if r.success:
            return {"success": True, "output": r.output, **extra}
        return {"success": False, "error": r.error, **extra}

    @staticmethod
    def _fetch_device_info(commands: dict[str, list[str]]) -> dict[str, str]:
        """在指定设备上批量执行 Shell 命令并收集结果。"""
        device_info = {}
        for key, cmd in commands.items():
            r = CommandRunner.run(cmd)
            device_info[key] = r.output if r.success else "N/A"
        return device_info
