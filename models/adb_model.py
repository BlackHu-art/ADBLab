"""
Core ADB infrastructure: async command decorator and base model class.

This module is independent — it does not import from any sibling model files.
Functional modules (adb_device, adb_app, adb_testing) each inherit from
ADBModelCore and are used independently by the controller.
"""

from functools import wraps

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .base.command_runner import CommandRunner

# ── Module-level async decorator ─────────────────────────────────────────


def async_command(method):
    """Decorator: run a synchronous method on QThreadPool, emit result via Signal."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        class CommandTask(QRunnable):
            def __init__(self, model, method_ref, *args, **kwargs):
                super().__init__()
                self.model = model
                self.method_ref = method_ref
                self.args = args
                self.kwargs = kwargs

            def run(self):
                import shiboken6

                try:
                    result = self.method_ref(self.model, *self.args, **self.kwargs)
                    if not shiboken6.isValid(self.model):
                        return
                    self.model.command_finished.emit(self.method_ref.__name__, result)
                except RuntimeError:
                    pass  # C++ object already deleted
                except Exception as e:
                    if shiboken6.isValid(self.model):
                        try:
                            self.model.command_finished.emit(
                                self.method_ref.__name__,
                                {"success": False, "error": str(e)},
                            )
                        except RuntimeError:
                            pass

        task = CommandTask(self, method, *args, **kwargs)
        self.thread_pool.start(task)

    return wrapper


# ── Core model base (shared infrastructure) ──────────────────────────────


class ADBModelCore(QObject):
    """Shared infrastructure: signal, thread pool, command execution.

    Each functional module (ADBDevice, ADBApp, ADBTesting) inherits from
    this class and gets its own command_finished signal + thread pool access.
    """

    command_finished = Signal(str, object)  # (method_name, result)

    def __init__(self):
        super().__init__()
        self.thread_pool = QThreadPool.globalInstance()

    # ── 公开统一 API ─────────────────────────────────────────────────────

    @classmethod
    def _run(cls, cmd: list, timeout: int = 30, shell: bool = False, **extra) -> dict:
        """执行命令，返回 {"success": True, "output": ..., ...} 或 {"success": False, "error": ..., ...}。

        extra 关键字参数会合并到返回字典（如 device_ip、package 等）。
        全项目 @async_command 方法的统一入口。
        """
        r = CommandRunner.run(cmd, timeout=timeout, shell=shell)
        if r.success:
            return {"success": True, "output": r.output, **extra}
        return {"success": False, "error": r.error, **extra}

    @staticmethod
    def _fetch_device_info(commands: dict[str, list[str]]) -> dict[str, str]:
        """Run a batch of shell commands on a device and collect results."""
        device_info = {}
        for key, cmd in commands.items():
            r = CommandRunner.run(cmd)
            device_info[key] = r.output if r.success else "N/A"
        return device_info
