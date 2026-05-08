"""
Core ADB infrastructure: async command decorator and base model class.

This module is independent — it does not import from any sibling model files.
Functional modules (adb_device, adb_app, adb_testing) each inherit from
ADBModelCore and are used independently by the controller.
"""

import subprocess
from functools import wraps

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

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
                                self.method_ref.__name__, f"AsyncError: {str(e)}"
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

    @staticmethod
    def _execute_command(command: list, timeout: int = 30) -> str:
        """Execute an ADB command synchronously, return stdout or error string."""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
                encoding="utf-8",
                errors="ignore",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            return f"Error: {str(e)}"
        except subprocess.TimeoutExpired:
            return f"Timeout: Command execution exceeded {timeout} seconds"
        except Exception as e:
            return f"SystemError: {str(e)}"

    @staticmethod
    def _fetch_device_info(commands: dict[str, list[str]]) -> dict[str, str]:
        """Run a batch of shell commands on a device and collect results."""
        device_info = {}
        for key, cmd in commands.items():
            output = ADBModelCore._execute_command(cmd)
            device_info[key] = (
                output if not output.startswith(("Error:", "Timeout:", "SystemError:")) else "N/A"
            )
        return device_info
