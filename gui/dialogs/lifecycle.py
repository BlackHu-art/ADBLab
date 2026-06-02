"""Small helpers for dialog signal and worker cleanup."""

from __future__ import annotations

import threading
import warnings
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QThread
from shiboken6 import isValid


def is_qobject_alive(obj: Any) -> bool:
    if obj is None:
        return False
    try:
        return bool(isValid(obj))
    except RuntimeError:
        return False
    except TypeError:
        return obj is not None


def safe_disconnect(signal: Any, handler: Callable | None = None) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            if handler is None:
                signal.disconnect()
            else:
                signal.disconnect(handler)
    except (TypeError, RuntimeError, SystemError):
        pass


def alive_callback(obj: Any, method_name: str, *args: Any, **kwargs: Any) -> Callable:
    obj_ref = weakref.ref(obj)

    def _callback(*_signal_args: Any) -> None:
        target = obj_ref()
        if not is_qobject_alive(target):
            return
        getattr(target, method_name)(*args, **kwargs)

    return _callback


@dataclass
class WorkerSignalBinding:
    worker: Any
    handlers: tuple[tuple[Any, Callable], ...]
    finished_handler: Callable | None = None
    _connected: bool = field(default=False, init=False)

    def connect(self) -> None:
        if self._connected:
            return
        for signal_, handler in self.handlers:
            signal_.connect(handler)
        if self.finished_handler is not None:
            self.worker.finished.connect(self.finished_handler)
        self._connected = True

    def disconnect(self) -> None:
        if not self._connected:
            return
        for signal_, handler in self.handlers:
            safe_disconnect(signal_, handler)
        if self.finished_handler is not None and is_qobject_alive(self.worker):
            safe_disconnect(self.worker.finished, self.finished_handler)
        self._connected = False


def wait_for_thread_later(thread: QThread, timeout_ms: int) -> None:
    threading.Thread(target=lambda: thread.wait(timeout_ms), daemon=True).start()


def wait_for_threads_later(threads: list[QThread], timeout_ms: int) -> None:
    threading.Thread(
        target=lambda: [thread.wait(timeout_ms) for thread in threads],
        daemon=True,
    ).start()
